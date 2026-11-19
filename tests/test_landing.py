"""Landing routing is separate from authenticated legacy API/data."""
from fastapi.testclient import TestClient
from app.web.server import app


def test_public_home_is_commercial_landing(monkeypatch):
    monkeypatch.delenv("PUBLIC_SITE_URL", raising=False)
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="pt-BR"' in response.text
    assert "estúdio para criar e gravar aulas" in response.text
    assert '/static/landing/assets/' in response.text


def test_legacy_studio_flag_does_not_remove_auth(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("ENABLE_WEB_STUDIO", "false")
    assert client.get("/studio").status_code == 404
    monkeypatch.setenv("ENABLE_WEB_STUDIO", "true")
    assert client.get("/studio").status_code == 200
    assert client.get("/api/auth/me").status_code in (200,401)


def test_production_canonical_and_legacy_redirect(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://kikamagalhaes.com.br/slidecast/")
    client = TestClient(app, base_url="https://kikamagalhaes.com.br")
    response = client.get("/")
    assert response.status_code == 200
    assert 'rel="canonical" href="https://kikamagalhaes.com.br/slidecast/"' in response.text
    legacy = TestClient(app, base_url="https://old.example")
    redirect = legacy.get("/", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://kikamagalhaes.com.br/slidecast/"


def test_release_metadata_and_missing_manifest(monkeypatch, tmp_path):
    from app.web import server
    import json

    monkeypatch.setattr(server, "static_dir", tmp_path)
    client = TestClient(app)
    assert client.get("/api/releases/latest").status_code == 404
    directory = tmp_path / "landing"
    directory.mkdir()
    metadata = {"version": "test", "platforms": {"linux": {"url": "https://example.com/app.tar.gz"}}}
    (directory / "releases.json").write_text(json.dumps(metadata))
    response = client.get("/api/releases/latest")
    assert response.status_code == 200
    assert response.json() == metadata
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "public, max-age=300"
