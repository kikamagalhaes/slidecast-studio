"""Stage a static ffmpeg binary for the PyInstaller bundle (build-time only).

Uses the ``imageio-ffmpeg`` wheel (pinned in requirements-packaging.txt),
which ships a static ffmpeg for Windows/macOS/Linux, and copies it to
``build/stage/``. The spec file bundles whatever it finds there at the bundle
root, where ``app.core.ffmpeg_utils`` already looks (app dir / bin / ffmpeg).

ffprobe is intentionally not bundled: every caller falls back to ``ffmpeg -i``
parsing when ffprobe is absent.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE_DIR = ROOT / "build" / "stage"


def main() -> int:
    try:
        import imageio_ffmpeg
    except ImportError:
        print("imageio-ffmpeg not installed (pip install -r requirements-packaging.txt)")
        return 1
    src = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if not src.is_file():
        print(f"ffmpeg binary not found at {src}")
        return 1
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    dest = STAGE_DIR / name
    shutil.copy2(src, dest)
    # Wheels may ship without the exec bit; the bundle needs it (also checked
    # by get_ffmpeg_paths via os.access(..., os.X_OK)).
    dest.chmod(dest.stat().st_mode | 0o111)
    print(f"staged {src.name} -> {dest} ({dest.stat().st_size // 1024 // 1024} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
