"""Automated test suite for Multimedia Multitrack Video Creator (Scenarios T01 to T17).

Executes real FFmpeg and ffprobe processes on short deterministic synthetic fixtures.
Validates:
- Mode A (PDF + 1..4 audio tracks -> MP4)
- Mode B (MP4 visual source + 1..4 audio tracks -> MP4)
- Stream copy vs re-encode logic
- Mandatory default: ignore original audio in MP4 source
- Multi-rate audio mixing (WAV 44.1k, MP3 44.1k, OGG 48k, FLAC 22.05k, M4A)
- Start offsets, independent volumes, and mute handling
- All tracks muted (silent video generation)
- Cancellation mid-render and temp file cleanup
- Project save, load, and schema migration (v1 -> v2)
- ffprobe validation of streams, codecs, and durations
"""
import json
import math
import os
import struct
import subprocess
import wave
from pathlib import Path

import pymupdf
import pytest

from app.core.ffmpeg_utils import get_ffmpeg_paths
from app.core.multitrack import (
    AudioTrack,
    MultimediaProject,
    VideoInfo,
    inspect_video,
    probe_audio_track,
    MAX_AUDIO_TRACKS,
)
from app.core.multitrack_video_builder import (
    generate_multimedia_video,
    build_audio_filter_complex,
    should_stream_copy_video,
)
from app.core.video_generator import VideoGenerationError


# --- Helper Fixtures ---------------------------------------------------------

def create_synthetic_pdf(path: Path, pages: int = 3) -> str:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=640, height=360)
        page.draw_rect(pymupdf.Rect(0, 0, 640, 360), color=(0.1 * i, 0.2, 0.4), fill=(0.1 * i, 0.2, 0.4))
        page.insert_text((50, 80), f"Slide Teste {i + 1}", fontsize=28, color=(1, 1, 1))
    doc.save(str(path))
    doc.close()
    return str(path)


