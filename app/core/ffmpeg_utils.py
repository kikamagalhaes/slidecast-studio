import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)


def get_ffmpeg_paths() -> Tuple[Optional[str], Optional[str]]:
    """Honor explicit overrides, prefer packaged tools in frozen apps, then PATH."""
    suffix = ".exe" if sys.platform == "win32" else ""
    app_dir = Path(__file__).resolve().parent.parent.parent
    bundle_dir = Path(getattr(sys, "_MEIPASS", app_dir))
    candidates = [bundle_dir, app_dir, app_dir / "bin", app_dir / "ffmpeg"]

    def locate(name: str) -> Optional[str]:
        override = os.environ.get(name.upper() + "_PATH")
        if override:
            return override
        executable = name + suffix
        packaged = next((str(folder / executable) for folder in candidates
                         if (folder / executable).is_file() and os.access(folder / executable, os.X_OK)), None)
        if getattr(sys, "frozen", False):
            return packaged or shutil.which(executable)
        return shutil.which(executable) or packaged

    return locate("ffmpeg"), locate("ffprobe")


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
    # stdin=DEVNULL: FFmpeg reads interactive commands from stdin; inheriting
    # a GUI/terminal stdin can stall renders. Renders never need stdin input.
    process = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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

