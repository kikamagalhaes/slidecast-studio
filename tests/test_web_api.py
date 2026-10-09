"""Web API integration tests (upload -> thumbnail -> render -> download).

Renders run the real ffmpeg pipeline on tiny generated fixtures, with the
storage directory isolated per test. No Gemini key is touched.
"""

import math
import shutil
import struct
import time
import uuid
import wave

import pymupdf
import pytest
from fastapi.testclient import TestClient

import app.web.server as server_module

ffmpeg_available = shutil.which("ffmpeg") is not None


def make_pdf_bytes(pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Slide {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_wav_bytes(seconds=2.0, rate=22050):
    import io

    frames = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for i in range(frames):
            sample = int(8000 * math.sin(2 * math.pi * 220 * i / rate))
            wav.writeframes(struct.pack("<h", sample))
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(server_module.app) as test_client:
        yield test_client


def upload_project(
    test_client, pdf_name="slides.pdf", audio_name="narr.wav", pdf_bytes=None
):
    return test_client.post(
        "/api/upload",
        files={
            "pdf_file": (pdf_name, pdf_bytes or make_pdf_bytes(), "application/pdf"),
            "audio_file": (audio_name, make_wav_bytes(), "audio/wav"),
        },
    )


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "slidecast-web"
    assert body["ffmpeg"] == bool(shutil.which("ffmpeg"))
    assert body["status"] == ("healthy" if body["ffmpeg"] else "degraded")
    assert isinstance(body["pending_jobs"], int)


def test_health_degraded_without_ffmpeg(client, monkeypatch):
    monkeypatch.setattr(server_module, "get_ffmpeg_paths", lambda: (None, None))
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["ffmpeg"] is False
    assert any("ffmpeg" in reason for reason in body["reasons"])


def test_health_degraded_on_low_disk(client, monkeypatch):
    monkeypatch.setattr(server_module, "_disk_free_mb", lambda path: 1)
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert any("disk" in reason for reason in body["reasons"])


def test_thumbnail_is_rendered_once_then_cached(client, tmp_path, monkeypatch):
    project_id = upload_project(client).json()["project_id"]
    original = server_module.render_thumbnail
    calls = []

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(server_module, "render_thumbnail", counting)
    first = client.get(f"/api/projects/{project_id}/thumbnail/1")
    second = client.get(f"/api/projects/{project_id}/thumbnail/1")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content
    assert len(calls) == 1
    cached = (
        tmp_path / "storage" / "projects" / project_id / "thumbs" / "thumb_0001.png"
    )
    assert cached.exists()


def test_key_status_unconfigured(client, monkeypatch):
    monkeypatch.setattr(server_module, "get_gemini_api_key", lambda: None)
    res = client.get("/api/config/key")
    assert res.json() == {"configured": False, "masked": None}


def test_key_save_refused_when_env_managed(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    res = client.post("/api/config/key", data={"key": "other"})
    assert res.status_code == 409


def test_key_save_requires_admin_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    saved = []
    monkeypatch.setattr(server_module, "set_gemini_api_key", saved.append)

    assert client.post("/api/config/key", data={"key": "k"}).status_code == 401
    assert (
        client.post(
            "/api/config/key", data={"key": "k"}, headers={"X-Admin-Token": "wrong"}
        ).status_code
        == 401
    )
    res = client.post(
        "/api/config/key", data={"key": "k"}, headers={"X-Admin-Token": "secret"}
    )
    assert res.status_code == 200
    assert saved == ["k"]


def test_upload_rejects_wrong_extensions(client):
    res = upload_project(client, pdf_name="slides.txt")
    assert res.status_code == 400
    res = upload_project(client, audio_name="narr.pdf")
    assert res.status_code == 400


def test_upload_rejects_fake_pdf_content(client):
    res = upload_project(client, pdf_bytes=b"this is not a pdf at all")
    assert res.status_code == 400
    assert "assinatura" in res.json()["detail"]


def test_delete_job_endpoint_wiring(client, monkeypatch):
    calls = {}

    class StubQueue:
        def cancel_job(self, job_id):
            calls["job_id"] = job_id
            return "cancelled"

    monkeypatch.setattr(server_module, "queue_manager", StubQueue())
    job_id = str(uuid.uuid4())
    res = client.delete(f"/api/jobs/{job_id}")
    assert res.status_code == 200
    assert res.json() == {"id": job_id, "status": "cancelled"}
    assert calls["job_id"] == job_id


def test_delete_job_not_found_and_malformed(client, monkeypatch):
    class StubQueue:
        def cancel_job(self, job_id):
            return None

    monkeypatch.setattr(server_module, "queue_manager", StubQueue())
    assert client.delete(f"/api/jobs/{uuid.uuid4()}").status_code == 404
    assert client.delete("/api/jobs/nope").status_code == 400


def test_unknown_and_malformed_project_ids(client):
    assert client.get(f"/api/projects/{uuid.uuid4()}/thumbnail/0").status_code == 404
    assert client.get("/api/projects/not-a-uuid/thumbnail/0").status_code == 400
    assert client.get(f"/api/jobs/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/jobs/traversal..").status_code == 400


@pytest.mark.skipif(not ffmpeg_available, reason="ffmpeg not installed")
def test_full_render_flow(client):
    res = upload_project(client)
    assert res.status_code == 200, res.text
    body = res.json()
    project_id = body["project_id"]
    assert body["page_count"] == 2
    assert len(body["slides"]) == 2
    assert body["pdf_name"] == "slides.pdf"

    thumb = client.get(f"/api/projects/{project_id}/thumbnail/0")
    assert thumb.status_code == 200
    assert thumb.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/projects/{project_id}/thumbnail/9").status_code == 400

    # Invalid render payloads are rejected before any job is queued.
    bad = client.post(
        f"/api/projects/{project_id}/render",
        json={"durations": [1.0], "resolution_w": 320, "resolution_h": 240, "fps": 15},
    )
    assert bad.status_code == 400
    bad = client.post(
        f"/api/projects/{project_id}/render",
        json={"durations": [1.0, 1.0], "resolution_w": 321, "resolution_h": 240, "fps": 15},
    )
    assert bad.status_code == 400

    res = client.post(
        f"/api/projects/{project_id}/render",
        json={"durations": [1.0, 1.0], "resolution_w": 320, "resolution_h": 240, "fps": 15},
    )
    assert res.status_code == 200, res.text
    job_id = res.json()["job_id"]

    deadline = time.time() + 180
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert status["status"] == "completed", status.get("error")

    download = client.get(f"/api/jobs/{job_id}/download")
    assert download.status_code == 200
    assert len(download.content) > 1000
    video = client.get(f"/api/jobs/{job_id}/video")
    assert video.status_code == 200
    assert len(video.content) > 1000
