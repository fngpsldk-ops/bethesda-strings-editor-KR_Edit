"""Tests for gui.app_version — the single source of truth for the app's
version and the CHANGES.md parser behind the "What's New" panel.

Covers the regression where main.py hardcoded setApplicationVersion("0.2.3"),
disconnected from both the CI-stamped _version.py and the real release tags,
so the updater compared everything against a fake frozen version.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gui import app_version
from gui.app_version import (
    _unwrap_hard_wraps,
    load_local_changelog,
    parse_changes_md,
    resolve_app_version,
)

ROOT = Path(__file__).resolve().parent.parent

_SAMPLE = """# Changelog preamble

This preamble text must never appear in any parsed section.

---

## v1.0.0_KR — 최초 릴리스

## 버그 수정

- 첫 번째 수정 사항으로 아주 길게 설명이
  이어지는 줄바꿈된 항목.
- 두 번째 항목.

---

## v1.1.0_KR — 다음 릴리스 · 2026-07-14

- 짧은 항목.

---

## v1.1.1_KR

`some/file.py`:
- 마지막 릴리스 항목.
"""


def test_sections_are_newest_first_and_preamble_skipped():
    secs = parse_changes_md(_SAMPLE)
    assert [s["tag"] for s in secs] == ["v1.1.1_KR", "v1.1.0_KR", "v1.0.0_KR"]
    for s in secs:
        assert "preamble" not in s["body"]


def test_inner_headings_stay_in_body():
    """Same-level '## something' headings that are not version tags (e.g.
    '## 버그 수정' inside v1.0.0_KR) must not start a new section."""
    secs = {s["tag"]: s for s in parse_changes_md(_SAMPLE)}
    assert "## 버그 수정" in secs["v1.0.0_KR"]["body"]


def test_title_and_date_extraction():
    secs = {s["tag"]: s for s in parse_changes_md(_SAMPLE)}
    assert secs["v1.1.0_KR"]["name"] == "v1.1.0_KR — 다음 릴리스"
    assert secs["v1.1.0_KR"]["date"] == "2026-07-14"
    assert secs["v1.1.1_KR"]["name"] == "v1.1.1_KR"          # no title
    assert secs["v1.0.0_KR"]["date"] == ""                    # no date


def test_hard_wrapped_bullets_are_unwrapped():
    secs = {s["tag"]: s for s in parse_changes_md(_SAMPLE)}
    body = secs["v1.0.0_KR"]["body"]
    assert "- 첫 번째 수정 사항으로 아주 길게 설명이 이어지는 줄바꿈된 항목." in body


def test_unwrap_leaves_code_fences_alone():
    lines = ["- item", "```", "  indented code", "```"]
    assert _unwrap_hard_wraps(lines) == lines


def test_real_changes_md_parses_and_has_expected_latest():
    """Integration against the repo's actual CHANGES.md: it must parse, be
    newest-first, and its newest tag must match what resolve_app_version()
    falls back to when _version.py is the 'dev' placeholder."""
    text = (ROOT / "CHANGES.md").read_text(encoding="utf-8")
    secs = parse_changes_md(text)
    assert len(secs) >= 3
    tags = [s["tag"] for s in secs]
    assert tags == sorted(tags, key=lambda t: [int(p.split("_")[0]) for p in t.lstrip("v").split(".")], reverse=True)

    resolved = resolve_app_version()
    # _version.py in the repo is the "dev" placeholder, so the resolver must
    # fall back to CHANGES.md's newest section.
    assert resolved == secs[0]["tag"].lstrip("v")
    assert resolved != "dev"


def test_resolver_prefers_stamped_version(monkeypatch, tmp_path):
    """When _version.py carries a real (CI-stamped) version it must win over
    CHANGES.md."""
    import sys
    import types

    fake = types.ModuleType("_version")
    fake.__version__ = "9.9.9_KR"
    monkeypatch.setitem(sys.modules, "_version", fake)
    assert resolve_app_version() == "9.9.9_KR"


def test_load_local_changelog_missing_file(monkeypatch):
    monkeypatch.setattr(app_version, "find_changes_md", lambda: None)
    assert load_local_changelog() == []
