"""Regression tests for translation-quality fixes made before the 1st release.

Covers:
  1. Per-string glossary-aware settings hash (gui.settings_hash): editing a
     glossary term invalidates only the cache entries for strings containing
     that term; glossary-free strings hash identically to the original
     builds, reviving caches accumulated under them. (The first fix here
     hashed the ENTIRE glossary into every key — correct but needlessly
     invalidated the whole cache on any term edit; before that, a
     get_all_entries() AttributeError silently excluded the glossary
     entirely.)
  2. TranslationMemory.get_by_id() must not return a translation for a
     colliding string ID from a different plugin when the source text differs.
  3. Loading a TXT TM with use_original=False must skip rows whose Translated
     column is empty (no English-original leakage).
  4. clear() + reloading a same-sized corpus must not leave a stale fuzzy
     word index behind (previously raised KeyError inside get_fuzzy()).
  5. save_json()/load_json() round-trips the id→source map used by (2).
  6. StringTableModel.import_translations() skips ID matches whose recorded
     source text differs from the row's original.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from gui.glossary import GlossaryEntry, GlossaryManager
from gui.translation_memory import TranslationMemory


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_tm_txt(path: Path) -> Path:
    path.write_text(
        '1 0x0000000A "Grav Drive" "중력 드라이브"\n'
        '2 0x0000000B "Boost Pack" ""\n',
        encoding="utf-8",
    )
    return path


# ── 1. glossary → per-string settings hash ───────────────────────────────────
# The settings hash is per-string (gui.settings_hash): each cache key mixes in
# only the glossary pairs that MATCH that string, so a term edit invalidates
# only the strings containing it, and glossary-free strings hash identically
# to the original builds (whose glossary contribution was silently skipped by
# a swallowed AttributeError) — reviving caches accumulated under them.

def test_glossary_manager_has_all_entries_api():
    """Workers rely on all_entries(); get_all_entries() never existed."""
    assert hasattr(GlossaryManager, "all_entries")


def test_glossary_edit_invalidates_only_matching_strings(tmp_path):
    from gui.settings_hash import base_settings_parts, settings_hash_for_text

    gm = GlossaryManager(tmp_path)
    gm.global_glossary.add_entry(
        GlossaryEntry(source_term="Grav Drive", target_term="중력 드라이브")
    )
    base = base_settings_parts("", "")
    s_match = "Repair the Grav Drive before takeoff."
    s_other = "Open the cargo hold door."

    h_match_1 = settings_hash_for_text(gm, s_match, base)
    h_other_1 = settings_hash_for_text(gm, s_other, base)

    entry = next(e for e in gm.global_glossary.entries)
    entry.target_term = "중력 추진기"
    gm.global_glossary.update_entry(entry)

    assert settings_hash_for_text(gm, s_match, base) != h_match_1
    assert settings_hash_for_text(gm, s_other, base) == h_other_1


def test_glossary_add_and_remove_scope_invalidation(tmp_path):
    from gui.settings_hash import base_settings_parts, settings_hash_for_text

    gm = GlossaryManager(tmp_path)
    base = base_settings_parts("", "")
    s_boost = "Equip your Boost Pack now."
    s_plain = "Nothing relevant here."

    h_boost_0 = settings_hash_for_text(gm, s_boost, base)
    h_plain_0 = settings_hash_for_text(gm, s_plain, base)

    e = GlossaryEntry(source_term="Boost Pack", target_term="부스트 팩")
    gm.global_glossary.add_entry(e)
    assert settings_hash_for_text(gm, s_boost, base) != h_boost_0
    assert settings_hash_for_text(gm, s_plain, base) == h_plain_0

    gm.global_glossary.remove_entry(e.id)
    assert settings_hash_for_text(gm, s_boost, base) == h_boost_0


def test_glossary_free_string_hash_matches_legacy_builds(tmp_path):
    """Cache-revival property: a string with NO matching glossary terms must
    hash byte-identically to what the original (pre-fix) builds produced, so
    caches accumulated under them become valid again."""
    from gui.settings_hash import base_settings_parts, settings_hash_for_text

    gm = GlossaryManager(tmp_path)
    gm.global_glossary.add_entry(
        GlossaryEntry(source_term="Grav Drive", target_term="중력 드라이브")
    )
    legacy = hashlib.sha256(
        "\n".join(["pv5", "persona=", "rules="]).encode("utf-8")
    ).hexdigest()[:12]
    assert settings_hash_for_text(gm, "No terms here.", base_settings_parts("", "")) == legacy


def test_empty_target_term_does_not_affect_hash(tmp_path):
    """build_prompt_snippet() skips entries with an empty target; the hash
    must mirror that selection exactly."""
    from gui.settings_hash import base_settings_parts, settings_hash_for_text

    gm = GlossaryManager(tmp_path)
    base = base_settings_parts("", "")
    before = settings_hash_for_text(gm, "The Starborn arrives.", base)
    gm.global_glossary.add_entry(GlossaryEntry(source_term="Starborn", target_term=""))
    assert settings_hash_for_text(gm, "The Starborn arrives.", base) == before


def test_persona_change_invalidates_everything(tmp_path):
    from gui.settings_hash import base_settings_parts, settings_hash_for_text

    gm = GlossaryManager(tmp_path)
    text = "Any string at all."
    h1 = settings_hash_for_text(gm, text, base_settings_parts("", ""))
    h2 = settings_hash_for_text(gm, text, base_settings_parts("new persona", ""))
    assert h1 != h2


# ── 2. get_by_id source verification ─────────────────────────────────────────

def test_get_by_id_verified_hit(tmp_path):
    tm = TranslationMemory()
    tm.load(_write_tm_txt(tmp_path / "tm.txt"))
    assert tm.get_by_id(0x0A, expected_source="Grav Drive") == "중력 드라이브"


def test_get_by_id_rejects_id_collision(tmp_path):
    tm = TranslationMemory()
    tm.load(_write_tm_txt(tmp_path / "tm.txt"))
    # Same raw ID, but a different plugin's unrelated string.
    assert tm.get_by_id(0x0A, expected_source="Reload speed +10%") is None


def test_get_by_id_normalizes_line_endings(tmp_path):
    tm = TranslationMemory()
    tm._by_id[1] = "번역"
    tm._id_src[1] = "Line one\nLine two"
    assert tm.get_by_id(1, expected_source="Line one\r\nLine two") == "번역"


def test_get_by_id_legacy_unverified_tm_still_works():
    """TMs loaded from bare .strings files record no source text and keep
    the old (unverified) behavior for same-plugin version updates."""
    tm = TranslationMemory()
    tm._by_id[5] = "테스트"
    assert tm.get_by_id(5, expected_source="anything") == "테스트"
    assert tm.get_by_id(5) == "테스트"


# ── 3. no English leakage on TXT load ────────────────────────────────────────

def test_txt_load_skips_untranslated_rows(tmp_path):
    tm = TranslationMemory()
    loaded = tm.load(_write_tm_txt(tmp_path / "tm.txt"), use_original=False)
    assert loaded == 1
    assert tm.get_by_id(0x0B) is None
    assert tm.get_by_source("Boost Pack") is None


# ── 4. stale fuzzy index after clear() ───────────────────────────────────────

def test_fuzzy_index_invalidated_by_clear_same_size_reload():
    tm = TranslationMemory()
    tm._by_src = {"open the door": "문을 열어라", "close the gate": "성문을 닫아라"}
    tm.get_fuzzy("open the door now")  # builds the index (size == 2)
    tm.clear()
    tm._by_src = {"take the key": "열쇠를 가져가라", "burn the bridge": "다리를 불태워라"}
    # Previously raised KeyError('open the door') from the stale index.
    result = tm.get_fuzzy("open the door now")
    assert result is None


def test_fuzzy_index_invalidated_by_load_json_same_size(tmp_path):
    a, b = TranslationMemory(), TranslationMemory()
    a._by_src = {"open the door": "문을 열어라", "close the gate": "성문을 닫아라"}
    b._by_src = {"take the key": "열쇠를 가져가라", "burn the bridge": "다리를 불태워라"}
    snap_a, snap_b = tmp_path / "a.json", tmp_path / "b.json"
    a.save_json(snap_a)
    b.save_json(snap_b)

    tm = TranslationMemory()
    tm.load_json(snap_a)
    tm.get_fuzzy("open the door now")
    tm.load_json(snap_b)  # same size — must still rebuild the index
    assert tm.get_fuzzy("open the door now") is None


# ── 5. id_src persists across save/load ─────────────────────────────────────

def test_save_load_json_roundtrips_id_src(tmp_path):
    tm = TranslationMemory()
    tm.load(_write_tm_txt(tmp_path / "tm.txt"))
    snap = tmp_path / "snapshot.json"
    tm.save_json(snap)

    tm2 = TranslationMemory()
    tm2.load_json(snap)
    assert tm2.get_by_id(0x0A, expected_source="Grav Drive") == "중력 드라이브"
    assert tm2.get_by_id(0x0A, expected_source="Wrong text") is None
    assert tm2.id_source_map() == {0x0A: "Grav Drive"}


# ── 6. import_translations verification ─────────────────────────────────────

def test_import_translations_respects_id_source_map(qapp_or_skip=None):
    pytest.importorskip("PySide6")
    from gui.string_table import StringTableModel

    model = StringTableModel()
    model._data = [
        {"id": 0x0A, "original": "Reload speed +10%", "translated": "", "status": ""},
        {"id": 0x0B, "original": "Grav Drive", "translated": "", "status": ""},
    ]
    applied = model.import_translations(
        {0x0A: "중력 드라이브", 0x0B: "중력 드라이브"},
        id_source_map={0x0A: "Grav Drive", 0x0B: "Grav Drive"},
    )
    # 0x0A is a raw-ID collision (original text differs) — must be skipped.
    assert applied == 1
    assert model._data[0]["translated"] == ""
    assert model._data[1]["translated"] == "중력 드라이브"
