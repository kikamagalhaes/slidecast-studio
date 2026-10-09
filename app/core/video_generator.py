import os
import subprocess
import tempfile
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Callable

from app.core.ffmpeg_utils import get_ffmpeg_paths


class VideoGenerationError(Exception):
    pass


def generate_video(
    slide_images: List[Path],
    durations: List[float],
    audio_path: str,
    output_path: str,
    resolution: Tuple[int, int] = (1920, 1080),
    fps: int = 30,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Combines slide images and audio into a high-quality MP4 video using FFmpeg.
    
    :param slide_images: List of slide image file paths.
    :param durations: List of durations in seconds for each slide.
    :param audio_path: Path to the audio file.
    :param output_path: Destination path for the rendered MP4 video.
    :param resolution: Target (width, height), e.g. (1920, 1080).
    :param fps: Frames per second.
    :param progress_callback: Function called with (progress_fraction [0.0 - 1.0], message).
    :param cancel_check: Function returning True if the user requested cancellation.
    :return: Absolute path to the created video.
    """
    if len(slide_images) != len(durations):
        raise ValueError("A quantidade de imagens e durações deve ser idêntica.")
    if len(slide_images) == 0:
        raise ValueError("Nenhum slide fornecido.")

    ffmpeg_path, _ = get_ffmpeg_paths()
    if not ffmpeg_path:
        raise VideoGenerationError(
            "FFmpeg não foi encontrado no sistema. "
            "Por favor, instale o FFmpeg ou coloque o executável na pasta do aplicativo."
        )

    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    total_expected_duration = sum(durations)
    if total_expected_duration <= 0:
        raise ValueError("A duração total dos slides deve ser maior que zero.")

    # Create temporary concat demuxer file
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f_concat:
        concat_file_path = f_concat.name
        for img_path, dur in zip(slide_images, durations):
            # Posix path with forward slashes is required by FFmpeg concat even on Windows
            posix_path = img_path.resolve().as_posix().replace("'", "'\\''")
            f_concat.write(f"file '{posix_path}'\n")
            f_concat.write(f"duration {dur:.4f}\n")
        # Demuxer requires repeating the last file
        last_posix_path = slide_images[-1].resolve().as_posix().replace("'", "'\\''")
        f_concat.write(f"file '{last_posix_path}'\n")

    w, h = resolution
    video_filter = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"format=yuv420p"
    )

    cmd = [
        ffmpeg_path,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file_path,
        "-i", str(Path(audio_path).resolve()),
        "-vf", video_filter,
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-shortest",
        "-progress", "pipe:1",
        str(out_file),
    ]

    # stderr goes to a temp file (not a pipe): FFmpeg is chatty and an
    # undrained pipe would eventually block the encoder mid-render.
    stderr_capture = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")
    try:
        # Hide console window on Windows
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=stderr_capture,
            text=True,
            bufsize=1,
            startupinfo=startupinfo,
        )

        encoded_time = 0.0

        while True:
            if cancel_check and cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                if out_file.exists():
                    out_file.unlink(missing_ok=True)
                raise InterruptedError("Geração de vídeo cancelada pelo usuário.")

            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue

            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    us_str = line.split("=")[1]
                    encoded_time = float(us_str) / 1_000_000.0
                    if total_expected_duration > 0 and progress_callback:
                        progress = min(1.0, max(0.0, encoded_time / total_expected_duration))
                        msg = f"Codificando vídeo: {encoded_time:.1f}s / {total_expected_duration:.1f}s ({int(progress * 100)}%)"
                        progress_callback(progress, msg)
                except Exception:
                    pass

        returncode = process.wait()
        if returncode != 0:
            stderr_capture.seek(0)
            stderr_output = stderr_capture.read()
            raise VideoGenerationError(f"Erro no FFmpeg (código {returncode}):\n{stderr_output[-500:]}")

        if progress_callback:
            progress_callback(1.0, "Vídeo renderizado com sucesso!")

        return str(out_file)

    finally:
        try:
            stderr_capture.close()
        except Exception:
            pass
        # Clean up concat temporary file
        try:
            if os.path.exists(concat_file_path):
                os.remove(concat_file_path)
        except Exception:
            pass
