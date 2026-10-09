"""Rate limiter unit + integration tests (in-memory counters)."""

import pytest
from fastapi.testclient import TestClient

import app.web.rate_limit as rate_limit
import app.web.server as server_module
from app.web.rate_limit import check_rate_limit
from tests.test_web_api import auth_headers, upload_project


def test_allows_under_limit_blocks_over_and_slides(monkeypatch):
    rate_limit.reset()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    assert check_rate_limit("k", now=0.0) is None
    assert check_rate_limit("k", now=1.0) is None
    retry = check_rate_limit("k", now=2.0)
    assert isinstance(retry, int) and retry > 0
    assert check_rate_limit("other-key", now=2.0) is None
    assert check_rate_limit("k", now=61.0) is None
    rate_limit.reset()


def test_disabled_allows_everything(monkeypatch):
    rate_limit.reset()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    for _ in range(5):
        assert check_rate_limit("k", now=0.0) is None
    rate_limit.reset()


@pytest.fixture()
def limited_client(tmp_path, monkeypatch):
    rate_limit.reset()
    monkeypatch.setattr(server_module, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    with TestClient(server_module.app) as test_client:
        yield test_client
    rate_limit.reset()


def test_upload_endpoint_returns_429_when_limited(limited_client):
    headers, _ = auth_headers(limited_client)
    assert upload_project(limited_client, headers=headers).status_code == 200
    assert upload_project(limited_client, headers=headers).status_code == 200
    res = upload_project(limited_client, headers=headers)
    assert res.status_code == 429
    assert "Retry-After" in res.headers
