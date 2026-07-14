"""Regression tests for translation-quality fixes made before the 1st release.

Covers:
  1. Glossary edits must change the workers' settings hash (cache invalidation).
     The old code called GlossaryManager.get_all_entries(), which does not
     exist; the AttributeError was swallowed and the glossary silently never
     entered the hash.
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

def _worker_settings_hash(gm: GlossaryManager | None) -> str:
    """Replicates the hash body shared by Ollama/OpenAICompat/Claude workers."""
    parts = ["pv5", "persona=", "rules="]
    if gm is not None:
        entries = [e for _scope, e in gm.all_entries()]
        for e in sorted(entries, key=lambda x: (x.source_term, x.target_term)):
            parts.append(f"{e.source_term}={e.target_term}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def _write_tm_txt(path: Path) -> Path:
    path.write_text(
        '1 0x0000000A "Grav Drive" "중력 드라이브"\n'
        '2 0x0000000B "Boost Pack" ""\n',
        encoding="utf-8",
    )
    return path


# ── 1. glossary → settings hash ──────────────────────────────────────────────

def test_glossary_manager_has_all_entries_api():
    """Workers rely on all_entries(); get_all_entries() never existed."""
    assert hasattr(GlossaryManager, "all_entries")


def test_glossary_edit_changes_settings_hash(tmp_path):
    gm = GlossaryManager(tmp_path)
    h_before = _worker_settings_hash(gm)
    gm.global_glossary.add_entry(
        GlossaryEntry(source_term="Grav Drive", target_term="중력 드라이브")
    )
    h_after = _worker_settings_hash(gm)
    assert h_before != h_after


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
