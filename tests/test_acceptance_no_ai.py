"""Aceitação determinística sem IA: PDF 3 slides + áudio 60s -> MP4.

Amostras geradas em código (sine 220Hz, slides sólidos) — sem rede, sem chave.
"""
import math, struct, subprocess, wave, io
import pymupdf, pytest
from fastapi.testclient import TestClient
import app.web.server as server_module
from app.core.slide_timing import uniform_durations, weighted_durations
from app.core.subtitles import parse_subtitles, export_subtitles

def make_pdf(pages=3):
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page(width=640, height=360)
        p.draw_rect(pymupdf.Rect(0,0,640,360), fill=(0.2*i, 0.3, 0.7))
        p.insert_text((40, 60), f"Slide {i+1} Acentuação", fontsize=24, color=(1,1,1))
    b = doc.tobytes(); doc.close(); return b

def make_wav(seconds=60.0, rate=22050):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        for i in range(int(seconds*rate)):
            w.writeframes(struct.pack("<h", int(6000*math.sin(2*math.pi*220*i/rate))))
    return buf.getvalue()

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "STORAGE_DIR", tmp_path/"storage")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(server_module.app) as c: yield c

def auth(c, email):
    r = c.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}

def test_timings_uniforme_pesos_travas():
    assert uniform_durations(3, 60.0) == [20.0, 20.0, 20.0]
    assert weighted_durations([1,2,3], 60.0) == [10.0, 20.0, 30.0]
    out = weighted_durations([1,1,1], 60.0, locked={0: 15.0})
    assert out[0] == 15.0 and abs(sum(out)-60.0) < 1e-6
    with pytest.raises(ValueError):
        weighted_durations([1,1], 0.9)  # insuficiente p/ mínimo 0.5x2

def test_subtitles_acentos_roundtrip():
    srt = "1\n00:00:00,000 --> 00:00:05,000\nOlá, acentuação: çãõ é vídeo!\n\n2\n00:00:05,000 --> 00:00:10,000\nSegundo trecho — São Paulo\n"
    cues = parse_subtitles(srt, "srt")
    assert "acentuação" in cues[0].text
    out = export_subtitles(cues, "vtt")
    assert "WEBVTT" in out and "São Paulo" in out

def test_render_60s_isolamento_cancelamento(client):
    h1, h2 = auth(client, "a@example.com"), auth(client, "b@example.com")
    up = client.post("/api/upload", files={"pdf_file": ("s.pdf", make_pdf(), "application/pdf"), "audio_file": ("a.wav", make_wav(), "audio/wav")}, headers=h1)
    assert up.status_code == 200, up.text
    pid = up.json()["project_id"]; assert abs(up.json()["audio_duration"]-60.0) < 0.5
    # isolamento: outro usuário não vê projeto/job alheio
    assert client.get(f"/api/projects/{pid}", headers=h2).status_code == 404
    r = client.post(f"/api/projects/{pid}/render", json={"durations": [20.0,20.0,20.0], "resolution_w": 320, "resolution_h": 180, "fps": 5}, headers=h1)
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    assert client.get(f"/api/jobs/{jid}", headers=h2).status_code == 404
    for _ in range(120):
        st = client.get(f"/api/jobs/{jid}", headers=h1).json()
        if st["status"] in ("completed","failed","cancelled"): break
        import time; time.sleep(1)
    assert st["status"] == "completed", st
    vid = client.get(f"/api/jobs/{jid}/video", headers=h1)
    assert vid.status_code == 200 and len(vid.content) > 10000
    dur = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0","/dev/stdin"], input=vid.content, capture_output=True).stdout or b"0")
    assert 55.0 <= dur <= 65.0, dur

def test_cancelamento_sem_duplicar(client):
    h = auth(client, "d@example.com")
    up = client.post("/api/upload", files={"pdf_file": ("s.pdf", make_pdf(), "application/pdf"), "audio_file": ("a.wav", make_wav(10), "audio/wav")}, headers=h)
    pid = up.json()["project_id"]
    r = client.post(f"/api/projects/{pid}/render", json={"durations": [4.0,3.0,3.0], "resolution_w": 320, "resolution_h": 180, "fps": 5}, headers=h)
    jid = r.json()["job_id"]
    d1 = client.delete(f"/api/jobs/{jid}", headers=h)
    assert d1.status_code == 200, d1.text
    jobs = client.get("/api/jobs", headers=h).json()["jobs"]
    assert len([j for j in jobs if j.get("job_id") == jid or j.get("id") == jid]) == 1

def test_apostila_longa_sem_perder_texto(client):
    h = auth(client, "c@example.com")
    texto = ("Apostila — lição com acentos: coração, vídeo, São Paulo. " * 800)
    r = client.post("/api/projects", json={"name": "Apostila", "kind": "material", "data": {"apostila": texto}}, headers=h)
    assert r.status_code in (200,201), r.text
    pid = r.json().get("id") or r.json().get("project_id")
    got = client.get(f"/api/projects/{pid}", headers=h).json()
    import json as _json
    data = got.get("data") or "{}"
    blob = _json.loads(data).get("apostila", "") if isinstance(data, str) else data.get("apostila", "")
    assert blob == texto
