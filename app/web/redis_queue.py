"""Redis/RQ queue backend: durable jobs shared by any number of processes.

Selected with ``QUEUE_BACKEND=redis``. Requires a reachable Redis
(``REDIS_URL``) and at least one worker process::

    rq worker slidecast --url "$REDIS_URL"

Web and workers must share the same ``/app/storage`` volume, because job
payloads carry filesystem paths. Finished-job retention is enforced by
Redis TTLs (``JOB_RESULT_TTL_HOURS``) instead of in-memory eviction.
"""

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from rq.registry import StartedJobRegistry

from app.web.queue_manager import FINISHED_STATUSES, RenderJob
from app.web.render_task import render_job_task

logger = logging.getLogger(__name__)

QUEUE_NAME = "slidecast"


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


class RedisJobQueue:
    """RQ-backed registry exposing the JobQueueManager interface."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", connection=None):
        self.redis_url = redis_url
        # `connection` is injectable so tests can use fakeredis.
        self.conn = connection if connection is not None else redis.from_url(redis_url)
        self.queue = Queue(QUEUE_NAME, connection=self.conn)
        self.result_ttl = int(_env_float("JOB_RESULT_TTL_HOURS", 24.0) * 3600)
        self.job_timeout = _env_int("RQ_JOB_TIMEOUT", 3600)

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
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "pdf_path": str(pdf_path),
            "audio_path": str(audio_path),
            "durations": [float(d) for d in durations],
            "resolution": [int(resolution[0]), int(resolution[1])],
            "fps": int(fps),
            "output_path": str(out_dir / f"video_{job_id}.mp4"),
        }
        created = time.time()
        self.queue.enqueue(
            render_job_task,
            payload,
            job_id=job_id,
            job_timeout=self.job_timeout,
            result_ttl=self.result_ttl,
            failure_ttl=self.result_ttl,
            meta={
                "status": "queued",
                "progress": 0.0,
                "message": "Na fila de processamento...",
                "error": None,
                "output_video_path": None,
                "created_at": created,
                "completed_at": None,
            },
        )
        logger.info("job %s queued on redis (%d pages)", job_id, len(durations))
        return RenderJob(
            id=job_id,
            pdf_path=payload["pdf_path"],
            audio_path=payload["audio_path"],
            durations=list(payload["durations"]),
            resolution=(payload["resolution"][0], payload["resolution"][1]),
            fps=payload["fps"],
            output_dir=out_dir,
            created_at=created,
        )

    def get_job(self, job_id: str) -> Optional[RenderJob]:
        try:
            job = Job.fetch(job_id, connection=self.conn)
            return self._to_view(job)
        except NoSuchJobError:
            return None

    def update_job(self, job_id: str, **fields) -> None:
        try:
            job = Job.fetch(job_id, connection=self.conn)
        except NoSuchJobError:
            return
        for key in (
            "status",
            "progress",
            "message",
            "error",
            "output_video_path",
            "completed_at",
        ):
            if key in fields:
                job.meta[key] = fields[key]
        try:
            job.save_meta()
        except Exception as exc:
            logger.debug("Could not persist job meta for %s: %s", job_id, exc)

    def cancel_job(self, job_id: str) -> Optional[str]:
        try:
            job = Job.fetch(job_id, connection=self.conn)
        except NoSuchJobError:
            return None
        view = self._to_view(job)
        if view is None:
            return None
        if view.status in FINISHED_STATUSES:
            return view.status
        if job.get_status() == JobStatus.STARTED:
            # A running task observes this flag at its next checkpoint and
            # reports itself as cancelled; the client keeps polling.
            job.meta["cancel_requested"] = True
            try:
                job.save_meta()
            except Exception as exc:
                logger.debug("Could not flag %s for cancel: %s", job_id, exc)
            return "rendering"
        try:
            job.cancel()
        except Exception as exc:
            logger.warning("Could not cancel job %s: %s", job_id, exc)
        return "cancelled"

    def pending_count(self) -> int:
        try:
            queued = len(self.queue)
        except Exception:
            queued = 0
        try:
            started = len(StartedJobRegistry(QUEUE_NAME, connection=self.conn))
        except Exception:
            started = 0
        return queued + started

    # -- RQ -> RenderJob mapping --------------------------------------
    def _to_view(self, job: Job) -> Optional[RenderJob]:
        try:
            rq_status = job.get_status()
            meta: Dict = dict(job.meta or {})
        except NoSuchJobError:
            return None

        payload = {}
        try:
            if job.args:
                payload = dict(job.args[0] or {})
        except Exception:
            payload = {}

        created = meta.get("created_at") or time.time()
        base = dict(
            pdf_path=payload.get("pdf_path", ""),
            audio_path=payload.get("audio_path", ""),
            durations=list(payload.get("durations", [])),
            resolution=tuple(payload.get("resolution", (1920, 1080))),
            fps=int(payload.get("fps", 30)),
            output_dir=Path(payload.get("output_path", "")).parent
            if payload.get("output_path")
            else Path("."),
            created_at=float(created),
        )

        if rq_status == JobStatus.FINISHED:
            result = {}
            try:
                latest = job.latest_result()
                returned = latest.return_value if latest is not None else None
                result = dict(returned or {})
            except Exception:
                result = {}
            if result.get("cancelled"):
                return RenderJob(
                    id=job.id,
                    status="cancelled",
                    message=meta.get("message") or "Renderização cancelada.",
                    completed_at=meta.get("completed_at") or time.time(),
                    **base,
                )
            return RenderJob(
                id=job.id,
                status="completed",
                progress=1.0,
                message=meta.get("message") or "Vídeo gerado com sucesso!",
                output_video_path=result.get("output_video_path")
                or meta.get("output_video_path"),
                completed_at=meta.get("completed_at") or time.time(),
                **base,
            )

        if rq_status == JobStatus.FAILED:
            try:
                latest = job.latest_result()
                exc_text = (getattr(latest, "exc_string", "") or "").strip()
            except Exception:
                exc_text = ""
            error_lines = exc_text.splitlines()
            error = error_lines[-1][-500:] if error_lines else "Falha na renderização."
            return RenderJob(
                id=job.id,
                status="failed",
                progress=float(meta.get("progress", 0.0) or 0.0),
                message=f"Erro na renderização: {error}",
                error=error,
                completed_at=meta.get("completed_at") or time.time(),
                **base,
            )

        if rq_status in (JobStatus.CANCELED, JobStatus.STOPPED):
            return RenderJob(
                id=job.id,
                status="cancelled",
                message=meta.get("message") or "Renderização cancelada.",
                completed_at=meta.get("completed_at") or time.time(),
                **base,
            )

        if rq_status == JobStatus.STARTED:
            return RenderJob(
                id=job.id,
                status="rendering",
                progress=float(meta.get("progress", 0.0) or 0.0),
                message=meta.get("message") or "Renderizando...",
                **base,
            )

        return RenderJob(
            id=job.id,
            status="queued",
            progress=float(meta.get("progress", 0.0) or 0.0),
            message=meta.get("message") or "Na fila de processamento...",
            **base,
        )
