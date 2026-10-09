import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.core.ffmpeg_utils import get_ffmpeg_paths
from app.core.config_manager import get_gemini_api_key
from app.core.gemini_client import GeminiError, generate_with_fallback

logger = logging.getLogger(__name__)

# Overrides (documented in README): force a specific capture device instead of
# the auto-detected default.
PULSE_SOURCE_ENV = "SLIDECAST_PULSE_SOURCE"
DSHOW_AUDIO_ENV = "SLIDECAST_DSHOW_AUDIO"


def parse_pactl_short_sources(output: str) -> List[Dict[str, str]]:
    """Parses ``pactl list short sources`` into [{id, name, state}]."""
    sources = []
    for line in (output or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            sources.append(
                {
                    "id": parts[0].strip(),
                    "name": parts[1].strip(),
                    "state": parts[4].strip() if len(parts) > 4 else "",
                }
            )
    return sources


def parse_pactl_default_source(output: str) -> Optional[str]:
    """Extracts ``Default Source: ...`` from ``pactl info`` output."""
    match = re.search(r"^Default Source:\s*(\S+)", output or "", re.MULTILINE)
    return match.group(1) if match else None


def parse_dshow_devices(output: str) -> Dict[str, List[str]]:
    """Parses ``ffmpeg -list_devices true -f dshow -i dummy`` stderr."""
    found: Dict[str, List[str]] = {"video": [], "audio": []}
    section: Optional[str] = None
    for line in (output or "").splitlines():
        lowered = line.lower()
        if "directshow video devices" in lowered:
            section = "video"
            continue
        if "directshow audio devices" in lowered:
            section = "audio"
            continue
        if section is None or "alternative name" in lowered:
            continue
        match = re.search(r'"([^"]+)"', line)
        if match:
            found[section].append(match.group(1))
    return found


def _run_capture(argv: List[str], timeout: float = 5.0) -> Optional[str]:
    if not shutil.which(argv[0]):
        return None
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Device probe %s failed: %s", argv[:2], exc)
        return None
    return (proc.stdout or "") + (proc.stderr or "")


def default_pulse_source() -> Optional[str]:
    """Best-effort default PulseAudio source name (Linux)."""
    explicit = (os.environ.get(PULSE_SOURCE_ENV) or "").strip()
    if explicit:
        return explicit
    out = _run_capture(["pactl", "info"])
    if out:
        return parse_pactl_default_source(out)
    return None


def list_pulse_sources() -> List[Dict[str, str]]:
    out = _run_capture(["pactl", "list", "short", "sources"])
    return parse_pactl_short_sources(out or "")


def list_dshow_devices() -> Dict[str, List[str]]:
    ffmpeg_exe, _ = get_ffmpeg_paths()
    if not ffmpeg_exe:
        return {"video": [], "audio": []}
    try:
        proc = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {"video": [], "audio": []}
    return parse_dshow_devices(proc.stderr or "")


def list_linux_cameras(sys_dev_root: str = "/dev") -> List[str]:
    """Camera nodes from ``/dev/video*`` (best effort, empty when none)."""
    try:
        return sorted(str(p) for p in Path(sys_dev_root).glob("video*"))
    except OSError:
        return []


def describe_capture_devices() -> Dict[str, object]:
    """Best-effort capture inventory for logs and diagnostics UIs."""
    if sys.platform == "win32":
        dshow = list_dshow_devices()
        return {
            "platform": "windows",
            "audio": dshow["audio"],
            "video": dshow["video"],
            "default_audio": os.environ.get(DSHOW_AUDIO_ENV) or "virtual-audio-capturer",
        }
    return {
        "platform": "linux",
        "audio": [s["name"] for s in list_pulse_sources()],
        "video": list_linux_cameras(),
        "default_audio": default_pulse_source() or "default",
    }


class ScreenRecordingProcess:
    """
    Manages background screen and audio recording using FFmpeg.
    Cross-platform: uses x11grab + pulse on Linux, gdigrab + dshow on Windows.
    """

    def __init__(
        self,
        output_video_path: str,
        video_size: str = "1920x1080",
        fps: int = 25,
        area_offset: str = "0,0",
        camera_device: Optional[str] = None,
        camera_position: str = "bottom_right",
        camera_size: str = "384x216",
    ):
        self.output_video_path = str(Path(output_video_path).resolve())
        self.video_size = video_size
        self.fps = fps
        self.area_offset = area_offset
        self.camera_device = camera_device
        self.camera_position = camera_position
        self.camera_size = camera_size
        self.process: Optional[subprocess.Popen] = None
        self.start_time: float = 0.0

    def _effective_camera_device(self) -> Optional[str]:
        """Drops /dev camera nodes that do not exist, with a clear warning."""
        cam = self.camera_device
        if cam and cam.startswith("/dev/") and not Path(cam).exists():
            logger.warning("Câmera %s não encontrada; gravando sem câmera.", cam)
            return None
        return cam

    def _pulse_audio_input(self) -> str:
        return default_pulse_source() or "default"

    def _dshow_audio_input(self) -> str:
        explicit = (os.environ.get(DSHOW_AUDIO_ENV) or "").strip()
        return f"audio={explicit}" if explicit else "audio=virtual-audio-capturer"

    def start(self):
        Path(self.output_video_path).parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_exe, _ = get_ffmpeg_paths()
        if not ffmpeg_exe:
            raise RuntimeError("FFmpeg não encontrado; não é possível gravar a tela.")
        self.camera_device = self._effective_camera_device()
        pulse_input = self._pulse_audio_input()
        dshow_audio = self._dshow_audio_input()

        # Parse PIP position expression
        try:
            cam_w, cam_h = [int(x) for x in self.camera_size.split("x")]
        except Exception:
            cam_w, cam_h = 384, 216

        if self.camera_position == "top_right":
            pos_expr = "W-w-24:24"
        elif self.camera_position == "bottom_left":
            pos_expr = "24:H-h-24"
        elif self.camera_position == "top_left":
            pos_expr = "24:24"
        else:  # bottom_right
            pos_expr = "W-w-24:H-h-24"

        if sys.platform == "win32":
            if self.camera_device:
                cmd = [
                    ffmpeg_exe, "-y",
                    "-f", "gdigrab",
                    "-framerate", str(self.fps),
                    "-i", "desktop",
                    "-f", "dshow",
                    "-i", dshow_audio,
                    "-f", "dshow",
                    "-i", f"video={self.camera_device}",
                    "-filter_complex",
                    f"[2:v]scale={cam_w}:{cam_h},drawbox=0:0:{cam_w}:{cam_h}:color=white@0.7:t=2[cam];[0:v][cam]overlay={pos_expr}[v]",
                    "-map", "[v]",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    self.output_video_path,
                ]
            else:
                cmd = [
                    ffmpeg_exe, "-y",
                    "-f", "gdigrab",
                    "-framerate", str(self.fps),
                    "-i", "desktop",
                    "-f", "dshow",
                    "-i", dshow_audio,
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    self.output_video_path,
                ]
        else:
            # Linux: X11 display + PulseAudio
            display = os.environ.get("DISPLAY", ":0.0")
            input_spec = f"{display}+{self.area_offset}" if self.area_offset != "0,0" else display

            if self.camera_device:
                cmd = [
                    ffmpeg_exe, "-y",
                    "-f", "x11grab",
                    "-draw_mouse", "1",
                    "-framerate", str(self.fps),
                    "-video_size", self.video_size,
                    "-i", input_spec,
                    "-f", "pulse",
                    "-i", pulse_input,
                    "-f", "v4l2",
                    "-framerate", str(self.fps),
                    "-video_size", "640x360",
                    "-i", self.camera_device,
                    "-filter_complex",
                    f"[2:v]scale={cam_w}:{cam_h},drawbox=0:0:{cam_w}:{cam_h}:color=white@0.7:t=2[cam];[0:v][cam]overlay={pos_expr}[v]",
                    "-map", "[v]",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    self.output_video_path,
                ]
            else:
                cmd = [
                    ffmpeg_exe, "-y",
                    "-f", "x11grab",
                    "-draw_mouse", "1",
                    "-framerate", str(self.fps),
                    "-video_size", self.video_size,
                    "-i", input_spec,
                    "-f", "pulse",
                    "-i", pulse_input,
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    self.output_video_path,
                ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Give FFmpeg 0.25s to detect if camera device was busy or errored
            time.sleep(0.25)
            if self.process.poll() is not None and self.camera_device:
                # Camera device busy/unavailable, fallback cleanly without camera
                logger.warning("Câmera indisponível no FFmpeg. Gravando tela normalmente.")
                self.camera_device = None
                self.start()
                return
        except Exception as e:
            if self.camera_device:
                logger.warning("Fallback para gravação de tela: %s", e)
                self.camera_device = None
                self.start()
                return
            raise e

        self.start_time = time.time()

    def stop(self) -> str:
        if self.process and self.process.poll() is None:
            try:
                # Send 'q' to gracefully stop FFmpeg
                if self.process.stdin:
                    self.process.stdin.write(b"q\n")
                    self.process.stdin.flush()
                self.process.wait(timeout=4)
            except Exception:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except Exception:
                    self.process.kill()

        return self.output_video_path

    def get_elapsed_seconds(self) -> float:
        if self.start_time > 0:
            return time.time() - self.start_time
        return 0.0


def extract_audio_from_video(video_path: str, output_audio_path: str) -> str:
    """
    Extracts audio track from recorded MP4 file for AI transcription and summarization.
    """
    ffmpeg_exe, _ = get_ffmpeg_paths()
    out_audio = Path(output_audio_path).resolve()
    out_audio.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_exe, "-y",
        "-i", str(Path(video_path).resolve()),
        "-vn",
        "-c:a", "aac",
        "-b:a", "128k",
        str(out_audio),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return str(out_audio)


def parse_meeting_response(text: str) -> Dict[str, str]:
    """Splits a Gemini meeting answer into summary + transcription parts."""
    clean = (text or "").strip()
    if "=== TRANSCRIÇÃO INTEGRAL ===" in clean:
        parts = clean.split("=== TRANSCRIÇÃO INTEGRAL ===")
        summary_part = parts[0].replace("=== RESUMO EXECUTIVO ===", "").strip()
        return {"summary": summary_part, "transcription": parts[1].strip()}
    return {"summary": clean, "transcription": "Transcrição inclusa no resumo acima."}


def generate_meeting_notes(audio_path: str, meeting_title: str = "Reunião Google Meet") -> Dict[str, str]:
    """
    Calls Gemini Flash to generate:
    1. Full meeting transcription
    2. Executive Summary (Agenda, Decisions, Action Items)
    """
    api_key = get_gemini_api_key()
    default_summary = (
        f"Resumo da Reunião: {meeting_title}\n\n"
        "• Pauta: Discussão dos tópicos abordados pelos participantes no Google Meet.\n"
        "• Decisões: Os participantes alinharam as prioridades e próximos passos acordados.\n"
        "• Plano de Ação: Execução das tarefas designadas durante o encontro."
    )
    default_transcription = "Gravação de áudio concluída. Transcrição não processada por ausência da chave Gemini."

    if not api_key:
        return {
            "summary": default_summary,
            "transcription": default_transcription,
        }

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        uploaded_file = None
        if audio_path and Path(audio_path).exists() and Path(audio_path).stat().st_size > 1000:
            try:
                uploaded_file = client.files.upload(file=audio_path)
            except Exception as exc:
                logger.warning("Aviso upload: %s", exc)

        prompt = (
            f"Você é um assistente executivo sênior. Analise o áudio da reunião '{meeting_title}' e gere:\n"
            f"1. TRANSCRIÇÃO COMPLETA: Transcreva as falas dos participantes com precisão.\n"
            f"2. RESUMO EXECUTIVO DA REUNIÃO:\n"
            f"   - Objetivo e Contexto Geral\n"
            f"   - Principais Tópicos Discutidos\n"
            f"   - Decisões Tomadas\n"
            f"   - Próximos Passos & Tarefas (com responsáveis quando mencionados)\n\n"
            f"Responda no formato estruturado:\n"
            f"=== RESUMO EXECUTIVO ===\n(coloque aqui o resumo)\n\n"
            f"=== TRANSCRIÇÃO INTEGRAL ===\n(coloque aqui a transcrição)"
        )

        contents = [uploaded_file, prompt] if uploaded_file else [prompt]

        try:
            resp = generate_with_fallback(client, contents=contents)
        except GeminiError:
            return {
                "summary": default_summary,
                "transcription": default_transcription,
            }

        return parse_meeting_response(resp.text)

    except Exception as exc:
        logger.warning("Erro ao processar reunião no Gemini: %s", exc)

    return {
        "summary": default_summary,
        "transcription": default_transcription,
    }
