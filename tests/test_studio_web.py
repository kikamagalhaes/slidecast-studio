"""Studio web endpoints: PDF slots, page render, recording conversion."""
import io

import pymupdf
import pytest
from fastapi.testclient import TestClient

import app.web.server as server_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "STORAGE_DIR", tmp_path / "storage")
    with TestClient(server_module.app) as c:
        yield c


def _pdf():
    doc = pymupdf.open()
    for i in range(2):
        p = doc.new_page(width=640, height=360)
        p.insert_text((40, 60), f"Slide {i + 1}", fontsize=24)
    b = doc.tobytes(); doc.close(); return b


def test_studio_pdf_page_and_recording_conversion(client):
    r = client.post("/api/auth/register",
                    json={"email": "s@t.local", "password": "password123"})
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['token']}"
    pid = client.post("/api/projects", json={"name": "Aula", "kind": "aula"}).json()["id"]
    up = client.post(f"/api/projects/{pid}/studio/pdfs/2",
                     files={"pdf_file": ("slides.pdf", io.BytesIO(_pdf()), "application/pdf")})
    assert up.status_code == 200 and up.json()["page_count"] == 2, up.text
    page = client.get(f"/api/projects/{pid}/studio/pdfs/2/page/1")
    assert page.status_code == 200 and page.content[:4] == b"\x89PNG"
    other = client.post("/api/auth/register",
                        json={"email": "o@t.local", "password": "password123"})
    client.headers["Authorization"] = f"Bearer {other.json()['token']}"
    assert client.get(f"/api/projects/{pid}/studio/pdfs/2/page/0").status_code == 404
