import json
import logging
import os
import secrets
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

from fastapi import Depends, FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.core.ffmpeg_utils import get_ffmpeg_paths
from app.core.logging_config import setup_logging
from app.core.pdf_processor import inspect_pdf, render_thumbnail
from app.core.audio_processor import get_audio_info
from app.core.ai_synchronizer import synchronize_slides_with_gemini
from app.core.config_manager import get_gemini_api_key, set_gemini_api_key
from app.web.queue_manager import queue_manager
from app.web import auth as auth_module
from app.web import billing as billing_module
from app.web import stripe_billing
from app.web.rate_limit import enforce_rate_limit
from app.web.validation import (
    META_FILENAME,
    STORED_AUDIO_BASENAME,
    STORED_PDF_NAME,
    ValidationError,
    assert_pdf_signature,
    display_name,
    get_max_upload_bytes,
    parse_project_id,
    project_dir,
    validate_durations,
    validate_fps,
    validate_resolution,
    validate_upload_filename,
)

setup_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="SlideCast Web API",
    description="SaaS Web API para criação de vídeos a partir de PDF e Áudio com IA",
    version="1.0.0",
)

# Static and Templates
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
templates_dir = BASE_DIR / "templates"
templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))


def _admin_token_configured() -> str:
    return (os.environ.get("ADMIN_TOKEN") or "").strip()


if not _admin_token_configured():
    logger.warning(
        "ADMIN_TOKEN is not set: POST /api/config/key is unprotected. "
        "Set ADMIN_TOKEN in production to require the X-Admin-Token header."
    )


def _db_path() -> Path:
    """Lazy DB path so tests can relocate STORAGE_DIR per test."""
    return STORAGE_DIR / "slidecast.db"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth_module.SESSION_COOKIE,
        token,
        httponly=True,
        secure=auth_module.cookie_secure(),
        samesite="lax",
        max_age=auth_module.session_days() * 86400,
        path="/",
    )


def _owned_project(user_id: int, project_id: str) -> Path:
    proj_dir = _project_or_404(project_id)
    if not billing_module.owns(user_id, "project", proj_dir.name, _db_path()):
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return proj_dir


def _owned_job(user_id: int, job_id: str):
    job_id = _validate_job_id(job_id)
    if not billing_module.owns(user_id, "job", job_id, _db_path()):
        raise HTTPException(status_code=404, detail="Job não encontrado")
    job = queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return job


def _plan_or_403(user_id: int) -> dict:
    try:
        return billing_module.plan_guard(user_id, _db_path())
    except billing_module.BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _render_or_403(user_id: int) -> dict:
    try:
        return billing_module.render_guard(user_id, _db_path())
    except billing_module.BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


class AISyncRequest(BaseModel):
    api_key: Optional[str] = None


class RenderRequest(BaseModel):
    durations: List[float]
    resolution_w: int = 1920
    resolution_h: int = 1080
    fps: int = 30


def _require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    """Enforces the admin token when ADMIN_TOKEN is configured."""
    expected = _admin_token_configured()
    if not expected:
        return
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Token de administrador inválido.")


def _project_or_404(project_id: str) -> Path:
    try:
        proj_dir = project_dir(STORAGE_DIR, project_id)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not proj_dir.exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return proj_dir


def _read_meta(proj_dir: Path) -> dict:
    meta_path = proj_dir / META_FILENAME
    if not meta_path.exists():
        raise HTTPException(status_code=400, detail="Metadados do projeto ausentes.")
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Metadados do projeto inválidos: {exc}")


async def _save_upload_capped(upload: UploadFile, dest: Path, max_bytes: int) -> int:
    """Streams an upload to disk enforcing the size cap (HTTP 413 on exceed)."""
    total = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Arquivo excede o limite de {max_bytes // (1024 * 1024)} MB.",
                )
            f.write(chunk)
    return total


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    has_api_key = bool(get_gemini_api_key())
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"has_api_key": has_api_key},
    )