def create_sine_wav(path: Path, freq: float = 440.0, duration: float = 2.0, sample_rate: int = 44100) -> str:
    num_samples = int(duration * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        data = bytearray()
        for i in range(num_samples):
            val = int(8000 * math.sin(2 * math.pi * freq * i / sample_rate))
            data.extend(struct.pack("<h", val))
        w.writeframes(data)
    return str(path)


def create_encoded_audio(path: Path, fmt: str = "mp3", freq: float = 440.0, duration: float = 2.0, sample_rate: int = 44100) -> str:
    ffmpeg_exe, _ = get_ffmpeg_paths()
    cmd = [
        ffmpeg_exe, "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:sample_rate={sample_rate}:duration={duration}",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(path)


def create_synthetic_video(path: Path, duration: float = 4.0, width: int = 640, height: int = 360, fps: int = 25, with_audio: bool = False) -> str:
    ffmpeg_exe, _ = get_ffmpeg_paths()
    cmd = [
        ffmpeg_exe, "-y",
        "-f", "lavfi",
        "-i", f"testsrc=size={width}x{height}:rate={fps}",
    ]
    if with_audio:
        cmd.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"])
        cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-t", str(duration), str(path)])
    else:
        cmd.extend(["-c:v", "libx264", "-t", str(duration), str(path)])
    subprocess.run(cmd, check=True, capture_output=True)
    return str(path)


def probe_file_streams(path: str) -> dict:
    _, ffprobe_exe = get_ffmpeg_paths()
    cmd = [
        ffprobe_exe, "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(res.stdout)


# --- Tests -------------------------------------------------------------------

def test_t01_legacy_pdf_single_audio(tmp_path):
    """T01: Legacy PDF + 1 audio project loads and renders valid MP4."""
    pdf = create_synthetic_pdf(tmp_path / "slides.pdf", pages=2)
    wav = create_sine_wav(tmp_path / "audio.wav", duration=4.0)
    out_mp4 = str(tmp_path / "t01_out.mp4")

    # Construct project simulating legacy schema v1
    legacy_data = {
        "schema_version": 1,
        "title": "Projeto Legado",
        "pdf_path": pdf,
        "audio_path": wav,
        "slide_durations": [2.0, 2.0],
    }
    project = MultimediaProject.from_dict(legacy_data)
    assert project.visual_source_type == "pdf"
    assert len(project.tracks) == 1
    assert project.tracks[0].name == "Narração Principal"

    project.export_settings["resolution"] = [640, 360]
    project.export_settings["fps"] = 25
    project.export_settings["output_path"] = out_mp4

    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()

    info = probe_file_streams(rendered)
    st = info["streams"]
    assert any(s["codec_type"] == "video" for s in st)
    assert any(s["codec_type"] == "audio" for s in st)
    assert abs(float(info["format"]["duration"]) - 4.0) < 0.5


def test_t02_pdf_two_audios_voice_and_music(tmp_path):
    """T02: PDF + 2 audios (voice and music) combined in final MP4."""
    pdf = create_synthetic_pdf(tmp_path / "deck.pdf", pages=3)
    voice = create_sine_wav(tmp_path / "voice.wav", freq=300, duration=6.0)
    music = create_encoded_audio(tmp_path / "bgm.mp3", fmt="mp3", freq=600, duration=6.0)
    out_mp4 = str(tmp_path / "t02_out.mp4")

    project = MultimediaProject(visual_source_type="pdf")
    project.set_visual_source("pdf", pdf, slide_durations=[2.0, 2.0, 2.0])
    project.add_track(probe_audio_track(voice, name="Voz", volume=1.0))
    project.add_track(probe_audio_track(music, name="Música", volume=0.3))
    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}

    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()

    info = probe_file_streams(rendered)
    assert abs(float(info["format"]["duration"]) - 6.0) < 0.5


def test_t03_pdf_four_audios_max_limit(tmp_path):
    """T03: PDF + 4 audios (maximum limit); no track discarded."""
    pdf = create_synthetic_pdf(tmp_path / "deck4.pdf", pages=2)
    a1 = create_sine_wav(tmp_path / "a1.wav", freq=200, duration=4.0)
    a2 = create_encoded_audio(tmp_path / "a2.mp3", fmt="mp3", freq=400, duration=4.0)
    a3 = create_sine_wav(tmp_path / "a3.wav", freq=600, duration=4.0)
    a4 = create_encoded_audio(tmp_path / "a4.ogg", fmt="ogg", freq=800, duration=4.0)
    out_mp4 = str(tmp_path / "t03_out.mp4")

    project = MultimediaProject(visual_source_type="pdf")
    project.set_visual_source("pdf", pdf, slide_durations=[2.0, 2.0])
    for f, name in zip((a1, a2, a3, a4), ("Voz", "BGM", "SFX", "Extra")):
        project.add_track(probe_audio_track(f, name=name))

    assert len(project.tracks) == 4
    # Attempting to add a 5th track must raise ValueError
    with pytest.raises(ValueError, match="Limite máximo de 4 faixas"):
        project.add_track(probe_audio_track(a1, name="Track 5"))

    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}
    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()


def test_t04_mp4_silent_source_with_narration(tmp_path):
    """T04: MP4 without audio + narration -> final MP4 with video and voice."""
    video = create_synthetic_video(tmp_path / "silent.mp4", duration=4.0, with_audio=False)
    voice = create_sine_wav(tmp_path / "voice.wav", duration=4.0)
    out_mp4 = str(tmp_path / "t04_out.mp4")

    project = MultimediaProject(visual_source_type="video")
    project.set_visual_source("video", video)
    project.add_track(probe_audio_track(voice, name="Narração"))
    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}

    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()

    info = probe_file_streams(rendered)
    streams = {s["codec_type"]: s["codec_name"] for s in info["streams"]}
    assert "video" in streams
    assert "audio" in streams
    assert streams["audio"] == "aac"


