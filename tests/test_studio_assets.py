"""O build do estúdio referencia /assets/* (base /slidecast/ em produção).

Após o StripPrefix do Traefik, /assets/* precisa ser servido por este app.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from app.web.server import app

ASSETS = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "studio" / "assets"


def test_studio_assets_servidos_em_assets():
    files = [p for p in ASSETS.glob("*.js")] if ASSETS.is_dir() else []
    if not files:
        return  # build do frontend ausente neste ambiente; nada a servir
    client = TestClient(app)
    r = client.get(f"/assets/{files[0].name}")
    assert r.status_code == 200
    assert len(r.content) > 0
