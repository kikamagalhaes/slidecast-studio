"""Job cancellation semantics (deterministic, no timing races)."""

import time
import uuid

from app.web.queue_manager import JobQueueManager


def _make_manager():
    manager = JobQueueManager(max_concurrent=0)  # worker thread never picks up
    return manager


def test_cancel_queued_job(tmp_path):
    manager = _make_manager()
    job = manager.create_job(
        pdf_path="p",
        audio_path="a",
        durations=[1.0],
        resolution=(320, 240),
        fps=15,
        output_dir=tmp_path / "out",
    )
    assert manager.cancel_job(job.id) == "cancelled"
    stored = manager.get_job(job.id)
    assert stored.status == "cancelled"
    assert stored.completed_at is not None
    assert manager.pending_count() == 0


def test_cancel_unknown_and_finished_jobs(tmp_path):
    manager = _make_manager()
    assert manager.cancel_job(str(uuid.uuid4())) is None
    job = manager.create_job(
        pdf_path="p",
        audio_path="a",
        durations=[1.0],
        resolution=(320, 240),
        fps=15,
        output_dir=tmp_path / "out",
    )
    manager.update_job(job.id, status="completed", completed_at=time.time())
    assert manager.cancel_job(job.id) == "completed"  # no-op, keeps status


def test_pre_requested_cancel_aborts_execution(tmp_path):
    from tests.test_web_api import make_pdf_bytes, make_wav_bytes

    pdf = tmp_path / "slides.pdf"
    pdf.write_bytes(make_pdf_bytes(pages=2))
    audio = tmp_path / "narr.wav"
    audio.write_bytes(make_wav_bytes(seconds=1.0))

    manager = _make_manager()
    job = manager.create_job(
        pdf_path=str(pdf),
        audio_path=str(audio),
        durations=[0.5, 0.5],
        resolution=(320, 240),
        fps=15,
        output_dir=tmp_path / "out",
    )
    manager.update_job(job.id, cancel_requested=True)
    manager.max_concurrent = 1  # release the worker only after flagging

    deadline = time.time() + 30
    while time.time() < deadline:
        if manager.get_job(job.id).status == "cancelled":
            break
        time.sleep(0.2)
    assert manager.get_job(job.id).status == "cancelled"
