"""SQLite persistence for accounts, sessions, subscriptions, ownership, usage.

Single-file database under the storage dir (volume-mounted in production),
WAL mode so concurrent uvicorn workers can read while one writes. Connections
are short-lived per operation: open, run, commit, close.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

DB_FILENAME = "slidecast.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'trialing',
  trial_ends_at TEXT NOT NULL,
  current_period_end TEXT,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ownership (
  kind TEXT NOT NULL,
  object_id TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (kind, object_id)
);
CREATE TABLE IF NOT EXISTS usage (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  period TEXT NOT NULL,
  renders INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, period)
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sub_stripe ON subscriptions(stripe_subscription_id);
CREATE TABLE IF NOT EXISTS webhook_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  received_at TEXT NOT NULL
);
"""


MIGRATIONS = [
    (1, """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT 'Sem título', kind TEXT NOT NULL DEFAULT 'video',
  revision INTEGER NOT NULL DEFAULT 1, data TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL, kind TEXT NOT NULL, filename TEXT NOT NULL,
  stored_name TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS durable_jobs (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, project_id TEXT,
  kind TEXT NOT NULL DEFAULT 'render', idempotency_key TEXT,
  status TEXT NOT NULL DEFAULT 'aguardando', progress REAL NOT NULL DEFAULT 0,
  stage TEXT NOT NULL DEFAULT '', params TEXT NOT NULL DEFAULT '{}',
  output_path TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idem ON durable_jobs(user_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, project_id TEXT,
  job_id TEXT, format TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}',
  output_path TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS preferences (
  user_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS automations (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
  trigger TEXT NOT NULL, actions TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON durable_jobs(user_id, status);
"""),
]

JOB_STATUSES = ("aguardando", "processando", "concluido", "falhou", "cancelando", "cancelado")
_LEGACY_TO_PT = {"queued": "aguardando", "rendering": "processando",
                 "completed": "concluido", "failed": "falhou", "cancelled": "cancelado"}


def normalize_job_status(status: str) -> str:
    return _LEGACY_TO_PT.get(status, status if status in JOB_STATUSES else "falhou")


def apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                 "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    for version, sql in MIGRATIONS:
        if version not in done:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations VALUES (?,?)",
                         (version, utcnow_iso()))
    conn.commit()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def default_db_path() -> Path:
    override = (os.environ.get("SLIDECAST_DB_PATH") or "").strip()
    if override:
        return Path(override)
    # Local import: app.web.server imports this module at startup.
    from app.web import server as server_module

    return server_module.STORAGE_DIR / DB_FILENAME


def connect(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    apply_migrations(conn)
    return conn
