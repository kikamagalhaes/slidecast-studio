"""Shared recording-studio core for SlideCast Web and Desktop.

Pure Python (no PySide6, no FastAPI): both platforms import this module so
scene state, multi-PDF handling, annotations and project files behave the
same everywhere. Media rendering itself stays in platform adapters
(FFmpeg builders on desktop/server, canvas capture on web).
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

SCHEMA_VERSION = 1
MAX_PDF_SLOTS = 3
TEMP_PEN_TTLS = (3, 5, 8)
DEFAULT_TEMP_TTL = 5
SCENES = ("camera", "slide", "pip", "bible", "whiteboard",
          "brainstorm", "quiz", "screen", "title")
PIP_POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left")
PIP_SIZES = ("small", "medium", "large")


def new_studio_state() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "scene": "slide",
        "previous_scene": "slide",
        "pip": {"position": "bottom-right", "size": "medium", "visible": True},
        "pdfs": [
            {"slot": i + 1, "title": f"PDF {i + 1}", "file": None,
             "page": 0, "page_count": 0}
            for i in range(MAX_PDF_SLOTS)
        ],
        "active_pdf": 1,
        "teleprompter": {"text": "", "font_size": 28, "speed": 30,
                         "playing": False, "show_in_recording": False},
        "timer": {"mode": "up", "seconds": 0, "show_in_recording": False},
        "annotations": [],  # strokes, see add_stroke()
        "temp_ttl": DEFAULT_TEMP_TTL,
        "bible": {"version": "Texto fornecido pela usuária",
                  "reference": "", "text": ""},
        "whiteboard": {"strokes": [], "background": "#ffffff"},
        "brainstorm": {"title": "Brainstorm", "cards": []},
        "quiz": {"question": "", "options": [], "correct": 0, "revealed": False},
        "scene_timeline": [],  # [{at, scene, pdf_slot, page}]
        "resources": [],
    }


def normalize_state(raw) -> dict:
    """Fill defaults and clamp values; never raises on partial input."""
    state = new_studio_state()
    if not isinstance(raw, dict):
        return state
    for key, value in raw.items():
        if key in state:
            state[key] = value
    if state.get("scene") not in SCENES:
        state["scene"] = "slide"
    pip = state.get("pip") or {}
    if pip.get("position") not in PIP_POSITIONS:
        pip["position"] = "bottom-right"
    if pip.get("size") not in PIP_SIZES:
        pip["size"] = "medium"
    pip["visible"] = bool(pip.get("visible", True))
    state["pip"] = pip
    pdfs = []
    for i in range(MAX_PDF_SLOTS):
        src = {}
        if isinstance(state.get("pdfs"), list) and i < len(state["pdfs"]):
            src = state["pdfs"][i] or {}
        pdfs.append({
            "slot": i + 1,
            "title": str(src.get("title") or f"PDF {i + 1}")[:80],
            "file": src.get("file"),
            "page": max(0, int(src.get("page") or 0)),
            "page_count": max(0, int(src.get("page_count") or 0)),
        })
    state["pdfs"] = pdfs
    state["active_pdf"] = min(MAX_PDF_SLOTS, max(1, int(state.get("active_pdf") or 1)))
    if state.get("temp_ttl") not in TEMP_PEN_TTLS:
        state["temp_ttl"] = DEFAULT_TEMP_TTL
    state["schema_version"] = SCHEMA_VERSION
    return state


# --- multi-PDF slots -------------------------------------------------------
def set_pdf(state: dict, slot: int, file_ref, page_count: int, title=None) -> dict:
    state = normalize_state(state)
    if not 1 <= int(slot) <= MAX_PDF_SLOTS:
        raise ValueError("Slot de PDF deve ser 1, 2 ou 3.")
    pdf = state["pdfs"][int(slot) - 1]
    pdf.update({"file": file_ref, "page_count": int(page_count), "page": 0})
    if title:
        pdf["title"] = str(title)[:80]
    state["active_pdf"] = int(slot)
    return state


def switch_pdf(state: dict, slot: int) -> dict:
    """Switch active PDF; each slot keeps its own current page."""
    state = normalize_state(state)
    if not 1 <= int(slot) <= MAX_PDF_SLOTS:
        raise ValueError("Slot de PDF deve ser 1, 2 ou 3.")
    state["active_pdf"] = int(slot)
    return state


def set_pdf_page(state: dict, page: int, slot=None) -> dict:
    state = normalize_state(state)
    pdf = state["pdfs"][(int(slot or state["active_pdf"])) - 1]
    top = max(0, pdf["page_count"] - 1)
    pdf["page"] = min(top, max(0, int(page)))
    return state


# --- scenes / timeline ------------------------------------------------------
def set_scene(state: dict, scene: str, at: float | None = None) -> dict:
    if scene not in SCENES:
        raise ValueError(f"Cena desconhecida: {scene}")
    state = normalize_state(state)
    state["previous_scene"] = state["scene"]
    state["scene"] = scene
    if at is not None:
        pdf = state["pdfs"][state["active_pdf"] - 1]
        state["scene_timeline"].append({
            "at": round(float(at), 3), "scene": scene,
            "pdf_slot": state["active_pdf"], "page": pdf["page"],
            "bible": copy.deepcopy(state["bible"]),
            "quiz": copy.deepcopy(state["quiz"]),
            "brainstorm": copy.deepcopy(state["brainstorm"]),
        })
    return state


def scene_at(state: dict, when: float) -> dict | None:
    events = sorted(normalize_state(state)["scene_timeline"],
                    key=lambda e: e["at"])
    current = None
    for event in events:
        if event["at"] <= when:
            current = event
    return current


# --- annotations: permanent + temporary pen --------------------------------
def add_stroke(state: dict, points, kind="temp", color="#e11d48",
               width=4, now=None, pdf_slot=None, page=None) -> dict:
    if kind not in ("perm", "temp", "highlight"):
        raise ValueError("Tipo de traço deve ser perm, temp ou highlight.")
    state = normalize_state(state)
    pdf = state["pdfs"][state["active_pdf"] - 1]
    state["annotations"].append({
        "id": f"{int(time.time() * 1000)}-{len(state['annotations'])}",
        "kind": kind, "color": color, "width": int(width),
        "points": [[float(x), float(y)] for x, y in points],
        "created_at": float(now if now is not None else time.time()),
        "ttl": state["temp_ttl"] if kind == "temp" else None,
        "pdf_slot": int(pdf_slot or state["active_pdf"]),
        "page": int(page if page is not None else pdf["page"]),
    })
    return state


def visible_strokes(state: dict, now=None, pdf_slot=None, page=None):
    """Temp strokes vanish after their TTL; they never touch the PDF file."""
    state = normalize_state(state)
    now = float(now if now is not None else time.time())
    pdf = state["pdfs"][state["active_pdf"] - 1]
    slot = int(pdf_slot or state["active_pdf"])
    pg = int(page if page is not None else pdf["page"])
    out = []
    for s in state["annotations"]:
        if s["pdf_slot"] != slot or s["page"] != pg:
            continue
        if s["kind"] == "temp" and now - s["created_at"] > float(s["ttl"] or DEFAULT_TEMP_TTL):
            continue
        out.append(s)
    return out


def prune_expired(state: dict, now=None) -> dict:
    state = normalize_state(state)
    now = float(now if now is not None else time.time())
    state["annotations"] = [
        s for s in state["annotations"]
        if s["kind"] != "temp"
        or now - s["created_at"] <= float(s["ttl"] or DEFAULT_TEMP_TTL)]
    return state


def undo_stroke(state: dict, pdf_slot=None, page=None) -> dict:
    state = normalize_state(state)
    pdf = state["pdfs"][state["active_pdf"] - 1]
    slot = int(pdf_slot or state["active_pdf"])
    pg = int(page if page is not None else pdf["page"])
    for i in range(len(state["annotations"]) - 1, -1, -1):
        s = state["annotations"][i]
        if s["pdf_slot"] == slot and s["page"] == pg:
            del state["annotations"][i]
            break
    return state


def clear_strokes(state: dict, pdf_slot=None, page=None) -> dict:
    state = normalize_state(state)
    pdf = state["pdfs"][state["active_pdf"] - 1]
    slot = int(pdf_slot or state["active_pdf"])
    pg = int(page if page is not None else pdf["page"])
    state["annotations"] = [
        s for s in state["annotations"]
        if not (s["pdf_slot"] == slot and s["page"] == pg)]
    return state


# --- teaching resources -----------------------------------------------------
def validate_quiz(quiz: dict) -> dict:
    q = {"question": str((quiz or {}).get("question") or "").strip(),
         "options": [str(o).strip() for o in (quiz or {}).get("options", []) if str(o).strip()],
         "correct": int((quiz or {}).get("correct") or 0),
         "revealed": bool((quiz or {}).get("revealed"))}
    if len(q["options"]) < 2:
        raise ValueError("Quiz precisa de ao menos 2 alternativas.")
    q["correct"] = min(len(q["options"]) - 1, max(0, q["correct"]))
    return q


def teleprompter_sections(text: str) -> list[dict]:
    """Split script on [Slide N] / [Cena: nome] markers (manual, no AI)."""
    import re
    parts, current = [], {"marker": "Início", "text": ""}
    for line in (text or "").splitlines():
        m = re.match(r"\s*\[(Slide\s+\d+|Cena:[^\]]+)\]\s*(.*)", line, re.I)
        if m:
            if current["text"].strip() or parts:
                parts.append(current)
            current = {"marker": m.group(1).strip(), "text": m.group(2)}
        else:
            current["text"] += ("\n" if current["text"] else "") + line
    if current["text"].strip() or not parts:
        parts.append(current)
    return parts


def format_bible_card(bible: dict) -> str:
    ref = str((bible or {}).get("reference") or "").strip()
    txt = str((bible or {}).get("text") or "").strip()
    return f"{ref}\n\n{txt}" if ref else txt


# --- project file (portable between web and desktop) -----------------------
def export_project(state: dict, name="Aula") -> dict:
    return {"schema_version": SCHEMA_VERSION, "kind": "slidecast-studio",
            "name": name, "studio": normalize_state(state),
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def import_project(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("kind") != "slidecast-studio":
        raise ValueError("Arquivo não é um projeto SlideCast Studio.")
    version = int(payload.get("schema_version") or 0)
    if version > SCHEMA_VERSION:
        raise ValueError("Projeto de versão mais nova que este aplicativo.")
    return normalize_state(payload.get("studio"))


def missing_media(state: dict, base_dir) -> list[str]:
    """Local desktop paths may not exist on web (and vice versa)."""
    base = Path(base_dir)
    missing = []
    for pdf in normalize_state(state)["pdfs"]:
        ref = pdf.get("file")
        if ref and not (base / str(ref)).exists() and not Path(str(ref)).exists():
            missing.append(str(ref))
    return missing


def render_scene_card_png(kind: str, payload: dict, out_path,
                          width=1920, height=1080) -> str:
    """Render bible/quiz/brainstorm/title cards as PNG via PyMuPDF.

    Used by the desktop exporter (and server renders) so didactic scenes
    recorded in the timeline appear in the final MP4 as real frames.
    """
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(pymupdf.Rect(0, 0, width, height),
                   fill=(0.98, 0.99, 1.0), color=None)
    def text_box(rect, text, size=44, bold=False, color=(0.08, 0.12, 0.25)):
        page.insert_textbox(pymupdf.Rect(*rect), text,
                            fontsize=size, color=color,
                            fontname="hebo" if bold else "helv")
    if kind == "bible":
        text_box((90, 70, width - 90, 180), payload.get("reference", "Bíblia"), 54, True)
        text_box((90, 200, width - 90, height - 90), payload.get("text", ""), 42)
        text_box((90, height - 80, width - 90, height - 30),
                 payload.get("version", ""), 24, False, (0.4, 0.45, 0.55))
    elif kind == "quiz":
        text_box((90, 70, width - 90, 260), payload.get("question", "Quiz"), 50, True)
        y = 300
        for i, opt in enumerate(payload.get("options", [])):
            mark = " ✓" if payload.get("revealed") and i == payload.get("correct") else ""
            text_box((120, y, width - 120, y + 90), f"{i + 1}. {opt}{mark}", 40)
            y += 110
    elif kind == "brainstorm":
        text_box((90, 60, width - 90, 170), payload.get("title", "Brainstorm"), 52, True)
        y = 210
        for card in payload.get("cards", []):
            text_box((120, y, width - 120, y + 80), f"• {card}", 38)
            y += 95
    else:  # title / opening / closing
        text_box((90, height // 2 - 120, width - 90, height // 2 + 120),
                 payload.get("text", "SlideCast Studio"), 64, True)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(1, 1))
    pix.save(str(out_path))
    doc.close()
    return str(out_path)


def project_to_json(state: dict, name="Aula") -> str:
    return json.dumps(export_project(state, name), ensure_ascii=False, indent=2)
