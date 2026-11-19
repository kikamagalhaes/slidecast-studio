"""
Dual-region screen recording and pedagogical video composition for SlideCast.

Enables simultaneous capture of:
  - Presentation area (slides/materials)
  - Presenter area (teacher/speaker)

And automatic composition into a professional 16:9 video where the presentation
is prominent (~80% width) and the presenter is compact (~20% width), either in a
sidebar column or overlaid (PiP), regardless of captured rectangle sizes.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from app.core.ffmpeg_utils import get_ffmpeg_paths
from app.core.meeting_recorder import default_pulse_source, DSHOW_AUDIO_ENV

logger = logging.getLogger(__name__)


@dataclass
class ScreenRegion:
    """Represents a bounded screen capture region."""
    name: str  # "presentation" or "presenter"
    label: str  # e.g. "Apresentação" or "Professor"
    x: int = 0
    y: int = 0
    width: int = 800
    height: int = 600
    monitor_id: Optional[str] = None
    scale_factor: float = 1.0

    def __post_init__(self):
        if self.width < 32 or self.height < 32:
            raise ValueError(f"Dimensões da região inválidas ({self.width}x{self.height}). Mínimo de 32x32 px.")
        if self.width % 2 != 0:
            self.width -= 1
        if self.height % 2 != 0:
            self.height -= 1

    def is_valid(self) -> bool:
        return self.width >= 32 and self.height >= 32

    def as_even_rect(self) -> Tuple[int, int, int, int]:
        """Returns (x, y, w, h) with width and height forced to even integers."""
        w = self.width if self.width % 2 == 0 else self.width - 1
        h = self.height if self.height % 2 == 0 else self.height - 1
        return (max(0, self.x), max(0, self.y), max(32, w), max(32, h))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRegion":
        return cls(**data)


def format_ms_to_time(ms: int) -> str:
    """Formats milliseconds into mm:ss or hh:mm:ss string."""
    if ms < 0:
        ms = 0
    total_seconds = int(ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def parse_time_to_ms(time_str: str) -> int:
    """
    Parses 'mm:ss' or 'hh:mm:ss' (or decimal seconds) into integer milliseconds.
    Example: '02:00' -> 120000; '01:30:00' -> 5400000; '45' -> 45000.
    """
    if isinstance(time_str, (int, float)):
        val = float(time_str)
        if val < 0:
            raise ValueError("Tempo não pode ser negativo.")
        return int(val * 1000)
    s = str(time_str).strip()
    if not s:
        return 0
    if s.startswith("-"):
        raise ValueError(f"Tempo não pode ser negativo: '{time_str}'.")
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            sec = float(parts[2])
            if h < 0 or m < 0 or sec < 0:
                raise ValueError("Tempo não pode ser negativo.")
            return int((h * 3600 + m * 60 + sec) * 1000)
        elif len(parts) == 2:
            m = int(parts[0])
            sec = float(parts[1])
            if m < 0 or sec < 0:
                raise ValueError("Tempo não pode ser negativo.")
            return int((m * 60 + sec) * 1000)
        else:
            val = float(parts[0])
            if val < 0:
                raise ValueError("Tempo não pode ser negativo.")
            return int(val * 1000)
    except Exception as e:
        raise ValueError(f"Formato de tempo inválido '{time_str}'. Use mm:ss ou hh:mm:ss.") from e


@dataclass
class PresentationInterval:
    """
    Represents a semi-open time interval [start_ms, end_ms) where presentation slides
    are actively shared on screen.
    """
    start_ms: int
    end_ms: int
    origin: str = "manual"  # "manual" | "live_marker" | "auto_suggestion"
    confidence: float = 1.0

    def __post_init__(self):
        if self.start_ms < 0:
            raise ValueError(f"Tempo de início inválido ({self.start_ms}ms): deve ser maior ou igual a zero.")
        if self.end_ms <= self.start_ms:
            raise ValueError(
                f"Intervalo inválido: início ({self.start_ms}ms) deve ser estritamente menor que o fim ({self.end_ms}ms)."
            )

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def start_seconds(self) -> float:
        return self.start_ms / 1000.0

    @property
    def end_seconds(self) -> float:
        return self.end_ms / 1000.0

    @property
    def duration_seconds(self) -> float:
        return (self.end_ms - self.start_ms) / 1000.0

    @property
    def start_time_str(self) -> str:
        return format_ms_to_time(self.start_ms)

    @property
    def end_time_str(self) -> str:
        return format_ms_to_time(self.end_ms)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PresentationInterval":
        return cls(
            start_ms=int(data["start_ms"]),
            end_ms=int(data["end_ms"]),
            origin=data.get("origin", "manual"),
            confidence=float(data.get("confidence", 1.0)),
        )


def normalize_and_validate_intervals(
    intervals: List[PresentationInterval],
    total_duration_ms: Optional[int] = None,
) -> List[PresentationInterval]:
    """
    Validates, sorts chronologically, and checks for overlaps in presentation intervals.
    Raises ValueError with a clear human-readable explanation if any overlap is detected.
    """
    if not intervals:
        return []

    sorted_ints = sorted(intervals, key=lambda x: x.start_ms)
    validated: List[PresentationInterval] = []

    for item in sorted_ints:
        start_ms = item.start_ms
        end_ms = item.end_ms
        if total_duration_ms and total_duration_ms > 0:
            if start_ms >= total_duration_ms:
                continue
            end_ms = min(end_ms, total_duration_ms)
        if start_ms >= end_ms:
            continue

        if validated:
            prev = validated[-1]
            if start_ms < prev.end_ms:
                raise ValueError(
                    f"Sobreposição de intervalos de slides detectada: [{prev.start_time_str} - {prev.end_time_str}] "
                    f"e [{item.start_time_str} - {item.end_time_str}]. Os intervalos devem ser disjuntos."
                )

        validated.append(PresentationInterval(
            start_ms=start_ms,
            end_ms=end_ms,
            origin=item.origin,
            confidence=item.confidence,
        ))

    return validated


def probe_video_dimensions(video_path: str) -> Tuple[int, int]:
    """
    Returns (width, height) of the first video stream, or (640, 480) on failure.
    """
    if not video_path or not Path(video_path).is_file():
        return (640, 480)
    _, ffprobe_exe = get_ffmpeg_paths()
    if not ffprobe_exe:
        return (640, 480)
    try:
        cmd = [
            ffprobe_exe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            video_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            if streams:
                w = int(streams[0].get("width", 640))
                h = int(streams[0].get("height", 480))
                return (w, h)
    except Exception as e:
        logger.debug("probe_video_dimensions failed: %s", e)
    return (640, 480)


def detect_slide_intervals_heuristic(
    presentation_video_path: str,
    min_duration_sec: float = 3.0,
) -> List[PresentationInterval]:
    """
    Local, offline heuristic that analyzes the presentation video track to propose
    candidate intervals where slides were active. Always opt-in and non-binding.
    """
    if not presentation_video_path or not Path(presentation_video_path).exists():
        return []

    ffmpeg_exe, ffprobe_exe = get_ffmpeg_paths()
    if not ffmpeg_exe or not ffprobe_exe:
        return []

    try:
        probe_cmd = [
            ffprobe_exe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            presentation_video_path,
        ]
        res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            return []
        data = json.loads(res.stdout)
        duration = float(data.get("format", {}).get("duration", 0.0))
        if duration <= 0:
            return []
    except Exception:
        return []

    # Detect black/empty periods via ffmpeg blackdetect
    black_cmd = [
        ffmpeg_exe, "-i", presentation_video_path,
        "-vf", "blackdetect=d=1.5:pic_th=0.98",
        "-an", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(black_cmd, capture_output=True, text=True, timeout=20)
        stderr = proc.stderr or ""
    except Exception:
        stderr = ""

    pattern = re.compile(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)")
    black_intervals = []
    for match in pattern.finditer(stderr):
        black_intervals.append((float(match.group(1)), float(match.group(2))))

    if not black_intervals:
        # If no completely black screen was detected, suggest full duration
        return [PresentationInterval(
            start_ms=0,
            end_ms=int(duration * 1000),
            origin="auto_suggestion",
            confidence=0.8,
        )]

    candidates: List[PresentationInterval] = []
    current_time = 0.0
    for b_start, b_end in sorted(black_intervals):
        if b_start - current_time >= min_duration_sec:
            candidates.append(PresentationInterval(
                start_ms=int(current_time * 1000),
                end_ms=int(b_start * 1000),
                origin="auto_suggestion",
                confidence=0.75,
            ))
        current_time = max(current_time, b_end)

    if duration - current_time >= min_duration_sec:
        candidates.append(PresentationInterval(
            start_ms=int(current_time * 1000),
            end_ms=int(duration * 1000),
            origin="auto_suggestion",
            confidence=0.75,
        ))

    return candidates


@dataclass
class CompositionConfig:
    """Configuration for final video layout and timeline composition."""
    layout: str = "sidebar"  # "sidebar" (Layout 1) or "overlay_pip" (Layout 2)
    presenter_position: str = "center"  # sidebar: "top"|"center"|"bottom"; pip: "bottom_right"|"top_right"|"bottom_left"|"top_left"
    output_resolution: str = "1920x1080"  # "1920x1080" or "1280x720"
    presentation_width_ratio: float = 0.80  # 78–82%
    presenter_width_ratio: float = 0.20  # 18–22%
    bg_color: str = "#10201E"  # SlideCast dark theme stage color

    # Timeline-based Automated Class Direction
    presenter_focus_layout: str = "centered_title_card"  # Layout when slides are inactive
    lesson_title: str = ""  # Title displayed in presenter_focus layout
    lesson_subtitle: str = ""  # Subtitle or speaker name
    presenter_scale_limit: float = 1.5  # Max upscale factor for low-res presenter captures
    transition_type: str = "cut"  # "cut" or "dissolve"
    transition_duration_ms: int = 250
    presentation_intervals: List[PresentationInterval] = field(default_factory=list)

    @property
    def background_color(self) -> str:
        return self.bg_color

    def parse_resolution(self) -> Tuple[int, int]:
        try:
            w, h = [int(p) for p in self.output_resolution.split("x")]
            return w, h
        except Exception:
            return 1920, 1080

    def to_dict(self) -> dict:
        d = asdict(self)
        d["presentation_intervals"] = [i.to_dict() for i in self.presentation_intervals]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "CompositionConfig":
        raw_intervals = data.get("presentation_intervals") or []
        intervals = [
            PresentationInterval.from_dict(i) if isinstance(i, dict) else i
            for i in raw_intervals
        ]
        return cls(
            layout=data.get("layout", "sidebar"),
            presenter_position=data.get("presenter_position", "center"),
            output_resolution=data.get("output_resolution", "1920x1080"),
            presentation_width_ratio=float(data.get("presentation_width_ratio", 0.80)),
            presenter_width_ratio=float(data.get("presenter_width_ratio", 0.20)),
            bg_color=data.get("bg_color", "#10201E"),
            presenter_focus_layout=data.get("presenter_focus_layout", "centered_title_card"),
            lesson_title=data.get("lesson_title", ""),
            lesson_subtitle=data.get("lesson_subtitle", ""),
            presenter_scale_limit=float(data.get("presenter_scale_limit", 1.5)),
            transition_type=data.get("transition_type", "cut"),
            transition_duration_ms=int(data.get("transition_duration_ms", 250)),
            presentation_intervals=intervals,
        )


@dataclass
class DualRegionSession:
    """Represents a recorded session with both raw video sources, layout configuration and timeline."""
    session_id: str = field(default_factory=lambda: str(int(time.time())))
    title: str = "Aula Gravada"
    capture_mode: str = "dual_region"  # "dual_region" or "full_screen"
    presentation_region: Optional[ScreenRegion] = None
    presenter_region: Optional[ScreenRegion] = None
    presentation_video_path: Optional[str] = None
    presenter_video_path: Optional[str] = None
    audio_path: Optional[str] = None
    composition: CompositionConfig = field(default_factory=CompositionConfig)
    final_output_path: Optional[str] = None
    live_markers: List[Dict[str, any]] = field(default_factory=list)
    lesson_title: str = ""
    lesson_subtitle: str = ""
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    status: str = "idle"  # "idle" | "recording" | "recorded" | "rendering" | "completed" | "error"

    def __init__(
        self,
        session_id: Optional[str] = None,
        title: str = "Aula Gravada",
        capture_mode: str = "dual_region",
        presentation_region: Optional[ScreenRegion] = None,
        presenter_region: Optional[ScreenRegion] = None,
        presentation_video_path: Optional[str] = None,
        presenter_video_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        composition: Optional[CompositionConfig] = None,
        final_output_path: Optional[str] = None,
        live_markers: Optional[List[Dict[str, any]]] = None,
        lesson_title: str = "",
        lesson_subtitle: str = "",
        created_at: Optional[str] = None,
        status: str = "idle",
        # Aliases
        raw_presentation_video: Optional[str] = None,
        raw_presenter_video: Optional[str] = None,
        output_video: Optional[str] = None,
        config: Optional[CompositionConfig] = None,
    ):
        self.session_id = session_id or str(int(time.time()))
        self.title = title
        self.capture_mode = capture_mode
        self.presentation_region = presentation_region
        self.presenter_region = presenter_region
        self.presentation_video_path = presentation_video_path or raw_presentation_video
        self.presenter_video_path = presenter_video_path or raw_presenter_video
        self.audio_path = audio_path
        self.composition = composition or config or CompositionConfig()
        self.final_output_path = final_output_path or output_video
        self.live_markers = live_markers or []
        self.lesson_title = lesson_title or (self.composition.lesson_title if self.composition else "")
        self.lesson_subtitle = lesson_subtitle or (self.composition.lesson_subtitle if self.composition else "")
        if self.lesson_title and self.composition:
            self.composition.lesson_title = self.lesson_title
        if self.lesson_subtitle and self.composition:
            self.composition.lesson_subtitle = self.lesson_subtitle
        self.created_at = created_at or time.strftime("%Y-%m-%dT%H:%M:%S")
        self.status = status

    @property
    def output_video(self) -> Optional[str]:
        return self.final_output_path

    @output_video.setter
    def output_video(self, val: str):
        self.final_output_path = val

    @property
    def config(self) -> CompositionConfig:
        return self.composition

    @config.setter
    def config(self, val: CompositionConfig):
        self.composition = val

    @property
    def raw_presentation_video(self) -> Optional[str]:
        return self.presentation_video_path

    @property
    def raw_presenter_video(self) -> Optional[str]:
        return self.presenter_video_path

    def to_dict(self) -> dict:
        d = asdict(self)
        d["composition"] = self.composition.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "DualRegionSession":
        pres_dict = data.get("presentation_region")
        prof_dict = data.get("presenter_region")
        comp_dict = data.get("composition") or data.get("config") or {}

        pres = ScreenRegion.from_dict(pres_dict) if pres_dict else None
        prof = ScreenRegion.from_dict(prof_dict) if prof_dict else None
        comp = CompositionConfig.from_dict(comp_dict)

        return cls(
            session_id=data.get("session_id", str(int(time.time()))),
            title=data.get("title", "Aula Gravada"),
            capture_mode=data.get("capture_mode", "dual_region"),
            presentation_region=pres,
            presenter_region=prof,
            presentation_video_path=data.get("presentation_video_path") or data.get("raw_presentation_video"),
            presenter_video_path=data.get("presenter_video_path") or data.get("raw_presenter_video"),
            audio_path=data.get("audio_path"),
            composition=comp,
            final_output_path=data.get("final_output_path") or data.get("output_video"),
            live_markers=data.get("live_markers") or [],
            lesson_title=data.get("lesson_title", comp.lesson_title),
            lesson_subtitle=data.get("lesson_subtitle", comp.lesson_subtitle),
            created_at=data.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
            status=data.get("status", "idle"),
        )

    def save(self, file_path: str):
        p = Path(file_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, file_path: str) -> "DualRegionSession":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


class DualRegionRecordingProcess:
    """
    Manages simultaneous background recording of two screen regions + audio.
    Saves presentation_raw.mp4 (video + audio) and presenter_raw.mp4 (video).
    """

    def __init__(
        self,
        presentation_region: ScreenRegion,
        presenter_region: ScreenRegion,
        presentation_output_path: str,
        presenter_output_path: str,
        fps: int = 25,
        audio_source: Optional[str] = None,
    ):
        self.presentation_region = presentation_region
        self.presenter_region = presenter_region
        self.presentation_output_path = str(Path(presentation_output_path).resolve())
        self.presenter_output_path = str(Path(presenter_output_path).resolve())
        self.fps = fps
        self.audio_source = audio_source
        self.process: Optional[subprocess.Popen] = None
        self.start_time: float = 0.0

    def _get_audio_input_args(self) -> List[str]:
        if sys.platform == "win32":
            explicit = (os.environ.get(DSHOW_AUDIO_ENV) or "").strip()
            dev = f"audio={explicit}" if explicit else "audio=virtual-audio-capturer"
            return ["-f", "dshow", "-i", dev]
        else:
            pulse_dev = self.audio_source or default_pulse_source() or "default"
            return ["-f", "pulse", "-i", pulse_dev]

    def start(self):
        ffmpeg_exe, _ = get_ffmpeg_paths()
        if not ffmpeg_exe:
            raise RuntimeError("FFmpeg não encontrado no sistema.")

        Path(self.presentation_output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.presenter_output_path).parent.mkdir(parents=True, exist_ok=True)

        pres_x, pres_y, pres_w, pres_h = self.presentation_region.as_even_rect()
        prof_x, prof_y, prof_w, prof_h = self.presenter_region.as_even_rect()

        audio_args = self._get_audio_input_args()

        if sys.platform == "win32":
            # On Windows: gdigrab with desktop inputs or grab and crop
            # Determine bounding area to grab once and crop into two streams
            min_x = min(pres_x, prof_x)
            min_y = min(pres_y, prof_y)
            max_x = max(pres_x + pres_w, prof_x + prof_w)
            max_y = max(pres_y + pres_h, prof_y + prof_h)
            bound_w = max_x - min_x
            bound_h = max_y - min_y
            bound_w = bound_w if bound_w % 2 == 0 else bound_w + 1
            bound_h = bound_h if bound_h % 2 == 0 else bound_h + 1

            rel_pres_x = pres_x - min_x
            rel_pres_y = pres_y - min_y
            rel_prof_x = prof_x - min_x
            rel_prof_y = prof_y - min_y

            filter_complex = (
                f"[0:v]crop={pres_w}:{pres_h}:{rel_pres_x}:{rel_pres_y}[pres]; "
                f"[0:v]crop={prof_w}:{prof_h}:{rel_prof_x}:{rel_prof_y}[prof]"
            )

            cmd = [
                ffmpeg_exe, "-y",
                "-f", "gdigrab",
                "-framerate", str(self.fps),
                "-offset_x", str(min_x),
                "-offset_y", str(min_y),
                "-video_size", f"{bound_w}x{bound_h}",
                "-i", "desktop",
            ] + audio_args + [
                "-filter_complex", filter_complex,
                "-map", "[pres]",
                "-map", "1:a?",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                self.presentation_output_path,
                "-map", "[prof]",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                self.presenter_output_path,
            ]
        else:
            # Linux X11: Display
            display = os.environ.get("DISPLAY", ":0.0")

            # Check if both regions share the same display
            # We can grab bounding area and crop cleanly, which is reliable and low CPU
            min_x = min(pres_x, prof_x)
            min_y = min(pres_y, prof_y)
            max_x = max(pres_x + pres_w, prof_x + prof_w)
            max_y = max(pres_y + pres_h, prof_y + prof_h)
            bound_w = max_x - min_x
            bound_h = max_y - min_y
            bound_w = bound_w if bound_w % 2 == 0 else bound_w + 1
            bound_h = bound_h if bound_h % 2 == 0 else bound_h + 1

            rel_pres_x = pres_x - min_x
            rel_pres_y = pres_y - min_y
            rel_prof_x = prof_x - min_x
            rel_prof_y = prof_y - min_y

            filter_complex = (
                f"[0:v]crop={pres_w}:{pres_h}:{rel_pres_x}:{rel_pres_y}[pres]; "
                f"[0:v]crop={prof_w}:{prof_h}:{rel_prof_x}:{rel_prof_y}[prof]"
            )

            input_spec = f"{display}+{min_x},{min_y}"

            cmd = [
                ffmpeg_exe, "-y",
                "-f", "x11grab",
                "-draw_mouse", "1",
                "-framerate", str(self.fps),
                "-video_size", f"{bound_w}x{bound_h}",
                "-i", input_spec,
            ] + audio_args + [
                "-filter_complex", filter_complex,
                "-map", "[pres]",
                "-map", "1:a?",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                self.presentation_output_path,
                "-map", "[prof]",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                self.presenter_output_path,
            ]

        logger.info("Iniciando gravação de duas áreas com FFmpeg: %s", " ".join(cmd))
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.start_time = time.time()

    def stop(self) -> Tuple[str, str]:
        """Stops the recording process gracefully and returns (presentation_path, presenter_path)."""
        if self.process and self.process.poll() is None:
            try:
                if self.process.stdin:
                    self.process.stdin.write(b"q\n")
                    self.process.stdin.flush()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except Exception:
                    self.process.kill()

        return self.presentation_output_path, self.presenter_output_path

    def get_elapsed_seconds(self) -> float:
        if self.start_time > 0:
            return time.time() - self.start_time
        return 0.0


def compose_dual_region_video(
    presentation_video_path: Optional[str] = None,
    presenter_video_path: Optional[str] = None,
    output_path: Optional[str] = None,
    config: Optional[CompositionConfig] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    presentation_video: Optional[str] = None,
    presenter_video: Optional[str] = None,
    output_video: Optional[str] = None,
) -> str:
    """
    Composes a dual-region recording into a final pedagogical 16:9 MP4 video.

    Core Rule (Captura != Tamanho final):
    Presentation is rendered prominent (~80% width) and presenter is rendered
    compact (~20% width), regardless of the input dimensions of either video.

    Layouts:
      - 'sidebar' (default): Presentation on the left, Presenter on the right column (top/center/bottom).
      - 'overlay_pip': Presentation fills 16:9 canvas, Presenter overlays corner (bottom_right/top_right/etc).
    """
    presentation_video_path = presentation_video_path or presentation_video
    presenter_video_path = presenter_video_path or presenter_video
    output_path = output_path or output_video

    if not presentation_video_path or not presenter_video_path or not output_path:
        raise ValueError("presentation_video_path, presenter_video_path e output_path são obrigatórios.")
    if config is None:
        config = CompositionConfig()

    ffmpeg_exe, ffprobe_exe = get_ffmpeg_paths()
    if not ffmpeg_exe:
        raise RuntimeError("FFmpeg não encontrado.")

    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    canvas_w, canvas_h = config.parse_resolution()

    # Probe duration and audio stream presence from presentation video
    duration = 0.0
    has_audio = False
    if ffprobe_exe and Path(presentation_video_path).is_file():
        try:
            probe_cmd = [
                ffprobe_exe, "-v", "error",
                "-show_entries", "format=duration",
                "-show_entries", "stream=codec_type",
                "-of", "json",
                presentation_video_path,
            ]
            res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                duration = float(data.get("format", {}).get("duration", 0.0))
                streams = data.get("streams", [])
                has_audio = any(s.get("codec_type") == "audio" for s in streams)
        except Exception as e:
            logger.debug("ffprobe probe info failed: %s", e)

    # Probe duration and audio stream presence from presentation video
    duration = 0.0
    has_audio = False
    if ffprobe_exe and Path(presentation_video_path).is_file():
        try:
            probe_cmd = [
                ffprobe_exe, "-v", "error",
                "-show_entries", "format=duration",
                "-show_entries", "stream=codec_type",
                "-of", "json",
                presentation_video_path,
            ]
            res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                duration = float(data.get("format", {}).get("duration", 0.0))
                streams = data.get("streams", [])
                has_audio = any(s.get("codec_type") == "audio" for s in streams)
        except Exception as e:
            logger.debug("ffprobe probe info failed: %s", e)

    # Probe presenter video resolution for quality policy
    prof_src_w = 640
    prof_src_h = 480
    if ffprobe_exe and Path(presenter_video_path).is_file():
        try:
            probe_p_cmd = [
                ffprobe_exe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json",
                presenter_video_path,
            ]
            p_res = subprocess.run(probe_p_cmd, capture_output=True, text=True, timeout=10)
            if p_res.returncode == 0:
                p_data = json.loads(p_res.stdout)
                p_streams = p_data.get("streams", [])
                if p_streams:
                    prof_src_w = int(p_streams[0].get("width", 640))
                    prof_src_h = int(p_streams[0].get("height", 480))
        except Exception as e:
            logger.debug("ffprobe presenter resolution probe failed: %s", e)

    # Check if this composition has timeline intervals or title card
    has_timeline = bool(
        config.presentation_intervals
        or config.lesson_title
        or config.lesson_subtitle
        or getattr(config, "has_timeline_override", False)
    )

    layout = config.layout
    bg_color = config.bg_color

    # Presentation mode scaling (sidebar or PiP)
    if layout == "sidebar":
        pres_box_w = int(canvas_w * config.presentation_width_ratio) - 24
        pres_box_h = canvas_h - 32
        prof_box_w = int(canvas_w * config.presenter_width_ratio) - 24
        prof_box_h = canvas_h - 32
        prof_x_start = int(canvas_w * config.presentation_width_ratio) + 8

        pos = config.presenter_position
        if pos == "top":
            prof_y_expr = "24"
        elif pos == "bottom":
            prof_y_expr = f"{canvas_h}-h-24"
        else:  # "center"
            prof_y_expr = f"({canvas_h}-h)/2"
    else:  # overlay_pip
        prof_w = int(canvas_w * config.presenter_width_ratio)
        prof_w = prof_w if prof_w % 2 == 0 else prof_w - 1
        pos = config.presenter_position
        if pos == "top_right":
            prof_overlay_expr = f"x={canvas_w}-w-24:y=24"
        elif pos == "top_left":
            prof_overlay_expr = "x=24:y=24"
        elif pos == "bottom_left":
            prof_overlay_expr = f"x=24:y={canvas_h}-h-24"
        else:  # bottom_right (default)
            prof_overlay_expr = f"x={canvas_w}-w-24:y={canvas_h}-h-24"

    # Presenter Focus Mode Scaling (Center Stage with honest scaling policy)
    max_center_w = int(canvas_w * 0.55)
    max_center_h = int(canvas_h * 0.60)
    allowed_w = int(prof_src_w * config.presenter_scale_limit)
    allowed_h = int(prof_src_h * config.presenter_scale_limit)
    prof_focus_w = min(max_center_w, max(prof_src_w, allowed_w))
    prof_focus_h = min(max_center_h, max(prof_src_h, allowed_h))
    prof_focus_w = prof_focus_w if prof_focus_w % 2 == 0 else prof_focus_w - 1
    prof_focus_h = prof_focus_h if prof_focus_h % 2 == 0 else prof_focus_h - 1

    has_title_elements = bool(config.lesson_title.strip() or config.lesson_subtitle.strip())
    prof_focus_y = f"({canvas_h}-h)/2 + 40" if has_title_elements else f"({canvas_h}-h)/2"

    import tempfile
    tmp_text_dir = Path(tempfile.mkdtemp(prefix="slidecast_txt_"))
    try:
        title_txt_path = tmp_text_dir / "title.txt"
        sub_txt_path = tmp_text_dir / "sub.txt"
        title_txt_path.write_text(config.lesson_title.strip(), encoding="utf-8")
        sub_txt_path.write_text(config.lesson_subtitle.strip(), encoding="utf-8")

        title_size = 38 if canvas_h >= 1080 else 26
        sub_size = 22 if canvas_h >= 1080 else 16
        title_y = 55 if canvas_h >= 1080 else 38
        sub_y = 105 if canvas_h >= 1080 else 72

        if has_timeline:
            valid_intervals = normalize_and_validate_intervals(
                config.presentation_intervals,
                total_duration_ms=int(duration * 1000) if duration > 0 else None,
            )

            if valid_intervals:
                terms = [
                    f"between(t,{i.start_seconds:.3f},{i.end_seconds:.3f})"
                    for i in valid_intervals
                ]
                pres_active_expr = "+".join(terms)
                pres_inactive_expr = f"not({pres_active_expr})"
            else:
                # 100% presenter focus
                pres_active_expr = "0"
                pres_inactive_expr = "1"

            # Base background and center presenter
            filter_parts = [
                f"color=c={bg_color}:s={canvas_w}x{canvas_h}[bg]",
                f"[1:v]scale={prof_focus_w}:{prof_focus_h}:force_original_aspect_ratio=decrease,drawbox=x=0:y=0:w=iw:h=ih:color=white@0.3:t=2[prof_center]",
                f"[bg][prof_center]overlay=x=(W-w)/2:y={prof_focus_y}:enable='{pres_inactive_expr}'[stg0]",
            ]

            curr_stage = "stg0"
            if config.lesson_title.strip():
                posix_title = title_txt_path.as_posix()
                filter_parts.append(
                    f"[{curr_stage}]drawtext=textfile='{posix_title}':fontsize={title_size}:fontcolor=white:x=(w-text_w)/2:y={title_y}:enable='{pres_inactive_expr}'[stg_t]"
                )
                curr_stage = "stg_t"

            if config.lesson_subtitle.strip():
                posix_sub = sub_txt_path.as_posix()
                filter_parts.append(
                    f"[{curr_stage}]drawtext=textfile='{posix_sub}':fontsize={sub_size}:fontcolor=#38bdf8:x=(w-text_w)/2:y={sub_y}:enable='{pres_inactive_expr}'[stg_s]"
                )
                curr_stage = "stg_s"

            # Overlay presentation active state on top
            if layout == "sidebar":
                filter_parts.extend([
                    f"[0:v]scale={pres_box_w}:{pres_box_h}:force_original_aspect_ratio=decrease[pres_side]",
                    f"[1:v]scale={prof_box_w}:{prof_box_h}:force_original_aspect_ratio=decrease[prof_side]",
                    f"[{curr_stage}][pres_side]overlay=x=16+({pres_box_w}-w)/2:y=({canvas_h}-h)/2:enable='{pres_active_expr}'[stg_pres]",
                    f"[stg_pres][prof_side]overlay=x={prof_x_start}+({prof_box_w}-w)/2:y={prof_y_expr}:enable='{pres_active_expr}'[v]",
                ])
            else:
                filter_parts.extend([
                    f"[0:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color={bg_color}[pres_pip]",
                    f"[1:v]scale={prof_w}:-2,drawbox=x=0:y=0:w=iw:h=ih:color=white@0.6:t=2[prof_pip]",
                    f"[{curr_stage}][pres_pip]overlay=x=0:y=0:enable='{pres_active_expr}'[stg_pres]",
                    f"[stg_pres][prof_pip]overlay={prof_overlay_expr}:enable='{pres_active_expr}'[v]",
                ])

            filter_complex = "; ".join(filter_parts)

        else:
            # Full duration presentation layout (legacy default)
            if layout == "sidebar":
                filter_complex = (
                    f"[0:v]scale={pres_box_w}:{pres_box_h}:force_original_aspect_ratio=decrease[pres]; "
                    f"[1:v]scale={prof_box_w}:{prof_box_h}:force_original_aspect_ratio=decrease[prof]; "
                    f"color=c={bg_color}:s={canvas_w}x{canvas_h}[bg]; "
                    f"[bg][pres]overlay=x=16+({pres_box_w}-w)/2:y=({canvas_h}-h)/2[bg1]; "
                    f"[bg1][prof]overlay=x={prof_x_start}+({prof_box_w}-w)/2:y={prof_y_expr}[v]"
                )
            else:
                filter_complex = (
                    f"[0:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
                    f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color={bg_color}[pres]; "
                    f"[1:v]scale={prof_w}:-2,drawbox=x=0:y=0:w=iw:h=ih:color=white@0.6:t=2[prof]; "
                    f"[pres][prof]overlay={prof_overlay_expr}[v]"
                )

        # Audio handling: continuous mapping from presentation video or silence fallback
        inputs = [
            "-i", presentation_video_path,
            "-i", presenter_video_path,
        ]

        audio_map = []
        if has_audio:
            audio_map = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
        else:
            inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            audio_map = ["-map", "2:a:0", "-c:a", "aac", "-b:a", "192k"]

        cmd = [
            ffmpeg_exe, "-y",
        ] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[v]",
        ] + audio_map + [
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-shortest",
            str(out_file),
        ]

        if progress_callback:
            progress_callback(0.05, "Iniciando composição do vídeo...")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        try:
            time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
            last_progress_time = time.time()

            while proc.poll() is None:
                if cancel_check and cancel_check():
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    raise RuntimeError("Composição do vídeo cancelada pelo usuário.")

                line = proc.stderr.readline() if proc.stderr else ""
                if line:
                    m = time_pattern.search(line)
                    if m and duration > 0 and progress_callback:
                        h, mins, s = m.groups()
                        current_s = int(h) * 3600 + int(mins) * 60 + float(s)
                        frac = min(0.95, max(0.05, current_s / duration))
                        if time.time() - last_progress_time > 0.25:
                            progress_callback(frac, f"Compondo vídeo: {int(frac * 100)}%")
                            last_progress_time = time.time()
                else:
                    time.sleep(0.05)

            ret = proc.wait()
            if ret != 0:
                stderr_out = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"FFmpeg falhou ao compor vídeo (código {ret}): {stderr_out[-300:]}")

        except Exception:
            if out_file.exists():
                out_file.unlink(missing_ok=True)
            raise

    finally:
        shutil.rmtree(tmp_text_dir, ignore_errors=True)

    if progress_callback:
        progress_callback(1.0, "Vídeo composto com sucesso!")

    return str(out_file)
