"""Tests for meeting-notes parsing and the no-key default path."""

import app.core.meeting_recorder as meeting_recorder
from app.core.meeting_recorder import generate_meeting_notes, parse_meeting_response


def test_parse_with_markers():
    text = (
        "=== RESUMO EXECUTIVO ===\nDecidimos X.\n\n"
        "=== TRANSCRIÇÃO INTEGRAL ===\nAlice: oi\nBob: olá"
    )
    result = parse_meeting_response(text)
    assert result["summary"] == "Decidimos X."
    assert result["transcription"] == "Alice: oi\nBob: olá"


def test_parse_without_markers():
    result = parse_meeting_response("  texto corrido  ")
    assert result["summary"] == "texto corrido"
    assert "inclusa no resumo" in result["transcription"]


def test_parse_empty():
    result = parse_meeting_response("")
    assert result["summary"] == ""


def test_default_path_without_api_key(monkeypatch):
    monkeypatch.setattr(meeting_recorder, "get_gemini_api_key", lambda: None)
    result = generate_meeting_notes("/nonexistent/audio.aac", "Sprint 12")
    assert "Sprint 12" in result["summary"]
    assert result["transcription"]
