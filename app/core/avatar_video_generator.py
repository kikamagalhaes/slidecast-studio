import asyncio
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests
import edge_tts

from app.core.config_manager import (
    get_elevenlabs_api_key,
    get_replicate_api_key,
)
from app.core.clone_manager import update_clone_metadata
from app.core.ffmpeg_utils import get_ffmpeg_paths, get_video_duration

logger = logging.getLogger(__name__)


def edge_tts_timeout() -> float:
    """Neural TTS time budget in seconds (env ``EDGE_TTS_TIMEOUT``)."""
    try:
        return max(10.0, float(os.environ.get("EDGE_TTS_TIMEOUT", "180")))
    except ValueError:
        return 180.0


def synthesize_edge_tts(text: str, voice: str, out_path: Path, timeout: float) -> None:
    """Runs Edge-TTS synthesis in a dedicated thread with a hard timeout.

    Isolates ``asyncio.run`` from any Qt worker thread that may already own
    an event loop, and guarantees a hung network call cannot block forever.
    """
    errors: Dict[str, BaseException] = {}

    def _target() -> None:
        try:

            async def _run() -> None:
                comm = edge_tts.Communicate(text, voice)
                await comm.save(str(out_path))

            asyncio.run(_run())
        except BaseException as exc:  # re-raised in the caller thread
            errors["error"] = exc

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"Edge-TTS excedeu o tempo limite de {timeout:g}s.")
    if "error" in errors:
        raise errors["error"]