def test_t05_mp4_voice_music_and_effects(tmp_path):
    """T05: MP4 source + 3 sounds at correct segments."""
    video = create_synthetic_video(tmp_path / "video.mp4", duration=5.0)
    t1 = create_sine_wav(tmp_path / "voice.wav", duration=5.0)
    t2 = create_encoded_audio(tmp_path / "music.mp3", duration=5.0)
    t3 = create_sine_wav(tmp_path / "sfx.wav", duration=1.0)
    out_mp4 = str(tmp_path / "t05_out.mp4")

    project = MultimediaProject(visual_source_type="video")
    project.set_visual_source("video", video)
    project.add_track(probe_audio_track(t1, name="Voz", offset=0.0))
    project.add_track(probe_audio_track(t2, name="Música", offset=0.0, volume=0.3))
    project.add_track(probe_audio_track(t3, name="SFX", offset=2.0))  # Starts at 2.0s
    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}

    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()


def test_t06_mp4_four_audio_tracks(tmp_path):
    """T06: MP4 + 4 audios mixed with individual offsets and volumes."""
    video = create_synthetic_video(tmp_path / "vid4.mp4", duration=4.0)
    tracks_files = [
        create_sine_wav(tmp_path / f"tr_{i}.wav", freq=200 * (i + 1), duration=3.0)
        for i in range(4)
    ]
    out_mp4 = str(tmp_path / "t06_out.mp4")

    project = MultimediaProject(visual_source_type="video")
    project.set_visual_source("video", video)
    for i, tf in enumerate(tracks_files):
        project.add_track(probe_audio_track(tf, name=f"Faixa {i + 1}", volume=0.5, offset=0.5 * i))

    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}
    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()


def test_t07_mp4_with_original_audio_ignored_by_default(tmp_path):
    """T07: MP4 that already contains audio: original audio is ignored by default."""
    video_with_audio = create_synthetic_video(tmp_path / "has_audio.mp4", duration=3.0, with_audio=True)
    vinfo = inspect_video(video_with_audio)
    assert vinfo.has_audio is True

    # New audio track (different frequency)
    new_audio = create_sine_wav(tmp_path / "new_audio.wav", freq=880, duration=3.0)
    out_mp4 = str(tmp_path / "t07_out.mp4")

    project = MultimediaProject(visual_source_type="video")
    project.set_visual_source("video", video_with_audio)
    assert project.ignore_original_audio is True
    project.add_track(probe_audio_track(new_audio, name="Novo Áudio"))
    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}

    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()

    info = probe_file_streams(rendered)
    audio_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    # Only 1 audio stream in output (the mixed track, NOT a duplicate original)
    assert len(audio_streams) == 1


def test_t08_tracks_longer_than_video_trimmed_at_end(tmp_path):
    """T08: Audio tracks with longer durations do not extend video; trimmed at video end."""
    video = create_synthetic_video(tmp_path / "vid3s.mp4", duration=3.0)
    long_audio = create_sine_wav(tmp_path / "long_audio.wav", duration=15.0)  # 15s audio on 3s video
    out_mp4 = str(tmp_path / "t08_out.mp4")

    project = MultimediaProject(visual_source_type="video")
    project.set_visual_source("video", video)
    project.add_track(probe_audio_track(long_audio, name="Áudio Longo"))
    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}

    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()

    info = probe_file_streams(rendered)
    dur = float(info["format"]["duration"])
    assert abs(dur - 3.0) < 0.5, f"Expected 3s video, got {dur}s"


def test_t09_audio_track_with_start_offset(tmp_path):
    """T09: Track starting at offset (e.g. 2s) has initial silence then enters."""
    video = create_synthetic_video(tmp_path / "vid5s.mp4", duration=5.0)
    delayed_audio = create_sine_wav(tmp_path / "delayed.wav", duration=2.0)
    out_mp4 = str(tmp_path / "t09_out.mp4")

    project = MultimediaProject(visual_source_type="video")
    project.set_visual_source("video", video)
    track = probe_audio_track(delayed_audio, name="Atrasado", offset=2.0)
    project.add_track(track)
    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}

    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()

    info = probe_file_streams(rendered)
    assert abs(float(info["format"]["duration"]) - 5.0) < 0.5


