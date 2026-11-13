"""Web: capas prontas de podcast e composição (título + assinatura)."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.web.server as server_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    with TestClient(server_module.app) as test_client:
        yield test_client


def _auth(client):
    res = client.post("/api/auth/register", json={"email": "capa@example.com", "password": "password123"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_podcast_covers_require_login(client):
    assert client.get("/api/podcast/covers").status_code in (401, 403)


def test_list_and_fetch_preset_covers(client):
    h = _auth(client)
    res = client.get("/api/podcast/covers", headers=h)
    assert res.status_code == 200, res.text
    covers = res.json()["covers"]
    assert len(covers) == 3
    img_res = client.get(covers[0]["url"], headers=h)
    assert img_res.status_code == 200
    with Image.open(io.BytesIO(img_res.content)) as img:
        assert img.size == (1080, 1080)


def test_compose_from_preset_and_from_upload(client):
    h = _auth(client)
    res = client.post("/api/podcast/cover/compose", headers=h, data={
        "preset_id": "estudio",
        "title": "Por que a Nova Jerusalém tem formato de cubo?",
        "author": "Kika Magalhães",
        "title_color": "#ffffff", "title_outline_color": "#000000",
        "author_color": "#f2d492", "author_outline_color": "#000000",
    })
    assert res.status_code == 200, res.text
    with Image.open(io.BytesIO(res.content)) as img:
        assert img.size == (1080, 1080)
    preset = client.get("/api/podcast/covers", headers=h).json()["covers"][0]
    raw = client.get(preset["url"], headers=h).content
    assert res.content != raw  # título/assinatura foram gravados

    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (90, 40, 40)).save(buf, format="PNG")
    up = client.post("/api/podcast/cover/compose", headers=h,
                     files={"image": ("minha-capa.png", buf.getvalue(), "image/png")},
                     data={"title": "Episódio 1", "author": "Andréia Silva"})
    assert up.status_code == 200, up.text
    with Image.open(io.BytesIO(up.content)) as img:
        assert img.size == (1080, 1080)


def test_compose_rejects_missing_base_and_bad_color(client):
    h = _auth(client)
    assert client.post("/api/podcast/cover/compose", headers=h, data={"title": "X"}).status_code == 400
    bad = client.post("/api/podcast/cover/compose", headers=h,
                      data={"preset_id": "estudio", "title": "X", "title_color": "roxo"})
    assert bad.status_code == 400
    assert client.post("/api/podcast/cover/compose", headers=h,
                       data={"preset_id": "nao-existe", "title": "X"}).status_code == 400
