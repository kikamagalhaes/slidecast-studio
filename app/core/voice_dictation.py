from typing import Optional
from app.core.config_manager import get_gemini_api_key
from app.core.gemini_client import GeminiError, generate_with_fallback


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

    try:
        try:
            resp = generate_with_fallback(client, contents=[uploaded, prompt])
        except GeminiError as exc:
            raise RuntimeError(f"Não foi possível transcrever a gravação de voz: {exc}")
        return resp.text.strip().strip('"').strip("'")
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
