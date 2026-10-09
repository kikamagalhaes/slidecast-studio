import json
import logging
import urllib.request
import urllib.parse
from pathlib import Path
from typing import List, Optional

import pymupdf

from app.core.config_manager import (
    get_gemini_api_key,
    get_openai_api_key,
    get_image_provider,
)
from app.core.gemini_client import GeminiError, generate_with_fallback

logger = logging.getLogger(__name__)


def enhance_slide_prompt_with_gemini(
    user_prompt: str,
    slide_num: int,
    total_slides: int,
    lesson_topic: Optional[str] = None,
) -> str:
    """
    Uses Gemini Flash to expand and enhance a slide description into a
    detailed, visually striking prompt for image generation.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        return user_prompt

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        context = f"Slide {slide_num} de {total_slides}."
        if lesson_topic:
            context += f" Tema geral da aula: {lesson_topic}."

        instructions = (
            "Você é um diretor de arte e designer especialista em criar apresentações visuais de impacto "
            "no estilo NotebookLM, Apple Keynote e TED Talks. Transforme o texto fornecido pelo usuário "
            "em um prompt em inglês altamente descritivo e detalhado para um gerador de imagens de IA (como Flux/DALL-E 3). "
            "O prompt DEVE descrever uma apresentação de slide moderno em formato 16:9 widescreen, com iluminação elegante, "
            "composição limpa, estética visual premium e minimalista, sem artefatos ou poluição visual. "
            "Retorne APENAS o texto do prompt descritivo em inglês, sem aspas e sem explicações adicionais."
        )

        full_content = f"{instructions}\n\nContexto: {context}\nDescrição do usuário: {user_prompt}"

        try:
            resp = generate_with_fallback(client, contents=full_content)
            return resp.text.strip()
        except GeminiError:
            pass

    except Exception:
        pass

    return user_prompt


def enhance_background_prompt_with_gemini(
    user_prompt: str,
    format_ratio: str = "16:9",
) -> str:
    """
    Uses Gemini Flash to expand and enhance a video background prompt into a
    detailed, photorealistic prompt for AI image generators (Flux/Midjourney).
    Focuses on empty realistic studio/office/bookshelf backdrops with cinematic lighting and bokeh,
    specifically avoiding people in the foreground so the presenter stands out.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        return user_prompt

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        ratio_desc = "9:16 vertical smartphone format" if format_ratio in ("9:16", "vertical") else "16:9 widescreen format"

        instructions = (
            "You are a world-class studio set designer and cinematic lighting director for premium broadcasts, podcasts, and online courses. "
            "Convert the user's description into an ultra-detailed, photorealistic prompt in English for Flux/Midjourney. "
            f"The image MUST be an EMPTY background backdrop for video recording in {ratio_desc}. "
            "CRITICAL: There must be NO people, NO persons, NO silhouettes, NO faces in the scene! "
            "The center foreground must remain open and uncluttered for the presenter. "
            "Describe rich ambient lighting, shallow depth of field (subtle bokeh in the background), premium textures "
            "(dark wood, glass, subtle LED edge lighting, warm acoustic elements), 8k resolution, cinematic architecture. "
            "Return ONLY the raw descriptive prompt in English without quotes, introduction, or explanations."
        )

        full_content = f"{instructions}\n\nUser request: {user_prompt}"

        try:
            resp = generate_with_fallback(
                client,
                contents=full_content,
                models=[
                    "gemini-2.5-flash",
                    "gemini-3.8-flash",
                    "gemini-3-flash-preview",
                    "gemini-flash-latest",
                ],
            )
            return resp.text.strip()
        except GeminiError:
            pass

    except Exception:
        pass

    return user_prompt