def _disk_free_mb(path: Path) -> int:
    """Free disk space in MB, or -1 when it cannot be determined."""
    try:
        return shutil.disk_usage(path).free // (1024 * 1024)
    except OSError:
        return -1


@app.get("/api/health")
async def health():
    ffmpeg_path, _ = get_ffmpeg_paths()
    free_mb = _disk_free_mb(STORAGE_DIR)
    try:
        min_disk_mb = int(os.environ.get("HEALTH_MIN_DISK_MB", "500"))
    except ValueError:
        min_disk_mb = 500

    reasons = []
    if not ffmpeg_path:
        reasons.append("ffmpeg not found")
    if free_mb >= 0 and free_mb < min_disk_mb:
        reasons.append(f"low disk space ({free_mb} MB free)")

    return {
        "status": "healthy" if not reasons else "degraded",
        "service": "slidecast-web",
        "ffmpeg": bool(ffmpeg_path),
        "disk_free_mb": free_mb,
        "pending_jobs": queue_manager.pending_count(),
        "reasons": reasons,
    }


@app.get("/api/config/key")
async def get_key_status():
    key = get_gemini_api_key()
    if key:
        masked = key[:4] + "..." + key[-4:] if len(key) > 8 else "***"
        return {"configured": True, "masked": masked}
    return {"configured": False, "masked": None}


@app.post("/api/config/key")
async def save_api_key(
    key: str = Form(...),
    x_admin_token: Optional[str] = Header(default=None),
):
    _require_admin(x_admin_token)
    if (os.environ.get("GEMINI_API_KEY") or "").strip():
        raise HTTPException(
            status_code=409,
            detail="Chave gerenciada pela variável de ambiente GEMINI_API_KEY; "
            "alteração via API desabilitada.",
        )
    key_clean = key.strip()
    if not key_clean:
        raise HTTPException(status_code=400, detail="Chave vazia não é aceita.")
    set_gemini_api_key(key_clean)
    return {"success": True, "configured": True}


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register", dependencies=[Depends(enforce_rate_limit)])
async def api_register(payload: RegisterRequest, response: Response):
    try:
        user = auth_module.register(payload.email, payload.password, _db_path())
    except auth_module.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    token = auth_module.create_session(user["id"], _db_path())
    _set_session_cookie(response, token)
    logger.info("register user=%s", user["email"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"]},
        "plan": billing_module.plan_status(user["id"], _db_path()),
    }


@app.post("/api/auth/login", dependencies=[Depends(enforce_rate_limit)])
async def api_login(payload: LoginRequest, response: Response):
    try:
        token = auth_module.authenticate(
            payload.email, payload.password, _db_path()
        )
    except auth_module.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    user = auth_module.get_user_by_token(token, _db_path())
    assert user is not None
    _set_session_cookie(response, token)
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"]},
        "plan": billing_module.plan_status(user["id"], _db_path()),
    }


