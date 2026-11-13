"""Capas prontas e composição (título + assinatura) das capas de podcast."""

from pathlib import Path

import pytest
from PIL import Image

from app.core.podcast_cover import (
    PRESET_COVERS,
    compose_podcast_cover,
    ensure_preset_covers,
    get_preset_palette,
    render_preset_cover,
)


def test_preset_covers_are_three_square_images(tmp_path):
    paths = ensure_preset_covers(output_dir=tmp_path)
    assert len(PRESET_COVERS) == 3
    assert len(paths) == 3
    for path in paths:
        with Image.open(path) as img:
            assert img.size == (1080, 1080)


def test_compose_burns_title_and_author_over_uploaded_cover(tmp_path):
    base = tmp_path / "upload.jpg"
    Image.new("RGB", (800, 500), (30, 60, 90)).save(base)
    out = tmp_path / "final.png"

    result = compose_podcast_cover(
        base, out,
        title="Por que a Nova Jerusalém tem formato de cubo?",
        author="Kika Magalhães",
        title_color="#ffffff", title_outline_color="#000000",
        author_color="#ffd98a", author_outline_color="#1a1a1a",
    )

    assert Path(result) == out
    with Image.open(out) as img:
        assert img.size == (1080, 1080)  # sempre quadrada, mesmo com upload retangular
    with Image.open(base) as img:
        assert out.read_bytes() != base.read_bytes()


def test_compose_changes_pixels_where_text_is_drawn(tmp_path):
    base = tmp_path / "base.png"
    Image.new("RGB", (1080, 1080), (20, 20, 20)).save(base)
    out = tmp_path / "final.png"
    compose_podcast_cover(base, out, title="Título", author="Andréia Silva")
    with Image.open(base) as a, Image.open(out) as b:
        assert list(a.getdata()) != list(b.getdata())


def test_compose_without_text_keeps_square_cover(tmp_path):
    base = tmp_path / "base.png"
    Image.new("RGB", (400, 900), (200, 200, 200)).save(base)
    out = tmp_path / "final.png"
    compose_podcast_cover(base, out, title="", author="")
    with Image.open(out) as img:
        assert img.size == (1080, 1080)


def test_preset_recolor_with_any_colors(tmp_path):
    palette = get_preset_palette("estudio")
    assert set(palette) == {"bg", "mic", "accent"}
    custom = tmp_path / "custom.png"
    render_preset_cover("estudio", custom, bg_color="#5b21b6",
                        mic_color="#fef08a", accent_color="#22c55e")
    default = ensure_preset_covers(output_dir=tmp_path / "p")[0]
    with Image.open(custom) as img:
        assert img.size == (1080, 1080)
        corner = img.getpixel((60, 60))  # fundo recolorido
    assert corner[2] > 120 and corner[0] > 40  # roxo escolhido, não o fundo padrão escuro
    assert custom.read_bytes() != default.read_bytes()


def test_compose_widescreen_format(tmp_path):
    base = tmp_path / "base.png"
    Image.new("RGB", (1080, 1080), (30, 60, 90)).save(base)
    out = tmp_path / "wide.png"
    compose_podcast_cover(base, out, title="Episódio Wide", author="Kika Magalhães",
                          cover_format="widescreen")
    with Image.open(out) as img:
        assert img.size == (1920, 1080)


def test_compose_rejects_invalid_format(tmp_path):
    base = tmp_path / "base.png"
    Image.new("RGB", (100, 100)).save(base)
    with pytest.raises(ValueError):
        compose_podcast_cover(base, tmp_path / "o.png", title="X", cover_format="retrato")


def test_compose_rejects_invalid_color(tmp_path):
    base = tmp_path / "base.png"
    Image.new("RGB", (100, 100)).save(base)
    with pytest.raises(ValueError):
        compose_podcast_cover(base, tmp_path / "o.png", title="X", title_color="roxo")
