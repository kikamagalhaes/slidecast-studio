"""Tests for PDF inspection/thumbnail/slide rendering (PyMuPDF, no fixtures)."""

import pymupdf
import pytest

from app.core.pdf_processor import (
    inspect_pdf,
    render_all_slides_to_dir,
    render_thumbnail,
)


def make_pdf(path, pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Slide {i + 1} content")
    doc.save(str(path))
    doc.close()
    return str(path)


def test_inspect_pdf(tmp_path):
    pdf = make_pdf(tmp_path / "slides.pdf", pages=3)
    info = inspect_pdf(pdf)
    assert info.page_count == 3
    assert info.file_name == "slides.pdf"
    assert len(info.slides) == 3
    assert info.slides[0].page_number == 1
    assert info.aspect_ratio > 0


def test_inspect_pdf_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        inspect_pdf(str(tmp_path / "nope.pdf"))


def test_render_thumbnail_png(tmp_path):
    pdf = make_pdf(tmp_path / "slides.pdf", pages=2)
    data = render_thumbnail(pdf, 1, max_dimension=120)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(IndexError):
        render_thumbnail(pdf, 5)
    with pytest.raises(IndexError):
        render_thumbnail(pdf, -1)


def test_render_all_slides_to_dir(tmp_path):
    pdf = make_pdf(tmp_path / "slides.pdf", pages=2)
    out = tmp_path / "slides"
    seen = []
    images = render_all_slides_to_dir(
        pdf, out, target_dpi=72, progress_callback=lambda c, t: seen.append((c, t))
    )
    assert len(images) == 2
    assert all(p.exists() and p.stat().st_size > 0 for p in images)
    assert seen == [(1, 2), (2, 2)]


def test_render_all_slides_cancel(tmp_path):
    pdf = make_pdf(tmp_path / "slides.pdf", pages=3)
    with pytest.raises(InterruptedError):
        render_all_slides_to_dir(pdf, tmp_path / "s", cancel_check=lambda: True)
