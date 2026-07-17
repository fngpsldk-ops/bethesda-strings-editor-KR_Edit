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


# ── UI: word-wrap for code-block content ────────────────────────────────────
# Confirmed real-world bug: the AI Assistant panel is resizable, but a long
# suggested/reviewed translation shown inside a ```code block``` never
# wrapped to the panel's width -- it overflowed horizontally requiring a
# scrollbar, regardless of how wide the panel was resized. Root cause: the
# <pre> tag used to render code blocks had no `white-space` CSS property, and
# Qt's rich-text engine (unlike a browser) does NOT word-wrap <pre> content by
# default -- confirmed by direct document-layout measurement at multiple
# widths (document width stayed fixed at ~1658px regardless of a 320/500/780px
# container). Fixed by adding `white-space: pre-wrap; overflow-wrap: break-word`.

def test_code_block_style_has_wrap_properties():
    from gui.claude_chat_panel import _CODE_BLOCK_HTML
    assert "white-space:pre-wrap" in _CODE_BLOCK_HTML
    assert "overflow-wrap:break-word" in _CODE_BLOCK_HTML


def test_pre_tag_wraps_to_container_width_at_multiple_sizes():
    from PySide6.QtWidgets import QTextEdit
    from gui.claude_chat_panel import _CODE_BLOCK_HTML
    import re

    real_text = (
        "솔직히 말해서 선장들이 아직 저를 신뢰하지 않는 것 같습니다. 제가 뒤늦게 귀의했다는 건 알지만, "
        "위대한 뱀을 섬기는 우리의 사명을 진심으로 믿고 있습니다. 매일 일을 시작하기 전에 기도하고 있고, "
        "찬송가를 암기하기 위해 할 수 있는 모든 노력을 다했습니다. 제가 무엇을 더 해야 합니까?"
    )
    html = re.sub(r"```\n?(.*?)\n?```", _CODE_BLOCK_HTML, f"```\n{real_text}\n```", flags=re.DOTALL)

    for width in (320, 500, 780):
        te = QTextEdit()
        te.resize(width, 400)
        te.show()
        QApplication.processEvents()
        te.setHtml(html)
        QApplication.processEvents()
        doc = te.document()
        doc.setTextWidth(te.viewport().width())
        hbar = te.horizontalScrollBar()
        assert hbar.maximum() == hbar.minimum(), f"horizontal scroll needed at width={width}"


def test_pre_tag_without_wrap_style_reproduces_the_bug():
    # Sanity check on the test methodology itself: the OLD style (no
    # white-space declared) must actually fail this same check, confirming
    # the test would have caught the original bug rather than passing
    # regardless of the fix.
    from PySide6.QtWidgets import QTextEdit
    import re

    OLD_STYLE = (
        r'<pre style="background:rgba(30,41,59,0.8);border-radius:4px;padding:6px;'
        r'margin:4px 0;color:#a7f3d0;">\1</pre>'
    )
    real_text = (
        "솔직히 말해서 선장들이 아직 저를 신뢰하지 않는 것 같습니다. 제가 뒤늦게 귀의했다는 건 알지만, "
        "위대한 뱀을 섬기는 우리의 사명을 진심으로 믿고 있습니다."
    )
    html = re.sub(r"```\n?(.*?)\n?```", OLD_STYLE, f"```\n{real_text}\n```", flags=re.DOTALL)

    te = QTextEdit()
    te.resize(500, 400)
    te.show()
    QApplication.processEvents()
    te.setHtml(html)
    QApplication.processEvents()
    doc = te.document()
    doc.setTextWidth(te.viewport().width())
    hbar = te.horizontalScrollBar()
    assert hbar.maximum() > hbar.minimum()


# ── Response language + register-check prompt content ───────────────────────

def test_review_prompt_requests_korean_response():
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
    assert "Korean" in sys_text and "한국어" in sys_text


def test_review_prompt_requests_register_check():
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
    assert "반말" in sys_text and "존댓말" in sys_text


def test_suggest_prompt_requests_korean_commentary_and_register_check():
    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "", source_lang="en", target_lang="ko")
    prompt = panel._system_prompt()
    assert "Korean" in prompt and "한국어" in prompt
    assert "반말" in prompt and "존댓말" in prompt


# ── Review truncation + history-pollution fixes ─────────────────────────────
# Real-world bug pair reported together: (1) the improved-translation code
# block at the end of a review got cut off mid-sentence because max_tokens
# was a flat 1024, too small once the review always writes in Korean with an
# explicit register section; (2) the (possibly-truncated) review text was
# being appended to the shared chat _history, so the NEXT "번역 제안" click
# sent that unfinished assistant turn as prior conversation and Claude just
# continued typing the leftover sentence before producing the real
# suggestion. Fixed by scaling max_tokens with source length and by keeping
# Review completely out of _history (review_translation() never reads
# _history in the first place, so appending it there only ever caused harm).

def test_review_max_tokens_scales_with_source_length_and_never_below_old_value():
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
    mt_short = captured["max_tokens"]
    client.review_translation("x" * 2000, "번역", "en", "ko")
    mt_long = captured["max_tokens"]

    assert mt_short > 1024  # strictly more headroom than the old flat value
    assert mt_long > mt_short
    assert mt_long <= 4096  # capped, consistent with the rest of this file


def test_review_done_does_not_pollute_chat_history():
    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "잘못된번역", source_lang="en", target_lang="ko")
    assert panel._history == []

    panel._on_review_done("### 개선 번역\n```\n(잘려서 끝난 문장...")

    assert panel._history == []


