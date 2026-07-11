"""OpenAI-compatible translation worker for BSEK.

This worker talks to any OpenAI-compatible Chat Completions endpoint:
  - OpenAI / ChatGPT  : base_url = https://api.openai.com/v1
  - Google Gemini     : base_url = https://generativelanguage.googleapis.com/v1beta/openai/
  - Any other vendor exposing /chat/completions

Design notes
------------
* It is an INDEPENDENT worker (does not subclass OllamaWorker), so local-only
  logic (timeout circuit breaker, per-paragraph newline restore, etc.) can never
  misfire in an API context.  Bug isolation was the explicit goal.
* It REUSES the prompt builders on TranslationRequest
  (``to_system_prompt()`` / ``to_prompt()``), so the carefully tuned Korean
  prompt — examples, rules, glossary enforcement — is identical to the Ollama path.
* Signals are identical to OllamaWorker / ClaudeTranslationWorker so the rest of
  the app can drive it interchangeably.
* Cache keys include settings_hash (glossary + prompt version) so editing the
  glossary or bumping PROMPT_VERSION invalidates stale entries automatically —
  matching the behaviour we added to the Ollama path.
"""

from __future__ import annotations

import hashlib
import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import List, Optional

from PySide6.QtCore import QMutex, QMutexLocker, QObject, Signal, Slot

logger = logging.getLogger(__name__)

# Bump this when the prompt-construction logic changes in a way that should
# invalidate cached translations produced by this worker.
PROMPT_VERSION = 5  # bumped: DEFAULT_CUSTOM_RULES (rules 10-11) translated to Korean


