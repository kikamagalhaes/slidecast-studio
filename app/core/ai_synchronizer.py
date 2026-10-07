import json
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import pymupdf

from app.core.config_manager import get_gemini_api_key


class AISyncError(Exception):
    pass


def extract_presentation_summary(pdf_path: str) -> List[Dict[str, Any]]:
    """Extracts text content for each slide to provide context to Gemini."""
    doc = pymupdf.open(pdf_path)
    slides_data = []

    for i, page in enumerate(doc):
        text = page.get_text().strip()
        clean_text = " ".join(text.split())
        if len(clean_text) > 400:
            clean_text = clean_text[:400] + "..."
        slides_data.append({
            "slide_number": i + 1,
            "text": clean_text if clean_text else "[Slide predominantemente visual / sem texto]"
        })

    doc.close()
    return slides_data


def synchronize_slides_with_gemini(
    pdf_path: str,
    audio_path: str,
    total_audio_duration: float,
    api_key: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[float]:
    """
    Sends presentation slide structure and narration audio to Gemini Flash
    to intelligently determine the optimal duration for each slide.
    """
    key = api_key or get_gemini_api_key()
    if not key:
        raise AISyncError(
            "Chave de API do Gemini não configurada.\n"
            "Clique no botão '🔑 Chave Gemini API' para informar sua chave gratuita."
        )

    from google import genai
    from google.genai import types

    if progress_callback:
        progress_callback("Lendo conteúdo dos slides do PDF...")

    slides_info = extract_presentation_summary(pdf_path)
    slide_count = len(slides_info)
    if slide_count == 0:
        raise AISyncError("O arquivo PDF não contém slides.")

    client = genai.Client(api_key=key)

    uploaded_audio = None
    try:
        if progress_callback:
            progress_callback("Enviando áudio para análise do Gemini...")

        uploaded_audio = client.files.upload(file=audio_path)

        if progress_callback:
            progress_callback("IA analisando a fala e sincronizando os slides...")

        slides_text_block = "\n".join(
            [f"- Slide {s['slide_number']}: {s['text']}" for s in slides_info]
        )

        prompt = f"""Você é um diretor de vídeo e especialista em sincronização audiovisual.
Recebeu uma apresentação de slides em PDF contendo {slide_count} slides e um arquivo de áudio de narração com duração total de exatamente {total_audio_duration:.2f} segundos.

Resumo dos {slide_count} slides da apresentação:
{slides_text_block}

Instruções:
1. Ouça com atenção o áudio e compreenda o fluxo da fala e as trocas de assunto do apresentador.
2. Identifique os momentos em que o apresentador começa a falar de cada slide e quando faz a transição para o próximo.
3. Determine a duração exata em segundos para CADA UM dos {slide_count} slides.
4. Cada slide deve ter pelo menos 1.0 segundo de duração.
5. A soma de todas as durações DEVE corresponder à duração total do áudio ({total_audio_duration:.2f} segundos).
6. Responda ESTRITAMENTE em formato JSON com a seguinte estrutura:
{{
  "durations": [duracao_slide_1, duracao_slide_2, ..., duracao_slide_{slide_count}],
  "explanation": "Breve justificativa de como os tópicos falados correspondem a cada slide"
}}
"""

        # Prioritize gemini-3.8-flash and gemini-3-flash-preview, with automatic fallbacks
        models_to_try = ["gemini-3.8-flash", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-flash-latest"]
        response = None
        last_err = None

        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        uploaded_audio,
                        prompt,
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.2,
                    ),
                )
                if response and response.text:
                    break
            except Exception as e:
                last_err = e
                continue

        if not response or not response.text:
            raise AISyncError(f"Falha ao obter resposta do Gemini: {last_err}")

        # Parse JSON
        result_data = json.loads(response.text)
        raw_durations = result_data.get("durations", [])

        if len(raw_durations) != slide_count:
            raise AISyncError(
                f"O modelo retornou {len(raw_durations)} durações, mas a apresentação possui {slide_count} slides."
            )

        # Ensure all are positive floats
        durations = [max(0.5, float(d)) for d in raw_durations]

        # Proportionally normalize to exact total_audio_duration
        current_sum = sum(durations)
        if current_sum > 0:
            scale_factor = total_audio_duration / current_sum
            durations = [round(d * scale_factor, 1) for d in durations]
            # Fix any micro rounding difference on the last slide
            diff = total_audio_duration - sum(durations)
            durations[-1] = max(0.5, round(durations[-1] + diff, 1))

        if progress_callback:
            progress_callback("Sincronização concluída com sucesso!")

        return durations

    except Exception as e:
        traceback.print_exc()
        raise AISyncError(f"Erro na sincronização com Gemini:\n{e}")
    finally:
        # Delete temporary uploaded audio file from Gemini Files API
        if uploaded_audio:
            try:
                client.files.delete(name=uploaded_audio.name)
            except Exception:
                pass
