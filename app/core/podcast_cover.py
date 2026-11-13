"""Capas de podcast: 3 artes prontas neutras (quadradas) e composição final.

A composição grava, sobre qualquer capa — pronta, enviada pelo usuário ou
gerada por IA — o título do episódio e o nome de quem apresenta, cada um com
cor de preenchimento e cor de contorno escolhidas na interface. O resultado é
sempre uma imagem quadrada de 1080x1080, pronta para o vídeo do podcast e
para as plataformas (Spotify, YouTube, Instagram).
"""

import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

COVER_SIZE = 1080

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "podcast_covers"

PRESET_COVERS = [
    {"id": "estudio", "name": "Estúdio Escuro", "file": "capa_pronta_estudio.png"},
    {"id": "noite", "name": "Azul Noite", "file": "capa_pronta_noite.png"},
    {"id": "claro", "name": "Claro Minimalista", "file": "capa_pronta_claro.png"},
]

_FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_FONT_CANDIDATES_SERIF_ITALIC = [
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "C:/Windows/Fonts/georgiai.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
]


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """Aceita '#RRGGBB' ou 'RRGGBB'; qualquer outro formato é ValueError."""
    text = (value or "").strip()
    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
        raise ValueError(f"Cor inválida: {value!r} (use o formato #RRGGBB)")
    text = text.lstrip("#")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _font(size: int, candidates: list[str]) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()  # type: ignore[return-value]


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        ratio = y / max(size - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return img


def _draw_microphone(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float,
                     body: tuple, accent: tuple) -> None:
    """Microfone de estúdio desenhado com formas simples, centrado em (cx, cy)."""
    w, h = int(150 * scale), int(300 * scale)
    x0, y0, x1, y1 = cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2
    draw.rounded_rectangle([x0, y0, x1, y1], radius=w // 2, fill=body)
    # Grade da cápsula
    for i in range(1, 4):
        gy = y0 + int(h * i / 5)
        draw.line([(x0 + 14 * scale, gy), (x1 - 14 * scale, gy)], fill=accent, width=max(3, int(5 * scale)))
    draw.line([(cx, y0 + 12 * scale), (cx, y1 - 12 * scale)], fill=accent, width=max(3, int(5 * scale)))
    # Arco (suporte em U)
    r = int(230 * scale)
    draw.arc([cx - r, cy - int(r * 0.72), cx + r, cy + int(r * 0.95)], start=0, end=180,
             fill=body, width=max(6, int(16 * scale)))
    # Haste e base
    stem_top = cy + int(r * 0.95)
    draw.line([(cx, stem_top), (cx, stem_top + int(90 * scale))], fill=body, width=max(6, int(16 * scale)))
    base_y = stem_top + int(100 * scale)
    draw.line([(cx - int(130 * scale), base_y), (cx + int(130 * scale), base_y)],
              fill=body, width=max(6, int(16 * scale)))
    # Ondas sonoras laterais
    for side in (-1, 1):
        for i, rr in enumerate((300, 370, 440)):
            rr = int(rr * scale)
            box = [cx - rr, cy - rr, cx + rr, cy + rr]
            start, end = (-55, 55) if side > 0 else (125, 235)
            draw.arc(box, start=start, end=end, fill=accent, width=max(4, int(10 * scale)))


def _spaced(text: str) -> str:
    return " ".join(list(text))


_PRESET_PALETTES = {
    "estudio": dict(top=(16, 21, 31), bottom=(29, 43, 58), body=(232, 238, 244),
                    accent=(240, 179, 92), word=(232, 238, 244)),
    "noite": dict(top=(23, 35, 63), bottom=(36, 54, 94), body=(240, 244, 248),
                  accent=(126, 200, 227), word=(240, 244, 248)),
    "claro": dict(top=(236, 231, 221), bottom=(216, 208, 191), body=(51, 58, 66),
                  accent=(176, 121, 63), word=(51, 58, 66)),
}


def _rgb_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _blend(rgb, other, ratio: float):
    return tuple(int(rgb[i] + (other[i] - rgb[i]) * ratio) for i in range(3))


def get_preset_palette(preset_id: str) -> dict:
    """Paleta padrão de uma capa pronta, em hex (fundo/microfone/detalhes)."""
    if preset_id not in _PRESET_PALETTES:
        raise ValueError(f"Capa pronta desconhecida: {preset_id!r}")
    pal = _PRESET_PALETTES[preset_id]
    return {"bg": _rgb_hex(pal["top"]), "mic": _rgb_hex(pal["body"]),
            "accent": _rgb_hex(pal["accent"])}


def render_preset_cover(preset_id: str, output_path, bg_color: Optional[str] = None,
                        mic_color: Optional[str] = None,
                        accent_color: Optional[str] = None,
                        size: int = COVER_SIZE) -> str:
    """Desenha a capa pronta com as cores escolhidas (qualquer cor vale)."""
    if preset_id not in _PRESET_PALETTES:
        raise ValueError(f"Capa pronta desconhecida: {preset_id!r}")
    pal = dict(_PRESET_PALETTES[preset_id])
    if bg_color:
        top = parse_hex_color(bg_color)
        # Fundo vira um degradê suave a partir da cor escolhida
        luminance = 0.299 * top[0] + 0.587 * top[1] + 0.114 * top[2]
        pal["top"] = top
        pal["bottom"] = _blend(top, (255, 255, 255), 0.14) if luminance < 128 else _blend(top, (0, 0, 0), 0.10)
    if mic_color:
        pal["body"] = pal["word"] = parse_hex_color(mic_color)
    if accent_color:
        pal["accent"] = parse_hex_color(accent_color)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _render_preset(preset_id, size=size, palette=pal).save(out, format="PNG")
    return str(out)


def _render_preset(preset_id: str, size: int = COVER_SIZE, palette: Optional[dict] = None) -> Image.Image:
    pal = palette if palette is not None else _PRESET_PALETTES[preset_id]
    img = _vertical_gradient(size, pal["top"], pal["bottom"])
    draw = ImageDraw.Draw(img)
    # Moldura fina interna
    m = int(size * 0.045)
    draw.rounded_rectangle([m, m, size - m, size - m], radius=28,
                           outline=pal["accent"], width=4)
    # "PODCAST" vai no topo: o terço inferior fica livre para, na composição,
    # entrarem o título do episódio e a assinatura de quem apresenta.
    font = _font(int(size * 0.062), _FONT_CANDIDATES_BOLD)
    draw.text((size // 2, int(size * 0.135)), _spaced("PODCAST"), font=font,
              fill=pal["word"], anchor="mm")
    _draw_microphone(draw, size // 2, int(size * 0.44), (size / 1080.0) * 0.92,
                     pal["body"], pal["accent"])
    return img


def ensure_preset_covers(output_dir: Optional[Path] = None) -> list[Path]:
    """Garante as 3 capas prontas em disco e devolve os caminhos (1080x1080)."""
    target_dir = Path(output_dir) if output_dir else _ASSETS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for preset in PRESET_COVERS:
        path = target_dir / preset["file"]
        if not path.exists():
            _render_preset(preset["id"]).save(path, format="PNG")
        paths.append(path)
    return paths


def preset_cover_path(preset_id: str) -> Path:
    for preset, path in zip(PRESET_COVERS, ensure_preset_covers()):
        if preset["id"] == preset_id:
            return path
    raise ValueError(f"Capa pronta desconhecida: {preset_id!r}")


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:4]


def _fit_title_font(draw: ImageDraw.ImageDraw, title: str, max_width: int):
    size = 68
    while size > 30:
        font = _font(size, _FONT_CANDIDATES_BOLD)
        if len(_wrap_text(draw, title, font, max_width)) <= 3:
            return font
        size -= 6
    return _font(30, _FONT_CANDIDATES_BOLD)


COVER_FORMATS = {"quadrada": (1080, 1080), "widescreen": (1920, 1080)}


def compose_podcast_cover(
    base_image_path,
    output_path,
    title: str = "",
    author: str = "",
    title_color: str = "#ffffff",
    title_outline_color: str = "#000000",
    author_color: str = "#f2d492",
    author_outline_color: str = "#000000",
    size: int = COVER_SIZE,
    cover_format: str = "quadrada",
) -> str:
    """Grava título e assinatura sobre a capa e salva a imagem final.

    Formatos: "quadrada" (1080x1080) ou "widescreen" (1920x1080, 16:9).
    Funciona igual para capa enviada, capa pronta ou capa gerada por IA.
    Título/autor vazios simplesmente não são desenhados.
    """
    if cover_format not in COVER_FORMATS:
        raise ValueError(f"Formato de capa inválido: {cover_format!r} (use 'quadrada' ou 'widescreen')")
    title_rgb = parse_hex_color(title_color)
    title_outline_rgb = parse_hex_color(title_outline_color)
    author_rgb = parse_hex_color(author_color)
    author_outline_rgb = parse_hex_color(author_outline_color)

    out_w, out_h = COVER_FORMATS[cover_format]
    if cover_format == "quadrada":
        out_w = out_h = size

    with Image.open(base_image_path) as src:
        img = src.convert("RGB")
    # Recorte central na proporção do formato + redimensionamento
    target_ratio = out_w / out_h
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        crop_w, crop_h = int(img.height * target_ratio), img.height
    else:
        crop_w, crop_h = img.width, int(img.width / target_ratio)
    left, top = (img.width - crop_w) // 2, (img.height - crop_h) // 2
    img = img.crop((left, top, left + crop_w, top + crop_h)).resize((out_w, out_h), Image.LANCZOS)

    ref = min(out_w, out_h)  # referência p/ tamanhos de fonte e contornos
    title, author = (title or "").strip(), (author or "").strip()
    if title or author:
        # Faixa inferior escurecida com degradê, para o texto ficar legível
        # sobre qualquer arte, sem esconder a capa inteira.
        overlay = Image.new("L", (1, out_h))
        for y in range(out_h):
            start = int(out_h * 0.52)
            overlay.putpixel((0, y), 0 if y < start else int(175 * (y - start) / max(out_h - start, 1)))
        shade = Image.new("RGB", (out_w, out_h), (5, 8, 14))
        img = Image.composite(shade, img, overlay.resize((out_w, out_h)))

        draw = ImageDraw.Draw(img)
        margin = int(out_w * 0.07)
        max_width = out_w - 2 * margin
        cursor_y = int(out_h * 0.945)

        if author:
            font_author = _font(int(ref * 0.042), _FONT_CANDIDATES_SERIF_ITALIC)
            # Linha decorativa curta acima da assinatura
            line_w = int(ref * 0.09)
            line_y = cursor_y - int(ref * 0.075)
            draw.line([(out_w // 2 - line_w, line_y), (out_w // 2 + line_w, line_y)],
                      fill=author_rgb, width=max(2, int(ref * 0.003)))
            draw.text((out_w // 2, cursor_y), author, font=font_author, fill=author_rgb,
                      anchor="ms", stroke_width=max(1, int(ref * 0.001)),
                      stroke_fill=author_outline_rgb)
            cursor_y -= int(ref * 0.105)

        if title:
            font_title = _fit_title_font(draw, title, max_width)
            lines = _wrap_text(draw, title, font_title, max_width)
            line_h = int(font_title.size * 1.18)
            y = cursor_y - line_h * len(lines)
            for line in lines:
                draw.text((out_w // 2, y), line, font=font_title, fill=title_rgb,
                          anchor="ma", stroke_width=max(1, int(ref * 0.002)),
                          stroke_fill=title_outline_rgb)
                y += line_h

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG")
    return str(out)
