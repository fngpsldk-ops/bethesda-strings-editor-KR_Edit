"""
Claude API translation worker — same signal interface as OllamaWorker.

Drop-in replacement: when a Claude model is selected, MainWindow uses this
worker instead of OllamaWorker.  Signals are identical so all existing
progress/results plumbing in main_window.py works unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import List

from PySide6.QtCore import QMutex, QMutexLocker, QObject, Signal, Slot

logger = logging.getLogger(__name__)


def _close_unclosed_guillemets(text: str) -> str:
    """Append a closing » for every unclosed « on each line."""
    lines = text.split("\n")
    fixed = []
    for line in lines:
        missing = line.count("«") - line.count("»")
        if missing > 0:
            m = re.search(r'([.!?…]+)\s*$', line)
            if m:
                line = line[:m.start()] + "»" * missing + line[m.start():]
            else:
                line = line.rstrip() + "»" * missing
        fixed.append(line)
    return "\n".join(fixed)


def _restore_dropped_opening_brackets(translated: str, original: str) -> str:
    """Prepend missing [ when the model kept ] but dropped the opening [."""
    orig_lines = original.split("\n")
    trans_lines = translated.split("\n")
    fixed = []
    for i, line in enumerate(trans_lines):
        missing = line.count("]") - line.count("[")
        if missing > 0:
            orig_line = orig_lines[i] if i < len(orig_lines) else ""
            prefix = "[" * missing
            if orig_line.lstrip().startswith("["):
                stripped = line.lstrip()
                indent = line[: len(line) - len(stripped)]
                line = indent + prefix + stripped
            else:
                line = prefix + line
        fixed.append(line)
    return "\n".join(fixed)


class ClaudeTranslationWorker(QObject):
    """
    Translates game strings using the Claude API.

    Emits the same four signals as OllamaWorker:
      translation_ready(index, text, string_id)
      progress(done, total)
      error(message)
      finished(success_count, error_count)

    The worker is designed to be moved to a QThread and receive
    translate_batch() calls via QueuedConnection, exactly like OllamaWorker.
    """

    translation_ready = Signal(int, str, object)  # object avoids signed-int overflow for FormIDs > 0x7FFFFFFF
    progress = Signal(int, int)
    error = Signal(str)
    finished = Signal(int, int)

    def __init__(
        self,
        api_key: str,
        model: str,
        source_lang: str = "ru",
        target_lang: str = "uk",
        max_workers: int = 5,
        term_protector=None,
        translation_cache=None,
        protect_named_entities: bool = False,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.max_workers = max(1, max_workers)
        self.term_protector = term_protector
        self.translation_cache = translation_cache
        self.protect_named_entities = protect_named_entities
        self.glossary_manager = None
        self.lore_rag_manager = None    # gui.lore_rag_manager.LoreRAGManager (optional)
        self.profile_manager = None     # bethesda_strings.character_profiles.ProfileManager (optional)
        self.profile_assignments = None # bethesda_strings.character_profiles.ProfileAssignments (optional)
        self.skipped_types: list = []
        # TM fuzzy-match tolerance — mirrors OllamaWorker.tm_fuzzy_max_score.
        # Overwritten from settings by main_window the same way as the Ollama
        # worker (self.ollama_worker.tm_fuzzy_max_score = ...), since that
        # attribute name is shared across both worker classes.
        self.tm_fuzzy_max_score: float = 3.0

        self._stop_flag = False
        self._mutex = QMutex()

        # Settings hash for cache keys (TranslationCache.make_key). Unlike
        # OllamaWorker/OpenAICompatWorker, this worker has no
        # _compute_settings_hash() (no glossary-driven cache invalidation
        # here yet) — left as "" so the key format still matches theirs
        # exactly, just without that extra invalidation dimension.
        self._settings_hash = ""

        # Shared client — one connection pool reused across all worker threads.
        # Creating a new ClaudeClient per request was wasteful and broke prompt
        # caching (each new client has a fresh cache-write on the first call).
        from gui.claude_client import ClaudeClient
        self._claude = ClaudeClient(api_key, model)

    def stop(self) -> None:
        """Signal the worker to stop after the current request."""
        with QMutexLocker(self._mutex):
            self._stop_flag = True

    def update_config(self, **kwargs) -> None:
        """Accept the same kwargs as OllamaWorker.update_config() for compatibility."""
        for key, val in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, val)

    # ── Main translation slot ──────────────────────────────────────────────────

    @Slot(list)
    def translate_batch(self, requests: list) -> None:
        """Translate a batch of TranslationRequest objects using Claude."""
        if not requests:
            self.finished.emit(0, 0)
            return

        with QMutexLocker(self._mutex):
            self._stop_flag = False

        total = len(requests)
        done = 0
        success = 0
        errors = 0

        # ── Pre-flight scan (single-threaded — mirrors OllamaWorker /
        # OpenAICompatWorker) ────────────────────────────────────────────────
        # Resolve everything answerable without an API call (skip-type,
        # cache, TM), and deduplicate the rest: when the same source text
        # appears multiple times in the batch, only the first is submitted
        # to the thread pool; the rest are "followers" that get its result
        # fanned out to them once it's ready, instead of each independently
        # calling the API for identical text.
        from gui.translation_cache import TranslationCache

        pending: list = []
        followers: dict = {}

        for req in requests:
            with QMutexLocker(self._mutex):
                if self._stop_flag:
                    self.finished.emit(0, 0)
                    return

            source_text = req.original_text.replace("\r\n", "\n").replace("\r", "\n")

            if self.skipped_types:
                from gui.string_type_detector import classify
                if classify(source_text).name in self.skipped_types:
                    done += 1
                    self.progress.emit(done, total)
                    continue

            # is_retry marks a quality-hint-guided retranslation (see
            # OllamaWorker/OpenAICompatWorker): the whole point is to get a
            # DIFFERENT, improved result, so both TM and cache -- which can
            # only return whatever's already on record, including the exact
            # flawed translation this retry exists to replace -- must be
            # skipped for these requests, or the retry silently short-circuits
            # back to the same broken text with the API never called again.
            is_retry = bool(req.retry_hint) or bool(req.fix_translation)

            # Check translation cache. Uses TranslationCache.make_key() — the
            # same format OllamaWorker/OpenAICompatWorker use — instead of the
            # ad-hoc hash this previously built inline (no settings_hash,
            # different field order). That mismatch meant a manually-corrected
            # translation cached via the standard key (e.g. from the string
            # editor, which writes through TranslationCache.make_key) was
            # never found by this worker's own lookup.
            cache_key = TranslationCache.make_key(
                source_text, self.model, self.source_lang, self.target_lang,
                self._settings_hash,
            )
            if not is_retry and self.translation_cache:
                cached = self.translation_cache.get(cache_key)
                if cached:
                    self.translation_ready.emit(req.index, cached, req.string_id)
                    success += 1
                    done += 1
                    self.progress.emit(done, total)
                    continue

            # Check translation memory — exact ID hit, then exact source-text
            # hit, then fuzzy match. Mirrors OllamaWorker's cascade; TranslationMemory
            # has no .get() method, only get_by_id/get_by_source/get_fuzzy.
            # Guarded by is_retry (this worker previously had NO such guard,
            # unlike OllamaWorker/OpenAICompatWorker) for the same reason as
            # the cache guard above.
            if not is_retry and hasattr(self, "translation_memory") and self.translation_memory:
                tm_result = self.translation_memory.get_by_id(req.string_id)
                if tm_result is None:
                    tm_result = self.translation_memory.get_by_source(source_text)
                if tm_result is None:
                    tm_result = self.translation_memory.get_fuzzy(
                        source_text, max_score=self.tm_fuzzy_max_score
                    )
                if tm_result is not None:
                    self.translation_ready.emit(req.index, tm_result, req.string_id)
                    success += 1
                    done += 1
                    self.progress.emit(done, total)
                    continue

            # Dedup (retries always go through fresh, matching OllamaWorker)
            owns_followers = False
            if not is_retry:
                if cache_key in followers:
                    followers[cache_key].append(req)
                    continue
                followers[cache_key] = []
                owns_followers = True

            pending.append((req, source_text, cache_key, owns_followers))

        if not pending:
            self.finished.emit(success, errors)
            return

        def _translate_one(item):
            req, source_text, cache_key, _owns = item
            with QMutexLocker(self._mutex):
                if self._stop_flag:
                    return req.index, None, req.string_id

            # Term protection
            protected = source_text
            token_map: dict = {}
            if self.term_protector and req.protected_terms_enabled:
                try:
                    from gui.term_protector import SOFT_CATEGORIES
                    exclude = [] if self.protect_named_entities else list(SOFT_CATEGORIES)
                    protected, token_map = self.term_protector.protect_text(
                        source_text, exclude_categories=exclude
                    )
                except Exception as exc:
                    logger.warning("Term protection failed: %s", exc)

            # Glossary snippet
            glossary_snippet = req.glossary_snippet
            if not glossary_snippet and self.glossary_manager:
                try:
                    glossary_snippet = self.glossary_manager.build_prompt_snippet(source_text)
                except Exception:
                    glossary_snippet = ""

            # Lore RAG context
            lore_snippet = req.lore_snippet
            if not lore_snippet and self.lore_rag_manager:
                try:
                    lore_snippet = self.lore_rag_manager.get_snippet(source_text)
                except Exception:
                    lore_snippet = ""

            # Character profile
            profile = req.character_profile
            if profile is None and self.profile_assignments and self.profile_manager:
                pid = self.profile_assignments.get(req.string_id)
                if pid:
                    profile = self.profile_manager.get(pid)

            try:
                result = self._claude.translate(
                    text=protected,
                    source_lang=self.source_lang,
                    target_lang=self.target_lang,
                    retry_hint=req.retry_hint,
                    glossary_snippet=glossary_snippet,
                    lore_snippet=lore_snippet,
                    context_note=req.context_note,
                    character_profile=profile,
                )
            except Exception as exc:
                logger.error(
                    "Claude translation error index=%d string_id=0x%08X: %s",
                    req.index, req.string_id, exc,
                )
                return req.index, None, req.string_id

            # Restore protected terms
            # BSEK bug fix: same nonexistent-method bug as openai_compat_worker.py
            # — `restore()` does not exist on TermProtector (only `restore_text()`),
            # so restoration silently failed via AttributeError every time.
            if token_map and self.term_protector:
                try:
                    result = self.term_protector.restore_text(result, token_map, protected)
                except Exception as exc:
                    logger.warning("Term restore failed: %s", exc)

            # Close any unclosed «guillemets left open by the model
            result = _close_unclosed_guillemets(result)
            # Restore [ dropped by the model when ] was kept
            result = _restore_dropped_opening_brackets(result, req.original_text)

            # Store in cache.
            # BSEK bug fix: called the nonexistent `.put()` (TranslationCache
            # only defines `.set()`). Every cache write after a SUCCESSFUL
            # translation raised AttributeError, which propagated out of this
            # function uncaught -- the as_completed loop below caught it as a
            # generic exception and counted the string as FAILED, discarding
            # the successful translation entirely instead of ever emitting it.
            if cache_key and self.translation_cache:
                self.translation_cache.set(cache_key, result)

            return req.index, result, req.string_id

        # Parallel API calls — Claude allows concurrent requests
        # Default max_workers=5 is conservative; raise in settings for faster throughput
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_item = {pool.submit(_translate_one, item): item for item in pending}
            for fut in as_completed(future_to_item):
                with QMutexLocker(self._mutex):
                    stopped = self._stop_flag
                if stopped:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

                item_req, _src, item_cache_key, owns_followers = future_to_item[fut]
                req_followers = followers.get(item_cache_key, []) if owns_followers else []

                try:
                    idx, result, string_id = fut.result()
                except Exception as exc:
                    errors += 1 + len(req_followers)
                    self.error.emit(str(exc))
                    done += 1 + len(req_followers)
                    self.progress.emit(done, total)
                    continue

                if result is not None:
                    self.translation_ready.emit(idx, result, string_id)
                    success += 1
                    done += 1
                    self.progress.emit(done, total)
                    for follower in req_followers:
                        self.translation_ready.emit(follower.index, result, follower.string_id)
                        success += 1
                        done += 1
                        self.progress.emit(done, total)
                else:
                    errors += 1 + len(req_followers)
                    done += 1 + len(req_followers)
                    self.error.emit(
                        self.tr("Translation failed for string index {idx}").format(idx=idx)
                    )
                    self.progress.emit(done, total)

        self.finished.emit(success, errors)
