"""Render recorded studio segments (slides + didactic scenes + ink) to MP4."""
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from app.core.video_generator import generate_video


class StudioRenderWorker(QThread):
    progress_changed = Signal(float, str)
    render_finished = Signal(str)
    render_error = Signal(str)

    def __init__(self, segments, audio_path, output_path, parent=None):
        super().__init__(parent)
        self.segments, self.audio_path, self.output_path = segments, audio_path, output_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            images = [Path(s["image"]) for s in self.segments]
            durations = [float(s["duration"]) for s in self.segments]
            generate_video(images, durations, self.audio_path, self.output_path,
                           progress_callback=lambda f, m: self.progress_changed.emit(f, m),
                           cancel_check=lambda: self._cancelled)
            self.render_finished.emit(self.output_path)
        except Exception as exc:  # surfaced in result view, never silent
            self.render_error.emit(str(exc))