@app.post("/api/auth/logout")
async def api_logout(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(default=None),
    user: dict = Depends(auth_module.current_user),
):
    auth_module.logout(
        auth_module.extract_token(request, authorization), _db_path()
    )
    response.delete_cookie(auth_module.SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
async def api_me(user: dict = Depends(auth_module.current_user)):
    return {
        "user": {"id": user["id"], "email": user["email"]},
        "plan": billing_module.plan_status(user["id"], _db_path()),
        "billing_configured": stripe_billing.is_configured(),
    }


@app.post("/api/billing/checkout")
async def api_checkout(user: dict = Depends(auth_module.current_user)):
    url = stripe_billing.create_checkout_session(
        user["id"], user["email"], _db_path()
    )
    return {"url": url}


@app.post("/api/billing/portal")
async def api_portal(user: dict = Depends(auth_module.current_user)):
    url = stripe_billing.create_portal_session(user["id"], _db_path())
    return {"url": url}


@app.post("/api/billing/webhook")
async def api_stripe_webhook(request: Request):
    payload = await request.body()
    event_type = stripe_billing.handle_webhook(
        payload, request.headers.get("stripe-signature")
    )
    return {"received": True, "type": event_type}


@app.post("/api/upload", dependencies=[Depends(enforce_rate_limit)])
async def upload_files(
    pdf_file: UploadFile = File(...),
    audio_file: UploadFile = File(...),
    user: dict = Depends(auth_module.current_user),
):
    _plan_or_403(user["id"])
    try:
        audio_ext = validate_upload_filename(audio_file.filename, "audio")
        validate_upload_filename(pdf_file.filename, "pdf")
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    max_bytes = get_max_upload_bytes()
    project_id = str(uuid.uuid4())
    proj_dir = STORAGE_DIR / "projects" / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    # Fixed on-disk names: user filenames are never used as paths.
    pdf_path = proj_dir / STORED_PDF_NAME
    audio_path = proj_dir / f"{STORED_AUDIO_BASENAME}{audio_ext}"

    try:
        try:
            await _save_upload_capped(pdf_file, pdf_path, max_bytes)
            await _save_upload_capped(audio_file, audio_path, max_bytes)
        finally:
            await pdf_file.close()
            await audio_file.close()

        try:
            assert_pdf_signature(pdf_path)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            pdf_info = inspect_pdf(str(pdf_path))
            audio_info = get_audio_info(str(audio_path))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Arquivo inválido: {exc}")

        meta = {
            "pdf_name": display_name(pdf_file.filename, "slides.pdf"),
            "audio_name": display_name(audio_file.filename, "audio"),
            "audio_ext": audio_ext,
            "page_count": pdf_info.page_count,
            "audio_duration": audio_info.duration,
        }
        (proj_dir / META_FILENAME).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(proj_dir, ignore_errors=True)
        raise

    logger.info(
        "upload project=%s pages=%d duration=%.1fs user=%d",
        project_id,
        pdf_info.page_count,
        audio_info.duration,
        user["id"],
    )
    billing_module.record_project(user["id"], project_id, _db_path())

    default_slide_duration = (
        audio_info.duration / pdf_info.page_count if pdf_info.page_count > 0 else 5.0
    )

    slides = []
    for i in range(pdf_info.page_count):
        slides.append(
            {
                "index": i,
                "slide_number": i + 1,
                "thumbnail_url": f"/api/projects/{project_id}/thumbnail/{i}",
                "duration": round(default_slide_duration, 1),
            }
        )

    return {
        "project_id": project_id,
        "pdf_name": meta["pdf_name"],
        "page_count": pdf_info.page_count,
        "audio_name": meta["audio_name"],
        "audio_duration": audio_info.duration,
        "formatted_audio_duration": audio_info.formatted_duration,
        "slides": slides,
    }


@app.get("/api/projects/{project_id}/thumbnail/{slide_index}")
async def get_slide_thumbnail(
    project_id: str,
    slide_index: int,
    user: dict = Depends(auth_module.current_user),
):
    proj_dir = _owned_project(user["id"], project_id)
    meta = _read_meta(proj_dir)

    if slide_index < 0 or slide_index >= meta["page_count"]:
        raise HTTPException(status_code=400, detail="Índice de slide fora do alcance.")

    pdf_path = proj_dir / STORED_PDF_NAME
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF não encontrado")

    # Thumbnails are immutable per project: render once, serve from disk after.
    thumbs_dir = proj_dir / "thumbs"
    thumbs_dir.mkdir(exist_ok=True)
    cached = thumbs_dir / f"thumb_{slide_index:04d}.png"
    if cached.exists():
        return FileResponse(str(cached), media_type="image/png")

    try:
        png_bytes = render_thumbnail(str(pdf_path), slide_index, max_dimension=280)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        cached.write_bytes(png_bytes)
    except OSError as exc:
        logger.warning("Could not cache thumbnail %s: %s", cached, exc)
    return Response(content=png_bytes, media_type="image/png")


@app.post("/api/projects/{project_id}/ai-sync", dependencies=[Depends(enforce_rate_limit)])
async def ai_sync(
    project_id: str,
    payload: AISyncRequest,
    user: dict = Depends(auth_module.current_user),
):
    _plan_or_403(user["id"])
    proj_dir = _owned_project(user["id"], project_id)
    meta = _read_meta(proj_dir)

    pdf_path = proj_dir / STORED_PDF_NAME
    audio_path = proj_dir / f"{STORED_AUDIO_BASENAME}{meta['audio_ext']}"
    if not pdf_path.exists() or not audio_path.exists():
        raise HTTPException(status_code=400, detail="Arquivos do projeto incompletos")

    try:
        audio_info = get_audio_info(str(audio_path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Áudio inválido: {exc}")

    api_key = (payload.api_key or "").strip() or get_gemini_api_key()

    try:
        durations = synchronize_slides_with_gemini(
            pdf_path=str(pdf_path),
            audio_path=str(audio_path),
            total_audio_duration=audio_info.duration,
            api_key=api_key,
        )
        return {"success": True, "durations": durations}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{project_id}/render", dependencies=[Depends(enforce_rate_limit)])
async def render_video(
    project_id: str,
    payload: RenderRequest,
    user: dict = Depends(auth_module.current_user),
):
    proj_dir = _owned_project(user["id"], project_id)
    _render_or_403(user["id"])
    meta = _read_meta(proj_dir)

    try:
        durations = validate_durations(payload.durations, meta["page_count"])
        resolution = validate_resolution(payload.resolution_w, payload.resolution_h)
        fps = validate_fps(payload.fps)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    pdf_path = proj_dir / STORED_PDF_NAME
    audio_path = proj_dir / f"{STORED_AUDIO_BASENAME}{meta['audio_ext']}"
    if not pdf_path.exists() or not audio_path.exists():
        raise HTTPException(status_code=400, detail="Arquivos do projeto incompletos")

    job = queue_manager.create_job(
        pdf_path=str(pdf_path),
        audio_path=str(audio_path),
        durations=durations,
        resolution=resolution,
        fps=fps,
        output_dir=proj_dir / "output",
    )
    billing_module.record_render(user["id"], job.id, _db_path())

    return {"job_id": job.id, "status": job.status}


def _validate_job_id(job_id: str) -> str:
    try:
        return parse_project_id(job_id)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _job_or_404(job_id: str):
    job = queue_manager.get_job(_validate_job_id(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return job


@app.get("/api/jobs/{job_id}")
async def get_job_status(
    job_id: str, user: dict = Depends(auth_module.current_user)
):
    job = _owned_job(user["id"], job_id)

    return {
        "id": job.id,
        "status": job.status,
        "progress": round(job.progress, 2),
        "message": job.message,
        "error": job.error,
        "has_video": bool(job.output_video_path and os.path.exists(job.output_video_path)),
        "download_url": f"/api/jobs/{job_id}/download" if job.status == "completed" else None,
        "video_url": f"/api/jobs/{job_id}/video" if job.status == "completed" else None,
    }


@app.delete("/api/jobs/{job_id}")
async def cancel_job(
    job_id: str, user: dict = Depends(auth_module.current_user)
):
    job_id = _validate_job_id(job_id)
    if not billing_module.owns(user["id"], "job", job_id, _db_path()):
        raise HTTPException(status_code=404, detail="Job não encontrado")
    status = queue_manager.cancel_job(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return {"id": job_id, "status": status}


@app.get("/api/jobs/{job_id}/video")
async def get_job_video(
    job_id: str, user: dict = Depends(auth_module.current_user)
):
    job = _owned_job(user["id"], job_id)
    if not job.output_video_path or not os.path.exists(job.output_video_path):
        raise HTTPException(status_code=404, detail="Vídeo não disponível")

    return FileResponse(job.output_video_path, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/download")
async def download_job_video(
    job_id: str, user: dict = Depends(auth_module.current_user)
):
    job = _owned_job(user["id"], job_id)
    if not job.output_video_path or not os.path.exists(job.output_video_path):
        raise HTTPException(status_code=404, detail="Vídeo não disponível para download")

    return FileResponse(
        job.output_video_path,
        media_type="video/mp4",
        filename="slidecast_video.mp4",
    )
