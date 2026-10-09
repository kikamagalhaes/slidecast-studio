"""Shared web-render pipeline plus the RQ task entrypoint.

Both queue backends run the exact same :func:`run_render_pipeline`:

- in-memory backend: called from its worker thread (see ``queue_manager``);
- Redis backend: called from :func:`render_job_task` by ``rq worker``.

The RQ task must stay importable as ``app.web.render_task.render_job_task``
(RQ resolves tasks by dotted path, never from ``__main__``).
"""

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from app.core.pdf_processor import render_all_slides_to_dir
from app.core.video_generator import generate_video

logger = logging.getLogger(__name__)


def run_render_pipeline(
    pdf_path: str,
    audio_path: str,
    durations: List[float],
    resolution: Tuple[int, int],
    fps: int,
    output_path: str,
    target_dpi: int = 150,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """Extracts slides (0-25%) then encodes with ffmpeg (25-100%).

    :raises InterruptedError: when ``cancel_check`` fires mid-render.
    :returns: absolute path of the rendered video.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="slidecast_render_"))
    try:

        def slide_progress(curr: int, total: int) -> None:
            if progress_callback:
                progress_callback(
                    0.02 + 0.23 * (curr / total),
                    f"Extraindo slide {curr} de {total}...",
                )

        images = render_all_slides_to_dir(
            file_path=pdf_path,
            output_dir=temp_dir,
            target_dpi=target_dpi,
            progress_callback=slide_progress,
            cancel_check=cancel_check,
        )

        if progress_callback:
            progress_callback(0.25, "Renderizando vídeo com FFmpeg...")

        def video_progress(frac: float, msg: str) -> None:
            if progress_callback:
                progress_callback(min(0.99, 0.25 + 0.74 * frac), msg)

        out = generate_video(
            slide_images=images,
            durations=durations,
            audio_path=audio_path,
            output_path=str(out_file),
            resolution=resolution,
            fps=fps,
            progress_callback=video_progress,
            cancel_check=cancel_check,
        )

        if progress_callback:
            progress_callback(1.0, "Vídeo gerado com sucesso!")
        return out
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def render_job_task(payload: Dict) -> Dict:
    """RQ entrypoint: renders one job, mirroring progress into job.meta.

    :param payload: ``pdf_path``, ``audio_path``, ``durations``,
        ``resolution``, ``fps``, ``output_path``.
    :returns: ``{"output_video_path": ...}`` or ``{"cancelled": True}``.
        Unexpected exceptions propagate so RQ marks the job FAILED.
    """
    from rq import get_current_job

    rq_job = None
    try:
        rq_job = get_current_job()
    except Exception:
        rq_job = None

    last_refresh = [0.0]

    def set_meta(**fields) -> None:
        if rq_job is None:
            return
        rq_job.meta.update(fields)
        try:
            rq_job.save_meta()
        except Exception as exc:
            logger.debug("Could not persist job meta: %s", exc)

    def cancel_requested() -> bool:
        if rq_job is None:
            return False
        now = time.monotonic()
        if now - last_refresh[0] > 1.0:
            try:
                rq_job.refresh()
            except Exception:
                pass
            last_refresh[0] = now
        try:
            meta = rq_job.meta or {}
        except Exception:
            return False
        return bool(meta.get("cancel_requested"))

    def progress(frac: float, msg: str) -> None:
        set_meta(status="rendering", progress=frac, message=msg)

    logger.info(
        "render task started: %s pages -> %s",
        len(payload.get("durations", [])),
        payload.get("output_path"),
    )
    set_meta(status="rendering", progress=0.0, message="Iniciando renderização...")

    try:
        out = run_render_pipeline(
            pdf_path=payload["pdf_path"],
            audio_path=payload["audio_path"],
            durations=list(payload["durations"]),
            resolution=tuple(payload["resolution"]),
            fps=int(payload["fps"]),
            output_path=payload["output_path"],
            progress_callback=progress,
            cancel_check=cancel_requested,
        )
    except InterruptedError:
        logger.info("render task cancelled: %s", payload.get("output_path"))
        set_meta(
            status="cancelled",
            message="Renderização cancelada.",
            completed_at=time.time(),
        )
        return {"cancelled": True}

    set_meta(
        status="completed",
        progress=1.0,
        message="Vídeo gerado com sucesso!",
        output_video_path=out,
        completed_at=time.time(),
    )
    logger.info("render task completed: %s", out)
    return {"output_video_path": out}
