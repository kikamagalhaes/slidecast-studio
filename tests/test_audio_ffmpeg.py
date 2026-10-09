"""Tests for audio probing and ffmpeg helpers (generated WAV, no fixtures)."""

import math
import shutil
import struct
import wave

import sys
import threading
import time

import pytest

from app.core.audio_processor import get_audio_info
from app.core.ffmpeg_utils import format_duration, get_ffmpeg_paths, run_process_cancellable


def make_wav(path, seconds=1.0, rate=44100):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for i in range(frames):
            sample = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
            wav.writeframes(struct.pack("<h", sample))
    return str(path)


def test_get_audio_info_wav(tmp_path):
    audio = make_wav(tmp_path / "narr.wav", seconds=1.0)
    info = get_audio_info(audio)
    assert info.file_name == "narr.wav"
    assert info.duration == pytest.approx(1.0, abs=0.05)
    assert info.file_size_bytes > 0
    assert info.formatted_duration


def test_get_audio_info_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_audio_info(str(tmp_path / "nope.wav"))


def test_get_audio_info_garbage_raises(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_text("this is not audio", encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        get_audio_info(str(bad))


def test_format_duration():
    assert format_duration(0) == "00:00.0"
    assert format_duration(-5) == "00:00.0"
    assert format_duration(65.25) == "01:05.2"
    assert format_duration(3661) == "01:01:01"


def test_get_ffmpeg_paths_when_installed():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    ffmpeg, _ = get_ffmpeg_paths()
    assert ffmpeg


def test_run_process_cancellable_success():
    completed = run_process_cancellable([sys.executable, "-c", "print('hi')"])
    assert completed.returncode == 0
    assert "hi" in completed.stdout


def test_run_process_cancellable_nonzero_passthrough():
    completed = run_process_cancellable([sys.executable, "-c", "raise SystemExit(3)"])
    assert completed.returncode == 3


def test_run_process_cancellable_aborts_on_cancel():
    flag = {"cancel": False}

    def setter():
        time.sleep(0.5)
        flag["cancel"] = True

    thread = threading.Thread(target=setter)
    thread.start()
    try:
        start = time.monotonic()
        with pytest.raises(InterruptedError):
            run_process_cancellable(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cancel_check=lambda: flag["cancel"],
                poll_interval=0.1,
            )
        assert time.monotonic() - start < 10
    finally:
        thread.join()
