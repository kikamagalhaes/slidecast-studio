"""Stage verified FFmpeg/ffprobe executables for desktop packaging.

FFmpeg comes from the pinned imageio-ffmpeg wheel. ffprobe must be supplied by
FFPROBE_PATH or the build machine PATH (apt/brew or checksum-verified Windows
archive in release.yml). PyInstaller collects ffprobe's shared dependencies.
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
    import imageio_ffmpeg

    probe = os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe")
    if not probe:
        print("ffprobe is required: install FFmpeg on the build machine or set FFPROBE_PATH.")
        return 1
    sources = {"ffmpeg": Path(imageio_ffmpeg.get_ffmpeg_exe()), "ffprobe": Path(probe)}
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
