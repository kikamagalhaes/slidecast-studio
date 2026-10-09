"""Account registration, login, sessions and /api/auth/* endpoints."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.web.server as server_module
from app.web import auth as auth_module
from app.web import db as db_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    with TestClient(server_module.app) as test_client:
        yield test_client


def db_path(client):
    return server_module.STORAGE_DIR / "slidecast.db"


def test_password_hash_roundtrip():
    stored = auth_module.hash_password("correct horse!")
    assert auth_module.verify_password("correct horse!", stored)
    assert not auth_module.verify_password("wrong", stored)
    assert not auth_module.verify_password("correct horse!", "garbage")
    assert not auth_module.verify_password("correct horse!", "")
    # Same password yields different hashes (random salt).
    assert auth_module.hash_password("x" * 8) != auth_module.hash_password("x" * 8)


def test_register_login_me_logout_flow(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "User@Example.com", "password": "password123"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user"]["email"] == "user@example.com"
    assert body["plan"]["state"] == "trial"
    assert res.cookies.get(auth_module.SESSION_COOKIE)

    token = body["token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "user@example.com"

    assert client.post("/api/auth/login", json={"email": "user@example.com", "password": "password123"}).status_code == 200

    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_cookie_authenticates_without_bearer_header(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "cookie@example.com", "password": "password123"},
    )
    assert res.status_code == 200
    # TestClient keeps the session cookie: no explicit header needed.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "cookie@example.com"


def test_register_validation_errors(client):
    assert (
        client.post(
            "/api/auth/register",
            json={"email": "user@example.com", "password": "password123"},
        ).status_code
        == 200
    )
    dup = client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert dup.status_code == 409
    bad_email = client.post(
        "/api/auth/register", json={"email": "not-an-email", "password": "password123"}
    )
    assert bad_email.status_code == 400
    short_pw = client.post(
        "/api/auth/register", json={"email": "a@b.co", "password": "short"}
    )
    assert short_pw.status_code == 400


def test_login_rejects_unknown_user_and_wrong_password(client):
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "password123"},
        ).status_code
        == 401
    )
    client.post(
        "/api/auth/register",
        json={"email": "real@example.com", "password": "password123"},
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "real@example.com", "password": "nope-nope-nope"},
        ).status_code
        == 401
    )


def test_expired_session_is_rejected(client):
    token = client.post(
        "/api/auth/register",
        json={"email": "old@example.com", "password": "password123"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    conn = db_module.connect(db_path(client))
    try:
        conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
        conn.commit()
    finally:
        conn.close()
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_me_and_logout_require_auth(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/logout").status_code == 401
    bad = {"Authorization": "Bearer bogus-token"}
    assert client.get("/api/auth/me", headers=bad).status_code == 401


def test_tokens_are_stored_hashed(client):
    token = client.post(
        "/api/auth/register",
        json={"email": "hash@example.com", "password": "password123"},
    ).json()["token"]
    conn = sqlite3.connect(str(db_path(client)))
    try:
        blob = "".join(
            row[0] for row in conn.execute("SELECT token_hash FROM sessions")
        )
    finally:
        conn.close()
    assert token not in blob
