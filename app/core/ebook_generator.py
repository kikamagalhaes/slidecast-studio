import os
import sys
import json
import time
from pathlib import Path
from typing import List, Optional, Dict, Callable

import pymupdf

from app.core.config_manager import get_gemini_api_key


def generate_class_ebook(
    title: str,
    teacher: str,
    audio_path: str,
    slide_images: List[str],
    output_pdf_path: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Generates a complete, beautifully styled A4 educational eBook / study guide
    interleaving AI-generated pedagogical explanations with high-resolution slide images.
    """
    out_file = Path(output_pdf_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(10.0, "Analisando áudio da aula com IA Gemini...")

    api_key = get_gemini_api_key()
    total_slides = max(1, len(slide_images))

    # 1. Ask Gemini to structure the educational book
    sections_data = _generate_ebook_content_with_gemini(
        title=title,
        teacher=teacher,
        audio_path=audio_path,
        total_slides=total_slides,
        api_key=api_key,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback(60.0, "Diagramando e intercalando slides e textos didáticos...")

    # 2. Build PDF Document with PyMuPDF
    doc = pymupdf.open()
    A4_W, A4_H = 595, 842  # Standard A4 in points

    # --- 2.1 COVER PAGE ---
    cover_page = doc.new_page(width=A4_W, height=A4_H)
    _render_ebook_cover(cover_page, title, teacher, A4_W, A4_H)

    # --- 2.2 CHAPTER PAGES (Slide + Interleaved Explanatory Text) ---
    for i in range(total_slides):
        slide_num = i + 1
        sec_info = sections_data.get(slide_num, {})
        slide_img = slide_images[i] if i < len(slide_images) else None

        page = doc.new_page(width=A4_W, height=A4_H)
        _render_ebook_slide_chapter(
            page=page,
            doc=doc,
            slide_num=slide_num,
            total_slides=total_slides,
            sec_info=sec_info,
            slide_img_path=slide_img,
            W=A4_W,
            H=A4_H,
        )

        if progress_callback:
            pct = 60.0 + (30.0 * (slide_num / total_slides))
            progress_callback(pct, f"Diagramando Capítulo {slide_num} de {total_slides}...")

    # --- 2.3 FINAL SUMMARY & EXERCISES PAGE ---
    final_page = doc.new_page(width=A4_W, height=A4_H)
    _render_ebook_summary_and_quiz(
        final_page,
        sections_data.get("summary", ""),
        sections_data.get("exercises", []),
        A4_W,
        A4_H,
    )

    # Add page numbers to all pages except cover
    for p_idx in range(1, len(doc)):
        p = doc[p_idx]
        p.insert_text(
            (A4_W - 120, A4_H - 30),
            f"Página {p_idx + 1} de {len(doc)}",
            fontsize=9,
            color=(0.5, 0.55, 0.65),
        )

    doc.save(str(out_file))

    if progress_callback:
        progress_callback(100.0, "E-book didático em PDF gerado com sucesso!")

    return str(out_file)


def _render_ebook_cover(page, title: str, teacher: str, W: float, H: float):
    # Dark modern gradient background
    page.draw_rect(pymupdf.Rect(0, 0, W, H), fill=(0.06, 0.08, 0.12))

    # Elegant border frame
    page.draw_rect(pymupdf.Rect(35, 35, W - 35, H - 35), color=(0.22, 0.74, 0.97), width=1.5)
    page.draw_rect(pymupdf.Rect(40, 40, W - 40, H - 40), color=(0.15, 0.25, 0.4), width=0.8)

    # Badge
    page.draw_rect(pymupdf.Rect(60, 160, 240, 190), fill=(0.12, 0.18, 0.3), radius=None)
    page.insert_text((75, 180), "MATERIAL DIDÁTICO OFICIAL", fontsize=10, color=(0.38, 0.82, 0.98))

    # Title
    page.insert_textbox(
        pymupdf.Rect(60, 230, W - 60, 420),
        title,
        fontsize=28,
        color=(1.0, 1.0, 1.0),
        align=pymupdf.TEXT_ALIGN_LEFT,
    )

    # Subtitle
    page.insert_text((60, 440), "Apostila Completa da Aula com Slides e Anotações", fontsize=14, color=(0.7, 0.75, 0.85))

    # Teacher Info
    if teacher:
        page.insert_text((60, 520), "Ministrado por:", fontsize=11, color=(0.5, 0.55, 0.65))
        page.insert_text((60, 545), teacher, fontsize=16, color=(0.22, 0.74, 0.97))

    # Footer note
    page.insert_text((60, H - 70), "Gerado automaticamente por SlideCast Studio", fontsize=10, color=(0.4, 0.45, 0.55))


def _render_ebook_slide_chapter(
    page,
    doc,
    slide_num: int,
    total_slides: int,
    sec_info: dict,
    slide_img_path: Optional[str],
    W: float,
    H: float,
):
    # Top banner header
    page.draw_rect(pymupdf.Rect(40, 40, W - 40, 78), fill=(0.09, 0.12, 0.18), radius=None)
    page.draw_line(pymupdf.Point(40, 78), pymupdf.Point(W - 40, 78), color=(0.22, 0.74, 0.97), width=1.5)

    topic_title = sec_info.get("topic", f"Tópico do Slide {slide_num}")
    page.insert_text((55, 63), f"Capítulo {slide_num}: {topic_title}", fontsize=13, color=(1.0, 1.0, 1.0))

    cur_y = 95.0

    # 1. Slide Image (Interleaved)
    if slide_img_path and Path(slide_img_path).exists():
        try:
            # Place slide image centered: 16:9 width 440, height 247.5
            img_w = 440.0
            img_h = 247.5
            img_x = (W - img_w) / 2.0
            img_rect = pymupdf.Rect(img_x, cur_y, img_x + img_w, cur_y + img_h)

            # Draw subtle background border
            page.draw_rect(
                pymupdf.Rect(img_x - 3, cur_y - 3, img_x + img_w + 3, cur_y + img_h + 3),
                fill=(0.92, 0.94, 0.97),
                color=(0.75, 0.8, 0.88),
                radius=None,
            )
            page.insert_image(img_rect, filename=str(slide_img_path))
            cur_y += img_h + 16.0
        except Exception as e:
            print(f"Erro ao inserir imagem do slide {slide_num}: {e}")
            cur_y += 10.0

    # 2. Explanatory Pedagogical Text
    text_content = sec_info.get("content", "")
    if not text_content:
        text_content = (
            f"Nesta seção da aula correspondente ao Slide {slide_num}, o professor aprofundou "
            f"os principais conceitos sobre {topic_title}, articulando a teoria com aplicações práticas "
            f"e destacando os aspectos mais relevantes para a compreensão sólida da matéria pelos alunos."
        )

    text_rect = pymupdf.Rect(45, cur_y, W - 45, cur_y + 240)
    page.insert_textbox(
        text_rect,
        text_content,
        fontsize=10.5,
        color=(0.12, 0.15, 0.2),
        align=pymupdf.TEXT_ALIGN_LEFT,
    )
    cur_y += 245.0

    # 3. Callout Box: Ponto de Atenção / Destaque Prático
    highlight = sec_info.get("highlight", "")
    if highlight and cur_y < H - 120:
        box_rect = pymupdf.Rect(45, cur_y, W - 45, min(H - 60, cur_y + 65))
        page.draw_rect(box_rect, fill=(0.93, 0.96, 1.0), color=(0.25, 0.65, 0.95), width=1.2, radius=None)
        page.draw_rect(pymupdf.Rect(45, cur_y, 49, min(H - 60, cur_y + 65)), fill=(0.1, 0.5, 0.9))
        page.insert_text((58, cur_y + 18), "💡 Ponto-Chave / Destaque da Aula:", fontsize=10, color=(0.08, 0.35, 0.75))
        page.insert_textbox(
            pymupdf.Rect(58, cur_y + 24, W - 55, cur_y + 60),
            highlight,
            fontsize=9.5,
            color=(0.2, 0.25, 0.35),
        )


def _render_ebook_summary_and_quiz(page, summary: str, exercises: list, W: float, H: float):
    # Header
    page.draw_rect(pymupdf.Rect(40, 40, W - 40, 78), fill=(0.09, 0.12, 0.18), radius=None)
    page.draw_line(pymupdf.Point(40, 78), pymupdf.Point(W - 40, 78), color=(0.22, 0.74, 0.97), width=1.5)
    page.insert_text((55, 63), "Conclusão da Aula & Questões de Fixação", fontsize=13, color=(1.0, 1.0, 1.0))

    cur_y = 95.0

    # Summary box
    page.draw_rect(pymupdf.Rect(45, cur_y, W - 45, cur_y + 190), fill=(0.97, 0.98, 1.0), color=(0.8, 0.85, 0.9), radius=None)
    page.insert_text((60, cur_y + 22), "📌 Resumo dos Principais Aprendizados:", fontsize=11, color=(0.1, 0.2, 0.4))

    sum_text = summary or (
        "Ao longo desta aula, foram explorados os fundamentos essenciais do tema, "
        "permitindo que o estudante desenvolva uma visão crítica e prática sobre cada conceito apresentado. "
        "Revise as anotações e realize as questões de fixação a seguir para consolidar os conhecimentos adquiridos."
    )
    page.insert_textbox(
        pymupdf.Rect(60, cur_y + 32, W - 60, cur_y + 180),
        sum_text,
        fontsize=10,
        color=(0.2, 0.25, 0.3),
    )
    cur_y += 210.0

    # Exercises Header
    page.insert_text((45, cur_y), "📝 Exercícios de Fixação para os Alunos:", fontsize=12, color=(0.1, 0.2, 0.4))
    cur_y += 18.0

    if not exercises:
        exercises = [
            "1. Quais foram os conceitos centrais apresentados na primeira parte da aula e como eles se relacionam?",
            "2. Explique a importância prática dos exemplos demonstrados pelo professor durante a apresentação.",
            "3. Como você aplicaria as estratégias discutidas neste conteúdo na resolução de problemas reais?",
        ]

    for q in exercises[:4]:
        page.insert_textbox(
            pymupdf.Rect(50, cur_y, W - 50, cur_y + 55),
            q,
            fontsize=9.5,
            color=(0.15, 0.2, 0.28),
        )
        cur_y += 60.0


def _generate_ebook_content_with_gemini(
    title: str,
    teacher: str,
    audio_path: str,
    total_slides: int,
    api_key: Optional[str],
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    Calls Gemini Flash to extract pedagogical chapters, explanations, highlights
    and exercises from the lesson audio.
    """
    default_data: Dict = {}
    for i in range(1, total_slides + 1):
        default_data[i] = {
            "topic": f"Tópico da Apresentação #{i}",
            "content": f"Explicação detalhada dos conceitos apresentados no slide {i} pelo professor {teacher or 'responsável'}.",
            "highlight": f"Foco nos pontos principais e conceitos fundamentais do Slide {i}.",
        }
    default_data["summary"] = f"Resumo geral da aula '{title}' ministrada por {teacher}."
    default_data["exercises"] = [
        "1. Descreva o conceito principal trabalhado na primeira metade da aula.",
        "2. Identifique os pontos de atenção destacados pelo professor.",
        "3. Como os conceitos teóricos apresentados podem ser aplicados na prática?",
    ]

    if not api_key:
        return default_data

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        models_to_try = [
            "gemini-3.8-flash",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-flash-latest",
        ]

        # Upload audio to Gemini File API if available
        uploaded_file = None
        if audio_path and Path(audio_path).exists() and Path(audio_path).stat().st_size > 1000:
            try:
                uploaded_file = client.files.upload(file=audio_path)
            except Exception as e:
                print(f"Aviso: upload de áudio falhou: {e}")

        prompt = (
            f"Você é um renomado pedagogo e autor de livros didáticos. A partir da aula gravada intitulada '{title}' "
            f"do professor '{teacher}', crie uma APOSTILA DIDÁTICA COMPLETA em português para ser entregue aos alunos.\n"
            f"A aula contém {total_slides} slides que serão intercalados com o texto didático.\n"
            f"Estruture sua resposta EXATAMENTE no seguinte formato JSON:\n"
            f"{{\n"
            f'  "slides": [\n'
            f'    {{\n'
            f'      "slide_number": 1,\n'
            f'      "topic": "Título do Tópico 1",\n'
            f'      "content": "Texto didático detalhado, fluido e aprofundado (2 a 3 parágrafos explicativos ensinando o conteúdo do slide 1 para os alunos)",\n'
            f'      "highlight": "Dica prática ou conceito essencial a ser memorizado"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "summary": "Resumo executivo dos aprendizados da aula",\n'
            f'  "exercises": [\n'
            f'    "1. Pergunta de fixação sobre o tema...",\n'
            f'    "2. Pergunta de fixação sobre o tema...",\n'
            f'    "3. Pergunta de fixação sobre o tema..."\n'
            f'  ]\n'
            f"}}\n"
            f"Gere um item para cada um dos {total_slides} slides. Responda apenas o JSON puro, sem blocos markdown extras."
        )

        contents = [uploaded_file, prompt] if uploaded_file else [prompt]

        for m in models_to_try:
            try:
                resp = client.models.generate_content(model=m, contents=contents)
                raw_text = resp.text.strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]

                parsed = json.loads(raw_text.strip())
                result_map: Dict = {}
                slides_list = parsed.get("slides", [])
                for item in slides_list:
                    s_num = item.get("slide_number", len(result_map) + 1)
                    result_map[s_num] = {
                        "topic": item.get("topic", f"Tópico #{s_num}"),
                        "content": item.get("content", ""),
                        "highlight": item.get("highlight", ""),
                    }
                result_map["summary"] = parsed.get("summary", default_data["summary"])
                result_map["exercises"] = parsed.get("exercises", default_data["exercises"])
                return result_map
            except Exception:
                continue

    except Exception as e:
        print(f"Aviso ao consultar Gemini para o E-book: {e}")

    return default_data
