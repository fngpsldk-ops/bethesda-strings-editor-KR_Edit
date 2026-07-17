"""Regression tests for Force Retranslate (Ctrl+Alt+T) actually bypassing
the translation cache read (and overwriting the stale entry), across all
three worker backends.

Bug: _force_retranslate_selected() cleared the ROW's own translated text
and re-ran the normal translate flow, but never touched the separate
translation-cache STORE. Since every request still went through the normal
cache-read path, a cache hit silently re-served the exact same (possibly
wrong) cached value with zero fresh API call -- Force Retranslate was a
no-op whenever a cache entry already existed, which is the common case
(a prior batch is what populated the cache to begin with).

Fix: TranslationRequest.force_retranslate, threaded through main_window's
_start_translation/translate_selected, makes all three workers skip the
cache READ (evicting the stale entry) while still consulting Translation
Memory normally (TM is curated reference material, not the AI's own past
output, so force-retranslate has no reason to override it). The end-of-
request cache WRITE was already unconditional in all three workers, so the
fresh result overwrites the evicted entry automatically.
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.instance() or QApplication([])

from unittest.mock import patch  # noqa: E402

from gui.ollama_worker import OllamaWorker, TranslationMemory, TranslationRequest  # noqa: E402
from gui.translation_cache import TranslationCache  # noqa: E402


def _tm_with(source: str, translation: str) -> TranslationMemory:
    # TranslationMemory.__bool__ is keyed off _by_id, not _by_src -- a TM
    # loaded only via _by_src (as a hand-built test fixture might do) would
    # evaluate as falsy and be skipped entirely by every "if self.translation_memory"
    # gate. Populate both so the fixture behaves like a real loaded TM.
    tm = TranslationMemory()
    tm._by_id = {999: translation}
    tm._by_src = {source: translation}
    return tm


# ── OllamaWorker ─────────────────────────────────────────────────────────────

def test_ollama_normal_request_still_serves_cache():
    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = OllamaWorker(model="gemma4:26b-a4b-it-qat", enable_term_protection=False)
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(index=0, string_id=1, original_text="Open the door.",
                              source_lang="en", target_lang="ko")
    key = TranslationCache.make_key(req.original_text, w.model, "en", "ko",
                                     w._settings_hash_for(req.original_text))
    cache.set(key, "기존 캐시 값.")

    with patch.object(OllamaWorker, "_stream_ollama",
                       side_effect=AssertionError("must not call the API")):
        result = w._translate_single(req)
    assert result == "기존 캐시 값."


def test_ollama_force_retranslate_bypasses_cache_and_overwrites():
    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = OllamaWorker(model="gemma4:26b-a4b-it-qat", enable_term_protection=False)
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(index=0, string_id=1, original_text="Open the door.",
                              source_lang="en", target_lang="ko",
                              force_retranslate=True)
    key = TranslationCache.make_key(req.original_text, w.model, "en", "ko",
                                     w._settings_hash_for(req.original_text))
    cache.set(key, "기존(잘못된) 캐시 값.")

    with patch.object(OllamaWorker, "_stream_ollama", return_value="새로 번역된 값."):
        result = w._translate_single(req)

    assert result == "새로 번역된 값."
    assert cache.get(key) == "새로 번역된 값."


def test_ollama_force_retranslate_preflight_path_also_bypasses_cache():
    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = OllamaWorker(model="gemma4:26b-a4b-it-qat", enable_term_protection=False, max_workers=1)
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(index=0, string_id=1, original_text="Open the door.",
                              source_lang="en", target_lang="ko",
                              force_retranslate=True)
    key = TranslationCache.make_key(req.original_text, w.model, "en", "ko",
                                     w._settings_hash_for(req.original_text))
    cache.set(key, "기존(잘못된) 캐시 값.")

    results = []
    w.translation_ready.connect(lambda i, txt, sid, src: results.append((txt, src)))
    with patch.object(OllamaWorker, "_stream_ollama", return_value="배치로 새로 번역됨."):
        w.translate_batch([req])

    assert results == [("배치로 새로 번역됨.", "api")]
    assert cache.get(key) == "배치로 새로 번역됨."


def test_ollama_force_retranslate_still_respects_translation_memory():
    tm = _tm_with("Open the door.", "공식 TM 번역.")
    w = OllamaWorker(model="gemma4:26b-a4b-it-qat", enable_term_protection=False)
    w.translation_cache = None
    w.translation_memory = tm
    w.glossary_manager = None

    req = TranslationRequest(index=0, string_id=1, original_text="Open the door.",
                              source_lang="en", target_lang="ko",
                              force_retranslate=True)
    with patch.object(OllamaWorker, "_stream_ollama",
                       side_effect=AssertionError("TM hit must short-circuit before the API")):
        result = w._translate_single(req)

    assert result == "공식 TM 번역."


# ── OpenAICompatWorker ───────────────────────────────────────────────────────

def test_openai_compat_force_retranslate_bypasses_cache_and_overwrites():
    from gui.openai_compat_worker import OpenAICompatWorker

    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = OpenAICompatWorker(api_key="x", model="gemini-2.5-flash", base_url="http://x/")
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(index=0, string_id=1, original_text="Open the door.",
                              source_lang="en", target_lang="ko",
                              force_retranslate=True)
    key = w._make_cache_key(req.original_text)
    cache.set(key, "기존(잘못된) 캐시 값.")

    results = []
    w.translation_ready.connect(lambda i, txt, sid, src: results.append((txt, src)))

    with patch.object(OpenAICompatWorker, "_call_api", return_value="새로 번역된 값."):
        w.translate_batch([req])

    assert cache.get(key) == "새로 번역된 값."
    assert results and results[0][0] == "새로 번역된 값."


def test_openai_compat_normal_request_still_serves_cache():
    from gui.openai_compat_worker import OpenAICompatWorker

    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = OpenAICompatWorker(api_key="x", model="gemini-2.5-flash", base_url="http://x/")
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(index=0, string_id=1, original_text="Open the door.",
                              source_lang="en", target_lang="ko")
    key = w._make_cache_key(req.original_text)
    cache.set(key, "기존 캐시 값.")

    results = []
    w.translation_ready.connect(lambda i, txt, sid, src: results.append((txt, src)))

    with patch.object(OpenAICompatWorker, "_call_api",
                       side_effect=AssertionError("must not call the API")):
        w.translate_batch([req])

    assert results == [("기존 캐시 값.", "cache")]


# ── ClaudeTranslationWorker ──────────────────────────────────────────────────

def test_claude_worker_force_retranslate_bypasses_cache_and_overwrites(monkeypatch):
    from gui.claude_translation_worker import ClaudeTranslationWorker

    # ClaudeClient's constructor talks to the Anthropic SDK; stub it out so
    # this test only exercises the cache-bypass logic, not real API auth.
    monkeypatch.setattr(
        "gui.claude_client.ClaudeClient.__init__", lambda self, api_key, model: None
    )
    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = ClaudeTranslationWorker(api_key="x", model="claude-sonnet-5")
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(index=0, string_id=1, original_text="Open the door.",
                              source_lang="en", target_lang="ko",
                              force_retranslate=True)
    key = TranslationCache.make_key(
        req.original_text, w.model, w.source_lang, w.target_lang,
        w._settings_hash_for(req.original_text),
    )
    cache.set(key, "기존(잘못된) 캐시 값.")

    results = []
    w.translation_ready.connect(lambda i, txt, sid: results.append(txt))
    with patch.object(w._claude, "translate", return_value="새로 번역된 값."):
        w.translate_batch([req])

    assert cache.get(key) == "새로 번역된 값."
    assert results == ["새로 번역된 값."]


def test_claude_worker_normal_request_still_serves_cache(monkeypatch):
    from gui.claude_translation_worker import ClaudeTranslationWorker

    monkeypatch.setattr(
        "gui.claude_client.ClaudeClient.__init__", lambda self, api_key, model: None
    )
    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = ClaudeTranslationWorker(api_key="x", model="claude-sonnet-5")
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(index=0, string_id=1, original_text="Open the door.",
                              source_lang="en", target_lang="ko")
    key = TranslationCache.make_key(
        req.original_text, w.model, w.source_lang, w.target_lang,
        w._settings_hash_for(req.original_text),
    )
    cache.set(key, "기존 캐시 값.")

    results = []
    w.translation_ready.connect(lambda i, txt, sid: results.append(txt))
    with patch.object(w._claude, "translate",
                       side_effect=AssertionError("must not call the API")):
        w.translate_batch([req])

    assert results == ["기존 캐시 값."]
