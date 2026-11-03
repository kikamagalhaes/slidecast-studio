"""Regression test: podcast render must terminate (with and without BGM).

Bug history: with a looped background track (-stream_loop -1) the render ran
forever because the cover image is infinite (-loop 1) and no audio-driven
boundary fired. The builder now caps output at the narration duration.
"""
import subprocess

import pytest

from app.core.ffmpeg_utils import get_ffmpeg_paths, get_video_duration
from app.core.podcast_video_builder import build_podcast_video

ffmpeg, _ = get_ffmpeg_paths()
pytestmark = pytest.mark.skipif(not ffmpeg, reason="ffmpeg not available")


def _make_media(tmp_path):
    cover = tmp_path / "cover.jpg"
    voice = tmp_path / "voice.mp3"
    bgm = tmp_path / "bgm.mp3"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0x1a1a2e:s=640x640:d=1", "-frames:v", "1", str(cover)],
        check=True,
    )
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=5", str(voice)],
        check=True,
    )
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=110:duration=4", str(bgm)],
        check=True,
    )
    return str(cover), str(voice), str(bgm)


def test_podcast_render_with_bgm_terminates(tmp_path):
    cover, voice, bgm = _make_media(tmp_path)
    out = build_podcast_video(cover, voice, str(tmp_path / "out.mp4"), bgm_path=bgm)
    duration = get_video_duration(out)
    assert 4.0 <= duration <= 6.5, f"unexpected output duration: {duration}"


def test_podcast_render_without_bgm_terminates(tmp_path):
    cover, voice, _bgm = _make_media(tmp_path)
    out = build_podcast_video(cover, voice, str(tmp_path / "out.mp4"))
    duration = get_video_duration(out)
    assert 4.0 <= duration <= 6.5, f"unexpected output duration: {duration}"
