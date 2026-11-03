"""Deterministic export presets. 4K requires an explicit opt-in limit."""

import os
from typing import Tuple

PRESETS = {
    "720p": (1280, 720), "1080p": (1920, 1080),
    "square": (1080, 1080), "vertical": (1080, 1920), "4k": (3840, 2160),
}
AUDIO_FORMATS = ("mp3", "wav")


def resolve_preset(name: str, allow_4k: bool = False) -> Tuple[int, int]:
    key = (name or "1080p").lower()
    if key not in PRESETS:
        raise ValueError(f"Preset desconhecido: {name!r} (use {sorted(PRESETS)})")
    if key == "4k" and not (allow_4k or os.environ.get("ALLOW_4K") == "1"):
        raise ValueError("4K exige limite explícito (allow_4k / ALLOW_4K=1).")
    return PRESETS[key]


def ffmpeg_video_args(width: int, height: int, fps: int = 30) -> list:
    """Structured argv fragment (never a shell string)."""
    if width % 2 or height % 2:
        raise ValueError("Dimensões H.264 devem ser pares.")
    return ["-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:v", "libx264", "-r", str(fps), "-c:a", "aac", "-b:a", "192k"]
