import os
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable

from app.core.ffmpeg_utils import get_ffmpeg_paths
from app.core.subtitles_generator import generate_subtitles_with_gemini


def build_podcast_video(
    cover_image_path: str,
    narration_audio_path: str,
    output_video_path: str,
    bgm_path: Optional[str] = None,
    waveform_color: str = "0x38bdf8",
    enable_subtitles: bool = False,
    subtitles_language: str = "pt",
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Renders a Full HD video for a podcast episode:
    - Cover image with animated audio waveform pulsing to the voice
    - Narration audio mixed with optional looped background music (ducking)
    - Optional burned-in AI-translated subtitles
    """
    ffmpeg_exe, _ = get_ffmpeg_paths()
    out_file = Path(output_video_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(10.0, "Preparando capa e visualizador de ondas sonoras...")

    # Optional Subtitles generation
    srt_path = None
    if enable_subtitles:
        if progress_callback:
            progress_callback(20.0, "Transcrevendo e traduzindo legendas com IA Gemini...")
        try:
            srt_path = generate_subtitles_with_gemini(
                audio_path=narration_audio_path,
                target_language=subtitles_language,
            )
        except Exception as e:
            print(f"Aviso: falha ao gerar legendas no podcast: {e}")

    if progress_callback:
        progress_callback(40.0, "Iniciando renderização de vídeo e sincronização de áudio...")

    # Build filter complex
    # Base video 1080p canvas with cover image centered/scaled
    # [0:v] is cover image
    # [1:a] is narration audio
    # [2:a] is bgm audio (if present)

    has_bgm = bool(bgm_path and Path(bgm_path).exists())

    filter_complex_parts = []

    # 1. Scale cover image to 1920x1080 (maintaining aspect ratio on dark background)
    filter_complex_parts.append(
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0b0d13[bg]"
    )

    # 2. Audio waveform generator from narration
    filter_complex_parts.append(
        f"[1:a]showwaves=s=1400x200:mode=line:colors={waveform_color}@0.92:scale=cbrt,format=yuva420p[wave]"
    )

    # 3. Overlay waveform onto bottom third of background
    filter_complex_parts.append("[bg][wave]overlay=(W-w)/2:H-h-70[v_pre]")

    # 4. Burn in subtitles if requested
    if srt_path and Path(srt_path).exists():
        escaped_srt = str(Path(srt_path).resolve()).replace("\\", "/").replace(":", "\\:")
        sub_filter = (
            f"subtitles='{escaped_srt}':"
            "force_style='FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H90000000,BackColour=&H60000000,BorderStyle=3,MarginV=30'"
        )
        filter_complex_parts.append(f"[v_pre]{sub_filter}[v_out]")
        final_video_label = "[v_out]"
    else:
        final_video_label = "[v_pre]"

    # 5. Audio mixing
    if has_bgm:
        # Loop BGM with reduced volume (15%) + narration (100%)
        filter_complex_parts.append("[1:a]volume=1.0[voice]")
        filter_complex_parts.append("[2:a]volume=0.14[bgm]")
        filter_complex_parts.append("[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[a_out]")
        final_audio_label = "[a_out]"
    else:
        final_audio_label = "1:a"

    cmd = [
        ffmpeg_exe, "-y",
        "-loop", "1", "-i", str(Path(cover_image_path).resolve()),
        "-i", str(Path(narration_audio_path).resolve()),
    ]

    if has_bgm:
        cmd.extend(["-stream_loop", "-1", "-i", str(Path(bgm_path).resolve())])

    full_filter = ";".join(filter_complex_parts)

    cmd.extend([
        "-filter_complex", full_filter,
        "-map", final_video_label,
        "-map", final_audio_label,
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out_file),
    ])

    if progress_callback:
        progress_callback(60.0, "Processando vídeo com aceleração FFmpeg...")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou ao criar vídeo do podcast:\n{stderr[-600:]}")

    if progress_callback:
        progress_callback(100.0, "Vídeo do podcast gerado com sucesso!")

    return str(out_file)
