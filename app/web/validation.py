"""Pure validation helpers for the SlideCast web API.

Kept free of FastAPI imports so the rules are unit-testable in isolation;
``app.web.server`` maps :class:`ValidationError` to HTTP 400 responses.
"""

import os
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

# Fixed on-disk names inside a project directory. User-supplied filenames are
# stored only as display metadata (see meta.json) to prevent path traversal.
STORED_PDF_NAME = "slides.pdf"
STORED_AUDIO_BASENAME = "audio"
META_FILENAME = "meta.json"

AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"})

MIN_SLIDE_SECONDS = 0.1
MAX_SLIDE_SECONDS = 7200.0
MIN_RESOLUTION_DIM = 16
MAX_RESOLUTION_DIM = 3840
MIN_FPS = 1
MAX_FPS = 60


class ValidationError(ValueError):
    """Raised when user input fails validation (maps to HTTP 400)."""


def get_max_upload_bytes() -> int:
    """Upload size cap in bytes (env ``MAX_UPLOAD_MB``, default 500)."""
    try:
        mb = float(os.environ.get("MAX_UPLOAD_MB", "500"))
    except ValueError:
        mb = 500.0
    return max(1, int(mb * 1024 * 1024))


def parse_project_id(value: str) -> str:
    """Validates that ``value`` is a UUID4 (the only id shape we generate)."""
    try:
        parsed = uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"Identificador de projeto inválido: {value!r}") from exc
    if parsed.version != 4:
        raise ValidationError(f"Identificador de projeto inválido: {value!r}")
    return str(parsed)


def project_dir(storage_dir: Path, project_id: str) -> Path:
    """Returns the containment-checked directory for a project id."""
    safe_id = parse_project_id(project_id)
    base = storage_dir.resolve()
    candidate = (base / "projects" / safe_id).resolve()
    if candidate != base / "projects" / safe_id or base not in candidate.parents:
        raise ValidationError(f"Identificador de projeto inválido: {project_id!r}")
    return candidate


def validate_upload_filename(filename: Optional[str], kind: str) -> str:
    """Validates an uploaded filename; returns the normalized extension.

    :param kind: ``"pdf"`` or ``"audio"``.
    """
    name = (filename or "").strip()
    if not name:
        raise ValidationError(f"Nome de arquivo {kind} ausente.")
    ext = Path(name).suffix.lower()
    if kind == "pdf":
        if ext != ".pdf":
            raise ValidationError(f"Arquivo de slides deve ser .pdf (recebido: {name!r}).")
    elif kind == "audio":
        if ext not in AUDIO_EXTENSIONS:
            allowed = ", ".join(sorted(AUDIO_EXTENSIONS))
            raise ValidationError(f"Áudio deve ter uma destas extensões: {allowed}.")
    else:  # pragma: no cover - defensive
        raise ValidationError(f"Tipo de upload desconhecido: {kind!r}.")
    return ext


def validate_durations(durations: List[float], page_count: int) -> List[float]:
    """Validates per-slide durations against the presentation page count."""
    if not durations:
        raise ValidationError("A lista de durações está vazia.")
    if page_count <= 0:
        raise ValidationError("A apresentação não possui páginas.")
    if len(durations) != page_count:
        raise ValidationError(
            f"A apresentação tem {page_count} páginas, mas {len(durations)} "
            "durações foram enviadas."
        )
    clean: List[float] = []
    for i, raw in enumerate(durations):
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Duração do slide {i + 1} não é um número.") from exc
        if not (MIN_SLIDE_SECONDS <= value <= MAX_SLIDE_SECONDS):
            raise ValidationError(
                f"Duração do slide {i + 1} fora do intervalo "
                f"({MIN_SLIDE_SECONDS}s–{MAX_SLIDE_SECONDS}s)."
            )
        clean.append(value)
    return clean


def validate_resolution(width: int, height: int) -> Tuple[int, int]:
    """Validates a target resolution (H.264 requires even dimensions)."""
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Resolução inválida.") from exc
    for dim, label in ((w, "largura"), (h, "altura")):
        if not (MIN_RESOLUTION_DIM <= dim <= MAX_RESOLUTION_DIM):
            raise ValidationError(
                f"{label.capitalize()} deve estar entre {MIN_RESOLUTION_DIM} e "
                f"{MAX_RESOLUTION_DIM} pixels."
            )
        if dim % 2 != 0:
            raise ValidationError(f"{label.capitalize()} deve ser um número par (H.264).")
    return w, h


def validate_fps(fps: int) -> int:
    """Validates frames-per-second."""
    try:
        value = int(fps)
    except (TypeError, ValueError) as exc:
        raise ValidationError("FPS inválido.") from exc
    if not (MIN_FPS <= value <= MAX_FPS):
        raise ValidationError(f"FPS deve estar entre {MIN_FPS} e {MAX_FPS}.")
    return value


def assert_pdf_signature(path: Path) -> None:
    """Confirms a stored upload starts with the ``%PDF-`` magic bytes."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(5)
    except OSError as exc:
        raise ValidationError(f"Não foi possível ler o arquivo enviado: {exc}") from exc
    if not header.startswith(b"%PDF-"):
        raise ValidationError("O arquivo enviado não é um PDF válido (assinatura).")


def display_name(filename: Optional[str], fallback: str, limit: int = 120) -> str:
    """Truncates a user filename for safe display (never used as a path)."""
    name = (filename or "").strip() or fallback
    return name if len(name) <= limit else name[: limit - 1] + "…"
