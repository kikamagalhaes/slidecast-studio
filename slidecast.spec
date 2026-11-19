# -*- mode: python; coding: utf-8 -*-
"""PyInstaller bundle for the SlideCast Studio desktop app (one-dir).

Build (after installing requirements + requirements-packaging.txt):

    python scripts/fetch_ffmpeg.py   # stage static ffmpeg into build/stage/
    pyinstaller slidecast.spec       # -> dist/SlideCastStudio/

CI builds this per OS on release tags; see .github/workflows/release.yml.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH)
APP_NAME = "SlideCastStudio"

# Data files and media executables. Classify binaries so their shared libraries
# are collected too; ffprobe must work on machines without a system FFmpeg.
datas = [(str(ROOT / "app" / "ui" / "assets"), "app/ui/assets")]
libs_dir = ROOT / "libs"
if libs_dir.is_dir():
    for child in libs_dir.iterdir():
        datas.append((str(child), "libs"))
stage_dir = ROOT / "build" / "stage"
suffix = ".exe" if sys.platform == "win32" else ""
binaries = []
for tool in ("ffmpeg", "ffprobe"):
    executable = stage_dir / (tool + suffix)
    if not executable.is_file():
        raise FileNotFoundError(f"Missing {executable}; run scripts/fetch_ffmpeg.py first")
    binaries.append((str(executable), "."))
datas.append((str(stage_dir / "media-tools.json"), "."))
# replicate reads its own version via importlib.metadata at import time.
datas += copy_metadata("replicate")

block_cipher = None


a = Analysis(  # noqa: F821 (PyInstaller spec globals)
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
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
