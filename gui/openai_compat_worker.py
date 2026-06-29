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
PROMPT_VERSION = 1


class OpenAICompatWorker(QObject):
    """Translate via an OpenAI-compatible Chat Completions API.

    Signals mirror OllamaWorker exactly:
        translation_ready(index:int, text:str, string_id:object)
        progress(done:int, total:int)
        error(message:str)
        finished(success:int, errors:int)
    """

    translation_ready = Signal(int, str, object)
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
        temperature: float = 0.3,
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

        self._stop_flag = False
        self._mutex = QMutex()

        # Client is created lazily on first use so the app can start
        # even if the API key has not been configured yet.
        self._client = None

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

    # ── client (lazy) ─────────────────────────────────────────────────────────────
    def _get_client(self):
        """Return (or create) the OpenAI-compatible client.  Raises on missing key."""
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "OpenAI-compatible API key is not set.\n"
                    "Please enter your API key in Settings > Cloud AI Backend."
                )
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    # ── settings hash (cache invalidation) ─────────────────────────────────────
    def _compute_settings_hash(self) -> str:
        """Short hash of glossary contents + prompt version.

        Changing the glossary or bumping PROMPT_VERSION changes this hash, so
        old cache entries are bypassed and re-translated automatically.
        """
        parts = [f"pv{PROMPT_VERSION}"]
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

        def _translate_one(req):
            with QMutexLocker(self._mutex):
                if self._stop_flag:
                    return req.index, None, req.string_id

            source_text = req.original_text.replace("\r\n", "\n").replace("\r", "\n")

            # Skip configured string types
            if self.skipped_types:
                try:
                    from gui.string_type_detector import classify
                    if classify(source_text).name in self.skipped_types:
                        return req.index, None, req.string_id
                except Exception:
                    pass

            # Cache lookup
            cache_key = None
            if self.translation_cache:
                cache_key = self._make_cache_key(source_text)
                cached = self.translation_cache.get(cache_key)
                if cached:
                    return req.index, cached, req.string_id

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

            # OpenAI-compatible Chat Completions call
            try:
                resp = self._get_client().chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self.temperature,
                )
                result = (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                logger.error(
                    "OpenAI-compat translation error idx=%d string_id=%s: %s",
                    req.index, getattr(req, "string_id", "?"), exc,
                )
                return req.index, None, req.string_id

            if not result:
                return req.index, None, req.string_id

            # Restore protected terms
            if token_map and self.term_protector:
                try:
                    result = self.term_protector.restore(result, token_map)
                except Exception as exc:
                    logger.warning("Term restore failed: %s", exc)

            # Store in cache
            if cache_key and self.translation_cache:
                self.translation_cache.put(cache_key, result)

            return req.index, result, req.string_id

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures: List[Future] = [pool.submit(_translate_one, req) for req in requests]
            for fut in as_completed(futures):
                with QMutexLocker(self._mutex):
                    stopped = self._stop_flag
                if stopped:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    idx, result, string_id = fut.result()
                except Exception as exc:
                    errors += 1
                    self.error.emit(str(exc))
                    done += 1
                    self.progress.emit(done, total)
                    continue

                if result is not None:
                    self.translation_ready.emit(idx, result, string_id)
                    success += 1
                else:
                    errors += 1

                done += 1
                self.progress.emit(done, total)

        self.finished.emit(success, errors)
