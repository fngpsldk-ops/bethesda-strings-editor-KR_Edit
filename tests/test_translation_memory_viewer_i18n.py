"""Regression test: the Translation Memory viewer dialog (Translation ->
View Translation Memory...) was showing entirely in English even with the
Korean UI language selected.

Two distinct causes, both fixed:
  1. TranslationMemoryViewerDialog's own strings were correctly wrapped in
     self.tr(), but the "TranslationMemoryViewerDialog" context was
     completely missing from gui/translations/ko_KR.ts -- this dialog's
     strings were simply never extracted/translated at all (confirmed: zero
     matches for its source text anywhere in the .ts before this fix).
  2. The "Original"/"Translated" column headers were a plain class-level
     list literal (`HEADERS = ["Original", "Translated"]`), never wrapped in
     tr() at all -- self.tr() needs an instance and can't be called at
     class-definition time, so no .ts entry could ever have fixed this on
     its own; the code itself had to move the header text into a tr() call
     made at lookup time (headerData()).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("PySide6")
from PySide6.QtCore import QTranslator, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication([])

_QM_PATH = Path(__file__).parent.parent / "gui" / "translations" / "ko_KR.qm"


@pytest.fixture()
def korean_translator():
    """Install the compiled Korean catalog for the duration of a test, then
    remove it so other tests aren't affected."""
    translator = QTranslator()
    loaded = translator.load(str(_QM_PATH))
    assert loaded, f"Failed to load {_QM_PATH} -- run scripts/compile_translations.sh"
    app.installTranslator(translator)
    yield translator
    app.removeTranslator(translator)


def test_ts_source_has_translation_memory_viewer_context():
    ts_path = Path(__file__).parent.parent / "gui" / "translations" / "ko_KR.ts"
    content = ts_path.read_text(encoding="utf-8")
    assert "<name>TranslationMemoryViewerDialog</name>" in content
    assert "Filter by original or translated text" in content


def test_dialog_strings_are_korean_with_translator_installed(korean_translator):
    from gui.translation_memory import TranslationMemory
    from gui.translation_memory_viewer import TranslationMemoryViewerDialog

    tm = TranslationMemory()
    tm._by_id = {1: "번역1"}
    tm._by_src = {
        "Open the door.": "문을 여십시오.",
        "Close the door.": "문을 닫으십시오.",
    }

    dlg = TranslationMemoryViewerDialog(tm=tm)
    try:
        assert dlg.windowTitle() == "번역 메모리"
        assert dlg.edit_search.placeholderText() == "원문 또는 번역문으로 필터링…"
        assert "로드됨" in dlg.lbl_summary.text()
        assert "Translation Memory loaded" not in dlg.lbl_summary.text()

        buttons = dlg.findChildren(QPushButton)
        assert any(b.text() == "닫기" for b in buttons)

        dlg.edit_search.setText("door")
        app.processEvents()
        assert "일치" in dlg.lbl_hint.text()
        assert "match" not in dlg.lbl_hint.text()
    finally:
        dlg.deleteLater()


def test_empty_tm_message_is_korean(korean_translator):
    from gui.translation_memory_viewer import TranslationMemoryViewerDialog

    dlg = TranslationMemoryViewerDialog(tm=None)
    try:
        assert "로드된 번역 메모리가 없습니다" in dlg.lbl_summary.text()
        assert "No Translation Memory" not in dlg.lbl_summary.text()
    finally:
        dlg.deleteLater()


def test_table_headers_are_korean(korean_translator):
    from gui.translation_memory_viewer import _TmTableModel

    model = _TmTableModel([("Open the door.", "문을 여십시오.")])
    assert model.headerData(0, Qt.Horizontal) == "원본"
    assert model.headerData(1, Qt.Horizontal) == "번역됨"


def test_table_headers_fall_back_to_english_without_translator():
    # Sanity check: without a Korean translator installed, headers should
    # still work (fall back to the literal source text) rather than crash --
    # confirms headerData()'s per-call tr() didn't introduce a hard
    # dependency on a translator being present.
    from gui.translation_memory_viewer import _TmTableModel

    model = _TmTableModel([("a", "b")])
    assert model.headerData(0, Qt.Horizontal) in ("Original", "원본")
    assert model.headerData(1, Qt.Horizontal) in ("Translated", "번역됨")


def test_qm_catalog_still_covers_the_whole_app_not_just_one_dialog():
    # Regression guard for a real incident: regenerating this dialog's
    # translations by running lupdate scoped to ONLY
    # translation_memory_viewer.py marked every OTHER file's strings as
    # "obsolete" (lupdate only "sees" whatever source files it's given;
    # anything already in the .ts tied to an unscanned file gets treated as
    # no-longer-used) -- lrelease then correctly excludes obsolete entries
    # from the compiled .qm, silently dropping ~99% of the app's Korean
    # localization (verified: this dropped ko_KR.qm from ~201KB to ~1.5KB).
    # The fix is procedural (always run lupdate across every gui/*.py file,
    # never a single file in isolation) but this guards against it
    # regressing unnoticed: strings from an ENTIRELY unrelated part of the
    # app (main_window's UI) must still resolve correctly through the same
    # compiled catalog the TM viewer's translations live in.
    from PySide6.QtWidgets import QDialog

    translator = QTranslator()
    assert translator.load(str(_QM_PATH))
    app.installTranslator(translator)
    try:
        class MainWindow(QDialog):
            pass

        mw = MainWindow()
        assert mw.tr("Force &Retranslate Selected") == "선택 항목 강제 재번역(&R)"
        assert mw.tr("TM: {n} entries") == "TM: {n}개 항목"
    finally:
        app.removeTranslator(translator)


def test_qm_file_size_is_not_a_near_empty_stub():
    # A crude but effective tripwire for the same incident: a healthy
    # catalog compiled from the full 44-file source set is on the order of
    # ~200KB. A regression that scopes lupdate down to a handful of files
    # again would produce something in the low single-digit KB range.
    size = _QM_PATH.stat().st_size
    assert size > 100_000, f"ko_KR.qm is only {size} bytes -- looks truncated"
