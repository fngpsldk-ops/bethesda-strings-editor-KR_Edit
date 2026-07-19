"""Regression test for the app showing a stale hardcoded version ("0.2.3")
in the in-app update-checker regardless of the real release version.

Root cause: main.py (the actual PyInstaller entry point per
bethesda_strings_editor.spec's Analysis(['main.py'])) called
`app.setApplicationVersion("0.2.3")` with a hardcoded literal, completely
disconnected from `_version.py`'s `__version__` (which the release CI
correctly stamps with the real git tag). The update-check flow
(MainWindow._current_version()) reads `QApplication.applicationVersion()`,
so it always showed "0.2.3" no matter what was actually built or tagged.

A near-identical duplicate, gui/main.py, existed alongside main.py with a
different hardcoded version ("1.0.0_KR") and was never referenced by
anything (not the PyInstaller spec, not any script) -- almost certainly the
result of a past fix attempt landing on the wrong (unused) copy of the
file. It has been removed; main.py is the only entry point.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_main_py_does_not_hardcode_a_version_literal():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "setApplicationVersion(__version__)" in source, (
        "main.py must set the Qt application version from _version.py's "
        "__version__ (imported at module scope with a 'dev' fallback), not "
        "a hardcoded string literal."
    )
    # Guard against literal-looking calls like setApplicationVersion("1.2.3")
    # sneaking back in.
    import re
    assert not re.search(r'setApplicationVersion\(\s*["\']', source), (
        "found a hardcoded string literal passed to setApplicationVersion() "
        "in main.py -- this silently overrides the real _version.py value "
        "and breaks the in-app update checker."
    )


def test_no_orphaned_duplicate_entry_point():
    """gui/main.py used to be an unreferenced duplicate of main.py with its
    own separate (also wrong) hardcoded version. Guard against it, or any
    other stray top-level main.py copy, reappearing."""
    assert not (ROOT / "gui" / "main.py").exists(), (
        "gui/main.py should not exist -- it was an orphaned duplicate of "
        "the real entry point (main.py, per bethesda_strings_editor.spec) "
        "that carried its own stale hardcoded version string."
    )
