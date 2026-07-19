"""Regression tests for the ARX-15 WEAP FULL-chain bug: a record with the
same field signature repeated many times (e.g. WEAP's FULL — once for the
weapon's own name, then again for every OBTE/OBTF modification-grade label)
had extraction (_parse_record) and write-back (_patch_fields) disagree about
which occurrences count, silently shifting every later same-signature
translation in the record onto the wrong field.

Root cause: _parse_record skipped an occurrence if its text was empty OR
looked like a resource path; _patch_fields only skipped exactly b"\\x00" and
never checked for resource-path-like text. Fixed by routing both through a
single shared predicate, _field_translatable_text().
"""
from __future__ import annotations

import struct
from pathlib import Path

from bethesda_strings.esp_handler import (
    EspFile,
    _field_translatable_text,
    _patch_fields,
)


def _sub(sig: str, text: str) -> bytes:
    data = text.encode("utf-8") + b"\x00"
    return sig.encode("ascii") + struct.pack("<H", len(data)) + data


def _make_weap_body() -> bytes:
    """EDID + 4 FULL occurrences, mimicking the real ARX-15 WEAP layout:
    name, then a field whose original text looks like a resource path
    (should never be sent for translation and must survive untouched), then
    two modification-grade names."""
    return (
        _sub("EDID", "TEST_WEAP")
        + _sub("FULL", "ARX-15")            # weapon's own name
        + _sub("FULL", "Config/Low")        # looks like a resource path
        + _sub("FULL", "Standard (Low)")    # grade 1
        + _sub("FULL", "Standard (Mid)")    # grade 2
    )


# ── unit-level: the shared predicate itself ─────────────────────────────────

def test_translatable_text_predicate_empty_variants():
    assert _field_translatable_text(b"", "utf-8") is None
    assert _field_translatable_text(b"\x00", "utf-8") is None
    # Multi-byte all-null padding used to pass _patch_fields' old
    # `fdata != b"\x00"` check (it isn't a single null byte) even though
    # extraction's rstrip-based check always treated it as empty.
    assert _field_translatable_text(b"\x00\x00\x00", "utf-8") is None


def test_translatable_text_predicate_resource_path():
    assert _field_translatable_text(b"Config/Low\x00", "utf-8") is None
    assert _field_translatable_text(b"Meshes\\Weapons\\arx15.nif\x00", "utf-8") is None


def test_translatable_text_predicate_normal_text():
    assert _field_translatable_text(b"ARX-15\x00", "utf-8") == "ARX-15"
    assert _field_translatable_text(b"Standard (Low)\x00", "utf-8") == "Standard (Low)"


# ── extraction/write-back must agree on occurrence indices ─────────────────

def test_extraction_and_writeback_occurrence_indices_stay_aligned():
    body = _make_weap_body()

    ef = EspFile()
    ef.strings = []
    ef.is_localized = False
    ef._parse_record(b"WEAP", form_id=0x123456, flags=0, body=body, encoding="utf-8")

    # The resource-path-like field must never become a translatable entry.
    originals = [e.original for e in ef.strings]
    assert originals == ["ARX-15", "Standard (Low)", "Standard (Mid)"]

    for entry, translated in zip(ef.strings, ["[이름]", "[등급1]", "[등급2]"]):
        entry.translation = translated

    trans_map: dict[tuple[int, str, int], str] = {}
    occ: dict[tuple[int, str], int] = {}
    for entry in ef.strings:
        if entry.translation and entry.translation != entry.original:
            key = (entry.form_id, entry.field_sig)
            idx = occ.get(key, 0)
            occ[key] = idx + 1
            trans_map[(entry.form_id, entry.field_sig, idx)] = entry.translation

    new_body = _patch_fields(body, 0x123456, "WEAP", "utf-8", trans_map, {})

    ef2 = EspFile()
    ef2.strings = []
    ef2.is_localized = False
    ef2._parse_record(b"WEAP", form_id=0x123456, flags=0, body=bytes(new_body), encoding="utf-8")

    # Every translation must land on the field it was meant for — not
    # shifted by the skipped "Config/Low" occurrence.
    assert [e.original for e in ef2.strings] == ["[이름]", "[등급1]", "[등급2]"]

    # And the resource-path-like field must survive byte-for-byte untouched,
    # not overwritten with someone else's translation.
    assert b"Config/Low\x00" in bytes(new_body)


def test_full_file_roundtrip_weap_name_field_not_corrupted(tmp_path: Path):
    """End-to-end through EspFile.load()/.save(), matching how the GUI
    actually drives this (translate ef.strings in place, then save())."""
    tes4_body = b""
    tes4 = b"TES4" + struct.pack("<I", len(tes4_body)) + struct.pack("<I", 0) + struct.pack("<I", 0) + struct.pack("<I", 0) + struct.pack("<H", 0) + struct.pack("<H", 0) + tes4_body

    weap_body = _make_weap_body()
    weap_rec = b"WEAP" + struct.pack("<I", len(weap_body)) + struct.pack("<I", 0) + struct.pack("<I", 0x123456) + struct.pack("<I", 0) + struct.pack("<H", 0) + struct.pack("<H", 0) + weap_body

    src = tmp_path / "ARX-15_test.esm"
    src.write_bytes(tes4 + weap_rec)

    ef = EspFile()
    ef.load(src, encoding="utf-8")
    assert ef.is_localized is False

    by_text = {e.original: e for e in ef.strings}
    assert set(by_text) == {"ARX-15", "Standard (Low)", "Standard (Mid)"}
    by_text["ARX-15"].translation = "[이름번역]"
    by_text["Standard (Low)"].translation = "[등급1번역]"
    by_text["Standard (Mid)"].translation = "[등급2번역]"

    out = tmp_path / "ARX-15_test_translated.esm"
    ef.save(out, encoding="utf-8")

    ef2 = EspFile()
    ef2.load(out, encoding="utf-8")
    result = {e.field_sig: e.original for e in ef2.strings}
    got = [e.original for e in ef2.strings]

    # This is the exact bug: without the fix, the weapon's own name slot
    # ends up holding a modification-grade string instead of its name.
    assert got[0] == "[이름번역]", f"weapon name field corrupted, got {got!r}"
    assert got == ["[이름번역]", "[등급1번역]", "[등급2번역]"]
