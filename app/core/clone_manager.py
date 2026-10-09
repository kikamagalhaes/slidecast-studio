import json
import logging
import time
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

from app.core.config_manager import (
    get_config_dir,
    get_active_clone_id,
    set_active_clone_id,
)
from app.core.ffmpeg_utils import get_ffmpeg_paths


def get_clones_dir() -> Path:
    clones_dir = get_config_dir() / "clones"
    clones_dir.mkdir(parents=True, exist_ok=True)
    return clones_dir


def list_clones() -> List[Dict]:
    """Returns a list of all saved digital clones."""
    clones_dir = get_clones_dir()
    clones = []
    for d in sorted(clones_dir.iterdir()):
        if d.is_dir():
            meta_file = d / "metadata.json"
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        clones.append(data)
                except Exception as exc:
                    logger.warning("Aviso lendo clone em %s: %s", d, exc)
    return clones


def get_clone(clone_id: str) -> Optional[Dict]:
    clone_dir = get_clones_dir() / clone_id
    meta_file = clone_dir / "metadata.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def get_active_clone() -> Optional[Dict]:
    active_id = get_active_clone_id()
    if active_id:
        clone = get_clone(active_id)
        if clone:
            return clone
    all_clones = list_clones()
    if all_clones:
        return all_clones[0]
    return None


def _extract_clone_assets(
    raw_video_path: str,
    target_video: Path,
    target_voice: Path,
    target_face: Path,
    ffmpeg_exe: str,
) -> None:
    """Copies the sample video and derives the voice + face reference files."""
    # 1. Copy video file
    shutil.copy2(raw_video_path, str(target_video))

    # 2. Extract clean audio (16kHz mono PCM for voice cloning)
    cmd_audio = [
        ffmpeg_exe, "-y",
        "-i", str(target_video),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(target_voice),
    ]
    subprocess.run(cmd_audio, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 3. Extract clear face reference frame (at 2.0s mark)
    cmd_face = [
        ffmpeg_exe, "-y",
        "-ss", "2.0",
        "-i", str(target_video),
        "-frames:v", "1",
        "-q:v", "2",
        str(target_face),
    ]
    try:
        subprocess.run(cmd_face, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # Fallback to first frame if video is shorter than 2s
        cmd_fallback = [
            ffmpeg_exe, "-y",
            "-i", str(target_video),
            "-frames:v", "1",
            "-q:v", "2",
            str(target_face),
        ]
        subprocess.run(cmd_fallback, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def create_clone(
    name: str,
    raw_video_path: str,
    engine: str = "cloud",
    preferred_voice: str = "pt-BR-FranciscaNeural",
    background_image: Optional[str] = None,
) -> Dict:
    """
    Creates a new digital clone profile from a 10-20s calibration video:
    - Extracts voice_sample.wav (clean mono 16kHz audio)
    - Extracts face_photo.png (clear high-res facial reference image)
    - Stores reference video_sample.mp4
    - Generates metadata.json
    """
    ffmpeg_exe, _ = get_ffmpeg_paths()
    if not ffmpeg_exe:
        raise RuntimeError("FFmpeg não encontrado; não é possível criar o clone.")
    timestamp = int(time.time())
    safe_slug = "".join(c for c in name.lower().replace(" ", "_") if c.isalnum() or c in "_-")[:20] or "clone"
    clone_id = f"{safe_slug}_{timestamp}"

    clone_dir = get_clones_dir() / clone_id
    clone_dir.mkdir(parents=True, exist_ok=True)

    target_video = clone_dir / "video_sample.mp4"
    target_voice = clone_dir / "voice_sample.wav"
    target_face = clone_dir / "face_photo.png"

    try:
        _extract_clone_assets(raw_video_path, target_video, target_voice, target_face, ffmpeg_exe)
    except Exception:
        shutil.rmtree(clone_dir, ignore_errors=True)
        raise

    metadata = {
        "id": clone_id,
        "name": name.strip() or "Meu Clone IA",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "engine": engine,
        "video_path": str(target_video.resolve()),
        "voice_path": str(target_voice.resolve()),
        "face_path": str(target_face.resolve()),
        "elevenlabs_voice_id": None,
        "preferred_voice": preferred_voice,
        "background_image": None,
    }

    if background_image and Path(background_image).is_file():
        try:
            target_bg = clone_dir / f"background_{int(time.time())}{Path(background_image).suffix}"
            shutil.copy2(background_image, str(target_bg))
            metadata["background_image"] = str(target_bg.resolve())
        except Exception as exc:
            logger.warning("Aviso ao copiar fundo do clone: %s", exc)

    meta_file = clone_dir / "metadata.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    set_active_clone_id(clone_id)
    return metadata


def update_clone_metadata(clone_id: str, new_fields: dict) -> Optional[Dict]:
    """Updates fields in an existing clone's metadata.json."""
    clone_dir = get_clones_dir() / clone_id
    meta_file = clone_dir / "metadata.json"
    if not meta_file.exists():
        return None
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.update(new_fields)
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return data
    except Exception as exc:
        logger.error("Erro ao atualizar metadados do clone %s: %s", clone_id, exc)
        return None


def delete_clone(clone_id: str):
    clone_dir = get_clones_dir() / clone_id
    if clone_dir.exists() and clone_dir.is_dir():
        shutil.rmtree(str(clone_dir), ignore_errors=True)
    if get_active_clone_id() == clone_id:
        set_active_clone_id("")
