"""Tests for config precedence (env wins) and the JSON config file."""

import json

import app.core.config_manager as config_manager


def test_gemini_env_takes_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "  env-key-123  ")
    assert config_manager.get_gemini_api_key() == "env-key-123"


def test_gemini_file_roundtrip_isolated(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(config_manager, "get_config_dir", lambda: tmp_path)
    assert config_manager.get_gemini_api_key() is None
    config_manager.set_gemini_api_key("  file-key-456  ")
    assert config_manager.get_gemini_api_key() == "file-key-456"
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["gemini_api_key"] == "file-key-456"


def test_image_provider_default(monkeypatch, tmp_path):
    monkeypatch.setattr(config_manager, "get_config_dir", lambda: tmp_path)
    assert config_manager.get_image_provider() == "auto"
    config_manager.set_image_provider("openai")
    assert config_manager.get_image_provider() == "openai"
