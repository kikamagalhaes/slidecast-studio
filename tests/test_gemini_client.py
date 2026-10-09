"""Tests for the shared Gemini fallback client (fully stubbed, no network)."""

import pytest

from app.core.gemini_client import (
    DEFAULT_GEMINI_MODELS,
    GeminiError,
    generate_with_fallback,
    get_default_models,
)


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, script):
        # script: {model_name: text | Exception}
        self.script = script
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcome = self.script[model]
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)


class _FakeClient:
    def __init__(self, script):
        self.models = _FakeModels(script)


def test_first_model_wins():
    client = _FakeClient({"m1": "hello", "m2": "unused"})
    resp = generate_with_fallback(client, contents="prompt", models=["m1", "m2"])
    assert resp.text == "hello"
    assert [c["model"] for c in client.models.calls] == ["m1"]


def test_falls_through_to_next_model_on_error():
    client = _FakeClient({"m1": RuntimeError("boom"), "m2": "recovered"})
    resp = generate_with_fallback(client, contents="prompt", models=["m1", "m2"])
    assert resp.text == "recovered"
    assert [c["model"] for c in client.models.calls] == ["m1", "m2"]


def test_empty_text_counts_as_failure():
    client = _FakeClient({"m1": "", "m2": "second"})
    resp = generate_with_fallback(client, contents="prompt", models=["m1", "m2"])
    assert resp.text == "second"


def test_all_models_failing_raises():
    client = _FakeClient({"m1": RuntimeError("a"), "m2": RuntimeError("b")})
    with pytest.raises(GeminiError) as exc_info:
        generate_with_fallback(client, contents="prompt", models=["m1", "m2"])
    assert "b" in str(exc_info.value)


def test_config_is_forwarded():
    client = _FakeClient({"m1": "ok"})
    generate_with_fallback(client, contents="p", config={"t": 0.1}, models=["m1"])
    assert client.models.calls[0]["config"] == {"t": 0.1}


def test_default_models_and_env_override(monkeypatch):
    monkeypatch.delenv("GEMINI_MODELS", raising=False)
    assert get_default_models() == list(DEFAULT_GEMINI_MODELS)
    monkeypatch.setenv("GEMINI_MODELS", "custom-a, custom-b")
    assert get_default_models() == ["custom-a", "custom-b"]
    monkeypatch.setenv("GEMINI_MODELS", "   ")
    assert get_default_models() == list(DEFAULT_GEMINI_MODELS)
