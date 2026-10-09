"""Redis/RQ backend tests: fakeredis + inline worker, plus mapping stubs."""

import shutil
import uuid

import pytest

fakeredis = pytest.importorskip("fakeredis")

from rq import SimpleWorker
from rq.job import JobStatus

from app.web.queue_manager import JobQueueManager, build_queue_manager
from app.web.redis_queue import RedisJobQueue
from tests.test_web_api import make_pdf_bytes, make_wav_bytes

ffmpeg_available = shutil.which("ffmpeg") is not None


@pytest.fixture()
def backend():
    return RedisJobQueue("redis://fake/0", connection=fakeredis.FakeRedis())


def _media(tmp_path, pages=2, seconds=1.0):
    pdf = tmp_path / "slides.pdf"
    pdf.write_bytes(make_pdf_bytes(pages=pages))
    audio = tmp_path / "narr.wav"
    audio.write_bytes(make_wav_bytes(seconds=seconds))
    return str(pdf), str(audio)


def _burst(backend):
    worker = SimpleWorker([backend.queue], connection=backend.conn)
    worker.work(burst=True)


def test_factory_selects_backend(monkeypatch):
    monkeypatch.delenv("QUEUE_BACKEND", raising=False)
    assert isinstance(build_queue_manager(), JobQueueManager)
    monkeypatch.setenv("QUEUE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://fake/0")
    manager = build_queue_manager()
    assert isinstance(manager, RedisJobQueue)
    monkeypatch.setenv("QUEUE_BACKEND", "bogus")
    assert isinstance(build_queue_manager(), JobQueueManager)


def test_create_and_fetch_queued(backend, tmp_path):
    pdf, audio = _media(tmp_path)
    job = backend.create_job(
        pdf_path=pdf,
        audio_path=audio,
        durations=[0.5, 0.5],
        resolution=(320, 240),
        fps=10,
        output_dir=tmp_path / "out",
    )
    assert job.status == "queued"
    fetched = backend.get_job(job.id)
    assert fetched is not None
    assert fetched.status == "queued"
    assert fetched.durations == [0.5, 0.5]
    assert backend.pending_count() == 1
    assert backend.get_job(str(uuid.uuid4())) is None


@pytest.mark.skipif(not ffmpeg_available, reason="ffmpeg not installed")
def test_full_render_loop(backend, tmp_path):
    pdf, audio = _media(tmp_path)
    job = backend.create_job(
        pdf_path=pdf,
        audio_path=audio,
        durations=[0.5, 0.5],
        resolution=(320, 240),
        fps=10,
        output_dir=tmp_path / "out",
    )
    _burst(backend)
    fetched = backend.get_job(job.id)
    assert fetched.status == "completed"
    assert fetched.progress == 1.0
    assert fetched.output_video_path
    with open(fetched.output_video_path, "rb") as handle:
        assert len(handle.read()) > 1000
    assert backend.pending_count() == 0


def test_failed_job_mapping(backend, tmp_path):
    job = backend.create_job(
        pdf_path=str(tmp_path / "missing.pdf"),
        audio_path=str(tmp_path / "missing.wav"),
        durations=[1.0],
        resolution=(320, 240),
        fps=10,
        output_dir=tmp_path / "out",
    )
    _burst(backend)
    fetched = backend.get_job(job.id)
    assert fetched.status == "failed"
    assert fetched.error


def test_cancel_queued_job(backend, tmp_path):
    pdf, audio = _media(tmp_path)
    job = backend.create_job(
        pdf_path=pdf,
        audio_path=audio,
        durations=[0.5, 0.5],
        resolution=(320, 240),
        fps=10,
        output_dir=tmp_path / "out",
    )
    assert backend.cancel_job(job.id) == "cancelled"
    _burst(backend)  # cancelled jobs are skipped
    assert backend.get_job(job.id).status == "cancelled"
    assert backend.pending_count() == 0


def test_cancel_unknown_and_finished(backend, tmp_path):
    assert backend.cancel_job(str(uuid.uuid4())) is None
    job = backend.create_job(
        pdf_path=str(tmp_path / "missing.pdf"),
        audio_path=str(tmp_path / "missing.wav"),
        durations=[1.0],
        resolution=(320, 240),
        fps=10,
        output_dir=tmp_path / "out",
    )
    _burst(backend)
    assert backend.get_job(job.id).status == "failed"
    assert backend.cancel_job(job.id) == "failed"


class _StubResult:
    def __init__(self, return_value=None, exc_string=""):
        self.return_value = return_value
        self.exc_string = exc_string


class _StubJob:
    def __init__(self, job_id, status, meta=None, args=(), result=None, exc_info=""):
        self.id = job_id
        self._status = status
        self.meta = meta or {}
        self.args = args
        self._result = _StubResult(return_value=result, exc_string=exc_info)

    def get_status(self):
        return self._status

    def latest_result(self):
        return self._result


def _payload(tmp_path):
    pdf, audio = _media(tmp_path)
    return {
        "pdf_path": pdf,
        "audio_path": audio,
        "durations": [0.5, 0.5],
        "resolution": [320, 240],
        "fps": 10,
        "output_path": str(tmp_path / "out" / "video_x.mp4"),
    }


def test_started_mapping(backend, tmp_path):
    stub = _StubJob(
        "job-1",
        JobStatus.STARTED,
        meta={"progress": 0.42, "message": "Encoding..."},
        args=(_payload(tmp_path),),
    )
    view = backend._to_view(stub)
    assert view.status == "rendering"
    assert view.progress == 0.42
    assert view.message == "Encoding..."


def test_cancelled_result_mapping(backend, tmp_path):
    stub = _StubJob(
        "job-2",
        JobStatus.FINISHED,
        meta={"message": "Renderização cancelada."},
        args=(_payload(tmp_path),),
        result={"cancelled": True},
    )
    assert backend._to_view(stub).status == "cancelled"


def test_update_job_merges_meta(backend, tmp_path):
    pdf, audio = _media(tmp_path)
    job = backend.create_job(
        pdf_path=pdf,
        audio_path=audio,
        durations=[0.5, 0.5],
        resolution=(320, 240),
        fps=10,
        output_dir=tmp_path / "out",
    )
    backend.update_job(job.id, progress=0.7, message="Almost...")
    fetched = backend.get_job(job.id)
    assert fetched.progress == 0.7
    assert fetched.message == "Almost..."
    backend.update_job(str(uuid.uuid4()), progress=1.0)  # unknown: no crash