class OpenAICompatWorker(QObject):
    """Translate via an OpenAI-compatible Chat Completions API.

    Signals mirror OllamaWorker exactly:
        translation_ready(index:int, text:str, string_id:object)
        progress(done:int, total:int)
        error(message:str)
        finished(success:int, errors:int)
    """

    translation_ready = Signal(int, str, object, str)  # (index, text, string_id, source: "tm"|"cache"|"api")
    progress = Signal(int, int)
    error = Signal(str)
    finished = Signal(int, int)

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        source_lang: str = "en",
        target_lang: str = "ko",
        max_workers: int = 4,
        term_protector=None,
        translation_cache=None,
        protect_named_entities: bool = False,
        temperature: float = 1.0,  # Gemini 3.x default recommended; 0.3 may cause looping
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.strip()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.max_workers = max(1, max_workers)
        self.term_protector = term_protector
        self.translation_cache = translation_cache
        self.protect_named_entities = protect_named_entities
        self.temperature = temperature
        self.timeout = timeout

        # Optional managers set by main_window after construction (same as others)
        self.glossary_manager = None
        self.lore_rag_manager = None
        self.profile_manager = None
        self.profile_assignments = None
        self.skipped_types: list = []
        self.translation_memory = None  # gui.translation_memory.TranslationMemory (optional)
        self.tm_fuzzy_max_score: float = 3.0  # mirrors OllamaWorker.tm_fuzzy_max_score

        self._stop_flag = False
        self._mutex = QMutex()

        # Compute settings hash once (glossary + prompt version) for cache keys.
        self._settings_hash = self._compute_settings_hash()

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stop_flag = True

    def update_config(self, **kwargs) -> None:
        """Accept the same kwargs as OllamaWorker.update_config() for compatibility."""
        for key, val in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, val)

    # ── API call (requests-based, avoids httpx/Qt SSL conflict) ─────────────────
    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI-compatible Chat Completions API using requests.

        Uses the `requests` library instead of the openai SDK to avoid
        httpx/Qt SSL conflicts that cause "Connection error" in threaded contexts.

        Retries on 429 (rate limit) and 5xx (transient server error) with
        exponential backoff + jitter, honoring a Retry-After header when the
        API sends one. Without this, a burst of concurrent requests hitting a
        low RPM cap (e.g. Gemini 2.5 Flash's free tier: 10 requests/minute)
        made EVERY string in that burst fail outright with no retry at all --
        each one silently became an empty/failed translation instead of
        eventually succeeding a few seconds later.
        """
        if not self.api_key:
            raise RuntimeError(
                "OpenAI-compatible API key is not set.\n"
                "Please enter your API key in Settings > Cloud AI Backend."
            )
        import random
        import time
        import requests
        import json
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
        }

        max_retries = 5
        base_delay = 2.0
        max_delay = 60.0

        for attempt in range(max_retries + 1):
            resp = requests.post(
                url, headers=headers,
                data=json.dumps(payload),
                timeout=self.timeout,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == max_retries:
                    resp.raise_for_status()
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = base_delay * (2 ** attempt)
                else:
                    delay = base_delay * (2 ** attempt)
                delay = min(delay, max_delay) + random.uniform(0, 1.0)
                logger.warning(
                    "[RATE-LIMIT] HTTP %d, retrying in %.1fs (attempt %d/%d)",
                    resp.status_code, delay, attempt + 1, max_retries,
                )
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    # ── settings hash (cache invalidation) ─────────────────────────────────────
    def _compute_settings_hash(self) -> str:
        """Short hash of glossary contents + prompt version.

        Changing the glossary or bumping PROMPT_VERSION changes this hash, so
        old cache entries are bypassed and re-translated automatically.
        """
        from gui.ollama_worker import get_prompt_overrides
        _persona, _rules = get_prompt_overrides()
        parts = [f"pv{PROMPT_VERSION}", f"persona={_persona}", f"rules={_rules}"]
        if self.glossary_manager is not None:
            try:
                entries = self.glossary_manager.get_all_entries()
                for e in sorted(entries, key=lambda x: x.source_term):
                    parts.append(f"{e.source_term}={e.target_term}")
            except Exception:
                pass
        combined = "\n".join(parts)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]

    def _make_cache_key(self, source_text: str) -> str:
        """Cache key compatible with the Ollama path (model+langs+settings+text)."""
        raw = (
            f"{self.model}\x00{self.source_lang}\x00{self.target_lang}"
            f"\x00{self._settings_hash}\x00{source_text}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ── main slot ──────────────────────────────────────────────────────────────
    @Slot(list)
    def translate_batch(self, requests: list) -> None:
        logger.info("[DIAG] OpenAICompatWorker.translate_batch entered with %d requests", len(requests) if requests else 0)
        if not requests:
            self.finished.emit(0, 0)
            return

        with QMutexLocker(self._mutex):
            self._stop_flag = False

        # Recompute in case glossary_manager was attached after __init__.
        self._settings_hash = self._compute_settings_hash()

        total = len(requests)
        done = 0
        success = 0
        errors = 0

        # ── Pre-flight scan (single-threaded — no race condition is possible
        # here, unlike the earlier lock/Event-based coalescing this replaces) ──
        # Resolve everything answerable without an API call (skip-type, TM,
        # cache), and deduplicate the rest: when the same source text appears
        # multiple times in the batch (a repeated item name, "Chunks (105
        # Credits)" x50...), only the FIRST occurrence is submitted to the
        # thread pool; the others are "followers" that never touch a thread
        # at all and just get the primary's result fanned out to them once
        # it's ready. Mirrors OllamaWorker.translate_batch's structure, which
        # already worked this way and inspired this rewrite.
        pending: list = []          # [(req, source_text, cache_key), ...] — actually dispatched
        followers: dict = {}        # cache_key -> [follower TranslationRequest, ...]

        for req in requests:
            with QMutexLocker(self._mutex):
                if self._stop_flag:
                    self.finished.emit(0, 0)
                    return

            source_text = req.original_text.replace("\r\n", "\n").replace("\r", "\n")

            if self.skipped_types:
                try:
                    from gui.string_type_detector import classify
                    if classify(source_text).name in self.skipped_types:
                        done += 1
                        self.progress.emit(done, total)
                        continue
                except Exception:
                    pass

            # Translation memory — exact ID hit, then exact source-text hit,
            # then fuzzy match. Same cascade as OllamaWorker / ClaudeTranslationWorker.
            is_retry = bool(req.retry_hint) or bool(req.fix_translation)
            if not is_retry and self.translation_memory:
                tm_result = self.translation_memory.get_by_id(req.string_id)
                if tm_result is None:
                    tm_result = self.translation_memory.get_by_source(source_text)
                if tm_result is None:
                    tm_result = self.translation_memory.get_fuzzy(
                        source_text, max_score=self.tm_fuzzy_max_score
                    )
                if tm_result is not None:
                    self.translation_ready.emit(req.index, tm_result, req.string_id, "tm")
                    success += 1
                    done += 1
                    self.progress.emit(done, total)
                    continue

            # Cache lookup. Guarded by is_retry for the exact same reason as
            # the TM check above: a quality-hint-guided retry exists to get a
            # DIFFERENT, improved result. The cache stores this worker's own
            # past output — including whatever got flagged as needing this
            # retry in the first place — so an unguarded lookup here silently
            # short-circuits every retry back to the same flawed translation
            # without ever calling the API again. Confirmed in practice: a
            # retry_hint-carrying request for already-cached text returned the
            # stale cached value with zero new API calls.
            cache_key = self._make_cache_key(source_text)
            if not is_retry and self.translation_cache:
                cached = self.translation_cache.get(cache_key)
                logger.info(
                    "[DIAG] cache lookup string_id=%s key=%s...  hit=%s  cache_len=%d  settings_hash=%s",
                    req.string_id, cache_key[:12], cached is not None, len(self.translation_cache), self._settings_hash,
                )
                if cached:
                    self.translation_ready.emit(req.index, cached, req.string_id, "cache")
                    success += 1
                    done += 1
                    self.progress.emit(done, total)
                    continue
            elif is_retry:
                logger.info("[DIAG] cache lookup SKIPPED (is_retry) string_id=%s", req.string_id)
            else:
                logger.info("[DIAG] cache lookup SKIPPED (self.translation_cache is falsy) string_id=%s", req.string_id)

            # Dedup: retries always go through fresh (matching OllamaWorker).
            # owns_followers marks whether THIS pending item is the one that
            # created followers[cache_key] (the first non-retry occurrence).
            # A retry reuses the same cache_key but must NOT also claim that
            # followers list -- otherwise, whichever of the primary/retry
            # completes LAST steals the list and re-fans its own result out
            # to the primary's followers, silently overwriting what the
            # primary already delivered them.
            owns_followers = False
            if not is_retry:
                if cache_key in followers:
                    followers[cache_key].append(req)
                    continue
                followers[cache_key] = []
                owns_followers = True

            pending.append((req, source_text, cache_key, owns_followers))

        if not pending:
            logger.info(
                "Batch complete (all %d resolved pre-flight): %d hits",
                total, success,
            )
            self.finished.emit(success, errors)
            return

        dedup_count = sum(len(v) for v in followers.values())
        logger.info(
            "Starting batch: %d total -> %d to API, %d dedup followers",
            total, len(pending), dedup_count,
        )

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

            # Glossary snippet (reuse request's, else build from manager)
            glossary_snippet = req.glossary_snippet
            if not glossary_snippet and self.glossary_manager:
                try:
                    glossary_snippet = self.glossary_manager.build_prompt_snippet(source_text)
                except Exception:
                    glossary_snippet = ""

            # Build prompts by REUSING TranslationRequest's builders.
            # We temporarily set the request fields the builders read.
            req.glossary_snippet = glossary_snippet
            req.source_lang = self.source_lang
            req.target_lang = self.target_lang
            try:
                system_prompt = req.to_system_prompt()
                user_prompt = req.to_prompt(protected)
            except Exception as exc:
                logger.error("Prompt build failed idx=%d: %s", req.index, exc)
                return req.index, None, req.string_id

            # OpenAI-compatible Chat Completions call (via requests)
            try:
                result = self._call_api(system_prompt, user_prompt)
            except Exception as exc:
                logger.error(
                    "OpenAI-compat translation error idx=%d string_id=%s: %s",
                    req.index, getattr(req, "string_id", "?"), exc,
                )
                return req.index, None, req.string_id

            if not result:
                return req.index, None, req.string_id

            # Restore protected terms
            # BSEK bug fix: this called the nonexistent method `restore()`
            # (TermProtector only defines `restore_text()`), so every restore
            # attempt silently raised AttributeError and was swallowed by the
            # except clause below — protected terms (game tags, printf specifiers,
            # <Alias=...> tags, [BRACKET_ID] codes) were NEVER restored, which is
            # why they showed up corrupted/empty ([]) in translated output.
            # protected_text=protected (the placeholder-substituted source) enables
            # restore_text()'s anchor-based template matching for exact whitespace
            # and paragraph preservation, matching how ollama_worker.py calls it.
            if token_map and self.term_protector:
                try:
                    result = self.term_protector.restore_text(result, token_map, protected)
                except Exception as exc:
                    logger.warning("Term restore failed: %s", exc)

            # Store in cache
            if cache_key and self.translation_cache:
                self.translation_cache.set(cache_key, result)

            return req.index, result, req.string_id

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
                    self.translation_ready.emit(idx, result, string_id, "api")
                    success += 1
                    done += 1
                    self.progress.emit(done, total)
                    # Fan result out to all dedup followers — same call, so
                    # still "api" (not a separate TM/cache source).
                    for follower in req_followers:
                        self.translation_ready.emit(follower.index, result, follower.string_id, "api")
                        success += 1
                        done += 1
                        self.progress.emit(done, total)
                else:
                    errors += 1 + len(req_followers)
                    done += 1 + len(req_followers)
                    self.progress.emit(done, total)

        self.finished.emit(success, errors)
