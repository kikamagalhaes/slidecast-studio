"""Email+password accounts with opaque session tokens.

Passwords use PBKDF2-HMAC-SHA256 (210k iterations, per-user salt). Sessions
are random tokens of which only the SHA-256 hash is stored server-side, so a
database read alone never yields a usable token.

A request authenticates via the ``Authorization: Bearer`` header or the
``slidecast_session`` cookie (HttpOnly, SameSite=Lax), so plain ``<img>``,
``<video>`` and download links work without JavaScript token plumbing.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

from fastapi import Header, HTTPException, Request

from app.web import db as db_module

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8
PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERS = 210_000
SESSION_COOKIE = "slidecast_session"

DbPath = Optional[Union[str, Path]]


class AuthError(ValueError):
    """User-facing auth failure carrying an HTTP status code."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def session_days() -> int:
    return _int_env("SESSION_DAYS", 30, minimum=1)


def trial_days() -> int:
    return _int_env("TRIAL_DAYS", 14, minimum=0)


def cookie_secure() -> bool:
    return os.environ.get("SESSION_COOKIE_SECURE", "1") != "0"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERS
    )
    return f"{PBKDF2_ALGO}${PBKDF2_ITERS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = (stored or "").split("$")
        if algo != PBKDF2_ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            (password or "").encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iters),
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(digest.hex(), hash_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def register(email: str, password: str, db_path: DbPath = None) -> dict:
    email = _normalize_email(email)
    if not EMAIL_RE.match(email):
        raise AuthError("E-mail inválido.", 400)
    if len(password or "") < MIN_PASSWORD_LEN:
        raise AuthError(
            f"A senha deve ter ao menos {MIN_PASSWORD_LEN} caracteres.", 400
        )
    now = datetime.now(timezone.utc)
    trial_ends = now + timedelta(days=trial_days())
    conn = db_module.connect(db_path)
    try:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, created_at)"
                " VALUES (?, ?, ?)",
                (email, hash_password(password), now.isoformat(timespec="seconds")),
            )
        except sqlite3.IntegrityError:
            raise AuthError("Este e-mail já está cadastrado.", 409)
        user_id = cur.lastrowid
        conn.execute(
            "INSERT INTO subscriptions (user_id, status, trial_ends_at, updated_at)"
            " VALUES (?, 'trialing', ?, ?)",
            (
                user_id,
                trial_ends.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": user_id, "email": email}


def create_session(user_id: int, db_path: DbPath = None) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=session_days())
    conn = db_module.connect(db_path)
    try:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (
                _token_hash(token),
                user_id,
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def authenticate(email: str, password: str, db_path: DbPath = None) -> str:
    conn = db_module.connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?",
            (_normalize_email(email),),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not verify_password(password or "", row["password_hash"]):
        raise AuthError("E-mail ou senha inválidos.", 401)
    return create_session(row["id"], db_path)


def get_user_by_token(token: str, db_path: DbPath = None) -> Optional[dict]:
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    conn = db_module.connect(db_path)
    try:
        row = conn.execute(
            "SELECT u.id, u.email, u.created_at FROM sessions s"
            " JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ? AND s.expires_at > ?",
            (_token_hash(token), now),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"id": row["id"], "email": row["email"], "created_at": row["created_at"]}


def logout(token: str, db_path: DbPath = None) -> None:
    if not token:
        return
    conn = db_module.connect(db_path)
    try:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),)
        )
        conn.commit()
    finally:
        conn.close()


def extract_token(
    request: Request, authorization: Optional[str] = None
) -> Optional[str]:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    cookie = request.cookies.get(SESSION_COOKIE)
    return cookie or None


async def current_user(
    request: Request, authorization: Optional[str] = Header(default=None)
) -> dict:
    token = extract_token(request, authorization)
    user = get_user_by_token(token) if token else None
    if user is None:
        raise HTTPException(
            status_code=401, detail="Entre na sua conta para continuar."
        )
    return user
