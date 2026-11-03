import pytest
from app import services
from app.core.subtitles import parse_subtitles
from app.core.media_specs import resolve_preset
from app.web import db as dbmod

@pytest.fixture()
def db(tmp_path):
    return tmp_path / "t.db"

def _user(db):
    with dbmod.connect(db) as c:
        c.execute("INSERT INTO users(email,password_hash,created_at) VALUES('a@b.c','x','2026-01-01')")
        c.commit()
        return c.execute("SELECT id FROM users").fetchone()[0]

def test_project_crud_duplicate_versioning_isolation(db):
    uid, other = _user(db), _user(db) if False else None
    with dbmod.connect(db) as c:
        c.execute("INSERT INTO users(email,password_hash,created_at) VALUES('o@b.c','x','2026-01-01')")
        c.commit(); other = c.execute("SELECT id FROM users WHERE email='o@b.c'").fetchone()[0]
    p = services.create_project(uid, "Aula", path=db)
    assert services.get_project(other, p["id"], db) is None
    dup = services.duplicate_project(uid, p["id"], db)
    assert dup["name"].endswith("(cópia)")
    services.update_project(uid, p["id"], data={"page_count": 3}, revision=1, path=db)
    with pytest.raises(ValueError):
        services.update_project(uid, p["id"], data={}, revision=1, path=db)
    assert services.delete_project(uid, p["id"], db)

def test_timings_subtitles_preferences_automations(db):
    uid = _user(db)
    p = services.create_project(uid, "A", data={"page_count": 3}, path=db)
    assert services.compute_timings(uid, p["id"], "uniforme", 60.0, path=db) == [20.0, 20.0, 20.0]
    cues = services.set_subtitles(uid, p["id"], "1\n00:00:00,000 --> 00:00:02,500\nOlá, ação!\n", "srt", db)
    assert cues[0].text == "Olá, ação!"
    assert "00:00:00.000 --> 00:00:02.500" in services.get_subtitles_export(uid, p["id"], "vtt", db)
    services.set_preference(uid, "preset", "1080p", db)
    assert services.get_preferences(uid, db) == {"preset": "1080p"}

def test_durable_job_idempotency_and_status_pt(db):
    uid = _user(db)
    a = services.record_job(uid, "job-1", None, {}, idempotency_key="k1", path=db)
    b = services.record_job(uid, "job-2", None, {}, idempotency_key="k1", path=db)
    assert a["id"] == b["id"] == "job-1"
    services.update_job(uid, "job-1", status="rendering", progress=0.5, stage="slides", path=db)
    assert services.get_job(uid, "job-1", db)["status"] == "processando"
    assert services.get_job(999, "job-1", db) is None

def test_find_job_by_idempotency_is_user_scoped(db):
    uid = _user(db)
    services.record_job(uid, "job-1", None, {}, idempotency_key="k1", path=db)
    assert services.find_job_by_idempotency(uid, "k1", db)["id"] == "job-1"
    assert services.find_job_by_idempotency(999, "k1", db) is None
    assert services.find_job_by_idempotency(uid, None, db) is None

def test_subtitle_validation_and_preset_gate():
    with pytest.raises(ValueError):
        parse_subtitles("1\n00:00:02,000 --> 00:00:01,000\nx\n")
    assert resolve_preset("vertical") == (1080, 1920)
    with pytest.raises(ValueError): resolve_preset("4k")
    assert resolve_preset("4k", allow_4k=True) == (3840, 2160)

def test_migrations_idempotent(db):
    dbmod.connect(db).close(); dbmod.connect(db).close()
    with dbmod.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
