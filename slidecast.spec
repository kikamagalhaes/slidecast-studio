# -*- mode: python; coding: utf-8 -*-
"""PyInstaller bundle for the SlideCast Studio desktop app (one-dir).

Build (after installing requirements + requirements-packaging.txt):

    python scripts/fetch_ffmpeg.py   # stage static ffmpeg into build/stage/
    pyinstaller slidecast.spec       # -> dist/SlideCastStudio/

CI builds this per OS on release tags; see .github/workflows/release.yml.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH)
APP_NAME = "SlideCastStudio"

# Data files: linux xcb helper + staged static ffmpeg (build/stage/).
# ffmpeg lands at the bundle root, where app.core.ffmpeg_utils looks.
datas = []
libs_dir = ROOT / "libs"
if libs_dir.is_dir():
    for child in libs_dir.iterdir():
        datas.append((str(child), "libs"))
stage_dir = ROOT / "build" / "stage"
if stage_dir.is_dir():
    for child in sorted(stage_dir.iterdir()):
        if child.is_file() and not child.name.startswith("."):
            datas.append((str(child), "."))
# replicate reads its own version via importlib.metadata at import time.
datas += copy_metadata("replicate")

block_cipher = None


a = Analysis(  # noqa: F821 (PyInstaller spec globals)
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX breaks Qt plugins and macOS signing; keep off.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="SlideCast Studio.app",
        icon=None,
        bundle_identifier="com.slidecast.studio",
        info_plist={"NSHighResolutionCapable": "True"},
    )
