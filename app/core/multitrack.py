"""Multimedia Multitrack Core Model for SlideCast Studio Desktop.

Defines data models and serialization for:
- Audio tracks (up to 4 independent tracks with volume, mute, offset, probe metadata)
- Visual sources (PDF presentation or MP4 video)
- Multimedia project with schema versioning and backwards compatibility
- Probing helpers for video and audio
"""
from __future__ import annotations

import json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from app.core.ffmpeg_utils import get_ffmpeg_paths, format_duration
from app.core.audio_processor import get_audio_info

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
MAX_AUDIO_TRACKS = 4

SUPPORTED_AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".webm"}
)

SUPPORTED_VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".mkv", ".webm"}
)

DEFAULT_TRACK_NAMES = (
    "Narração / Voz",
    "Música de Fundo",
    "Efeitos Sonoros",
    "Áudio Complementar",
)


@dataclass
class AudioTrack:
    """Represents an independent audio track in the multimedia project."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Faixa de Áudio"
    file_path: str = ""
    duration: float = 0.0
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    file_size_bytes: int = 0
    volume: float = 1.0  # 0.0 to 2.0 (1.0 = 100%)
    mute: bool = False
    offset: float = 0.0  # Start offset in seconds on timeline (>= 0.0)
    fade_in: float = 0.0  # Optional fade in (seconds)
    fade_out: float = 0.0  # Optional fade out (seconds)
    loop: bool = False  # Optional loop setting

    def __post_init__(self):
        self.volume = max(0.0, min(2.0, float(self.volume)))
        self.offset = max(0.0, float(self.offset))
        self.fade_in = max(0.0, float(self.fade_in))
        self.fade_out = max(0.0, float(self.fade_out))
        self.duration = max(0.0, float(self.duration))

    @property
    def formatted_duration(self) -> str:
        return format_duration(self.duration)

    def effective_end(self) -> float:
        """Returns the timeline position (in seconds) where this track ends."""
        return self.offset + self.duration

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AudioTrack:
        clean = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**clean)


@dataclass
class VideoInfo:
    """Probed metadata for an imported MP4/video file."""
    file_path: str
    duration: float
    width: int
    height: int
    fps: float = 30.0
    codec_name: str = "h264"
    pix_fmt: str = "yuv420p"
    has_audio: bool = False
    audio_codec: Optional[str] = None
    file_size_bytes: int = 0

    @property
    def formatted_duration(self) -> str:
        return format_duration(self.duration)

    @property
    def resolution_str(self) -> str:
        return f"{self.width}x{self.height}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VideoInfo:
        clean = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**clean)


def inspect_video(file_path: str) -> VideoInfo:
    """Inspects a video file using ffprobe and extracts technical metadata."""
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo de vídeo não encontrado: {file_path}")

    _, ffprobe_path = get_ffmpeg_paths()
    if not ffprobe_path:
        raise RuntimeError("ffprobe não encontrado no sistema.")

    cmd = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(p),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
    except Exception as exc:
        raise ValueError(f"Falha ao inspecionar o arquivo de vídeo {file_path}: {exc}")

    format_info = data.get("format", {})
    streams = data.get("streams", [])

    duration = 0.0
    if "duration" in format_info:
        try:
            duration = float(format_info["duration"])
        except (ValueError, TypeError):
            pass

    width = 0
    height = 0
    fps = 30.0
    video_codec = "h264"
    pix_fmt = "yuv420p"
    has_audio = False
    audio_codec = None

    for s in streams:
        c_type = s.get("codec_type")
        if c_type == "video" and width == 0:
            width = int(s.get("width", 0))
            height = int(s.get("height", 0))
            video_codec = s.get("codec_name", "h264")
            pix_fmt = s.get("pix_fmt", "yuv420p")
            
            # Duration fallback
            if duration <= 0 and "duration" in s:
                try:
                    duration = float(s["duration"])
                except (ValueError, TypeError):
                    pass

            # FPS parsing (e.g. "30/1" or "29.97")
            r_fps = s.get("r_frame_rate", "")
            if "/" in r_fps:
                num, den = r_fps.split("/", 1)
                try:
                    den_f = float(den)
                    if den_f > 0:
                        fps = round(float(num) / den_f, 2)
                except ValueError:
                    pass
            elif r_fps:
                try:
                    fps = round(float(r_fps), 2)
                except ValueError:
                    pass

        elif c_type == "audio":
            has_audio = True
            audio_codec = s.get("codec_name")

    if duration <= 0:
        raise ValueError(f"Não foi possível determinar a duração do vídeo: {file_path}")
    if width <= 0 or height <= 0:
        raise ValueError(f"Dimensões de vídeo inválidas ({width}x{height}): {file_path}")

    return VideoInfo(
        file_path=str(p),
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        codec_name=video_codec,
        pix_fmt=pix_fmt,
        has_audio=has_audio,
        audio_codec=audio_codec,
        file_size_bytes=p.stat().st_size,
    )


def probe_audio_track(
    file_path: str,
    track_id: Optional[str] = None,
    name: Optional[str] = None,
    volume: float = 1.0,
    offset: float = 0.0,
    mute: bool = False,
) -> AudioTrack:
    """Probes an audio file and constructs a validated AudioTrack."""
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo de áudio não encontrado: {file_path}")

    ext = p.suffix.lower()
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise ValueError(
            f"Formato de áudio não suportado: {ext}. Formatos aceitos: {allowed}"
        )

    audio_info = get_audio_info(str(p))
    if audio_info.duration <= 0:
        raise ValueError(f"Arquivo de áudio sem duração válida: {file_path}")

    t_id = track_id or str(uuid.uuid4())[:8]
    t_name = name or p.stem

    return AudioTrack(
        id=t_id,
        name=t_name,
        file_path=str(p),
        duration=audio_info.duration,
        sample_rate=audio_info.sample_rate,
        channels=audio_info.channels,
        file_size_bytes=audio_info.file_size_bytes,
        volume=volume,
        mute=mute,
        offset=offset,
    )


@dataclass
class MultimediaProject:
    """Represents a complete multimedia project with PDF/video visual source and multitrack audio."""
    schema_version: int = SCHEMA_VERSION
    title: str = "Projeto SlideCast"
    visual_source_type: str = "pdf"  # "pdf" | "video"
    visual_source_path: Optional[str] = None
    slide_durations: List[float] = field(default_factory=list)
    video_info: Optional[VideoInfo] = None
    ignore_original_audio: bool = True  # Mandatory default for video sources
    tracks: List[AudioTrack] = field(default_factory=list)
    export_settings: Dict[str, Any] = field(
        default_factory=lambda: {
            "resolution": [1920, 1080],
            "fps": 30,
            "output_path": "",
        }
    )

    def set_visual_source(self, source_type: str, path: str, **kwargs) -> None:
        """Sets the visual source to PDF or Video, probing technical metadata."""
        st = source_type.lower().strip()
        if st not in ("pdf", "video"):
            raise ValueError(f"Tipo de fonte visual inválido: {source_type}. Use 'pdf' ou 'video'.")

        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Arquivo de origem visual não encontrado: {path}")

        if st == "pdf":
            if not p.suffix.lower() == ".pdf":
                raise ValueError(f"Arquivo selecionado não é um PDF: {path}")
            from app.core.pdf_processor import inspect_pdf
            info = inspect_pdf(str(p))
            self.visual_source_type = "pdf"
            self.visual_source_path = str(p)
            self.video_info = None
            # Initialize or keep slide durations
            durations = kwargs.get("slide_durations")
            if durations and len(durations) == info.page_count:
                self.slide_durations = [max(0.1, float(d)) for d in durations]
            else:
                self.slide_durations = [5.0] * info.page_count

        elif st == "video":
            ext = p.suffix.lower()
            if ext not in SUPPORTED_VIDEO_EXTENSIONS:
                allowed = ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
                raise ValueError(f"Formato de vídeo não suportado: {ext}. Aceitos: {allowed}")
            vinfo = inspect_video(str(p))
            self.visual_source_type = "video"
            self.visual_source_path = str(p)
            self.video_info = vinfo
            self.slide_durations = []
            # Keep original resolution as default export setting if not yet set
            if not self.export_settings.get("output_path"):
                self.export_settings["resolution"] = [vinfo.width, vinfo.height]
                self.export_settings["fps"] = int(round(vinfo.fps))

    def add_track(self, track: AudioTrack) -> None:
        """Adds an audio track, respecting the maximum limit of 4 tracks."""
        if len(self.tracks) >= MAX_AUDIO_TRACKS:
            raise ValueError(f"Limite máximo de {MAX_AUDIO_TRACKS} faixas de áudio atingido.")
        # Ensure track has a friendly default name if generic
        if not track.name or track.name == "Faixa de Áudio":
            idx = len(self.tracks)
            if idx < len(DEFAULT_TRACK_NAMES):
                track.name = DEFAULT_TRACK_NAMES[idx]
        self.tracks.append(track)

    def remove_track(self, track_id: str) -> bool:
        """Removes an audio track by ID."""
        for i, t in enumerate(self.tracks):
            if t.id == track_id:
                self.tracks.pop(i)
                return True
        return False

    def get_track(self, track_id: str) -> Optional[AudioTrack]:
        for t in self.tracks:
            if t.id == track_id:
                return t
        return None

    def move_track(self, from_idx: int, to_idx: int) -> None:
        """Reorders tracks within the list."""
        if 0 <= from_idx < len(self.tracks) and 0 <= to_idx < len(self.tracks):
            item = self.tracks.pop(from_idx)
            self.tracks.insert(to_idx, item)

    def calculate_total_duration(self) -> float:
        """Calculates total duration of the master visual source."""
        if self.visual_source_type == "pdf":
            return round(sum(self.slide_durations), 3)
        elif self.visual_source_type == "video" and self.video_info:
            return round(self.video_info.duration, 3)
        return 0.0

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validates the project configuration.
        Returns:
            (is_valid, list_of_errors_or_warnings)
        """
        messages = []
        if not self.visual_source_path:
            messages.append("Nenhuma fonte visual foi selecionada (PDF ou Vídeo).")
            return False, messages

        v_path = Path(self.visual_source_path)
        if not v_path.is_file():
            messages.append(f"Arquivo da fonte visual não encontrado: {self.visual_source_path}")
            return False, messages

        if self.visual_source_type == "pdf":
            if not self.slide_durations:
                messages.append("Nenhum slide ou duração configurada para a apresentação.")
                return False, messages
            if any(d <= 0 for d in self.slide_durations):
                messages.append("Todos os slides devem ter duração maior que zero.")
                return False, messages
        elif self.visual_source_type == "video":
            if not self.video_info or self.video_info.duration <= 0:
                messages.append("Metadados do vídeo de origem não estão disponíveis ou inválidos.")
                return False, messages

        total_dur = self.calculate_total_duration()
        if total_dur <= 0:
            messages.append("A duração total calculada é zero.")
            return False, messages

        if len(self.tracks) > MAX_AUDIO_TRACKS:
            messages.append(f"Excesso de faixas de áudio ({len(self.tracks)} > {MAX_AUDIO_TRACKS}).")
            return False, messages

        # Check track files existence and offsets
        active_tracks_count = 0
        for i, t in enumerate(self.tracks):
            if not Path(t.file_path).is_file():
                messages.append(f"Arquivo da faixa {i + 1} ('{t.name}') não encontrado: {t.file_path}")
                return False, messages
            if t.offset >= total_dur:
                messages.append(
                    f"Aviso: Faixa {i + 1} ('{t.name}') inicia após o final do vídeo ({t.offset:.1f}s >= {total_dur:.1f}s)."
                )
            if not t.mute and t.volume > 0.0:
                active_tracks_count += 1

        if self.tracks and active_tracks_count == 0:
            messages.append("Aviso: Todas as faixas de áudio estão mutadas ou com volume zero. O vídeo exportado será silencioso.")

        return True, messages

    def to_dict(self) -> Dict[str, Any]:
        """Serializes project to a JSON-compatible dictionary."""
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "visual_source_type": self.visual_source_type,
            "visual_source_path": self.visual_source_path,
            "slide_durations": [round(float(d), 4) for d in self.slide_durations],
            "video_info": self.video_info.to_dict() if self.video_info else None,
            "ignore_original_audio": self.ignore_original_audio,
            "tracks": [t.to_dict() for t in self.tracks],
            "export_settings": self.export_settings,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save_to_file(self, file_path: str) -> None:
        p = Path(file_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MultimediaProject:
        """Constructs project from dictionary, supporting schema migrations."""
        schema_ver = int(data.get("schema_version", 1))

        # Schema v1 compatibility (single pdf + single audio)
        if schema_ver == 1:
            project = cls(
                schema_version=SCHEMA_VERSION,
                title=str(data.get("title") or "Projeto SlideCast Legado"),
                visual_source_type="pdf",
                visual_source_path=data.get("pdf_path") or data.get("visual_source_path"),
                slide_durations=[float(d) for d in data.get("slide_durations", [])],
                ignore_original_audio=True,
            )
            # Legacy audio
            legacy_audio = data.get("audio_path")
            if legacy_audio and Path(legacy_audio).is_file():
                try:
                    t = probe_audio_track(legacy_audio, name="Narração Principal")
                    project.add_track(t)
                except Exception as exc:
                    logger.warning("Falha ao carregar áudio legado: %s", exc)
            return project

        # Schema v2
        video_info_raw = data.get("video_info")
        vinfo = VideoInfo.from_dict(video_info_raw) if video_info_raw else None

        tracks = []
        for t_data in data.get("tracks", []):
            try:
                tracks.append(AudioTrack.from_dict(t_data))
            except Exception as exc:
                logger.warning("Falha ao restaurar faixa de áudio: %s", exc)

        return cls(
            schema_version=SCHEMA_VERSION,
            title=str(data.get("title") or "Projeto SlideCast"),
            visual_source_type=str(data.get("visual_source_type", "pdf")),
            visual_source_path=data.get("visual_source_path"),
            slide_durations=[float(d) for d in data.get("slide_durations", [])],
            video_info=vinfo,
            ignore_original_audio=bool(data.get("ignore_original_audio", True)),
            tracks=tracks[:MAX_AUDIO_TRACKS],
            export_settings=data.get("export_settings", {
                "resolution": [1920, 1080],
                "fps": 30,
                "output_path": "",
            }),
        )

    @classmethod
    def load_from_file(cls, file_path: str) -> MultimediaProject:
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Arquivo de projeto não encontrado: {file_path}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
