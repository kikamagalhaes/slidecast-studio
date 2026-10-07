import os
import shutil
import uuid
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.core.pdf_processor import inspect_pdf, render_thumbnail, PresentationInfo
from app.core.audio_processor import get_audio_info, AudioInfo
from app.core.ai_synchronizer import synchronize_slides_with_gemini
from app.core.config_manager import get_gemini_api_key, set_gemini_api_key
from app.web.queue_manager import queue_manager

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


class AISyncRequest(BaseModel):
    api_key: Optional[str] = None


class RenderRequest(BaseModel):
    durations: List[float]
    resolution_w: int = 1920
    resolution_h: int = 1080
    fps: int = 30


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    has_api_key = bool(get_gemini_api_key())
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"has_api_key": has_api_key},
    )


@app.get("/api/health")
async def health():
    return {"status": "healthy", "service": "slidecast-web"}


@app.get("/api/config/key")
async def get_key_status():
    key = get_gemini_api_key()
    if key:
        masked = key[:4] + "..." + key[-4:] if len(key) > 8 else "***"
        return {"configured": True, "masked": masked}
    return {"configured": False, "masked": None}


@app.post("/api/config/key")
async def save_api_key(key: str = Form(...)):
    key_clean = key.strip()
    set_gemini_api_key(key_clean)
    return {"success": True, "configured": bool(key_clean)}


@app.post("/api/upload")
async def upload_files(
    pdf_file: UploadFile = File(...),
    audio_file: UploadFile = File(...),
):
    project_id = str(uuid.uuid4())
    proj_dir = STORAGE_DIR / "projects" / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = proj_dir / pdf_file.filename
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(pdf_file.file, f)

    audio_path = proj_dir / audio_file.filename
    with open(audio_path, "wb") as f:
        shutil.copyfileobj(audio_file.file, f)

    try:
        pdf_info = inspect_pdf(str(pdf_path))
        audio_info = get_audio_info(str(audio_path))
    except Exception as e:
        shutil.rmtree(proj_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e))

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
        "pdf_name": pdf_info.file_name,
        "page_count": pdf_info.page_count,
        "audio_name": audio_info.file_name,
        "audio_duration": audio_info.duration,
        "formatted_audio_duration": audio_info.formatted_duration,
        "slides": slides,
    }


@app.get("/api/projects/{project_id}/thumbnail/{slide_index}")
async def get_slide_thumbnail(project_id: str, slide_index: int):
    proj_dir = STORAGE_DIR / "projects" / project_id
    if not proj_dir.exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    pdf_files = list(proj_dir.glob("*.pdf"))
    if not pdf_files:
        raise HTTPException(status_code=404, detail="PDF não encontrado")

    try:
        png_bytes = render_thumbnail(str(pdf_files[0]), slide_index, max_dimension=280)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/projects/{project_id}/ai-sync")
async def ai_sync(project_id: str, payload: AISyncRequest):
    proj_dir = STORAGE_DIR / "projects" / project_id
    if not proj_dir.exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    pdf_files = list(proj_dir.glob("*.pdf"))
    if not pdf_files:
        raise HTTPException(status_code=404, detail="PDF não encontrado")

    # Find audio
    audio_extensions = [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"]
    audio_files = [f for f in proj_dir.iterdir() if f.suffix.lower() in audio_extensions]
    if not audio_files:
        raise HTTPException(status_code=404, detail="Arquivo de áudio não encontrado")

    audio_info = get_audio_info(str(audio_files[0]))
    api_key = payload.api_key or get_gemini_api_key()

    try:
        durations = synchronize_slides_with_gemini(
            pdf_path=str(pdf_files[0]),
            audio_path=str(audio_files[0]),
            total_audio_duration=audio_info.duration,
            api_key=api_key,
        )
        return {"success": True, "durations": durations}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/projects/{project_id}/render")
async def render_video(project_id: str, payload: RenderRequest):
    proj_dir = STORAGE_DIR / "projects" / project_id
    if not proj_dir.exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    pdf_files = list(proj_dir.glob("*.pdf"))
    audio_extensions = [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"]
    audio_files = [f for f in proj_dir.iterdir() if f.suffix.lower() in audio_extensions]

    if not pdf_files or not audio_files:
        raise HTTPException(status_code=400, detail="Arquivos do projeto incompletos")

    job = queue_manager.create_job(
        pdf_path=str(pdf_files[0]),
        audio_path=str(audio_files[0]),
        durations=payload.durations,
        resolution=(payload.resolution_w, payload.resolution_h),
        fps=payload.fps,
        output_dir=proj_dir / "output",
    )

    return {"job_id": job.id, "status": job.status}


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")

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


@app.get("/api/jobs/{job_id}/video")
async def get_job_video(job_id: str):
    job = queue_manager.get_job(job_id)
    if not job or not job.output_video_path or not os.path.exists(job.output_video_path):
        raise HTTPException(status_code=404, detail="Vídeo não disponível")

    return FileResponse(job.output_video_path, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/download")
async def download_job_video(job_id: str):
    job = queue_manager.get_job(job_id)
    if not job or not job.output_video_path or not os.path.exists(job.output_video_path):
        raise HTTPException(status_code=404, detail="Vídeo não disponível para download")

    return FileResponse(
        job.output_video_path,
        media_type="video/mp4",
        filename="slidecast_video.mp4",
    )
