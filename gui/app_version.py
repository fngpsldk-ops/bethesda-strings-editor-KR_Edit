"""Single source of truth for the app's own version, and a parser for the
bundled CHANGES.md so the welcome screen's "What's New" panel reflects it
automatically.

Version resolution order (resolve_app_version):
  1. `_version.py`'s `__version__` — stamped with the git tag by the release
     CI before building. Authoritative when present.
  2. The newest `## vX.Y.Z_KR — …` section heading in CHANGES.md — covers
     local `build_exe.bat` builds, where `_version.py` is still the "dev"
     placeholder. CHANGES.md is updated for every release anyway, so it is
     a reliable local mirror of the version.
  3. "dev" — nothing else available.

This exists because the app previously hardcoded
`app.setApplicationVersion("0.2.3")` in the entry point, completely
disconnected from both the CI-stamped `_version.py` and the actual release
tags — so the in-app updater compared every release against a frozen fake
"0.2.3" and the title/about dialogs could never show the real version.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Matches version section headings in CHANGES.md, e.g.
#   ## v1.1.1_KR — WEAP 등 반복 필드 레코드에서 번역이 밀리는 버그 수정
#   ## v1.0.0_KR
# Only headings whose tag starts with "v<digit>" count as version sections;
# other same-level headings inside a section (e.g. "## 버그 수정") are body.
_SECTION_RE = re.compile(r"^##\s+(v\d\S*)\s*(?:[—–-]+\s*(.*))?\s*$")

# Optional "· YYYY-MM-DD" / "— YYYY-MM-DD" date at the end of a title.
_DATE_RE = re.compile(r"(?:[·—–-]\s*)?(\d{4}-\d{2}-\d{2})\s*$")


def find_changes_md() -> Optional[Path]:
    """Locate CHANGES.md in both frozen (PyInstaller) and dev layouts.

    Frozen: the spec copies CHANGES.md next to the .exe (same sibling-level
    convention as the PortableData seed — see bethesda_strings_editor.spec's
    post-COLLECT block for why `datas` would land in the wrong place).
    Dev: repo root, one level above gui/.
    """
    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "CHANGES.md")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "CHANGES.md")
    else:
        candidates.append(Path(__file__).resolve().parent.parent / "CHANGES.md")
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _unwrap_hard_wraps(lines: List[str]) -> List[str]:
    """Join hand-wrapped continuation lines back onto their logical line.

    CHANGES.md is hand-wrapped at ~72 columns with 2-space-indented
    continuations. The tiny markdown renderer in gui.updater is
    line-oriented, so without unwrapping, each continuation line of a bullet
    would render as a separate stray paragraph outside the list.
    Fenced code blocks are passed through untouched.
    """
    out: List[str] = []
    in_fence = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(raw)
            continue
        if in_fence:
            out.append(raw)
            continue
        is_continuation = (
            bool(out)
            and out[-1].strip() != ""
            and not out[-1].strip().startswith("```")
            and raw[:1].isspace()
            and stripped != ""
            and not stripped.startswith(("- ", "* ", "#"))
        )
        if is_continuation:
            out[-1] = out[-1].rstrip() + " " + stripped
        else:
            out.append(raw)
    return out


def parse_changes_md(text: str) -> List[Dict]:
    """Parse CHANGES.md into version sections, newest first.

    Returns dicts shaped like gui.updater.parse_releases() output —
    ``{tag, name, date, body, url, prerelease}`` — so the existing
    changelog_to_html() renderer (styles, "(installed)" badge, truncation)
    can be reused as-is. Content before the first version heading (the
    document preamble) is skipped. ``url`` is left empty here; the caller
    fills in the releases-page URL to avoid importing network-facing
    modules from this one.
    """
    sections: List[Dict] = []
    current: Optional[Dict] = None
    body_lines: List[str] = []

    def _flush() -> None:
        nonlocal current, body_lines
        if current is not None:
            unwrapped = _unwrap_hard_wraps(body_lines)
            # Trim the "---" horizontal rules used as section separators.
            while unwrapped and unwrapped[-1].strip() in ("", "---"):
                unwrapped.pop()
            current["body"] = "\n".join(unwrapped).strip()
            sections.append(current)
        current = None
        body_lines = []

    for line in text.replace("\r\n", "\n").split("\n"):
        m = _SECTION_RE.match(line)
        if m:
            _flush()
            tag = m.group(1)
            title = (m.group(2) or "").strip()
            date = ""
            dm = _DATE_RE.search(title)
            if dm:
                date = dm.group(1)
                title = title[: dm.start()].rstrip(" ·—–-")
            current = {
                "tag": tag,
                "name": f"{tag} — {title}" if title else tag,
                "date": date,
                "url": "",
                "prerelease": False,
            }
        elif current is not None:
            body_lines.append(line)
    _flush()

    sections.reverse()  # file is oldest-first; panel wants newest-first
    return sections


def load_local_changelog(limit: int = 6) -> List[Dict]:
    """Read + parse the bundled CHANGES.md. Returns [] if unavailable —
    callers fall back to their own static content in that case."""
    path = find_changes_md()
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_changes_md(text)[: max(0, limit)]


def resolve_app_version() -> str:
    """The app's own version string, without a leading 'v' (e.g. "1.1.2_KR")."""
    try:
        from _version import __version__  # type: ignore[import]
    except ImportError:
        __version__ = "dev"
    if __version__ and __version__ != "dev":
        return __version__
    sections = load_local_changelog(limit=1)
    if sections:
        return sections[0]["tag"].lstrip("v")
    return "dev"
