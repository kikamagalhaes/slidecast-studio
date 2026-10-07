import shutil
import tempfile
import traceback
from pathlib import Path
from typing import List, Tuple
from PySide6.QtCore import QThread, Signal

from app.core.pdf_processor import render_all_slides_to_dir
from app.core.video_generator import generate_video


class VideoRenderWorker(QThread):
    progress_changed = Signal(float, str)  # (fraction 0.0 - 1.0, status_text)
    render_finished = Signal(str)  # output_video_path
    render_error = Signal(str)
    render_cancelled = Signal()

    def __init__(
        self,
        pdf_path: str,
        audio_path: str,
        durations: List[float],
        output_path: str,
        resolution: Tuple[int, int] = (1920, 1080),
        fps: int = 30,
        dpi: int = 150,
        parent=None,
    ):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.audio_path = audio_path
        self.durations = durations
        self.output_path = output_path
        self.resolution = resolution
        self.fps = fps
        self.dpi = dpi
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="slidecast_render_"))
        try:
            self.progress_changed.emit(0.02, "Iniciando renderização dos slides...")

            # 1. Render slides to images (allocated 0% - 25% of progress bar)
            def slide_progress(current: int, total: int):
                frac = 0.02 + 0.23 * (current / total)
                self.progress_changed.emit(frac, f"Renderizando slide {current} de {total}...")

            images = render_all_slides_to_dir(
                file_path=self.pdf_path,
                output_dir=temp_dir,
                target_dpi=self.dpi,
                progress_callback=slide_progress,
                cancel_check=lambda: self._is_cancelled,
            )

            if self._is_cancelled:
                self.render_cancelled.emit()
                return

            self.progress_changed.emit(0.25, "Iniciando montagem do vídeo com FFmpeg...")

            # 2. FFmpeg Video Generation (allocated 25% - 100% of progress bar)
            def ffmpeg_progress(frac: float, msg: str):
                total_frac = 0.25 + (0.75 * frac)
                self.progress_changed.emit(min(1.0, total_frac), msg)

            out_file = generate_video(
                slide_images=images,
                durations=self.durations,
                audio_path=self.audio_path,
                output_path=self.output_path,
                resolution=self.resolution,
                fps=self.fps,
                progress_callback=ffmpeg_progress,
                cancel_check=lambda: self._is_cancelled,
            )

            if self._is_cancelled:
                self.render_cancelled.emit()
                return

            self.progress_changed.emit(1.0, "Vídeo concluído!")
            self.render_finished.emit(out_file)

        except InterruptedError:
            self.render_cancelled.emit()
        except Exception as e:
            traceback.print_exc()
            self.render_error.emit(str(e))
        finally:
            # Clean up temp slide directory
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


class AISyncWorker(QThread):
    status_changed = Signal(str)
    sync_finished = Signal(list)  # List[float] durations
    sync_error = Signal(str)

    def __init__(
        self,
        pdf_path: str,
        audio_path: str,
        total_audio_duration: float,
        api_key: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.audio_path = audio_path
        self.total_audio_duration = total_audio_duration
        self.api_key = api_key

    def run(self):
        try:
            from app.core.ai_synchronizer import synchronize_slides_with_gemini

            durations = synchronize_slides_with_gemini(
                pdf_path=self.pdf_path,
                audio_path=self.audio_path,
                total_audio_duration=self.total_audio_duration,
                api_key=self.api_key,
                progress_callback=lambda msg: self.status_changed.emit(msg),
            )
            self.sync_finished.emit(durations)
        except Exception as e:
            traceback.print_exc()
            self.sync_error.emit(str(e))

