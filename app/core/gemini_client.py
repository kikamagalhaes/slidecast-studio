"""Shared Google Gemini client with automatic model fallback.

Every AI feature in SlideCast (slide synchronization, subtitles, e-books,
meeting summaries, image prompts, voice dictation) funnels through
:func:`generate_with_fallback` so the model list lives in exactly one place.

The ordered model list can be overridden without code changes via the
``GEMINI_MODELS`` environment variable (comma-separated, first = preferred)::

    GEMINI_MODELS="gemini-2.5-flash,gemini-flash-latest"
"""

import logging
import os
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)


class GeminiError(Exception):
    """Raised when every configured Gemini model failed."""


# Ordered by preference. Override with GEMINI_MODELS="model-a,model-b".
DEFAULT_GEMINI_MODELS = (
    "gemini-3.8-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-flash-latest",
)


def get_default_models() -> list:
    """Returns the ordered model list, honoring the GEMINI_MODELS override."""
    raw = os.environ.get("GEMINI_MODELS", "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        if models:
            return models
    return list(DEFAULT_GEMINI_MODELS)


def get_client(api_key: str):
    """Builds a ``google.genai`` client (import kept local for fast startup)."""
    from google import genai

    return genai.Client(api_key=api_key)


def generate_with_fallback(
    client: Any,
    contents: Any,
    config: Any = None,
    models: Optional[Sequence[str]] = None,
) -> Any:
    """Tries each model in order; returns the first response with text.

    :param client: ``genai.Client`` instance.
    :param contents: Prompt / uploaded-file contents for ``generate_content``.
    :param config: Optional ``GenerateContentConfig`` (or None).
    :param models: Optional explicit model order (defaults to
        :func:`get_default_models`).
    :raises GeminiError: If no model produced a usable response.
    """
    candidates = list(models) if models else get_default_models()
    last_err: Optional[BaseException] = None

    for model_name in candidates:
        try:
            kwargs = {"model": model_name, "contents": contents}
            if config is not None:
                kwargs["config"] = config
            response = client.models.generate_content(**kwargs)
            text = response.text if response is not None else None
            if text:
                logger.debug("Gemini answered with model %s", model_name)
                return response
            last_err = ValueError(f"model {model_name} returned an empty response")
            logger.warning("Gemini model %s returned empty text; trying next", model_name)
        except Exception as exc:  # noqa: BLE001 - fallback chain, error aggregated below
            last_err = exc
            logger.warning("Gemini model %s failed (%s); trying next", model_name, exc)

    raise GeminiError(
        f"All {len(candidates)} Gemini models failed. Last error: {last_err}"
    ) from last_err
