"""Application services shared by the web UI and deterministic automations.

Single implementation of project/preference/job/export rules; routes and
automations must call these instead of duplicating logic. Ownership is
always checked by ``user_id`` — IDs alone never authorize access.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from app.core.slide_timing import calculate_slide_durations_from_script, uniform_durations
from app.core.subtitles import Cue, export_subtitles, parse_subtitles
from app.web import db as db_module


def _conn(path):
    return db_module.connect(path)


def _row(r) -> Optional[dict]:
    return dict(r) if r else None


# --- projects -------------------------------------------------------------
def create_project(user_id, name="Sem título", kind="video", data=None, path=None, pid=None):
    pid = pid or str(uuid.uuid4())
    now = db_module.utcnow_iso()
    with _conn(path) as c:
        c.execute("INSERT INTO projects(id,user_id,name,kind,data,created_at,updated_at)"
                  " VALUES (?,?,?,?,?,?,?)",
                  (pid, user_id, name, kind, json.dumps(data or {}), now, now))
        c.commit()
    return get_project(user_id, pid, path)


def get_project(user_id, pid, path=None):
    with _conn(path) as c:
        return _row(c.execute("SELECT * FROM projects WHERE id=? AND user_id=?",
                              (pid, user_id)).fetchone())


def list_projects(user_id, path=None):
    with _conn(path) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM projects WHERE user_id=? ORDER BY updated_at DESC", (user_id,))]


def update_project(user_id, pid, name=None, data=None, revision=None, path=None):
    """Optimistic versioning: stale revision -> ValueError (no silent overwrite)."""
    cur = get_project(user_id, pid, path)
    if not cur:
        return None
    if revision is not None and int(revision) != cur["revision"]:
        raise ValueError("Versão desatualizada: recarregue o projeto antes de salvar.")
    merged = json.loads(cur["data"] or "{}")
    if data:
        merged.update(data)
    with _conn(path) as c:
        c.execute("UPDATE projects SET name=?, data=?, revision=revision+1, updated_at=? "
                  "WHERE id=? AND user_id=?",
                  (name or cur["name"], json.dumps(merged),
                   db_module.utcnow_iso(), pid, user_id))
        c.commit()
    return get_project(user_id, pid, path)


def duplicate_project(user_id, pid, path=None):
    src = get_project(user_id, pid, path)
    if not src:
        return None
    return create_project(user_id, f"{src['name']} (cópia)", src["kind"],
                          json.loads(src["data"] or "{}"), path)


def delete_project(user_id, pid, path=None) -> bool:
    with _conn(path) as c:
        cur = c.execute("DELETE FROM projects WHERE id=? AND user_id=?", (pid, user_id))
        c.commit()
        return cur.rowcount > 0


# --- timings / scripts / subtitles (stored inside project data) -----------
def compute_timings(user_id, pid, mode, total, script="", locked=None, path=None):
    proj = get_project(user_id, pid, path)
    if not proj:
        return None
    data = json.loads(proj["data"] or "{}")
    count = int(data.get("page_count") or len(data.get("slides") or []) or 1)
    if mode == "uniforme":
        durations = uniform_durations(count, float(total))
    else:  # roteiro: markers/paragraphs/weights with locks
        durations = calculate_slide_durations_from_script(
            script, count, float(total),
            locked={int(k): float(v) for k, v in (locked or {}).items()})
    update_project(user_id, pid, data={"timings": durations, "timing_mode": mode,
                                       "script": script}, path=path)
    return durations


def set_subtitles(user_id, pid, content, fmt="srt", path=None):
    cues = parse_subtitles(content, fmt)
    if get_project(user_id, pid, path) is None:
        return None
    update_project(user_id, pid, data={"subtitles": [vars(c) for c in cues]}, path=path)
    return cues


def get_subtitles_export(user_id, pid, fmt="srt", path=None):
    proj = get_project(user_id, pid, path)
    if not proj:
        return None
    cues = [Cue(**c) for c in json.loads(proj["data"] or "{}").get("subtitles", [])]
    return export_subtitles(cues, fmt)


# --- preferences / automations -------------------------------------------
def set_preference(user_id, key, value, path=None):
    with _conn(path) as c:
        c.execute("INSERT INTO preferences VALUES (?,?,?) ON CONFLICT(user_id,key) "
                  "DO UPDATE SET value=excluded.value",
                  (user_id, key, json.dumps(value)))
        c.commit()


def get_preferences(user_id, path=None) -> dict:
    with _conn(path) as c:
        return {r["key"]: json.loads(r["value"]) for r in c.execute(
            "SELECT * FROM preferences WHERE user_id=?", (user_id,))}


def apply_automations(user_id, trigger, context: dict, path=None) -> dict:
    """Deterministic rules: same inputs -> same merged defaults out."""
    out = dict(context)
    with _conn(path) as c:
        rows = c.execute("SELECT * FROM automations WHERE user_id=? AND trigger=? "
                         "AND enabled=1", (user_id, trigger)).fetchall()
    for r in rows:
        out.update(json.loads(r["actions"] or "{}"))
    return out


# --- durable jobs / exports ------------------------------------------------
def record_job(user_id, job_id, project_id, params, status="aguardando",
               idempotency_key=None, path=None):
    """Idempotent: same (user, idempotency_key) returns the existing job."""
    if idempotency_key:
        with _conn(path) as c:
            hit = c.execute("SELECT * FROM durable_jobs WHERE user_id=? AND "
                            "idempotency_key=?", (user_id, idempotency_key)).fetchone()
        if hit:
            return dict(hit)
    now = db_module.utcnow_iso()
    with _conn(path) as c:
        c.execute("INSERT OR IGNORE INTO durable_jobs"
                  "(id,user_id,project_id,kind,idempotency_key,status,params,created_at,updated_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?)",
                  (job_id, user_id, project_id, "render", idempotency_key,
                   db_module.normalize_job_status(status), json.dumps(params), now, now))
        c.commit()
        return _row(c.execute("SELECT * FROM durable_jobs WHERE id=?", (job_id,)).fetchone())


def find_job_by_idempotency(user_id, idempotency_key, path=None):
    if not idempotency_key:
        return None
    with _conn(path) as c:
        return _row(c.execute("SELECT * FROM durable_jobs WHERE user_id=? AND "
                              "idempotency_key=?", (user_id, idempotency_key)).fetchone())


def update_job(user_id, job_id, path=None, **fields):
    allowed = {"status", "progress", "stage", "output_path", "error"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "status" in sets:
        sets["status"] = db_module.normalize_job_status(sets["status"])
    if not sets:
        return get_job(user_id, job_id, path)
    sets["updated_at"] = db_module.utcnow_iso()
    sql = ", ".join(f"{k}=?" for k in sets)
    with _conn(path) as c:
        c.execute(f"UPDATE durable_jobs SET {sql} WHERE id=? AND user_id=?",
                  (*sets.values(), job_id, user_id))
        c.commit()
    return get_job(user_id, job_id, path)


def get_job(user_id, job_id, path=None):
    with _conn(path) as c:
        return _row(c.execute("SELECT * FROM durable_jobs WHERE id=? AND user_id=?",
                              (job_id, user_id)).fetchone())


def list_jobs(user_id, path=None):
    with _conn(path) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM durable_jobs WHERE user_id=? ORDER BY created_at DESC", (user_id,))]


def record_export(user_id, project_id, job_id, fmt, params, output_path, path=None):
    eid = str(uuid.uuid4())
    with _conn(path) as c:
        c.execute("INSERT INTO exports VALUES (?,?,?,?,?,?,?,?)",
                  (eid, user_id, project_id, job_id, fmt, json.dumps(params),
                   output_path, db_module.utcnow_iso()))
        c.commit()
    return eid


def list_exports(user_id, path=None):
    with _conn(path) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM exports WHERE user_id=? ORDER BY created_at DESC", (user_id,))]
