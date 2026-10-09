import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.web.render_task import run_render_pipeline

logger = logging.getLogger(__name__)

# NOTE: jobs live in process memory, so the web service must run with a single
# uvicorn worker (see Dockerfile). Finished jobs are evicted after
# JOB_RETENTION_HOURS (default 24) and the registry is capped at MAX_JOBS
# entries (default 200) to bound memory usage.


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class RenderJob:
    id: str
    pdf_path: str
    audio_path: str
    durations: List[float]
    resolution: Tuple[int, int]
    fps: int
    output_dir: Path
    status: str = "queued"  # queued, rendering, completed, failed, cancelled
    progress: float = 0.0
    message: str = "Na fila de processamento..."
    output_video_path: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    cancel_requested: bool = False


FINISHED_STATUSES = ("completed", "failed", "cancelled")


class JobQueueManager:
    def __init__(self, max_concurrent: int = 1):
        self.jobs: Dict[str, RenderJob] = {}
        self.queue: List[str] = []
        self.max_concurrent = max_concurrent
        self.active_count = 0
        self.lock = threading.Lock()
        self.retention_seconds = _env_float("JOB_RETENTION_HOURS", 24.0) * 3600.0
        self.max_jobs = _env_int("MAX_JOBS", 200)
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
            self._evict_finished_locked()
        logger.info("job %s queued (%d pages)", job_id, len(durations))
        return job

    def get_job(self, job_id: str) -> Optional[RenderJob]:
        with self.lock:
            return self.jobs.get(job_id)

    def pending_count(self) -> int:
        """Number of queued + actively rendering jobs."""
        with self.lock:
            return len(self.queue) + self.active_count

    def cancel_job(self, job_id: str) -> Optional[str]:
        """Requests cancellation; returns the resulting status, None if unknown.

        Queued jobs are dropped immediately; rendering jobs observe the flag
        at the next cancellation checkpoint (client should keep polling).
        """
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            if job.status in FINISHED_STATUSES:
                return job.status
            if job.status == "queued":
                if job_id in self.queue:
                    self.queue.remove(job_id)
                job.status = "cancelled"
                job.message = "Renderização cancelada."
                job.completed_at = time.time()
                logger.info("job %s cancelled while queued", job_id)
                return job.status
            job.cancel_requested = True
            job.message = "Cancelamento solicitado..."
            logger.info("job %s cancellation requested", job_id)
            return job.status

    def update_job(self, job_id: str, **fields) -> None:
        """Lock-protected in-place update of a job's mutable fields."""
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)

    def _evict_finished_locked(self) -> None:
        """Drops old finished jobs; caller must hold the lock."""
        now = time.time()
        finished = [
            job
            for job in self.jobs.values()
            if job.status in FINISHED_STATUSES and job.completed_at
        ]
        for job in finished:
            if now - job.completed_at > self.retention_seconds:
                logger.info("evicting expired job %s (%s)", job.id, job.status)
                del self.jobs[job.id]
        # Hard cap: evict oldest finished first, never queued/rendering jobs.
        overflow = len(self.jobs) - max(1, self.max_jobs)
        if overflow > 0:
            victims = sorted(
                (j for j in self.jobs.values() if j.status in FINISHED_STATUSES),
                key=lambda j: j.completed_at or 0.0,
            )[:overflow]
            for job in victims:
                logger.info("evicting job %s to enforce MAX_JOBS", job.id)
                del self.jobs[job.id]

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
        try:
            job.output_dir.mkdir(parents=True, exist_ok=True)
            final_video_path = job.output_dir / f"video_{job.id}.mp4"

            out_file = run_render_pipeline(
                pdf_path=job.pdf_path,
                audio_path=job.audio_path,
                durations=job.durations,
                resolution=job.resolution,
                fps=job.fps,
                output_path=str(final_video_path),
                progress_callback=lambda frac, msg: self.update_job(
                    job.id, progress=frac, message=msg
                ),
                cancel_check=lambda: bool(job.cancel_requested),
            )

            self.update_job(
                job.id,
                status="completed",
                progress=1.0,
                message="Vídeo gerado com sucesso!",
                output_video_path=out_file,
                completed_at=time.time(),
            )
            logger.info("job %s completed: %s", job.id, out_file)

        except InterruptedError:
            logger.info("job %s cancelled during rendering", job.id)
            try:
                final_video_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.update_job(
                job.id,
                status="cancelled",
                message="Renderização cancelada.",
                completed_at=time.time(),
            )
        except Exception as exc:
            logger.exception("job %s failed", job.id)
            self.update_job(
                job.id,
                status="failed",
                error=str(exc),
                message=f"Erro na renderização: {exc}",
                completed_at=time.time(),
            )


def build_queue_manager():
    """Builds the configured backend (``QUEUE_BACKEND``: memory or redis)."""
    backend = (os.environ.get("QUEUE_BACKEND", "memory") or "memory").strip().lower()
    if backend == "redis":
        from app.web.redis_queue import RedisJobQueue

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        logger.info("Using Redis queue backend at %s", url)
        return RedisJobQueue(url)
    if backend != "memory":
        logger.warning("Unknown QUEUE_BACKEND=%r; falling back to memory.", backend)
    return JobQueueManager(max_concurrent=1)


# Global singleton instance (backend chosen by QUEUE_BACKEND env var)
queue_manager = build_queue_manager()
