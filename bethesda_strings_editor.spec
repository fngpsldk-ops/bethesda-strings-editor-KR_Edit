# PyInstaller spec file for Bethesda Strings Editor
#
# Build:
#   pyinstaller bethesda_strings_editor.spec
#
# Produces dist/bethesda-strings-editor-KOR/ — zip this directory for distribution.
# The GitHub Actions release workflow (`.github/workflows/release.yml`) runs
# this automatically on every `v*` tag push.

import sys

block_cipher = None

# Data files that must be present at runtime alongside the frozen modules.
# Format: (source_glob, dest_dir_relative_to_sys._MEIPASS)
# Mirrors the source tree layout so that Path(__file__).parent… resolution
# in word checkers and main.py works identically in frozen and development mode.
datas = [
    # Word lists for every language-detection checker (en/ru/uk/de/fr/es/it/pl/pt/ko).
    # Globbed so a newly-added *_words.txt is bundled automatically.
    *[(str(p), 'data/') for p in __import__('pathlib').Path('data').glob('*_words.txt')],
    # Visual-context preview: game-UI reference images + bundled UI fonts.
    *[(str(p), 'data/') for p in __import__('pathlib').Path('data').glob('*.png')],
    *[(str(p), 'data/fonts/') for p in __import__('pathlib').Path('data/fonts').glob('*.ttf')],
    # UI: application icon and base stylesheet
    ('resources/app_icon.ico',    'resources/'),
    ('resources/app_icon.png',    'resources/'),
    ('resources/app_icon_64.png', 'resources/'),
    ('resources/style.qss',       'resources/'),
    # Compiled Qt UI translations (build step: scripts/compile_translations.sh)
    *[(str(p), 'gui/translations/') for p in __import__('pathlib').Path('gui/translations').glob('*.qm')],
    # Default protected-terms list shipped with the app
    ('protected_terms_starfield_hq.txt', '.'),
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # PySide6 modules that PyInstaller's hook may not detect via static import
        'PySide6.QtSvg',
        'PySide6.QtPrintSupport',
        'PySide6.QtXml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim unused stdlib / third-party packages to reduce bundle size
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'PIL', 'cv2'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='bethesda-strings-editor-KOR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Windows: hide the console window; Linux: keep it so log output is visible
    console=sys.platform != 'win32',
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/app_icon.ico' if sys.platform == 'win32' else 'resources/app_icon.png',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='bethesda-strings-editor-KOR',
)

# ── Seed default TM/cache/glossary as a TRUE SIBLING of the .exe ───────────
# Everything listed in `datas` above lands inside dist/<name>/_internal/<dest>
# under PyInstaller 6.x's onedir layout -- that's correct and expected for
# resources the frozen code loads via sys._MEIPASS (word lists, icons, .qm
# translations). But app_settings.py's portable-mode detection deliberately
# looks for a "PortableData" folder as a SIBLING of the .exe itself
# (Path(sys.executable).resolve().parent / "PortableData"), NOT inside
# _internal -- by design, so an end user can find/back up/move it without
# digging into PyInstaller's own internal implementation folder. Putting
# these files in `datas` therefore seeds the WRONG location: confirmed by a
# real build, where the files landed at .../_internal/PortableData/Config/
# and were silently ignored (the app looked one level up and found nothing,
# same as if these files weren't bundled at all).
#
# Fixed by copying directly to the top-level dist folder here, after
# COLLECT() has finished building it. Deliberately curated, not "everything
# under PortableData/Config/": config.json (personal settings — theme,
# window geometry, recent files, backend choice) and pre_est_weights.json
# (a small calibration file derived from this-machine correction history)
# are intentionally left OUT so a fresh download never carries anyone's
# personal settings, only shared reference/working data (see README's
# TM/cache section and .gitignore's comment for the full reasoning).
import shutil
from pathlib import Path as _Path

_dist_root = _Path(DISTPATH) / 'bethesda-strings-editor-KOR'
_seed_src  = _Path('PortableData') / 'Config'
_seed_dst  = _dist_root / 'PortableData' / 'Config'
_seed_dst.mkdir(parents=True, exist_ok=True)
for _fname in ('glossary.json', 'translation_cache.json', 'translation_memory.json'):
    _src_file = _seed_src / _fname
    if _src_file.exists():
        shutil.copy2(_src_file, _seed_dst / _fname)
        print(f"[seed] copied {_src_file} -> {_seed_dst / _fname}")
    else:
        print(f"[seed] WARNING: {_src_file} not found, skipping")
