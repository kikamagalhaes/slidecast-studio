import os
import shutil
import tempfile
import threading
import time
import uuid
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.pdf_processor import render_all_slides_to_dir
from app.core.video_generator import generate_video


@dataclass
class RenderJob:
    id: str
    pdf_path: str
    audio_path: str
    durations: List[float]
    resolution: Tuple[int, int]
    fps: int
    output_dir: Path
    status: str = "queued"  # queued, rendering, completed, failed
    progress: float = 0.0
    message: str = "Na fila de processamento..."
    output_video_path: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class JobQueueManager:
    def __init__(self, max_concurrent: int = 1):
        self.jobs: Dict[str, RenderJob] = {}
        self.queue: List[str] = []
        self.max_concurrent = max_concurrent
        self.active_count = 0
        self.lock = threading.Lock()
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()

    def create_job(
        self,
        pdf_path: str,
        audio_path: str,
        durations: List[float],
        resolution: Tuple[int, int],
        fps: int,
        output_dir: Path,
    ) -> RenderJob:
        job_id = str(uuid.uuid4())
        job = RenderJob(
            id=job_id,
            pdf_path=pdf_path,
            audio_path=audio_path,
            durations=durations,
            resolution=resolution,
            fps=fps,
            output_dir=output_dir,
        )
        with self.lock:
            self.jobs[job_id] = job
            self.queue.append(job_id)
        return job

    def get_job(self, job_id: str) -> Optional[RenderJob]:
        with self.lock:
            return self.jobs.get(job_id)

    def _process_queue(self):
        while True:
            time.sleep(0.5)
            job_to_run = None
            with self.lock:
                if self.active_count < self.max_concurrent and self.queue:
                    job_id = self.queue.pop(0)
                    job_to_run = self.jobs.get(job_id)
                    if job_to_run:
                        job_to_run.status = "rendering"
                        job_to_run.message = "Iniciando renderização..."
                        self.active_count += 1

            if job_to_run:
                self._execute_job(job_to_run)
                with self.lock:
                    self.active_count -= 1

    def _execute_job(self, job: RenderJob):
        temp_dir = Path(tempfile.mkdtemp(prefix="slidecast_web_"))
        try:
            job.output_dir.mkdir(parents=True, exist_ok=True)
            final_video_path = job.output_dir / f"video_{job.id}.mp4"

            # 1. Slide Extraction (0% to 25%)
            def slide_progress(curr, total):
                job.progress = 0.02 + 0.23 * (curr / total)
                job.message = f"Extraindo slide {curr} de {total}..."

            images = render_all_slides_to_dir(
                file_path=job.pdf_path,
                output_dir=temp_dir,
                target_dpi=150,
                progress_callback=slide_progress,
            )

            job.progress = 0.25
            job.message = "Renderizando vídeo com FFmpeg..."

            # 2. Video Encoding (25% to 100%)
            def video_progress(frac, msg):
                job.progress = min(0.99, 0.25 + 0.74 * frac)
                job.message = msg

            out_file = generate_video(
                slide_images=images,
                durations=job.durations,
                audio_path=job.audio_path,
                output_path=str(final_video_path),
                resolution=job.resolution,
                fps=job.fps,
                progress_callback=video_progress,
            )

            job.status = "completed"
            job.progress = 1.0
            job.message = "Vídeo gerado com sucesso!"
            job.output_video_path = out_file
            job.completed_at = time.time()

        except Exception as e:
            traceback.print_exc()
            job.status = "failed"
            job.error = str(e)
            job.message = f"Erro na renderização: {e}"
        finally:
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


# Global singleton instance
queue_manager = JobQueueManager(max_concurrent=1)