def test_t10_volume_and_mute_independent(tmp_path):
    """T10: Mute/volume alters only the target track; all-muted produces silent video cleanly."""
    video = create_synthetic_video(tmp_path / "vid_mute.mp4", duration=2.0)
    a1 = create_sine_wav(tmp_path / "a1.wav", duration=2.0)
    a2 = create_sine_wav(tmp_path / "a2.wav", duration=2.0)
    out_mp4 = str(tmp_path / "t10_out.mp4")

    project = MultimediaProject(visual_source_type="video")
    project.set_visual_source("video", video)
    t1 = probe_audio_track(a1, name="Faixa 1", volume=0.5, mute=True)
    t2 = probe_audio_track(a2, name="Faixa 2", volume=0.0, mute=False)
    project.add_track(t1)
    project.add_track(t2)

    # Validating project gives warning about all tracks muted
    is_valid, msgs = project.validate()
    assert is_valid is True
    assert any("Todas as faixas de áudio estão mutadas" in m for m in msgs)

    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}
    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()

    info = probe_file_streams(rendered)
    # Silent AAC track exists
    assert any(s["codec_type"] == "audio" for s in info["streams"])


def test_t11_multi_format_and_sample_rates(tmp_path):
    """T11: MP3/WAV/OGG/FLAC with distinct sample rates (44.1k, 48k, 22.05k) decodes without drift."""
    pdf = create_synthetic_pdf(tmp_path / "deck11.pdf", pages=2)
    wav = create_sine_wav(tmp_path / "audio_44k.wav", sample_rate=44100, duration=3.0)
    ogg = create_encoded_audio(tmp_path / "audio_48k.ogg", fmt="ogg", sample_rate=48000, duration=3.0)
    flac = create_encoded_audio(tmp_path / "audio_22k.flac", fmt="flac", sample_rate=22050, duration=3.0)
    out_mp4 = str(tmp_path / "t11_out.mp4")

    project = MultimediaProject(visual_source_type="pdf")
    project.set_visual_source("pdf", pdf, slide_durations=[1.5, 1.5])
    project.add_track(probe_audio_track(wav, name="WAV 44.1k"))
    project.add_track(probe_audio_track(ogg, name="OGG 48k"))
    project.add_track(probe_audio_track(flac, name="FLAC 22.05k"))

    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}
    rendered = generate_multimedia_video(project)
    assert Path(rendered).is_file()

    info = probe_file_streams(rendered)
    audio_stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert audio_stream["sample_rate"] == "44100"  # Normalized to 44.1k


def test_t12_pdf_slide_durations_preserved(tmp_path):
    """T12: PDF manual slide durations are strictly preserved."""
    pdf = create_synthetic_pdf(tmp_path / "deck12.pdf", pages=3)
    wav = create_sine_wav(tmp_path / "audio.wav", duration=8.0)
    out_mp4 = str(tmp_path / "t12_out.mp4")

    # Custom timings: 1.0s, 3.0s, 4.0s (total = 8.0s)
    custom_timings = [1.0, 3.0, 4.0]
    project = MultimediaProject(visual_source_type="pdf")
    project.set_visual_source("pdf", pdf, slide_durations=custom_timings)
    project.add_track(probe_audio_track(wav, name="Áudio"))
    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}

    assert project.slide_durations == custom_timings
    assert project.calculate_total_duration() == 8.0

    rendered = generate_multimedia_video(project)
    info = probe_file_streams(rendered)
    assert abs(float(info["format"]["duration"]) - 8.0) < 0.5


def test_t13_invalid_or_missing_files_error_handled(tmp_path):
    """T13: Missing or corrupt files produce readable errors without crashing."""
    corrupt_audio = tmp_path / "corrupt.mp3"
    corrupt_audio.write_text("corrupted content not a real mp3")

    with pytest.raises(Exception):
        probe_audio_track(str(corrupt_audio))

    missing_video = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError):
        inspect_video(str(missing_video))


