from pathlib import Path
from typing import Optional, Callable
from app.core.config_manager import get_gemini_api_key
from app.core.gemini_client import GeminiError, generate_with_fallback


class SubtitleGenerationError(Exception):
    pass


SUPPORTED_LANGUAGES = {
    "pt": "Português (Original)",
    "en": "Inglês (English)",
    "es": "Espanhol (Español)",
    "fr": "Francês (Français)",
    "de": "Alemão (Deutsch)",
    "it": "Italiano (Italiano)",
    "ja": "Japonês (日本語)",
    "zh": "Chinês (中文)",
    "ru": "Russo (Русский)",
}


def generate_subtitles_with_gemini(
    audio_path: str,
    output_srt_path: str,
    target_language: str = "pt",
    api_key: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Transcribes the recorded audio and formats it as an SRT subtitle file.
    If target_language is not Portuguese, translates the speech to the selected language.
    """
    key = api_key or get_gemini_api_key()
    if not key:
        raise SubtitleGenerationError("Chave de API do Gemini não configurada.")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)

    if progress_callback:
        progress_callback("Enviando áudio para transcrição com IA...")

    uploaded_audio = client.files.upload(file=audio_path)

    lang_name = SUPPORTED_LANGUAGES.get(target_language, "Português")
    is_translation = target_language != "pt"

    if is_translation:
        task_instruction = (
            f"Transcreva a fala com marcas de tempo e TRADUZA as legendas para o idioma: {lang_name}."
        )
    else:
        task_instruction = "Transcreva a fala original em Português com marcas de tempo precisas."

    prompt = f"""Você é um especialista profissional em legendagem e transcrição audiovisual.
Ouça com máxima atenção o áudio gravado da aula e gere um arquivo de legendas no formato padrão SRT (SubRip).

{task_instruction}

Regras obrigatórias:
1. Formato estritamente no padrão SRT, iniciando no número 1:
1
00:00:00,500 --> 00:00:03,800
Texto da legenda aqui...

2
00:00:04,100 --> 00:00:07,500
Continuação da fala...

2. Mantenha as frases curtas, fáceis de ler (máximo de 2 linhas por legenda e até 40 caracteres por linha).
3. Sincronize exatamente com o início e o fim de cada frase dita pelo professor.
4. Responda SOMENTE o bloco de texto SRT, sem blocos de markdown explicativos adicionais.
"""

    if progress_callback:
        progress_callback("IA gerando e sincronizando legendas...")

    try:
        response = generate_with_fallback(
            client,
            contents=[uploaded_audio, prompt],
            config=types.GenerateContentConfig(temperature=0.1),
        )
    except GeminiError as exc:
        raise SubtitleGenerationError(f"Falha ao gerar legendas com Gemini: {exc}")
    finally:
        try:
            client.files.delete(name=uploaded_audio.name)
        except Exception:
            pass

    raw_text = response.text.strip()
    # Clean markdown code blocks if model wrapped it in ```srt ... ```
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_text = "\n".join(lines).strip()

    out_file = Path(output_srt_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(raw_text)

    if progress_callback:
        progress_callback("Legendas geradas com sucesso!")

    return str(out_file)
