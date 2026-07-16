"""Regression test: Advanced Search/Replace's "Replace All" must write
corrected translations into the translation cache, the same way the
string-edit popup and inline in-table edit already do.

Bug: AdvancedSearchDialog._do_replace_all() called
StringTableModel.set_translated_text() directly, which updates the table
but never emits string_manually_corrected — the ONE signal
main_window._on_string_corrected listens for to write into the cache. Two
other callers of set_translated_text() had this exact same gap fixed
before (see the comments in string_table.py's setData() and its
StringEditDialog handler); Replace All was the third, still-missing case.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

QApplication.instance() or QApplication([])

from gui.advanced_search_dialog import AdvancedSearchDialog  # noqa: E402
from gui.string_table import StringTableModel  # noqa: E402
from gui.translation_cache import TranslationCache  # noqa: E402
from gui.ollama_worker import OllamaWorker  # noqa: E402


def _make_model_with_rows(rows: list) -> StringTableModel:
    model = StringTableModel()
    model._data = [
        {
            "id": i,
            "kind": "",
            "original": r["original"],
            "translated": r["translated"],
            "length": 0,
            "offset": 0,
            "status": "translated",
        }
        for i, r in enumerate(rows)
    ]
    return model


class _ParentStub(QWidget):
    """Minimal stand-in for MainWindow: AdvancedSearchDialog._do_replace_all
    only ever touches `parent().table_model`."""

    def __init__(self, table_model):
        super().__init__()
        self.table_model = table_model


def test_replace_all_emits_string_manually_corrected():
    model = _make_model_with_rows([
        {"original": "Open the door after unlocking it.",
         "translated": "잠금을 해제한 후에 문을 여십시오."},
    ])
    parent = _ParentStub(model)
    dlg = AdvancedSearchDialog(parent=parent)
    dlg.txt_search.setText("해제한 후에")
    dlg.txt_replace.setText("해제한 다음")

    received = []
    model.string_manually_corrected.connect(lambda row, orig: received.append((row, orig)))

    dlg._do_replace_all()

    assert model._data[0]["translated"] == "잠금을 해제한 다음 문을 여십시오."
    assert received == [(0, "Open the door after unlocking it.")]


def test_replace_all_writes_through_to_cache_via_real_handler():
    # Exercises the REAL main_window._on_string_corrected against a
    # lightweight stub carrying only the attributes it reads, so this test
    # verifies the actual production cache-key logic, not a reimplementation.
    from gui.main_window import MainWindow

    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    worker = OllamaWorker(model="gemma4:26b-a4b-it-qat", enable_term_protection=False)
    worker.translation_cache = None
    worker.translation_memory = None
    worker.glossary_manager = None

    model = _make_model_with_rows([
        {"original": "Open the door after unlocking it.",
         "translated": "잠금을 해제한 후에 문을 여십시오."},
    ])
    parent = _ParentStub(model)

    class _Settings:
        enable_cache = True
        default_source_lang = "en"
        default_target_lang = "ko"

    class _WindowStub:
        _pre_estimator = None
        settings = _Settings()
        ollama_worker = worker
        translation_cache = cache
        table_model = model

    stub = _WindowStub()
    model.string_manually_corrected.connect(
        lambda row, orig: MainWindow._on_string_corrected(stub, row, orig)
    )

    dlg = AdvancedSearchDialog(parent=parent)
    dlg.txt_search.setText("해제한 후에")
    dlg.txt_replace.setText("해제한 다음")
    dlg._do_replace_all()

    original = "Open the door after unlocking it."
    key = TranslationCache.make_key(
        original, worker.model, "en", "ko", worker._settings_hash_for(original)
    )
    assert cache.get(key) == "잠금을 해제한 다음 문을 여십시오."


def test_replace_all_skips_rows_with_no_match_no_spurious_emit():
    model = _make_model_with_rows([
        {"original": "Unrelated string.", "translated": "관련 없는 문자열."},
    ])
    parent = _ParentStub(model)
    dlg = AdvancedSearchDialog(parent=parent)
    dlg.txt_search.setText("존재하지않는패턴")
    dlg.txt_replace.setText("x")

    received = []
    model.string_manually_corrected.connect(lambda row, orig: received.append((row, orig)))
    dlg._do_replace_all()

    assert received == []
    assert model._data[0]["translated"] == "관련 없는 문자열."
