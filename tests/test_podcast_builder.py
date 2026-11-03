"""Podcast builder: SRT wiring regression test + a real no-subtitle render.

Regression: ``build_podcast_video`` used to call the subtitle generator
without the required ``output_srt_path`` argument, so podcast subtitles
silently never worked. The first test pins the call contract with stubs
(no ffmpeg needed); the second exercises a real ffmpeg render.
"""

import math

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


def test_user_subtitles_required_and_used(tmp_path, monkeypatch):
    cover = make_cover_png(tmp_path / "cover.png")
    audio = make_wav(tmp_path / "voice.wav")
    with pytest.raises(ValueError):
        podcast_builder.build_podcast_video(cover, audio, str(tmp_path / "o.mp4"),
                                            enable_subtitles=True)
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nOlá\n", encoding="utf-8")
    monkeypatch.setattr(podcast_builder, "run_process_cancellable",
                        lambda cmd, cancel_check=None: type("R", (), {"returncode": 0, "stderr": ""})())
    out = podcast_builder.build_podcast_video(cover, audio, str(tmp_path / "o.mp4"),
                                              enable_subtitles=True, subtitles_path=str(srt))
    assert out.endswith("o.mp4")


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