def generate_avatar_speech(
    text: str,
    output_audio_path: str,
    clone_data: Optional[Dict] = None,
    preferred_voice: str = "pt-BR-FranciscaNeural",
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Synthesizes speech for the digital clone:
    - If ElevenLabs API key is configured and clone has voice_sample: Uses ElevenLabs Instant Voice Cloning!
    - Otherwise (Local / Fallback): Uses neural Portuguese TTS (fast, natural, zero-cost).
    """
    out_p = Path(output_audio_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    eleven_key = get_elevenlabs_api_key()
    voice_path = clone_data.get("voice_path") if clone_data else None

    # Try ElevenLabs Voice Cloning if key is present
    if eleven_key and voice_path and Path(voice_path).exists():
        try:
            if progress_callback:
                progress_callback(0.15, "Sintetizando fala com voz clonada (ElevenLabs)...")

            voice_id = clone_data.get("elevenlabs_voice_id")
            if not voice_id:
                # Add voice to ElevenLabs
                if progress_callback:
                    progress_callback(0.25, "Registrando perfil de voz no ElevenLabs...")
                url_add = "https://api.elevenlabs.io/v1/voices/add"
                headers = {"xi-api-key": eleven_key}
                clone_name = clone_data.get("name", "Clone Digital")
                with open(voice_path, "rb") as f:
                    files = {"files": (Path(voice_path).name, f, "audio/wav")}
                    data = {"name": f"SlideCast_{clone_name}_{int(time.time())}", "description": "Clone SlideCast"}
                    resp = requests.post(url_add, headers=headers, data=data, files=files, timeout=30)
                if resp.status_code == 200:
                    voice_id = resp.json().get("voice_id")
                    clone_data["elevenlabs_voice_id"] = voice_id
                    # Persist so the voice is not re-registered (and re-billed
                    # in quota) on every synthesis.
                    clone_id = clone_data.get("id")
                    if clone_id:
                        update_clone_metadata(clone_id, {"elevenlabs_voice_id": voice_id})
                else:
                    logger.warning("ElevenLabs add voice falhou: %s", resp.text)

            if voice_id:
                if progress_callback:
                    progress_callback(0.4, "Gerando áudio com a voz da professora...")
                tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                headers = {"xi-api-key": eleven_key, "Content-Type": "application/json"}
                payload = {
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.45, "similarity_boost": 0.85},
                }
                tts_resp = requests.post(tts_url, headers=headers, json=payload, timeout=60)
                if tts_resp.status_code == 200:
                    with open(out_p, "wb") as f:
                        f.write(tts_resp.content)
                    return str(out_p)

        except Exception as exc:
            logger.warning("ElevenLabs falhou, usando TTS neural local: %s", exc)

    # Fallback to high-quality neural voice (Edge-TTS)
    if progress_callback:
        progress_callback(0.3, "Sintetizando voz em português (Motor Neural)...")

    try:
        synthesize_edge_tts(text, preferred_voice, out_p, edge_tts_timeout())
    except TimeoutError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Falha na síntese de voz neural (verifique a conexão): {exc}"
        ) from exc
    return str(out_p)


def detect_audio_silences(
    audio_path: str,
    noise_db: float = -28.0,
    min_silence_dur: float = 0.22,
) -> List[Tuple[float, float]]:
    """
    Detects silent pauses in the narration speech audio using FFmpeg's silencedetect filter.
    Returns a list of (start_sec, end_sec) for each pause.
    """
    import re
    ffmpeg_exe, _ = get_ffmpeg_paths()
    cmd = [
        ffmpeg_exe, "-y",
        "-i", str(Path(audio_path).resolve()),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_dur}",
        "-f", "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        silences = []
        current_start = None
        for line in proc.stderr.splitlines():
            if "silence_start:" in line:
                m = re.search(r"silence_start:\s*([\d\.]+)", line)
                if m:
                    current_start = float(m.group(1))
            elif "silence_end:" in line and current_start is not None:
                m = re.search(r"silence_end:\s*([\d\.]+)", line)
                if m:
                    end_sec = float(m.group(1))
                    silences.append((current_start, end_sec))
                    current_start = None
        return silences
    except Exception as exc:
        logger.warning("Falha ao detectar silêncios de áudio: %s", exc)
        return []


def generate_replicate_lipsync(
    video_path: str,
    audio_path: str,
    output_video_path: str,
    api_token: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> bool:
    """
    Calls Replicate cloud neural lip-sync API (sync/lipsync-2 with devxpy/cog-wav2lip fallback).
    Produces authentic per-phoneme mouth synchronization.
    """
    try:
        import replicate
        client = replicate.Client(api_token=api_token)
    except Exception as exc:
        logger.warning("Replicate client indisponível: %s", exc)
        return False

    if progress_callback:
        progress_callback(0.65, "Enviando para IA neural de sincronia labial (Replicate)...")

    # 1. Try sync/lipsync-2 (state-of-the-art zero-shot lip-sync)
    try:
        with open(video_path, "rb") as vf, open(audio_path, "rb") as af:
            if progress_callback:
                progress_callback(0.70, "Processando sincronia labial neural (Lipsync-2)...")
            output = client.run(
                "sync/lipsync-2",
                input={
                    "video": vf,
                    "audio": af,
                    "sync_mode": "loop",
                },
            )
            if output:
                video_url = str(output)
                if progress_callback:
                    progress_callback(0.85, "Baixando vídeo com sincronia labial neural...")
                resp = requests.get(video_url, stream=True, timeout=120)
                if resp.status_code == 200:
                    with open(output_video_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            f.write(chunk)
                    return True
    except Exception as e:
        logger.warning("Lipsync-2 falhou: %s. Tentando modelo Wav2Lip...", e)

    # 2. Fallback to devxpy/cog-wav2lip
    try:
        with open(video_path, "rb") as vf, open(audio_path, "rb") as af:
            if progress_callback:
                progress_callback(0.72, "Processando com Wav2Lip neural...")
            output = client.run(
                "devxpy/cog-wav2lip:2b9b772c6cfb2f0a1426ea5d63f0d5757ccb1e8fa8d39f7278d655f0532ff4ff",
                input={
                    "face": vf,
                    "audio": af,
                    "fps": 30,
                    "smooth": True,
                },
            )
            if output:
                video_url = str(output)
                if progress_callback:
                    progress_callback(0.85, "Baixando vídeo sincronizado do Wav2Lip...")
                resp = requests.get(video_url, stream=True, timeout=120)
                if resp.status_code == 200:
                    with open(output_video_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            f.write(chunk)
                    return True
    except Exception as e2:
        logger.warning("cog-wav2lip falhou: %s", e2)

    return False


def render_local_cadence_avatar(
    video_sample: str,
    face_path: Optional[str],
    audio_path: str,
    output_video_path: str,
    audio_dur: float,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Renders the local smart avatar with speech cadence synchronization:
    - Active speech: Plays the teacher's reference video with natural mouth and head motion.
    - Pauses in speech (>=0.32s): Shows the attentive resting face (mouth closed).
    - Uses temporal blending (tblend) to eliminate harsh instantaneous cuts and soften transitions.
    """
    ffmpeg_exe, _ = get_ffmpeg_paths()
    has_face = bool(face_path and Path(face_path).exists())

    silences = detect_audio_silences(audio_path, noise_db=-28.0, min_silence_dur=0.32)

    if has_face and silences:
        enable_expr = "+".join([f"between(t,{round(s, 3)},{round(e, 3)})" for s, e in silences])
        cmd = [
            ffmpeg_exe, "-y",
            "-stream_loop", "-1",
            "-i", str(Path(video_sample).resolve()),
            "-loop", "1",
            "-i", str(Path(face_path).resolve()),
            "-i", str(Path(audio_path).resolve()),
            "-filter_complex",
            f"[0:v]scale=1280:720,format=yuv420p[vid];"
            f"[1:v]scale=1280:720,format=yuv420p[rest];"
            f"[vid][rest]overlay=enable='{enable_expr}':eof_action=repeat[ov];"
            f"[ov]tblend=all_mode=average,format=yuv420p[vout]",
            "-t", str(audio_dur),
            "-map", "[vout]",
            "-map", "2:a:0",
            "-r", "30",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_video_path),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return output_video_path
        except Exception as e:
            logger.warning("tblend falhou, usando fallback sem blend: %s", e)
            cmd_fallback = [
                ffmpeg_exe, "-y",
                "-stream_loop", "-1",
                "-i", str(Path(video_sample).resolve()),
                "-loop", "1",
                "-i", str(Path(face_path).resolve()),
                "-i", str(Path(audio_path).resolve()),
                "-filter_complex",
                f"[0:v]scale=1280:720,format=yuv420p[vid];"
                f"[1:v]scale=1280:720,format=yuv420p[rest];"
                f"[vid][rest]overlay=enable='{enable_expr}':eof_action=repeat[vout]",
                "-t", str(audio_dur),
                "-map", "[vout]",
                "-map", "2:a:0",
                "-r", "30",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_video_path),
            ]
            subprocess.run(cmd_fallback, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return output_video_path
    else:
        cmd = [
            ffmpeg_exe, "-y",
            "-stream_loop", "-1",
            "-i", str(Path(video_sample).resolve()),
            "-i", str(Path(audio_path).resolve()),
            "-t", str(audio_dur),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-r", "30",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_video_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_video_path


def render_avatar_video(
    clone_data: Dict,
    audio_path: str,
    output_video_path: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    engine_mode: str = "local_cadence",
) -> str:
    """
    Renders the talking avatar video:
    - engine_mode == 'cloud_replicate': Uses Replicate Lipsync-2 / Wav2Lip neural AI (cloud GPU).
    - engine_mode == 'local_cadence' (or 'local_fast', 'local_neural', 'local', 'auto'):
      Uses Local Smart Engine with speech cadence & resting mouth synchronization.
    """
    ffmpeg_exe, _ = get_ffmpeg_paths()
    out_video = Path(output_video_path).resolve()
    out_video.parent.mkdir(parents=True, exist_ok=True)

    replicate_token = get_replicate_api_key()
    face_path = clone_data.get("face_path")
    video_sample = clone_data.get("video_path")

    # Measure speech audio duration
    audio_dur = get_video_duration(audio_path)
    if audio_dur <= 0.1:
        audio_dur = 5.0

    # 1. Option 1: Neural Cloud Engine (Replicate API)
    if engine_mode == "cloud_replicate" and replicate_token and video_sample and Path(video_sample).exists():
        if progress_callback:
            progress_callback(0.6, "Iniciando sincronia labial neural em nuvem (Replicate Lipsync-2)...")
        success = generate_replicate_lipsync(
            video_path=video_sample,
            audio_path=audio_path,
            output_video_path=str(out_video),
            api_token=replicate_token,
            progress_callback=progress_callback,
        )
        if success and out_video.exists() and out_video.stat().st_size > 1000:
            if progress_callback:
                progress_callback(0.9, "Sincronia labial neural concluída com sucesso!")
            return str(out_video)
        logger.warning(
            "Sincronia em nuvem falhou ou não retornou vídeo; usando motor local."
        )

    # 2. Option 2: Local Smart Engine (Cadence synchronization with resting mouth pauses)
    if progress_callback:
        progress_callback(0.6, "Sincronizando movimentos da professora com o ritmo e pausas da fala...")

    if video_sample and Path(video_sample).exists():
        render_local_cadence_avatar(
            video_sample=video_sample,
            face_path=face_path,
            audio_path=audio_path,
            output_video_path=str(out_video),
            audio_dur=audio_dur,
            progress_callback=progress_callback,
        )
    elif face_path and Path(face_path).exists():
        cmd = [
            ffmpeg_exe, "-y",
            "-loop", "1",
            "-i", str(Path(face_path).resolve()),
            "-i", str(Path(audio_path).resolve()),
            "-t", str(audio_dur),
            "-vf", "scale=1280:720,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-b:a", "192k",
            str(out_video),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        raise RuntimeError("O clone selecionado não possui amostras de vídeo ou imagem válidas.")

    if progress_callback:
        progress_callback(0.9, "Avatar finalizado com sucesso!")

    return str(out_video)


def composite_avatar_with_slide(
    slide_image_path: str,
    avatar_video_path: str,
    output_video_path: str,
    position: str = "bottom_right",
    pip_size: Tuple[int, int] = (384, 216),
) -> str:
    """
    Overlays the digital avatar video as a stylish picture-in-picture (PIP) box
    onto the slide presentation image.
    """
    ffmpeg_exe, _ = get_ffmpeg_paths()
    out_video = Path(output_video_path).resolve()
    out_video.parent.mkdir(parents=True, exist_ok=True)

    w, h = pip_size
    if position == "top_right":
        pos_expr = "W-w-24:24"
    elif position == "bottom_left":
        pos_expr = "24:H-h-24"
    elif position == "top_left":
        pos_expr = "24:24"
    else:  # bottom_right
        pos_expr = "W-w-24:H-h-24"

    cmd = [
        ffmpeg_exe, "-y",
        "-loop", "1",
        "-i", str(Path(slide_image_path).resolve()),
        "-i", str(Path(avatar_video_path).resolve()),
        "-filter_complex",
        f"[0:v]scale=1920:1080[bg];"
        f"[1:v]scale={w}:{h},drawbox=0:0:{w}:{h}:color=white@0.8:t=2[pip];"
        f"[bg][pip]overlay={pos_expr}:shortest=1[v]",
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(out_video),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return str(out_video)
