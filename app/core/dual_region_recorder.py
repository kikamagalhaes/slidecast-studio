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


@dataclass
class CompositionConfig:
    """Configuration for final video layout and composition."""
    layout: str = "sidebar"  # "sidebar" (Layout 1) or "overlay_pip" (Layout 2)
    presenter_position: str = "center"  # sidebar: "top"|"center"|"bottom"; pip: "bottom_right"|"top_right"|"bottom_left"|"top_left"
    output_resolution: str = "1920x1080"  # "1920x1080" or "1280x720"
    presentation_width_ratio: float = 0.80  # 78–82%
    presenter_width_ratio: float = 0.20  # 18–22%
    bg_color: str = "#10201E"  # SlideCast dark theme stage color

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
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CompositionConfig":
        return cls(**data)


@dataclass
class DualRegionSession:
    """Represents a recorded session with both raw video sources and layout configuration."""
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
        return asdict(self)

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

    # Build filter_complex based on chosen layout
    layout = config.layout
    bg_color = config.bg_color

    if layout == "sidebar":
        # Presentation takes ~80% width with margins
        pres_box_w = int(canvas_w * config.presentation_width_ratio) - 24
        pres_box_h = canvas_h - 32

        # Presenter takes ~20% width
        prof_box_w = int(canvas_w * config.presenter_width_ratio) - 24
        prof_box_h = canvas_h - 32

        prof_x_start = int(canvas_w * config.presentation_width_ratio) + 8

        # Vertical alignment of presenter in sidebar
        pos = config.presenter_position
        if pos == "top":
            prof_y_expr = "24"
        elif pos == "bottom":
            prof_y_expr = f"{canvas_h}-h-24"
        else:  # "center"
            prof_y_expr = f"({canvas_h}-h)/2"

        filter_complex = (
            f"[0:v]scale={pres_box_w}:{pres_box_h}:force_original_aspect_ratio=decrease[pres]; "
            f"[1:v]scale={prof_box_w}:{prof_box_h}:force_original_aspect_ratio=decrease[prof]; "
            f"color=c={bg_color}:s={canvas_w}x{canvas_h}[bg]; "
            f"[bg][pres]overlay=x=16+({pres_box_w}-w)/2:y=({canvas_h}-h)/2[bg1]; "
            f"[bg1][prof]overlay=x={prof_x_start}+({prof_box_w}-w)/2:y={prof_y_expr}[v]"
        )

    else:  # overlay_pip
        # Presentation fills full canvas with padding if necessary
        # Presenter is a small box in the designated corner
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

        filter_complex = (
            f"[0:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
            f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color={bg_color}[pres]; "
            f"[1:v]scale={prof_w}:-2,drawbox=x=0:y=0:w=iw:h=ih:color=white@0.6:t=2[prof]; "
            f"[pres][prof]overlay={prof_overlay_expr}[v]"
        )

    # Audio handling: use audio from presentation video or synthesize silence
    inputs = [
        "-i", presentation_video_path,
        "-i", presenter_video_path,
    ]

    audio_map = []
    if has_audio:
        audio_map = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    else:
        # Generate silent audio stream so output container is standard and playable
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
        # Monitor progress via stderr time regex
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

    if progress_callback:
        progress_callback(1.0, "Vídeo composto com sucesso!")

    return str(out_file)