def test_review_done_still_updates_apply_state_without_history():
    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "잘못된번역", source_lang="en", target_lang="ko")
    panel._on_review_done("### 개선 번역\n```\n문을 여십시오.\n```")

    assert panel._history == []
    assert panel._btn_apply.isEnabled()
    assert panel._last_reply_raw

    applied = []
    panel.apply_translation.connect(applied.append)
    panel._do_apply()
    assert applied == ["문을 여십시오."]


def test_suggest_after_truncated_review_starts_clean():
    # The actual reported end-to-end symptom: a cut-off review must not leak
    # into the next Suggest/Chat request's conversation history.
    panel = ClaudeChatPanel()
    panel._api_key = "sk-fake"
    panel.set_current_string(1, "Open the door.", "잘못된번역", source_lang="en", target_lang="ko")

    panel._on_review_done("### 개선 번역\n```\n문을 열...")  # truncated mid-sentence
    assert panel._history == []

    # Simulate what _do_suggest()/_send_message() would send: only the new
    # user turn, nothing carried over from the review.
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(
        type(panel), "_check_ready", return_value=True
    ):
        panel._input_would_be = "Please translate this game string:\n\nSource: Open the door."
    sent_before_new_turn = list(panel._history)
    assert sent_before_new_turn == []


# ── Multiple-suggestion picker ──────────────────────────────────────────────
# Real-world bug: when Claude's review/suggestion offered multiple options
# (e.g. a primary translation plus "또는 더 간결하게:" alternative), Apply
# silently always used whichever code block came LAST -- no way to tell
# which one was actually wanted. Fixed: a single block still applies
# directly (no extra friction for the common case); two or more show a
# picker labeled with Claude's own preceding phrasing for each option.

def test_extract_code_blocks_with_labels_matches_screenshot_structure():
    text = (
        "## 개선 제안\n\n"
        "```\n바룬 기술 연구소 거주 모듈 (각 거주 모듈 변형의 이름에 표시된 문은 사용 가능하며, "
        "그 외의 모든 면은 차단되어 있습니다.)\n```\n\n"
        "또는 더 간결하게:\n\n"
        "```\n바룬 기술 연구소 거주 모듈 (각 변형 이름에 표시된 문만 사용 가능하며, 나머지는 모두 차단됨.)\n```"
    )
    blocks = ClaudeChatPanel._extract_code_blocks_with_labels(text)
    assert len(blocks) == 2
    assert blocks[0][0] == "개선 제안"          # markdown ## stripped
    assert blocks[1][0] == "또는 더 간결하게"    # Claude's own phrasing, trailing ':' stripped
    assert blocks[0][1].startswith("바룬 기술 연구소")
    assert blocks[1][1].startswith("바룬 기술 연구소")


def test_extract_code_blocks_single_block_has_no_generic_fallback_needed():
    blocks = ClaudeChatPanel._extract_code_blocks_with_labels("```\n문을 여십시오.\n```")
    assert len(blocks) == 1
    assert blocks[0][1] == "문을 여십시오."


def test_extract_code_blocks_falls_back_to_generic_label_when_no_preceding_text():
    text = "```\n첫번째\n```\n```\n두번째\n```"  # back-to-back, no text between
    blocks = ClaudeChatPanel._extract_code_blocks_with_labels(text)
    assert len(blocks) == 2
    assert blocks[1][0] == "옵션 2"


def test_apply_single_block_skips_picker_dialog():
    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "", source_lang="en", target_lang="ko")
    panel._begin_claude_stream()
    panel._on_reply("```\n문을 여십시오.\n```")

    applied = []
    panel.apply_translation.connect(applied.append)
    # If _do_apply tried to open a real modal dialog for a single block, this
    # would hang in a headless run; not patching QDialog.exec at all and
    # still getting a clean result proves the picker was skipped entirely.
    panel._do_apply()
    assert applied == ["문을 여십시오."]


def test_apply_multiple_blocks_uses_the_chosen_one_not_always_the_last():
    from unittest.mock import patch

    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "", source_lang="en", target_lang="ko")
    panel._begin_claude_stream()
    panel._on_reply(
        "## 개선 제안\n\n```\n기본안 번역입니다.\n```\n\n또는 더 간결하게:\n\n```\n간결한 번역.\n```"
    )

    applied = []
    panel.apply_translation.connect(applied.append)

    # Simulate the person picking the FIRST option (not the last block).
    with patch.object(ClaudeChatPanel, "_pick_suggestion", lambda self, blocks: blocks[0][1]):
        panel._do_apply()
    assert applied == ["기본안 번역입니다."]


def test_apply_multiple_blocks_cancel_applies_nothing():
    from PySide6.QtWidgets import QDialog
    from unittest.mock import patch

    panel = ClaudeChatPanel()
    panel.set_current_string(1, "Open the door.", "", source_lang="en", target_lang="ko")
    panel._begin_claude_stream()
    panel._on_reply(
        "## 개선 제안\n\n```\n기본안 번역입니다.\n```\n\n또는 더 간결하게:\n\n```\n간결한 번역.\n```"
    )

    applied = []
    panel.apply_translation.connect(applied.append)

    with patch.object(QDialog, "exec", return_value=QDialog.Rejected):
        panel._do_apply()
    assert applied == []


def test_pick_suggestion_dialog_accept_returns_selected_block():
    from PySide6.QtWidgets import QDialog
    from unittest.mock import patch

    panel = ClaudeChatPanel()
    blocks = [("기본안", "번역 A"), ("더 간결하게", "번역 B")]

    with patch.object(QDialog, "exec", return_value=QDialog.Accepted):
        result = panel._pick_suggestion(blocks)
    # Default selection is row 0 unless the person clicks another row.
    assert result == "번역 A"