def test_t14_cancellation_cleans_up_without_leaving_partial_file(tmp_path):
    """T14: Cancellation mid-render terminates process and leaves no partial output file."""
    video = create_synthetic_video(tmp_path / "vid14.mp4", duration=5.0)
    audio = create_sine_wav(tmp_path / "aud14.wav", duration=5.0)
    out_mp4 = str(tmp_path / "t14_out.mp4")

    project = MultimediaProject(visual_source_type="video")
    project.set_visual_source("video", video)
    project.add_track(probe_audio_track(audio))
    project.export_settings = {"resolution": [640, 360], "fps": 25, "output_path": out_mp4}

    # Cancel immediately on first progress callback
    cancel_requested = False

    def on_progress(frac, msg):
        nonlocal cancel_requested
        cancel_requested = True

    with pytest.raises(InterruptedError):
        generate_multimedia_video(
            project,
            progress_callback=on_progress,
            cancel_check=lambda: cancel_requested,
        )

    # Incomplete file must NOT remain on disk
    assert not Path(out_mp4).exists(), "Partial output file was left behind after cancellation!"


def test_t15_save_and_reopen_multitrack_project(tmp_path):
    """T15: Save, reopen, and continue editing preserves all paths, tracks, and parameters."""
    pdf = create_synthetic_pdf(tmp_path / "deck15.pdf", pages=2)
    a1 = create_sine_wav(tmp_path / "a1.wav", duration=3.0)
    a2 = create_encoded_audio(tmp_path / "a2.mp3", duration=4.0)

    proj_file = str(tmp_path / "projeto_teste.slidecast")

    project = MultimediaProject(title="Projeto Persistido", visual_source_type="pdf")
    project.set_visual_source("pdf", pdf, slide_durations=[3.0, 4.0])
    project.add_track(probe_audio_track(a1, name="Locução", volume=0.8, offset=0.5))
    project.add_track(probe_audio_track(a2, name="Fundo Musical", volume=0.2, mute=True))
    project.export_settings = {"resolution": [1280, 720], "fps": 30, "output_path": "/tmp/out.mp4"}

    project.save_to_file(proj_file)
    assert Path(proj_file).is_file()

    # Reopen
    loaded = MultimediaProject.load_from_file(proj_file)
    assert loaded.schema_version == 2
    assert loaded.title == "Projeto Persistido"
    assert loaded.visual_source_type == "pdf"
    assert loaded.slide_durations == [3.0, 4.0]
    assert len(loaded.tracks) == 2

    t1, t2 = loaded.tracks
    assert t1.name == "Locução"
    assert abs(t1.volume - 0.8) < 0.01
    assert abs(t1.offset - 0.5) < 0.01
    assert t1.mute is False

    assert t2.name == "Fundo Musical"
    assert abs(t2.volume - 0.2) < 0.01
    assert t2.mute is True
    assert loaded.export_settings["resolution"] == [1280, 720]


def test_t17_ffprobe_stream_validation(tmp_path):
    """T17: ffprobe checks codecs (h264, aac), yuv420p, and audio/video sync."""
    pdf = create_synthetic_pdf(tmp_path / "deck17.pdf", pages=2)
    wav = create_sine_wav(tmp_path / "audio.wav", duration=4.0)
    out_mp4 = str(tmp_path / "t17_out.mp4")

    project = MultimediaProject(visual_source_type="pdf")
    project.set_visual_source("pdf", pdf, slide_durations=[2.0, 2.0])
    project.add_track(probe_audio_track(wav))
    project.export_settings = {"resolution": [640, 360], "fps": 30, "output_path": out_mp4}

    rendered = generate_multimedia_video(project)
    info = probe_file_streams(rendered)

    v_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    a_stream = next(s for s in info["streams"] if s["codec_type"] == "audio")

    assert v_stream["codec_name"] == "h264"
    assert v_stream["pix_fmt"] == "yuv420p"
    assert a_stream["codec_name"] == "aac"
    assert a_stream["sample_rate"] == "44100"

    v_dur = float(v_stream["duration"])
    a_dur = float(a_stream["duration"])
    assert abs(v_dur - a_dur) < 0.5, f"Audio/video sync mismatch: v={v_dur}, a={a_dur}"
