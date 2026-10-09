"""Edge-TTS isolation tests (stubbed network, real timeout behavior)."""

import time

import pytest

import app.core.avatar_video_generator as avatar


class _FakeCommunicate:
    behavior = "ok"  # ok | slow | boom
    seen = {}

    def __init__(self, text, voice):
        type(self).seen = {"text": text, "voice": voice}

    async def save(self, path):
        if type(self).behavior == "slow":
            time.sleep(5)
        elif type(self).behavior == "boom":
            raise ConnectionError("offline")
        with open(path, "wb") as handle:
            handle.write(b"FAKEAUDIO")


class _FakeEdgeTts:
    Communicate = _FakeCommunicate


@pytest.fixture()
def stubbed_tts(monkeypatch):
    _FakeCommunicate.behavior = "ok"
    monkeypatch.setattr(avatar, "edge_tts", _FakeEdgeTts)
    monkeypatch.setattr(avatar, "get_elevenlabs_api_key", lambda: None)
    return _FakeCommunicate


def test_synthesize_success(tmp_path, stubbed_tts):
    out = tmp_path / "voice.mp3"
    avatar.synthesize_edge_tts("olá", "pt-BR-FranciscaNeural", out, timeout=10)
    assert out.read_bytes() == b"FAKEAUDIO"
    assert stubbed_tts.seen == {"text": "olá", "voice": "pt-BR-FranciscaNeural"}


def test_synthesize_timeout(tmp_path, stubbed_tts):
    stubbed_tts.behavior = "slow"
    with pytest.raises(TimeoutError):
        avatar.synthesize_edge_tts("olá", "v", tmp_path / "o.mp3", timeout=0.3)


def test_generate_avatar_speech_wraps_network_errors(tmp_path, stubbed_tts):
    stubbed_tts.behavior = "boom"
    with pytest.raises(RuntimeError, match="conexão"):
        avatar.generate_avatar_speech("olá", str(tmp_path / "o.mp3"))


def test_generate_avatar_speech_happy_path(tmp_path, stubbed_tts):
    out = avatar.generate_avatar_speech(
        "olá", str(tmp_path / "o.mp3"), preferred_voice="pt-BR-AntonioNeural"
    )
    assert out.endswith("o.mp3")
    assert stubbed_tts.seen["voice"] == "pt-BR-AntonioNeural"


def test_edge_tts_timeout_env(monkeypatch):
    monkeypatch.delenv("EDGE_TTS_TIMEOUT", raising=False)
    assert avatar.edge_tts_timeout() == 180.0
    monkeypatch.setenv("EDGE_TTS_TIMEOUT", "42")
    assert avatar.edge_tts_timeout() == 42.0
    monkeypatch.setenv("EDGE_TTS_TIMEOUT", "bogus")
    assert avatar.edge_tts_timeout() == 180.0
