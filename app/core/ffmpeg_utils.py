import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)


def get_ffmpeg_paths() -> Tuple[Optional[str], Optional[str]]:
    """
    Locates ffmpeg and ffprobe executables across platforms (Linux, Windows, macOS).
    Checks:
    1. PATH environment variable
    2. Application directory / bundled directory
    3. Custom environment variables FFMPEG_PATH / FFPROBE_PATH
    """
    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"

    ffmpeg_path = os.environ.get("FFMPEG_PATH") or shutil.which(ffmpeg_name)
    ffprobe_path = os.environ.get("FFPROBE_PATH") or shutil.which(ffprobe_name)

    # If not in PATH, search in application directory and bin subfolder
    app_dir = Path(__file__).resolve().parent.parent.parent
    candidate_dirs = [
        app_dir,
        app_dir / "bin",
        app_dir / "ffmpeg",
    ]

    for c_dir in candidate_dirs:
        if not ffmpeg_path:
            candidate_ffmpeg = c_dir / ffmpeg_name
            if candidate_ffmpeg.is_file() and os.access(candidate_ffmpeg, os.X_OK):
                ffmpeg_path = str(candidate_ffmpeg)

        if not ffprobe_path:
            candidate_ffprobe = c_dir / ffprobe_name
            if candidate_ffprobe.is_file() and os.access(candidate_ffprobe, os.X_OK):
                ffprobe_path = str(candidate_ffprobe)

    return ffmpeg_path, ffprobe_path


def run_process_cancellable(
    cmd,
    cancel_check: Optional[Callable[[], bool]] = None,
    poll_interval: float = 0.5,
) -> subprocess.CompletedProcess:
    """Runs a process to completion, polling so cancellation aborts it.

    :param cmd: argv list for :class:`subprocess.Popen`.
    :param cancel_check: optional callable returning True to abort.
    :raises InterruptedError: if ``cancel_check`` fired (process is killed).
    :returns: :class:`subprocess.CompletedProcess` with captured output.
    """
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=poll_interval)
                return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if cancel_check and cancel_check():
                    process.kill()
                    process.communicate()
                    raise InterruptedError("Operação cancelada pelo usuário.")
    except BaseException:
        if process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
        raise


def format_duration(seconds: float) -> str:
    """Formats seconds into MM:SS or HH:MM:SS."""
    if seconds < 0:
        seconds = 0
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int((seconds - total_seconds) * 10)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}.{millis}"


def get_video_duration(media_path: str) -> float:
    """Returns duration in seconds of video/audio file using ffprobe or ffmpeg."""
    import re
    p = Path(media_path).resolve()
    if not p.exists():
        return 0.0

    _, ffprobe_exe = get_ffmpeg_paths()
    if ffprobe_exe:
        try:
            cmd = [
                ffprobe_exe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(p),
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=True)
            val = float(res.stdout.strip())
            if val > 0:
                return val
        except Exception as exc:
            logger.debug("ffprobe duration failed for %s: %s", media_path, exc)

    ffmpeg_exe, _ = get_ffmpeg_paths()
    if ffmpeg_exe:
        try:
            cmd = [ffmpeg_exe, "-i", str(p)]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res.stderr)
            if m:
                h, m_, s = m.groups()
                return int(h) * 3600 + int(m_) * 60 + float(s)
        except Exception as exc:
            logger.debug("ffmpeg duration parse failed for %s: %s", media_path, exc)
    return 0.0

