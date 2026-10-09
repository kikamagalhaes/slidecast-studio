"""Podcast builder: SRT wiring regression test + a real no-subtitle render.

Regression: ``build_podcast_video`` used to call the subtitle generator
without the required ``output_srt_path`` argument, so podcast subtitles
silently never worked. The first test pins the call contract with stubs
(no ffmpeg needed); the second exercises a real ffmpeg render.
"""

import math
import shutil
import struct
import wave

import pymupdf
import pytest

import app.core.podcast_video_builder as podcast_builder


def make_cover_png(path, width=320, height=240):
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(pymupdf.Rect(0, 0, width, height), fill=(0.05, 0.07, 0.12))
    page.insert_text((40, 120), "Podcast Cover", fontsize=28, color=(1, 1, 1))
    pix = page.get_pixmap()
    pix.save(str(path))
    doc.close()
    return str(path)


def make_wav(path, seconds=1.0, rate=22050):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for i in range(frames):
            sample = int(8000 * math.sin(2 * math.pi * 220 * i / rate))
            wav.writeframes(struct.pack("<h", sample))
    return str(path)


class _FakePopen:
    instance = None

    def __init__(self, cmd, **kwargs):
        type(self).instance = self
        self.cmd = cmd
        self.returncode = 0

    def communicate(self, timeout=None):
        return "", ""

    def poll(self):
        return 0

    def kill(self):
        pass


def test_subtitle_generator_receives_output_path(tmp_path, monkeypatch):
    recorded = {}

    def fake_subtitles(*, audio_path, output_srt_path, target_language="pt", **kwargs):
        recorded["audio_path"] = audio_path
        recorded["output_srt_path"] = output_srt_path
        recorded["target_language"] = target_language
        with open(output_srt_path, "w", encoding="utf-8") as handle:
            handle.write("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        return output_srt_path

    monkeypatch.setattr(podcast_builder, "generate_subtitles_with_gemini", fake_subtitles)
    monkeypatch.setattr("subprocess.Popen", _FakePopen)

    out = podcast_builder.build_podcast_video(
        cover_image_path=str(tmp_path / "cover.png"),
        narration_audio_path=str(tmp_path / "narr.wav"),
        output_video_path=str(tmp_path / "out.mp4"),
        enable_subtitles=True,
        subtitles_language="en",
    )

    assert out.endswith("out.mp4")
    assert recorded["output_srt_path"].endswith(".srt")  # the missing kwarg, pinned
    assert recorded["target_language"] == "en"
    cmd = _FakePopen.instance.cmd
    joined = " ".join(cmd)
    assert "subtitles=" in joined  # the SRT is actually burned into the filter


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_real_render_without_subtitles(tmp_path):
    cover = make_cover_png(tmp_path / "cover.png")
    audio = make_wav(tmp_path / "narr.wav", seconds=1.0)
    out = podcast_builder.build_podcast_video(
        cover_image_path=cover,
        narration_audio_path=audio,
        output_video_path=str(tmp_path / "pod.mp4"),
        enable_subtitles=False,
    )
    data = open(out, "rb").read()
    assert len(data) > 1000
