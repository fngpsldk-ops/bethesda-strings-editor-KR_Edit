"""Regression test: AI Quality Check (Ollama-based) must use whatever model
is currently selected for translation (settings.ollama_model), not a
separately configured, hardcoded default ("qcgemma4-st").

The old default was a specially fine-tuned QC-only model from the upstream
Ukrainian project. Most users (including anyone on the KR fork) never pull
that model into Ollama, so enabling AI QC either errored out or silently
did nothing. Reusing the model already loaded for translation guarantees it
exists locally and needs no separate setup — and lets the person pick
whichever model they've decided gives the best results (e.g.
gemma4:26b-a4b-it-qat) without a second, easy-to-forget setting to keep
in sync.
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

from unittest.mock import MagicMock, patch  # noqa: E402

from gui.app_settings import AppSettings  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.string_table import StringTableModel  # noqa: E402


class _FakeAiQcWorker:
    """Records the constructor args AiQcWorker was called with, then
    completes immediately (no real thread / Ollama call)."""

    captured: dict = {}

    def __init__(self, items, ollama_url, model, max_workers=4):
        _FakeAiQcWorker.captured = {
            "items": items, "ollama_url": ollama_url,
            "model": model, "max_workers": max_workers,
        }
        self.result = MagicMock()
        self.result.connect = lambda cb: None
        self.progress = MagicMock()
        self.progress.connect = lambda cb: None
        self.finished = MagicMock()
        self.finished.connect = lambda cb: None

    def start(self):
        pass

    def cancel(self):
        pass


class _FakeEventLoop:
    """_run_ai_qc blocks on QEventLoop().exec() until the worker's finished
    signal fires loop.quit(). The fake worker above never actually emits
    that signal (no real QThread), so exec() must be a no-op here instead."""

    def exec(self):
        return 0

    def quit(self):
        pass


class _MainWindowStub(QWidget):
    """Minimal stand-in carrying only what _run_ai_qc reads: current_file,
    table_model, settings, and (via QWidget) self.tr()/parent-for-dialogs."""

    def __init__(self, model: StringTableModel, settings: AppSettings):
        super().__init__()
        self.current_file = "dummy.esp"
        self.table_model = model
        self.settings = settings


def _model_with_one_translated_row() -> StringTableModel:
    model = StringTableModel()
    model._data = [
        {"id": 1, "original": "Open the door.", "translated": "문을 여십시오.",
         "status": "translated"},
    ]
    return model


def test_ai_qc_uses_currently_selected_ollama_model():
    settings = AppSettings()
    settings.ollama_model = "gemma4:26b-a4b-it-qat"
    settings.ollama_url = "http://localhost:11434"
    stub = _MainWindowStub(_model_with_one_translated_row(), settings)

    with patch("gui.ai_qc_worker.AiQcWorker", _FakeAiQcWorker), \
         patch("PySide6.QtCore.QEventLoop", _FakeEventLoop):
        MainWindow._run_ai_qc(stub, [])

    assert _FakeAiQcWorker.captured["model"] == "gemma4:26b-a4b-it-qat"
    assert _FakeAiQcWorker.captured["ollama_url"] == "http://localhost:11434"


def test_ai_qc_follows_model_change_without_a_separate_setting():
    # Same settings object, model switched between two runs -- AI QC must
    # track it automatically, with no separate "AI QC model" field to update.
    settings = AppSettings()
    settings.ollama_url = "http://localhost:11434"
    model = _model_with_one_translated_row()

    settings.ollama_model = "gemma4:12b-it-qat"
    stub1 = _MainWindowStub(model, settings)
    with patch("gui.ai_qc_worker.AiQcWorker", _FakeAiQcWorker), \
         patch("PySide6.QtCore.QEventLoop", _FakeEventLoop):
        MainWindow._run_ai_qc(stub1, [])
    assert _FakeAiQcWorker.captured["model"] == "gemma4:12b-it-qat"

    settings.ollama_model = "gemma4:26b-a4b-it-qat"
    stub2 = _MainWindowStub(model, settings)
    with patch("gui.ai_qc_worker.AiQcWorker", _FakeAiQcWorker), \
         patch("PySide6.QtCore.QEventLoop", _FakeEventLoop):
        MainWindow._run_ai_qc(stub2, [])
    assert _FakeAiQcWorker.captured["model"] == "gemma4:26b-a4b-it-qat"


def test_settings_dialog_no_longer_has_separate_ai_qc_model_field():
    from gui.app_settings import set_config_dir_override

    set_config_dir_override(Path(tempfile.mkdtemp()))

    class _StubThemeManager:
        available_themes = ["Slate"]
        def get_theme_description(self, name): return ""
        def get_hint_color(self, name): return "#888888"
        def effective_theme(self, name): return name

    from gui.settings_dialog import SettingsDialog

    settings = AppSettings()
    settings.ollama_model = "gemma4:26b-a4b-it-qat"
    dlg = SettingsDialog(settings, parent=None, theme_manager=_StubThemeManager())

    assert not hasattr(dlg, "ai_qc_model_edit")

    dlg.chk_enable_ai_qc.setChecked(True)
    dlg.apply_to_settings(settings)
    assert settings.enable_ai_qc is True
    # ollama_model itself (set via the main model combo, unrelated to AI QC)
    # is what AI QC now rides on -- untouched by this dialog's AI QC section.
    assert settings.ollama_model == "gemma4:26b-a4b-it-qat"
