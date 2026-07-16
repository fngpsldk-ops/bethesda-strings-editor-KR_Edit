"""
Tests for OllamaWorker's source-deterministic post-translation fixups:

  * _strip_spurious_br        — drop <br> tags the model invented
  * _unwrap_spurious_brackets — unwrap [LIST] the model put around bare LIST
  * _match_trailing_newlines  — make the trailing newline run match the source

All three are staticmethods, so they can be exercised directly off the class
without constructing an OllamaWorker (which needs a QThread).  The cases below
are taken verbatim from a real mamaylm batch (du_outlaws_01.xml) whose quality
report flagged EXTRA_TAG (<br>) and NEWLINE_COUNT_MISMATCH.

Run with:
    python -m pytest tests/test_ollama_artifact_fixups.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.ollama_worker import OllamaWorker, TranslationRequest  # noqa: E402

strip_br = OllamaWorker._strip_spurious_br
unwrap = OllamaWorker._unwrap_spurious_brackets
match_nl = OllamaWorker._match_trailing_newlines
heal = OllamaWorker._heal_known_artifacts
unwrap_leaked = OllamaWorker._unwrap_leaked_example_brackets
dropped_content = OllamaWorker._translation_dropped_content


# ── _strip_spurious_br ─────────────────────────────────────────────────────────

def test_br_removed_when_source_has_none():
    src = "Sentence one. Sentence two. Sentence three."
    tgt = "Речення одне.<br>\nРечення два.<br>\nРечення три."
    out = strip_br(tgt, src)
    assert "<br>" not in out
    # <br>\n collapses to a single space (sentence boundary preserved)
    assert out == "Речення одне. Речення два. Речення три."


def test_br_count_drops_to_zero_internal_newlines():
    src = "A single paragraph with no breaks at all."
    tgt = "Абзац.<br>\nДругий.<br>\nТретій.<br>\nЧетвертий."
    out = strip_br(tgt, src)
    assert out.count("\n") == 0
    assert out.count("<br>") == 0


def test_br_variants_and_case_insensitive():
    src = "x"
    for tag in ("<br>", "<br/>", "<br />", "<BR>", "<Br/>"):
        assert "br" not in strip_br(f"текст{tag}кінець", src).lower()


def test_br_preserved_up_to_source_count():
    # If the source legitimately carries a <br>, keep exactly that many.
    src = "Line<br>break"
    tgt = "Рядок<br>розрив<br>зайве"
    out = strip_br(tgt, src)
    assert out.count("<br>") == 1


def test_br_at_end_drops_cleanly():
    assert strip_br("текст<br>\n", "текст") == "текст"


def test_br_noop_when_absent():
    assert strip_br("звичайний текст", "plain text") == "звичайний текст"


# ── _unwrap_spurious_brackets ──────────────────────────────────────────────────

def test_list_unwrapped():
    src = "The frontier settlers who flirt with LIST want to believe."
    tgt = "Поселенці кордону, які фліртують із [LIST], хочуть вірити."
    assert unwrap(tgt, src) == "Поселенці кордону, які фліртують із LIST, хочуть вірити."


def test_unwrap_only_when_bare_in_source():
    # Source already brackets it → leave the translation's brackets alone.
    src = "Press [LIST] to continue."
    tgt = "Натисніть [LIST], щоб продовжити."
    assert unwrap(tgt, src) == tgt


def test_unwrap_requires_token_in_source():
    # Token not in source at all → don't touch translation brackets.
    src = "Nothing relevant here."
    tgt = "Тут є [LIST] звідкись."
    assert unwrap(tgt, src) == tgt


def test_unwrap_ignores_short_tokens():
    # 2-letter acronyms (UC) are left alone to avoid false positives.
    src = "Reported to UC command."
    tgt = "Повідомлено [UC] командуванню."
    assert unwrap(tgt, src) == tgt


def test_unwrap_multiple_distinct_tokens():
    src = "A LIST transport and a MAST relay."
    tgt = "Транспорт [LIST] і ретранслятор [MAST]."
    out = unwrap(tgt, src)
    assert "[LIST]" not in out and "[MAST]" not in out
    assert "LIST" in out and "MAST" in out


# ── _match_trailing_newlines ───────────────────────────────────────────────────

def test_trailing_newline_count_bumped_up():
    # Real case: source "…Grav\n\n", model produced "…\n" → must become "\n\n".
    src = "Whispers In The Grav\n\n"
    tgt = "Шепіт у гравітації\n"
    assert match_nl(tgt, src) == "Шепіт у гравітації\n\n"


def test_trailing_newline_count_trimmed_down():
    src = "Title\n"
    tgt = "Заголовок\n\n\n"
    assert match_nl(tgt, src) == "Заголовок\n"


def test_trailing_newline_stripped_when_source_has_none():
    src = "No trailing newline"
    tgt = "Без кінцевого переносу\n\n"
    assert match_nl(tgt, src) == "Без кінцевого переносу"


def test_trailing_newline_added_when_missing():
    src = "Ends with newline\n"
    tgt = "Закінчується переносом"
    assert match_nl(tgt, src) == "Закінчується переносом\n"


def test_trailing_literal_escape_form():
    # Literal two-character \n (backslash + n), as in some UI strings.
    src = "Label\\n\\n"
    tgt = "Мітка\\n"
    assert match_nl(tgt, src) == "Мітка\\n\\n"


def test_trailing_noop_when_equal():
    src = "x\n\n"
    tgt = "у\n\n"
    assert match_nl(tgt, src) == "у\n\n"


# ── _match_trailing_newlines: CRLF sources (real mamaylm RU→UK batch) ───────────
# The Russian source XML is CRLF, but mamaylm emits LF-only output.  A naive
# \n+$ capture under-counts a CRLF trailing run (it stops at the \r between the
# two breaks), so the source's "\r\n\r\n" (2 breaks) became "\n" (1) and tripped
# NEWLINE_COUNT_MISMATCH.  The count must be matched as plain LF.

def test_trailing_crlf_double_break_becomes_two_lf():
    # ID 46444: src "…<0.Name>.\r\n\r\n", model gave "…<0.Name>.\n" → need "\n\n".
    src = "Загружены данные для <0.Name>.\r\n\r\n"
    tgt = "Завантажено дані для <0.Name>.\n"
    out = match_nl(tgt, src)
    assert out == "Завантажено дані для <0.Name>.\n\n"
    assert "\r" not in out  # output stays LF-only to match the model's body
    assert out.count("\n") == src.count("\n")  # QC newline counts now agree


def test_trailing_crlf_single_break():
    src = "Одна строка\r\n"
    tgt = "Один рядок"
    assert match_nl(tgt, src) == "Один рядок\n"


def test_trailing_crlf_trims_excess_to_source_count():
    # Source has one CRLF break; model over-produced three LF — trim to one.
    src = "Заголовок\r\n"
    tgt = "Заголовок\n\n\n"
    assert match_nl(tgt, src) == "Заголовок\n"


def test_trailing_bare_cr_counts_as_one_break():
    src = "Текст\r"
    tgt = "Текст"
    assert match_nl(tgt, src) == "Текст\n"


# ── retry-hint feedback leak (regression) ──────────────────────────────────────
# A QC retry hint is English feedback.  It must NOT sit in the user turn after the
# "To {tgt}:" anchor — a translation-tuned model translates everything there, so
# the hint leaked into the output (e.g. "Переклад зворотного зв'язку — попередня
# спроба…").  The hint belongs in the system prompt only.

def _req(retry_hint: str = "") -> TranslationRequest:
    return TranslationRequest(
        index=0,
        original_text="Hello world.",
        string_id=1,
        source_lang="en",
        target_lang="uk",
        retry_hint=retry_hint,
    )


_HINT = "\n\nRetranslation feedback — previous attempt had issues:\n• Preserve all numbers."


def test_retry_hint_absent_from_user_turn():
    user_turn = _req(retry_hint=_HINT).to_prompt()
    assert "Retranslation feedback" not in user_turn
    assert "Preserve all numbers" not in user_turn
    # The source text itself is still present and the anchor is intact.
    assert user_turn.startswith("To Ukrainian:")
    assert "Hello world." in user_turn


def test_retry_hint_present_in_system_prompt():
    assert "Retranslation feedback" in _req(retry_hint=_HINT).to_system_prompt()


def test_no_retry_hint_user_turn_is_plain_anchor():
    assert _req().to_prompt() == "To Ukrainian:\nHello world."


# ── AI-fix mode: same leak vector via the "Issues to fix" block ─────────────────
# fix_translation mode passes the source, the flawed translation, and the QC
# issues.  The issues are English instructions, so they must sit in the system
# prompt — not the user turn — or a translation-tuned model echoes them as output.

def _fix_req(retry_hint: str = "") -> TranslationRequest:
    return TranslationRequest(
        index=0,
        original_text="Hello world.",
        string_id=1,
        source_lang="en",
        target_lang="uk",
        fix_translation="Привіт світ.",
        retry_hint=retry_hint,
    )


def test_fix_mode_issues_absent_from_user_turn():
    req = _fix_req(retry_hint=_HINT)
    user_turn = req.to_prompt()
    assert "Retranslation feedback" not in user_turn
    assert "Preserve all numbers" not in user_turn
    assert "Issues to fix" not in user_turn
    # Reference material and the output anchor are still there.
    assert "Hello world." in user_turn          # source
    assert "Привіт світ." in user_turn           # flawed translation to correct
    assert user_turn.rstrip().endswith("Corrected Ukrainian translation:")


def test_fix_mode_issues_present_in_system_prompt():
    sys_prompt = _fix_req(retry_hint=_HINT).to_system_prompt()
    assert "Issues to fix:" in sys_prompt
    assert "Preserve all numbers" in sys_prompt
    # Proofreader persona, not the plain-translator one.
    assert "proofreader" in sys_prompt.lower()


def test_fix_mode_without_hint_has_generic_issues_block():
    sys_prompt = _fix_req().to_system_prompt()
    assert "General quality issues." in sys_prompt


# ── _heal_known_artifacts (cache-hit healing path) ─────────────────────────────

def test_heal_applies_all_fixups():
    src = "A LIST transport jumped.\n\n"
    tgt = "Транспорт [LIST] стрибнув.<br>\n"
    out = heal(tgt, src)
    assert "<br>" not in out
    assert "[LIST]" not in out and "LIST" in out
    assert out.endswith("\n\n")


def test_heal_noop_on_clean_text():
    src = "Clean source."
    tgt = "Чисте джерело."
    assert heal(tgt, src) == "Чисте джерело."


# ── _unwrap_leaked_example_brackets ─────────────────────────────────────────────
# Rule 3.a/3.d of default_rules_block() teaches pairs like "[Flirt]→[유혹]" so
# the model can handle GENUINELY bracketed dialogue-choice/status tags. The
# model over-generalizes: it wraps brackets around the Korean translation any
# time the bare English word appears, even with nothing bracketed in the
# source. These cases are taken from an actual reported bug (BSEK string
# 0x02000943, an MCM "Flirt Cooldown" settings label mistranslated as
# "[유혹] 재사용 대기시간").

def test_reported_bug_flirt_cooldown_with_token():
    src = "Flirt Cooldown <Token=CurrentFlirt>"
    tgt = "[유혹] 재사용 대기시간 <Token=CurrentFlirt>"
    assert unwrap_leaked(tgt, src) == "유혹 재사용 대기시간 <Token=CurrentFlirt>"


def test_reported_bug_flirt_cooldown_multiline_block():
    src = "Flirt Cooldown: Click to toggle 0 or 3 days."
    tgt = "[유혹] 재사용 대기시간: 클릭하여 0일 또는 3일로 전환하십시오."
    assert unwrap_leaked(tgt, src) == "유혹 재사용 대기시간: 클릭하여 0일 또는 3일로 전환하십시오."


def test_leaked_brackets_common_and_unknown():
    src = "Common resource found in Unknown systems."
    tgt = "[알 수 없음] 시스템에서 발견된 [일반] 자원."
    assert unwrap_leaked(tgt, src) == "알 수 없음 시스템에서 발견된 일반 자원."


def test_genuinely_bracketed_dialogue_choice_preserved():
    # The rule's actual intended case: source has [Flirt] as a real dialogue
    # choice tag -- brackets must stay in the translation.
    src = "You can choose to [Flirt] with the companion."
    tgt = "동료에게 [유혹]을 선택할 수 있습니다."
    assert unwrap_leaked(tgt, src) == tgt


def test_leaked_bracket_noop_when_word_absent_from_source():
    src = "Totally unrelated sentence."
    tgt = "[일반] 텍스트입니다."
    assert unwrap_leaked(tgt, src) == tgt


def test_leaked_bracket_noop_on_empty_args():
    assert unwrap_leaked("", "Flirt Cooldown") == ""
    assert unwrap_leaked("[유혹] 텍스트", "") == "[유혹] 텍스트"


def test_all_caps_examples_excluded_from_leaked_table():
    # CANCELED/VATS etc. are already handled by _unwrap_spurious_brackets
    # (identity mapping); they must not also appear in the mixed-case table.
    from gui.ollama_worker import _BRACKET_TRANSLATION_EXAMPLES
    assert "CANCELED" not in _BRACKET_TRANSLATION_EXAMPLES
    assert "VATS" not in _BRACKET_TRANSLATION_EXAMPLES
    assert _BRACKET_TRANSLATION_EXAMPLES.get("Flirt") == "유혹"


def test_heal_known_artifacts_also_covers_leaked_example_brackets():
    # Cache-hit healing path must fix the same class of bug.
    src = "Flirt Cooldown <Token=CurrentFlirt>"
    tgt = "[유혹] 재사용 대기시간 <Token=CurrentFlirt>"
    assert heal(tgt, src) == "유혹 재사용 대기시간 <Token=CurrentFlirt>"


# ── _translation_dropped_content ────────────────────────────────────────────────
# Real-world failure with a small/quantized local model (gemma4:12b-it-qat via
# Ollama): given "Admire the artefacts [Animation]", the response was sometimes
# just "[Animation]" -- the translatable phrase vanished entirely, but this
# wasn't caught (non-empty, not a source echo) and was saved as a "success".

def test_reported_bug_admire_the_artefacts():
    assert dropped_content("Admire the artefacts [Animation]", "[Animation]")


def test_reported_bug_various_animation_marker_strings():
    for src, bad in [
        ("Beg [Animation]", "[Animation]"),
        ("Repair [Animation]", "[Animation]"),
        ("Rummage through this [Animation]", "[Animation]"),
    ]:
        assert dropped_content(src, bad), (src, bad)


def test_successful_translation_not_flagged():
    # This one actually succeeded in the same batch -- must not be flagged.
    assert not dropped_content("Arms crossed [Animation]", "팔짱을 낀 채 [Animation]")


def test_source_that_is_only_a_tag_not_flagged():
    # Nothing was ever supposed to be translated here.
    assert not dropped_content("[Animation]", "[Animation]")


def test_alias_tag_variant_also_detected():
    # The same failure mode with a different structural token shape.
    assert dropped_content("Repair the <Alias=ShipPart> now.", "<Alias=ShipPart>")


def test_empty_translation_not_flagged_here():
    # Empty output is a distinct, already-handled failure mode (EMPTY_TRANSLATION);
    # this guard only concerns "non-empty but content vanished".
    assert not dropped_content("Something to translate.", "")


def test_dropped_content_noop_on_empty_original():
    assert not dropped_content("", "[Animation]")


def test_bracket_wrapped_korean_translation_not_flagged():
    # Verification finding: a translation that EXISTS but was cosmetically
    # bracket-wrapped by the model ("[앉기] [Animation]") is content, not a
    # dropped-content failure — it must be left to the unwrap pipeline, not
    # hard-failed here. The strip regex is printable-ASCII-only for brackets.
    assert not dropped_content("Sit [Animation]", "[앉기] [Animation]")
    assert not dropped_content("Flirt [Animation]", "[유혹] [Animation]")


def test_preflight_cache_self_heals_poisoned_entry(qapp_or_skip=None):
    # Verification finding: the batch PRE-FLIGHT cache path (where most cache
    # hits are served during Translate All) previously had no poisoned-entry
    # check at all — a tag-only "[Animation]" entry written by an older run
    # was replayed as a "cache" success forever, bypassing the self-heal in
    # _translate_single entirely.
    pytest.importorskip("PySide6")
    from unittest.mock import patch
    from gui.ollama_worker import OllamaWorker, TranslationRequest
    from gui.translation_cache import TranslationCache
    from PySide6.QtWidgets import QApplication
    import tempfile
    from pathlib import Path
    QApplication.instance() or QApplication([])

    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = OllamaWorker(model="gemma4:12b-it-qat", enable_term_protection=False, max_workers=1)
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(
        index=0, string_id=10, original_text="Beg [Animation]",
        source_lang="en", target_lang="ko",
    )
    key = TranslationCache.make_key(
        req.original_text, w.model, "en", "ko", w._settings_hash_for(req.original_text)
    )
    cache.set(key, "[Animation]")  # poisoned entry from an older run

    results = []
    w.translation_ready.connect(lambda idx, text, sid, src: results.append((text, src)))
    with patch.object(OllamaWorker, "_stream_ollama", return_value="구걸하다 [Animation]"):
        w.translate_batch([req])

    assert results == [("구걸하다 [Animation]", "api")]
    assert cache.get(key) == "구걸하다 [Animation]"


def test_preflight_cache_still_serves_good_entries(qapp_or_skip=None):
    # Regression guard for the fix above: a GOOD cached entry must still be
    # served from pre-flight without touching the API.
    pytest.importorskip("PySide6")
    from unittest.mock import patch
    from gui.ollama_worker import OllamaWorker, TranslationRequest
    from gui.translation_cache import TranslationCache
    from PySide6.QtWidgets import QApplication
    import tempfile
    from pathlib import Path
    QApplication.instance() or QApplication([])

    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = OllamaWorker(model="gemma4:12b-it-qat", enable_term_protection=False, max_workers=1)
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None

    req = TranslationRequest(
        index=0, string_id=11, original_text="Beg [Animation]",
        source_lang="en", target_lang="ko",
    )
    key = TranslationCache.make_key(
        req.original_text, w.model, "en", "ko", w._settings_hash_for(req.original_text)
    )
    cache.set(key, "구걸하다 [Animation]")

    results = []
    w.translation_ready.connect(lambda idx, text, sid, src: results.append((text, src)))
    with patch.object(
        OllamaWorker, "_stream_ollama",
        side_effect=AssertionError("API must not be called for a good cache hit"),
    ):
        w.translate_batch([req])

    assert results == [("구걸하다 [Animation]", "cache")]


def test_full_pipeline_retries_once_and_recovers(qapp_or_skip=None):
    pytest.importorskip("PySide6")
    from unittest.mock import patch
    from gui.ollama_worker import OllamaWorker, TranslationRequest
    import gui.settings_dialog  # ensure QApplication-dependent imports resolve
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    w = OllamaWorker(model="gemma4:12b-it-qat", enable_term_protection=False)
    w.translation_cache = None
    w.translation_memory = None
    w.glossary_manager = None
    req = TranslationRequest(
        index=0, string_id=1, original_text="Admire the artefacts [Animation]",
        source_lang="en", target_lang="ko",
    )
    calls = {"n": 0}

    def fake_stream(payload, timeout):
        calls["n"] += 1
        return "[Animation]" if calls["n"] == 1 else "유물을 감상하다 [Animation]"

    with patch.object(OllamaWorker, "_stream_ollama", side_effect=fake_stream):
        result = w._translate_single(req)

    assert calls["n"] == 2
    assert result == "유물을 감상하다 [Animation]"


def test_full_pipeline_fails_when_retry_also_drops_content(qapp_or_skip=None):
    pytest.importorskip("PySide6")
    from unittest.mock import patch
    from gui.ollama_worker import OllamaWorker, TranslationRequest
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    w = OllamaWorker(model="gemma4:12b-it-qat", enable_term_protection=False)
    w.translation_cache = None
    w.translation_memory = None
    w.glossary_manager = None
    req = TranslationRequest(
        index=0, string_id=2, original_text="Beg [Animation]",
        source_lang="en", target_lang="ko",
    )
    with patch.object(OllamaWorker, "_stream_ollama", return_value="[Animation]"):
        result = w._translate_single(req)

    # Must be a genuine failure (None), NEVER silently saved as "[Animation]".
    assert result is None


def test_poisoned_cache_entry_self_heals(qapp_or_skip=None):
    pytest.importorskip("PySide6")
    from unittest.mock import patch
    from gui.ollama_worker import OllamaWorker, TranslationRequest
    from gui.translation_cache import TranslationCache
    from PySide6.QtWidgets import QApplication
    import tempfile
    from pathlib import Path
    QApplication.instance() or QApplication([])

    cache = TranslationCache(Path(tempfile.mkdtemp()) / "cache.json")
    w = OllamaWorker(model="gemma4:12b-it-qat", enable_term_protection=False)
    w.translation_cache = cache
    w.translation_memory = None
    w.glossary_manager = None
    req = TranslationRequest(
        index=0, string_id=3, original_text="Beg [Animation]",
        source_lang="en", target_lang="ko",
    )
    key = TranslationCache.make_key(
        req.original_text, w.model, req.source_lang, req.target_lang,
        w._settings_hash_for(req.original_text),
    )
    cache.set(key, "[Animation]")  # simulates a pre-fix poisoned entry

    with patch.object(OllamaWorker, "_stream_ollama", return_value="구걸하다 [Animation]"):
        result = w._translate_single(req)

    assert result == "구걸하다 [Animation]"
    assert cache.get(key) == "구걸하다 [Animation]"


