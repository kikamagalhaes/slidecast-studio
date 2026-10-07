from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Callable
import pymupdf


@dataclass
class SlideInfo:
    index: int  # 0-based
    page_number: int  # 1-based
    width: float
    height: float
    duration: float = 0.0  # seconds allocated for this slide


@dataclass
class PresentationInfo:
    file_path: str
    file_name: str
    page_count: int
    slides: List[SlideInfo]
    aspect_ratio: float  # width / height of first slide


def inspect_pdf(file_path: str) -> PresentationInfo:
    """Reads PDF metadata and returns PresentationInfo."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo PDF não encontrado: {file_path}")

    doc = pymupdf.open(str(path))
    page_count = len(doc)
    if page_count == 0:
        doc.close()
        raise ValueError("O arquivo PDF não contém páginas.")

    slides: List[SlideInfo] = []
    first_page = doc[0]
    rect = first_page.rect
    aspect_ratio = (rect.width / rect.height) if rect.height > 0 else 1.777

    for idx, page in enumerate(doc):
        r = page.rect
        slides.append(
            SlideInfo(
                index=idx,
                page_number=idx + 1,
                width=r.width,
                height=r.height,
                duration=0.0,
            )
        )

    doc.close()

    return PresentationInfo(
        file_path=str(path.resolve()),
        file_name=path.name,
        page_count=page_count,
        slides=slides,
        aspect_ratio=aspect_ratio,
    )


def render_thumbnail(file_path: str, page_index: int, max_dimension: int = 240) -> bytes:
    """Renders a single page as a PNG byte buffer for UI thumbnail preview."""
    doc = pymupdf.open(file_path)
    if page_index < 0 or page_index >= len(doc):
        doc.close()
        raise IndexError("Índice de página fora do alcance.")

    page = doc[page_index]
    rect = page.rect
    longest_side = max(rect.width, rect.height)
    zoom = max_dimension / longest_side if longest_side > 0 else 1.0
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


def render_all_slides_to_dir(
    file_path: str,
    output_dir: Path,
    target_dpi: int = 150,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> List[Path]:
    """
    Renders all PDF pages as high-resolution PNG files in output_dir.
    Calls progress_callback(current_slide, total_slides) after each page.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(file_path)
    total_pages = len(doc)
    image_paths: List[Path] = []

    # Calculate zoom for DPI (72 is standard PDF point size)
    zoom = target_dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)

    for i, page in enumerate(doc):
        if cancel_check and cancel_check():
            doc.close()
            raise InterruptedError("Renderização cancelada pelo usuário.")

        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img_path = output_dir / f"slide_{i:04d}.png"
        pix.save(str(img_path))
        image_paths.append(img_path)

        if progress_callback:
            progress_callback(i + 1, total_pages)

    doc.close()
    return image_paths
