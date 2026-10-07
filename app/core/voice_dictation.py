import time
from pathlib import Path
from typing import Optional
from app.core.config_manager import get_gemini_api_key


def transcribe_voice_prompt(audio_path: str, api_key: Optional[str] = None) -> str:
    """
    Transcribes a voice audio recording using Gemini Flash into text
    to be used directly as a prompt for image/presentation generation.
    """
    key = api_key or get_gemini_api_key()
    if not key:
        raise ValueError("Chave de API do Gemini não configurada.")

    from google import genai

    client = genai.Client(api_key=key)

    uploaded = client.files.upload(file=audio_path)

    prompt = (
        "Você é um transcrevedor de fala de alta precisão especializado em comandos e prompts em português. "
        "Ouça o áudio gravado pelo usuário e transcreva exatamente o que foi dito. "
        "Retorne APENAS o texto da fala em português, com pontuação adequada, sem aspas, "
        "sem frases introdutórias como 'o áudio diz' e sem observações. Retorne estritamente o texto falado."
    )

    models = [
        "gemini-3.8-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-flash-latest",
    ]

    for m in models:
        try:
            resp = client.models.generate_content(model=m, contents=[uploaded, prompt])
            if resp.text:
                clean_text = resp.text.strip().strip('"').strip("'")
                return clean_text
        except Exception:
            continue

    raise RuntimeError("Não foi possível transcrever a gravação de voz com o Gemini.")
