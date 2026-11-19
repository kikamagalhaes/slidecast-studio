"""Stage verified FFmpeg/ffprobe executables for desktop packaging.

Use the complete platform build (apt/brew or checksum-verified Windows archive).
Set FFMPEG_PATH/FFPROBE_PATH or install both tools on the build machine PATH.
PyInstaller collects their shared dependencies, including capture/audio support.
Nothing is downloaded when the installed application starts.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE_DIR = ROOT / "build" / "stage"


def main() -> int:
    sources = {}
    for name in ("ffmpeg", "ffprobe"):
        executable = os.environ.get(name.upper() + "_PATH") or shutil.which(name)
        if not executable:
            print(f"{name} is required on the build machine PATH or via {name.upper()}_PATH.")
            return 1
        sources[name] = Path(executable)
    manifest = {}
    # Validate both before replacing any staged executable.
    for name, src in sources.items():
        if not src.is_file():
            raise FileNotFoundError(f"{name} binary not found at {src}")
        result = subprocess.run([str(src), "-version"], capture_output=True, text=True, check=True, timeout=30)
        manifest[name] = {"version": result.stdout.splitlines()[0], "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    for name, src in sources.items():
        dest = STAGE_DIR / (name + suffix)
        shutil.copy2(src, dest)
        dest.chmod(dest.stat().st_mode | 0o111)
        print(f"staged {name}: {manifest[name]['version']}")
    (STAGE_DIR / "media-tools.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
