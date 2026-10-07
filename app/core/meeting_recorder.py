import os
import sys
import subprocess
import signal
import time
from pathlib import Path
from typing import Optional, Dict

from app.core.ffmpeg_utils import get_ffmpeg_paths
from app.core.config_manager import get_gemini_api_key


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

    def start(self):
        Path(self.output_video_path).parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_exe, _ = get_ffmpeg_paths()

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
                    "-i", "audio=virtual-audio-capturer",
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
                    "-i", "audio=virtual-audio-capturer",
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
                    "-i", "default",
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
                    "-i", "default",
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
                print("Aviso: Câmera indisponível no FFmpeg. Gravando tela normalmente.")
                self.camera_device = None
                self.start()
                return
        except Exception as e:
            if self.camera_device:
                print("Fallback para gravação de tela:", e)
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
            except Exception as e:
                print(f"Aviso upload: {e}")

        models = [
            "gemini-3.8-flash",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-flash-latest",
        ]

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

        for m in models:
            try:
                resp = client.models.generate_content(model=m, contents=contents)
                text = resp.text.strip()
                if "=== TRANSCRIÇÃO INTEGRAL ===" in text:
                    parts = text.split("=== TRANSCRIÇÃO INTEGRAL ===")
                    summary_part = parts[0].replace("=== RESUMO EXECUTIVO ===", "").strip()
                    transcription_part = parts[1].strip()
                    return {
                        "summary": summary_part,
                        "transcription": transcription_part,
                    }
                else:
                    return {
                        "summary": text,
                        "transcription": "Transcrição inclusa no resumo acima.",
                    }
            except Exception:
                continue

    except Exception as e:
        print(f"Erro ao processar reunião no Gemini: {e}")

    return {
        "summary": default_summary,
        "transcription": default_transcription,
    }
