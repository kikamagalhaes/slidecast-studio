import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.ffmpeg_utils import get_ffmpeg_paths, format_duration

logger = logging.getLogger(__name__)


@dataclass
class AudioInfo:
    file_path: str
    file_name: str
    duration: float
    formatted_duration: str
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    file_size_bytes: int = 0


def get_audio_info(file_path: str) -> AudioInfo:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de áudio não encontrado: {file_path}")

    file_size = path.stat().st_size
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None

    # 1. Try mutagen first (pure python)
    try:
        import mutagen
        audio = mutagen.File(file_path)
        if audio is not None and hasattr(audio, 'info') and audio.info is not None:
            if hasattr(audio.info, 'length') and audio.info.length is not None:
                duration = float(audio.info.length)
            if hasattr(audio.info, 'sample_rate'):
                sample_rate = int(audio.info.sample_rate)
            if hasattr(audio.info, 'channels'):
                channels = int(audio.info.channels)
    except Exception as exc:
        logger.debug("mutagen probe failed for %s: %s", file_path, exc)

    # 2. Fallback to ffprobe if mutagen didn't get duration or failed
    if duration is None or duration <= 0:
        _, ffprobe_path = get_ffmpeg_paths()
        if ffprobe_path:
            cmd = [
                ffprobe_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                data = json.loads(result.stdout)
                
                # Check format duration
                if "format" in data and "duration" in data["format"]:
                    duration = float(data["format"]["duration"])
                
                # Check streams
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "audio":
                        if duration is None and "duration" in stream:
                            duration = float(stream["duration"])
                        if sample_rate is None and "sample_rate" in stream:
                            sample_rate = int(stream["sample_rate"])
                        if channels is None and "channels" in stream:
                            channels = int(stream["channels"])
                        break
            except Exception as e:
                raise RuntimeError(f"Falha ao ler duração com ffprobe: {e}")

    if duration is None or duration <= 0:
        raise ValueError("Não foi possível determinar a duração do arquivo de áudio.")

    return AudioInfo(
        file_path=str(path.resolve()),
        file_name=path.name,
        duration=duration,
        formatted_duration=format_duration(duration),
        sample_rate=sample_rate,
        channels=channels,
        file_size_bytes=file_size,
    )
