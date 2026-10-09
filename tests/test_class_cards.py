"""Tests for intro/outro card rendering (PyMuPDF only, no ffmpeg)."""

import pymupdf

from app.core.class_video_builder import render_intro_card_image, render_outro_card_image


def make_cover_png(path):
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=640, height=360)
        page.draw_rect(pymupdf.Rect(0, 0, 640, 360), fill=(0.1, 0.2, 0.4))
        page.insert_text((60, 180), "Cover", fontsize=40, color=(1, 1, 1))
        pix = page.get_pixmap()
        pix.save(str(path))
    finally:
        doc.close()
    return str(path)


def png_size(path):
    img_doc = pymupdf.open(str(path))
    try:
        rect = img_doc[0].rect
        return int(rect.width), int(rect.height)
    finally:
        img_doc.close()


def test_intro_card_horizontal(tmp_path):
    out = tmp_path / "intro.png"
    result = render_intro_card_image(out, "Aula de Python", "Maria", resolution=(1920, 1080))
    assert result == out
    assert out.stat().st_size > 1000
    assert png_size(out) == (1920, 1080)


def test_intro_card_vertical_with_cover(tmp_path):
    cover = make_cover_png(tmp_path / "cover.png")
    out = tmp_path / "intro_v.png"
    render_intro_card_image(
        out, "Aula Vertical", "João", cover_image_path=cover, resolution=(1080, 1920)
    )
    assert png_size(out) == (1080, 1920)


def test_outro_cards_both_orientations(tmp_path):
    out_h = tmp_path / "outro_h.png"
    render_outro_card_image(out_h, "Fim", "Maria", resolution=(1920, 1080))
    assert png_size(out_h) == (1920, 1080)
    out_v = tmp_path / "outro_v.png"
    render_outro_card_image(out_v, "Fim", "Maria", resolution=(1080, 1920))
    assert png_size(out_v) == (1080, 1920)


def test_cards_accept_blank_titles(tmp_path):
    out = tmp_path / "blank.png"
    render_intro_card_image(out, "", "")
    assert out.stat().st_size > 1000