def generate_slide_image(
    prompt: str,
    output_path: str,
    width: int = 1280,
    height: int = 720,
    timeout: int = 40,
) -> str:
    """
    Generates a high-definition presentation slide or backdrop image from a prompt.
    Tries configured provider, with automatic fallback to high-quality Flux/Pollinations.
    Dynamically supports 16:9 widescreen, 9:16 vertical, and 1:1 square aspect ratios.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    openai_key = get_openai_api_key()
    provider = get_image_provider()

    # Determine optimal generation dimensions
    if height > width:
        target_w, target_h = 576, 1024
        dalle_size = "1024x1792"
    elif abs(width - height) < 50:
        target_w, target_h = 1024, 1024
        dalle_size = "1024x1024"
    else:
        target_w, target_h = 1024, 576
        dalle_size = "1792x1024"

    # 1. If OpenAI DALL-E is preferred or configured and key is present
    if provider == "openai" and openai_key:
        try:
            req_data = json.dumps({
                "model": "dall-e-3",
                "prompt": prompt,
                "n": 1,
                "size": dalle_size,
                "quality": "standard",
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.openai.com/v1/images/generations",
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                img_url = res_json["data"][0]["url"]
                urllib.request.urlretrieve(img_url, str(out_file))
                return str(out_file)
        except Exception:
            pass  # fallback to pollinations

    # 2. Free High-Definition Image Generation (Pollinations Flux)
    encoded_prompt = urllib.parse.quote(prompt[:450])
    gen_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?model=flux&width={target_w}&height={target_h}&nologo=true"
    req_timeout = min(timeout, 12)

    try:
        req = urllib.request.Request(
            gen_url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "image/jpeg,image/png,image/*",
            },
        )
        with urllib.request.urlopen(req, timeout=req_timeout) as response:
            data = response.read()
            if len(data) > 2048:
                with open(out_file, "wb") as f:
                    f.write(data)
                return str(out_file)
    except Exception as exc:
        logger.warning(
            "Geração remota de imagem falhou (%s); usando gerador gráfico local.", exc
        )

    # 3. High-Definition Stylized Title Card / Cover (Instant, Beautiful & 100% Reliable)
    try:
        doc = pymupdf.open()
        try:
            page = doc.new_page(width=width, height=height)

            # Base dark background
            page.draw_rect(pymupdf.Rect(0, 0, width, height), fill=(0.06, 0.08, 0.13))

            # Geometric accent panels
            page.draw_rect(pymupdf.Rect(0, int(height * 0.38), width, height), fill=(0.09, 0.12, 0.20))
            page.draw_rect(pymupdf.Rect(0, int(height * 0.72), width, height), fill=(0.07, 0.10, 0.17))

            # High-tech glowing frame
            page.draw_rect(pymupdf.Rect(32, 32, width - 32, height - 32), color=(0.39, 0.40, 0.95), width=2.5)
            page.draw_rect(pymupdf.Rect(38, 38, width - 38, height - 38), color=(0.22, 0.74, 0.97), width=1.0)

            # Corner bracket highlights
            for x, y in [(32, 32), (width - 62, 32), (32, height - 62), (width - 62, height - 62)]:
                page.draw_rect(pymupdf.Rect(x, y, x + 30, y + 30), color=(0.55, 0.58, 0.99), width=3.5)

            # Category pill badge
            is_cover = "capa" in prompt.lower() or "cover" in prompt.lower()
            badge_text = "CAPA OFICIAL DA AULA" if is_cover else "APRESENTAÇÃO EXCLUSIVA"
            page.draw_rect(pymupdf.Rect(64, 64, 320, 104), fill=(0.19, 0.17, 0.48), color=(0.39, 0.40, 0.95), width=1.5)
            page.insert_text(
                (80, 92),
                badge_text,
                fontsize=16,
                color=(0.75, 0.80, 0.99),
            )

            # Clean title text
            clean_title = prompt.strip()
            for prefix in ["Capa profissional moderna para ", "Capa para ", "Capa de "]:
                if clean_title.lower().startswith(prefix.lower()):
                    clean_title = clean_title[len(prefix):]
            clean_title = clean_title.strip("'").strip('"')

            page.insert_textbox(
                pymupdf.Rect(64, 130, width - 64, height - 120),
                clean_title[:140],
                fontsize=30,
                color=(0.96, 0.97, 0.99),
                align=pymupdf.TEXT_ALIGN_LEFT,
            )

            # Subtitle footer
            page.draw_line(pymupdf.Point(64, height - 85), pymupdf.Point(width - 64, height - 85), color=(0.20, 0.25, 0.36), width=1.0)
            page.insert_text(
                (64, height - 60),
                "SlideCast Studio • Produção Inteligente de Videoaulas e Conteúdos",
                fontsize=14,
                color=(0.58, 0.64, 0.72),
            )

            pix = page.get_pixmap()
            pix.save(str(out_file))
        finally:
            doc.close()
        return str(out_file)
    except Exception as exc:
        logger.warning("Gerador gráfico falhou (%s); tentando fallback Qt.", exc)
        # Final emergency fallback: write minimal valid JPEG
        try:
            from PySide6.QtGui import QImage, QColor
            img = QImage(width, height, QImage.Format_RGB32)
            img.fill(QColor(15, 23, 42))
            img.save(str(out_file), "JPEG", 90)
            return str(out_file)
        except Exception:
            raise RuntimeError(f"Não foi possível criar a imagem de capa: {exc}")


def create_pdf_from_images(image_paths: List[str], output_pdf_path: str) -> str:
    """
    Combines a list of image files into a single, high-resolution PDF document.
    """
    if not image_paths:
        raise ValueError("Nenhuma imagem fornecida para montar o PDF.")

    out_file = Path(output_pdf_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    pdf_doc = pymupdf.open()

    try:
        for path in image_paths:
            img_p = Path(path)
            if not img_p.exists():
                continue

            img_doc = None
            img_pdf = None
            try:
                img_doc = pymupdf.open(str(img_p))
                pdf_bytes = img_doc.convert_to_pdf()
                img_pdf = pymupdf.open("pdf", pdf_bytes)
                rect = img_pdf[0].rect
                page = pdf_doc.new_page(width=rect.width, height=rect.height)
                page.show_pdf_page(page.rect, img_pdf, 0)
            except Exception as exc:
                logger.warning("Erro ao incluir imagem %s no PDF: %s", img_p.name, exc)
            finally:
                for handle in (img_pdf, img_doc):
                    if handle is not None:
                        try:
                            handle.close()
                        except Exception:
                            pass

        if len(pdf_doc) == 0:
            raise RuntimeError("Não foi possível converter nenhuma imagem em página de PDF.")

        pdf_doc.save(str(out_file))
    finally:
        pdf_doc.close()
    return str(out_file)
