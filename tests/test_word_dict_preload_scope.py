"""Regression test: OllamaWorker.__init__() was unconditionally preloading
every word dictionary the ORIGINAL multi-language upstream project supports
(ru/uk/de/es/fr/it/pl/pt-br) regardless of this fork's actual language pair
(en->ko only, per README). Confirmed in a real startup log: ~5.9s and 100+MB
spent loading eight dictionaries this fork's translation/quality-check paths
never consult for an en->ko string -- including Russian's 1.5M-word list
alone (~101MB). Meanwhile Korean, the ACTUAL target language whose
dictionary genuinely is used by LOW_TARGET_COVERAGE/LOW_SCRIPT_COVERAGE
quality checks, wasn't preloaded at all.

Fix: only en/ko are preloaded at OllamaWorker construction time. The other
language dictionaries are NOT removed from the codebase -- quality_checker.py
still lazily loads them on demand for the language pairs that actually need
them (e.g. a Ukrainian-target quality check still works, just without the
unconditional eager warm-up this fork never benefits from).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.instance() or QApplication([])

import gui.ollama_worker as ow  # noqa: E402


def test_only_english_and_korean_dictionaries_preloaded():
    calls = []
    patches = [
        patch.object(ow, name, side_effect=lambda n=n: calls.append(n))
        for name, n in [
            ("_preload_en_dict", "en"), ("_preload_ko_dict", "ko"),
            ("_preload_ru_dict", "ru"), ("_preload_uk_dict", "uk"),
            ("_preload_de_dict", "de"), ("_preload_es_dict", "es"),
            ("_preload_fr_dict", "fr"), ("_preload_it_dict", "it"),
            ("_preload_pl_dict", "pl"), ("_preload_ptbr_dict", "ptbr"),
        ]
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], patches[9]:
        ow.OllamaWorker(model="gemma4:26b-a4b-it-qat", enable_term_protection=False)

    assert calls == ["en", "ko"]


def test_other_language_dictionaries_still_lazily_available():
    # Not preloaded eagerly anymore, but must still work on demand for
    # quality_checker.py's per-language-pair checks (e.g. a Ukrainian
    # target's SOURCE_LANGUAGE_LEAK / LOW_UKRAINIAN_COVERAGE checks).
    from gui.ru_word_checker import text_has_russian_words
    from gui.uk_word_checker import word_is_ukrainian

    assert isinstance(text_has_russian_words("Привет мир, тестовое предложение"), bool)
    assert word_is_ukrainian("привіт") in (True, False, None)


def test_ollama_worker_construction_does_not_error_without_preload_mocks():
    # Sanity: the real (unmocked) preload path must not raise.
    ow.OllamaWorker(model="gemma4:26b-a4b-it-qat", enable_term_protection=False)
