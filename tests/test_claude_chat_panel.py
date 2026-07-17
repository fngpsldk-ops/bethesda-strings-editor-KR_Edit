"""Regression tests for the Claude AI Assistant panel (claude_chat_panel.py):

  1. "Use as Translation" (Apply) was fundamentally broken: it re-parsed
     QTextEdit.toPlainText() for ```…``` fences, but the HTML-formatting step
     in _on_reply()/_on_review_done() already replaces those fences with
     <pre> tags before Apply could ever read them — the search matched
     nothing for every completed message, always. Fixed by storing the raw
     (pre-formatting) reply text and reading from that instead.
  2. Reviewing/Suggesting never accounted for the speaker's established voice
     (Character Profile: formality, tone, custom instructions) even though
     the codebase already has this data (ProfileManager/ProfileAssignments,
     used during actual translation). Fixed by threading a character-context
     string through set_current_string() into both the review and
     suggest/chat system prompts.
  3. Applying a Claude suggestion never wrote through to the translation
     cache (the same set_translated_text()-without-string_manually_corrected
     gap already found and fixed for the string-edit popup, inline in-table
     edit, and Advanced Search/Replace's Replace All -- this was the fourth
     occurrence).
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
from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.instance() or QApplication([])

from gui.claude_chat_panel import ClaudeChatPanel  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.string_table import StringTableModel  # noqa: E402
from gui.translation_cache import TranslationCache  # noqa: E402


# ── 1. Apply extraction ─────────────────────────────────────────────────────

def test_apply_extracts_suggestion_after_suggest_reply():
    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "", source_lang="en", target_lang="ko")
    panel._begin_claude_stream()
    panel._on_reply(
        "Here is a suggestion:\n\n```\n문을 여십시오.\n```\n\nLet me know if you need changes."
    )
    assert panel._btn_apply.isEnabled()

    applied = []
    panel.apply_translation.connect(applied.append)
    panel._do_apply()
    assert applied == ["문을 여십시오."]


def test_apply_extracts_suggestion_after_review_with_improved_version():
    panel = ClaudeChatPanel()
    panel.set_current_string(2, "Open the door.", "잘못된번역", source_lang="en", target_lang="ko")
    panel._on_review_done(
        "VERDICT: ISSUES_FOUND\n\nIssues: awkward phrasing.\n\n"
        "Improved version:\n```\n문을 여십시오.\n```"
    )
    assert panel._btn_apply.isEnabled()

    applied = []
    panel.apply_translation.connect(applied.append)
    panel._do_apply()
    assert applied == ["문을 여십시오."]


def test_apply_disabled_and_noop_when_no_code_block():
    from unittest.mock import patch

    panel = ClaudeChatPanel()
    panel.set_current_string(3, "Open the door.", "", source_lang="en", target_lang="ko")
    panel._begin_claude_stream()
    panel._on_reply("This translation looks fine, nothing to change.")
    assert not panel._btn_apply.isEnabled()

    applied = []
    panel.apply_translation.connect(applied.append)
    # _do_apply() shows a blocking QMessageBox when no code block is found;
    # patch it out so this test doesn't hang waiting for a modal that has
    # no user to click it in a headless run.
    with patch("gui.claude_chat_panel.QMessageBox.information"):
        panel._do_apply()
    assert applied == []


def test_switching_to_a_different_string_invalidates_pending_suggestion():
    # A suggestion generated for one string must never be silently applicable
    # to a different, later-selected row.
    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "", source_lang="en", target_lang="ko")
    panel._begin_claude_stream()
    panel._on_reply("```\n문을 여십시오.\n```")
    assert panel._btn_apply.isEnabled()

    panel.set_current_string(99, "A different string.", "", source_lang="en", target_lang="ko")
    assert not panel._btn_apply.isEnabled()
    assert panel._last_reply_raw == ""


def test_clear_resets_apply_state():
    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "", source_lang="en", target_lang="ko")
    panel._begin_claude_stream()
    panel._on_reply("```\n문을 여십시오.\n```")
    assert panel._btn_apply.isEnabled()

    panel._do_clear()
    assert not panel._btn_apply.isEnabled()
    assert panel._last_reply_raw == ""


# ── 2. Character-voice context ──────────────────────────────────────────────

def _profiles(tmp_path):
    from bethesda_strings.character_profiles import CharacterProfile, ProfileAssignments, ProfileManager

    pm = ProfileManager(tmp_path)
    pa = ProfileAssignments(tmp_path)
    profile = CharacterProfile(
        profile_id="devout_convert", name="독실한 개종자", description="",
        color="#8888ff", temperature=None,
        system_addendum="말투: 경건하고 격식 있는 존댓말. 종교적 어휘 다수 사용.",
        formality="formal", allow_contractions=False,
    )
    pm._profiles["devout_convert"] = profile
    pa.set(0x01004186, "devout_convert")
    return pm, pa


def test_character_context_lookup_returns_assigned_profile(tmp_path):
    pm, pa = _profiles(tmp_path)

    class Stub:
        _profile_assignments = pa
        _profile_manager = pm

    ctx = MainWindow._character_context_for_row(Stub(), 0x01004186)
    assert "독실한 개종자" in ctx
    assert "formal" in ctx
    assert "경건하고 격식" in ctx


def test_character_context_lookup_empty_when_unassigned(tmp_path):
    pm, pa = _profiles(tmp_path)

    class Stub:
        _profile_assignments = pa
        _profile_manager = pm

    assert MainWindow._character_context_for_row(Stub(), 0x999999) == ""


def test_review_translation_prompt_includes_character_context():
    from gui.claude_client import ClaudeClient

    client = ClaudeClient.__new__(ClaudeClient)
    client.model = "claude-sonnet-4-6"
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            class R:
                content = [type("C", (), {"text": "VERDICT: GOOD"})()]
            return R()

    client._client = type("C", (), {"messages": FakeMessages()})()
    client.review_translation(
        "Open the door.", "문을 여십시오.", "en", "ko",
        character_context="Character: 독실한 개종자 (formal register)\n말투: 경건하고 격식 있는 존댓말.",
    )
    sys_text = captured["system"][0]["text"]
    assert "독실한 개종자" in sys_text
    assert "established voice" in sys_text


def test_review_translation_prompt_omits_character_section_when_absent():
    from gui.claude_client import ClaudeClient

    client = ClaudeClient.__new__(ClaudeClient)
    client.model = "claude-sonnet-4-6"
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            class R:
                content = [type("C", (), {"text": "VERDICT: GOOD"})()]
            return R()

    client._client = type("C", (), {"messages": FakeMessages()})()
    client.review_translation("Open the door.", "문을 여십시오.", "en", "ko")
    sys_text = captured["system"][0]["text"]
    assert "established voice" not in sys_text


def test_suggest_system_prompt_includes_character_context():
    panel = ClaudeChatPanel()
    panel.set_current_string(
        1, "Open the door.", "", source_lang="en", target_lang="ko",
        character_context="Character: 독실한 개종자 (formal register)\n격식체 사용.",
    )
    prompt = panel._system_prompt()
    assert "독실한 개종자" in prompt


# ── 3. Apply writes through to the translation cache ────────────────────────

def test_apply_claude_translation_writes_through_to_cache():
    from PySide6.QtWidgets import QMainWindow
    from gui.ollama_worker import OllamaWorker

    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    worker = OllamaWorker(model="gemma4:26b-a4b-it-qat", enable_term_protection=False)
    worker.translation_cache = None
    worker.translation_memory = None
    worker.glossary_manager = None

    model = StringTableModel()
    model._data = [
        {"id": 1, "original": "Open the door.", "translated": "잘못된번역", "status": "translated"},
    ]

    class Stub(QMainWindow):
        def __init__(self):
            super().__init__()
            self.table_model = model
            self.table_view = type("V", (), {
                "selectionModel": lambda self_: type("SM", (), {
                    "selectedRows": lambda self__: [type("I", (), {"row": lambda self___: 0})()]
                })()
            })()

            class _Settings:
                enable_cache = True
                default_source_lang = "en"
                default_target_lang = "ko"

            self.settings = _Settings()
            self.ollama_worker = worker
            self.translation_cache = cache
            self._pre_estimator = None

    stub = Stub()
    model.string_manually_corrected.connect(
        lambda row, orig: MainWindow._on_string_corrected(stub, row, orig)
    )

    MainWindow._apply_claude_translation(stub, "제대로 된 번역.")

    assert model._data[0]["translated"] == "제대로 된 번역."
    key = TranslationCache.make_key(
        "Open the door.", worker.model, "en", "ko",
        worker._settings_hash_for("Open the door."),
    )
    assert cache.get(key) == "제대로 된 번역."
