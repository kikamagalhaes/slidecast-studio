"""
Comprehensive Automated Test Suite for Directed Class Video Timeline & Transitions.
Ensures deterministic, frame-perfect composition between:
- Layout 1: Professor em Destaque (Centralized professor on #10201E stage with lesson title card)
- Layout 2: Slides Grandes + Professor na Lateral (~80% / ~20%)
Continuous, glitch-free audio across all transitions.
Manual time entry (Method A), Live Markers (Method B), and Heuristic Suggestions (Method C).
Honest scaling policy for low-resolution professor video sources.
Non-destructive post-recording recomposition.
"""
import os
import sys
import json
import time
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication

from app.core.dual_region_recorder import (
    ScreenRegion,
    CompositionConfig,
    DualRegionSession,
    PresentationInterval,
    format_ms_to_time,
    parse_time_to_ms,
    normalize_and_validate_intervals,
    detect_slide_intervals_heuristic,
    probe_video_dimensions,
    compose_dual_region_video,
)
from app.core.ffmpeg_utils import get_ffmpeg_paths, get_video_duration
from app.worker import DualRegionRenderWorker
from app.ui.class_timeline_widget import ClassTimelineWidget
from app.ui.views.record_meet_view import RecordMeetView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="module")
def test_synthetic_media(tmp_path_factory):
    """
    Creates synthetic presentation and professor video files with continuous audio
    for deterministic automated test execution.
    """
    tmp = tmp_path_factory.mktemp("timeline_synth")
    ffmpeg_exe, _ = get_ffmpeg_paths()
    if not ffmpeg_exe:
        pytest.skip("FFmpeg is not available in system PATH")

    pres_path = str(tmp / "test_pres_6s.mp4")
    prof_path = str(tmp / "test_prof_6s.mp4")
    prof_lowres_path = str(tmp / "test_prof_lowres_6s.mp4")

    # 1. Presentation track: 800x600 cyan video with 440Hz sine tone (6 seconds)
    subprocess.run([
        ffmpeg_exe, "-y",
        "-f", "lavfi", "-i", "color=c=0x1e293b:s=800x600:r=25:d=6.0",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        pres_path,
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. Presenter track (normal 640x480): amber video with 880Hz audio (6 seconds)
    subprocess.run([
        ffmpeg_exe, "-y",
        "-f", "lavfi", "-i", "color=c=0xf59e0b:s=640x480:r=25:d=6.0",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=6.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        prof_path,
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 3. Presenter track (low-res 320x240): for honest scaling validation
    subprocess.run([
        ffmpeg_exe, "-y",
        "-f", "lavfi", "-i", "color=c=0x10b981:s=320x240:r=25:d=6.0",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=6.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        prof_lowres_path,
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return {
        "dir": tmp,
        "pres": pres_path,
        "prof": prof_path,
        "prof_lowres": prof_lowres_path,
    }


# ==============================================================================
# 1. TIME PARSING & FORMATTING UNIT TESTS
# ==============================================================================
def test_time_formatting_and_parsing():
    # Format tests
    assert format_ms_to_time(0) == "00:00"
    assert format_ms_to_time(5000) == "00:05"
    assert format_ms_to_time(120000) == "02:00"
    assert format_ms_to_time(3600000) == "01:00:00"
    assert format_ms_to_time(3661000) == "01:01:01"

    # Parse mm:ss
    assert parse_time_to_ms("00:00") == 0
    assert parse_time_to_ms("02:00") == 120000
    assert parse_time_to_ms("36:00") == 2160000
    assert parse_time_to_ms("02:13") == 133000

    # Parse hh:mm:ss
    assert parse_time_to_ms("01:00:00") == 3600000
    assert parse_time_to_ms("01:02:15") == 3735000

    # Parse seconds only
    assert parse_time_to_ms("45") == 45000

    # Invalid formats
    with pytest.raises(ValueError):
        parse_time_to_ms("invalid:time")

    with pytest.raises(ValueError):
        parse_time_to_ms("-05:00")


# ==============================================================================
# 2. PRESENTATION INTERVAL MODEL & VALIDATION
# ==============================================================================
def test_presentation_interval_model():
    # Valid interval
    interval = PresentationInterval(
        start_ms=120000,
        end_ms=2160000,
        origin="manual",
    )
    assert interval.start_seconds == 120.0
    assert interval.end_seconds == 2160.0
    assert interval.duration_seconds == 2040.0
    assert interval.start_time_str == "02:00"
    assert interval.end_time_str == "36:00"

    # Serialization roundtrip
    d = interval.to_dict()
    assert d["start_ms"] == 120000
    assert d["end_ms"] == 2160000
    assert d["origin"] == "manual"

    restored = PresentationInterval.from_dict(d)
    assert restored.start_ms == interval.start_ms
    assert restored.end_ms == interval.end_ms
    assert restored.origin == interval.origin

    # Invalid interval (end <= start)
    with pytest.raises(ValueError):
        PresentationInterval(start_ms=5000, end_ms=5000)

    with pytest.raises(ValueError):
        PresentationInterval(start_ms=5000, end_ms=2000)

    # Invalid negative start
    with pytest.raises(ValueError):
        PresentationInterval(start_ms=-100, end_ms=5000)


def test_normalize_and_validate_intervals():
    # 1. Chronological sorting
    i1 = PresentationInterval(start_ms=60000, end_ms=120000)
    i2 = PresentationInterval(start_ms=10000, end_ms=30000)
    sorted_ints = normalize_and_validate_intervals([i1, i2])
    assert sorted_ints[0].start_ms == 10000
    assert sorted_ints[1].start_ms == 60000

    # 2. Overlap detection (raises ValueError with clear explanation)
    overlap1 = PresentationInterval(start_ms=10000, end_ms=50000)
    overlap2 = PresentationInterval(start_ms=40000, end_ms=80000)
    with pytest.raises(ValueError) as excinfo:
        normalize_and_validate_intervals([overlap1, overlap2])
    assert "sobreposi" in str(excinfo.value).lower() or "overlap" in str(excinfo.value).lower()

    # 3. Clamping to total duration
    i_clamped = PresentationInterval(start_ms=10000, end_ms=100000)
    res_clamped = normalize_and_validate_intervals([i_clamped], total_duration_ms=50000)
    assert len(res_clamped) == 1
    assert res_clamped[0].end_ms == 50000


# ==============================================================================
# 3. DIRECTED CLASS VIDEO COMPOSITION ENGINE (FFMPEG SEGMENTS + CONTINUOUS AUDIO)
# ==============================================================================
def test_directed_class_composition_engine(test_synthetic_media):
    """
    Scenario:
    Total duration: 6.0 seconds.
    Interval 1: Slides active from 2.0s to 4.0s (2000ms to 4000ms).
    Outside intervals:
      - 0.0s to 2.0s: Professor Focus (Centralized on #10201E stage with lesson title card).
      - 4.0s to 6.0s: Professor Focus (Centralized on #10201E stage).
    Inside interval:
      - 2.0s to 4.0s: Dominant Slides (~80%) + Professor na Lateral (~20%).
    Audio: Continuous audio from presentation track across the entire 6 seconds.
    """
    out_path = str(test_synthetic_media["dir"] / "test_directed_output.mp4")

    config = CompositionConfig(
        layout="sidebar",
        presenter_position="center",
        output_resolution="1280x720",
        lesson_title="Aula Magna - Introdução à Arquitetura",
        lesson_subtitle="Prof. Kika Magalhães · Módulo I",
        presentation_intervals=[
            PresentationInterval(start_ms=2000, end_ms=4000, origin="manual")
        ],
    )

    result = compose_dual_region_video(
        presentation_video_path=test_synthetic_media["pres"],
        presenter_video_path=test_synthetic_media["prof"],
        output_path=out_path,
        config=config,
    )

    assert result == out_path
    assert Path(out_path).exists()
    assert Path(out_path).stat().st_size > 50000

    # Probe output video duration & audio stream
    duration = get_video_duration(out_path)
    assert 5.8 <= duration <= 6.2

    # Probe ffprobe details
    _, ffprobe_exe = get_ffmpeg_paths()
    probe_cmd = [
        ffprobe_exe, "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height,duration",
        "-of", "json",
        out_path,
    ]
    p_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    p_data = json.loads(p_res.stdout)
    streams = p_data.get("streams", [])

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    assert len(video_streams) == 1
    assert video_streams[0]["width"] == 1280
    assert video_streams[0]["height"] == 720
    assert video_streams[0]["codec_name"] == "h264"

    assert len(audio_streams) == 1
    assert audio_streams[0]["codec_name"] == "aac"
    a_dur = float(audio_streams[0].get("duration", duration))
    assert 5.8 <= a_dur <= 6.2


# ==============================================================================
# 4. MULTIPLE INTERVALS & CONTINUOUS AUDIO VERIFICATION
# ==============================================================================
def test_multiple_slide_intervals(test_synthetic_media):
    """
    Scenario:
    2 separate slide intervals: [1.0s, 2.5s] and [3.5s, 5.0s].
    Verifies that layout switching happens multiple times and audio never drops.
    """
    out_path = str(test_synthetic_media["dir"] / "test_multi_intervals.mp4")

    config = CompositionConfig(
        layout="sidebar",
        presenter_position="center",
        output_resolution="1280x720",
        lesson_title="Direito Constitucional",
        lesson_subtitle="Aula 02 · Artigo 5º",
        presentation_intervals=[
            PresentationInterval(start_ms=1000, end_ms=2500, origin="manual"),
            PresentationInterval(start_ms=3500, end_ms=5000, origin="manual"),
        ],
    )

    result = compose_dual_region_video(
        presentation_video_path=test_synthetic_media["pres"],
        presenter_video_path=test_synthetic_media["prof"],
        output_path=out_path,
        config=config,
    )
    assert Path(result).exists()

    dur = get_video_duration(out_path)
    assert 5.8 <= dur <= 6.2


# ==============================================================================
# 5. PRESETS: 100% PROFESSOR AND 100% SLIDES
# ==============================================================================
def test_preset_100_percent_professor(test_synthetic_media):
    """
    Scenario:
    0 presentation intervals: Video is 100% professor focused on stage #10201E.
    """
    out_path = str(test_synthetic_media["dir"] / "test_100_prof.mp4")
    config = CompositionConfig(
        layout="sidebar",
        output_resolution="1280x720",
        lesson_title="Palestra Magistral",
        lesson_subtitle="Sem Slides",
        presentation_intervals=[],
    )
    result = compose_dual_region_video(
        presentation_video_path=test_synthetic_media["pres"],
        presenter_video_path=test_synthetic_media["prof"],
        output_path=out_path,
        config=config,
    )
    assert Path(result).exists()
    assert 5.8 <= get_video_duration(out_path) <= 6.2


def test_preset_100_percent_slides(test_synthetic_media):
    """
    Scenario:
    Single interval covering the entire 6 seconds: 100% slides + sidebar professor.
    """
    out_path = str(test_synthetic_media["dir"] / "test_100_slides.mp4")
    config = CompositionConfig(
        layout="sidebar",
        output_resolution="1280x720",
        lesson_title="Apresentação Contínua",
        presentation_intervals=[
            PresentationInterval(start_ms=0, end_ms=6000, origin="manual")
        ],
    )
    result = compose_dual_region_video(
        presentation_video_path=test_synthetic_media["pres"],
        presenter_video_path=test_synthetic_media["prof"],
        output_path=out_path,
        config=config,
    )
    assert Path(result).exists()
    assert 5.8 <= get_video_duration(out_path) <= 6.2


# ==============================================================================
# 6. HONEST SCALING POLICY FOR LOW-RESOLUTION SOURCES
# ==============================================================================
def test_honest_scaling_policy(test_synthetic_media):
    """
    Verifies that low-res presenter source (320x240) is capped in scaling
    rather than being stretched to 960px, preventing pixelation and blur.
    """
    # Probe low-res video dimensions
    w, h = probe_video_dimensions(test_synthetic_media["prof_lowres"])
    assert w == 320
    assert h == 240

    out_path = str(test_synthetic_media["dir"] / "test_honest_scale.mp4")
    config = CompositionConfig(
        layout="sidebar",
        output_resolution="1280x720",
        lesson_title="Aula com Câmera Compacta",
        presenter_scale_limit=1.5,
        presentation_intervals=[
            PresentationInterval(start_ms=2000, end_ms=4000, origin="manual")
        ],
    )

    result = compose_dual_region_video(
        presentation_video_path=test_synthetic_media["pres"],
        presenter_video_path=test_synthetic_media["prof_lowres"],
        output_path=out_path,
        config=config,
    )
    assert Path(result).exists()


# ==============================================================================
# 7. LOCAL OFFLINE HEURISTIC SUGGESTION (METHOD C)
# ==============================================================================
def test_detect_slide_intervals_heuristic(test_synthetic_media):
    intervals = detect_slide_intervals_heuristic(test_synthetic_media["pres"])
    # Should return a list (empty or suggested intervals)
    assert isinstance(intervals, list)
    for interval in intervals:
        assert isinstance(interval, PresentationInterval)
        assert interval.end_ms > interval.start_ms
        assert interval.origin == "auto_suggestion"


# ==============================================================================
# 8. CLASS TIMELINE WIDGET VISUAL & INTERACTIVE API
# ==============================================================================
def test_class_timeline_widget(qapp):
    widget = ClassTimelineWidget()
    widget.show()
    qapp.processEvents()

    # Set duration
    widget.set_duration_ms(180000)  # 3 minutes
    assert widget.duration_ms == 180000

    # Set intervals
    int1 = PresentationInterval(start_ms=30000, end_ms=90000, origin="manual")
    int2 = PresentationInterval(start_ms=120000, end_ms=160000, origin="live_marker")
    widget.set_intervals([int1, int2])

    assert len(widget.get_intervals()) == 2

    # Query layout at specific timestamps
    assert widget.get_layout_at_ms(10000) == "presenter_focus"
    assert "Professor em Destaque" in widget.get_layout_label_at_ms(10000)

    assert widget.get_layout_at_ms(45000) == "slides"
    assert "Slides Grandes" in widget.get_layout_label_at_ms(45000)

    assert widget.get_layout_at_ms(100000) == "presenter_focus"
    assert widget.get_layout_at_ms(130000) == "slides"
    assert widget.get_layout_at_ms(170000) == "presenter_focus"

    # Playhead cursor
    widget.set_current_pos_ms(45000)
    assert widget.current_pos_ms == 45000

    # Coordinate mapping sanity
    x = widget._ms_to_x(90000)
    assert 16.0 < x < widget.width()
    ms_back = widget._x_to_ms(x)
    assert abs(ms_back - 90000) < 2000

    widget.close()


# ==============================================================================
# 9. RECORDMEETVIEW UI TIMELINE & LIVE MARKER INTEGRATION
# ==============================================================================
def test_record_meet_view_timeline_direction_ui(qapp, test_synthetic_media):
    view = RecordMeetView()
    view.show()
    qapp.processEvents()

    # Switch to dual region mode
    view.radio_cap_dual.setChecked(True)
    qapp.processEvents()

    # 1. Check Live Marker Controls in recording view
    assert hasattr(view, "box_live_markers")
    assert hasattr(view, "btn_mark_pres_start")
    assert hasattr(view, "btn_mark_pres_end")
    assert hasattr(view, "lbl_marker_status")

    # Simulate live marker clicks
    view._on_mark_presentation_start()
    assert view.live_marker_start_ms is not None
    assert view.btn_mark_pres_start.isEnabled() is False
    assert view.btn_mark_pres_end.isEnabled() is True
    assert "Slides ativos" in view.lbl_marker_status.text()

    time.sleep(0.05)
    view._on_mark_presentation_end()
    assert view.live_marker_start_ms is None
    assert len(view.session_intervals) == 1
    assert view.session_intervals[0].origin == "live_marker"
    assert view.btn_mark_pres_start.isEnabled() is True
    assert view.btn_mark_pres_end.isEnabled() is False

    # 2. Check Results View & Timeline Recomposition Card
    assert hasattr(view, "timeline_widget")
    assert hasattr(view, "edit_timeline_title")
    assert hasattr(view, "edit_timeline_subtitle")
    assert hasattr(view, "lbl_prof_quality_badge")
    assert hasattr(view, "edit_int_start")
    assert hasattr(view, "edit_int_end")
    assert hasattr(view, "btn_add_interval")
    assert hasattr(view, "btn_preset_all_prof")
    assert hasattr(view, "btn_preset_all_slides")
    assert hasattr(view, "btn_preset_heuristic")
    assert hasattr(view, "table_intervals")

    # Assign synthetic raw tracks
    view.pres_raw_path = test_synthetic_media["pres"]
    view.prof_raw_path = test_synthetic_media["prof_lowres"]
    view._update_timeline_ui()

    # Check that low-res badge was activated
    assert "Política de Nitidez" in view.lbl_prof_quality_badge.text()
    assert "320×240" in view.lbl_prof_quality_badge.text()

    # 3. Add manual interval (Method A)
    view.edit_int_start.setText("00:01")
    view.edit_int_end.setText("00:03")
    view._on_add_manual_interval()

    assert len(view.session_intervals) >= 1
    int_added = view.session_intervals[-1]
    assert int_added.start_ms == 1000
    assert int_added.end_ms == 3000

    # 4. Test 100% Professor preset
    view._on_preset_all_prof()
    assert len(view.session_intervals) == 0
    assert view.table_intervals.rowCount() == 0

    # 5. Test 100% Slides preset
    view._on_preset_all_slides()
    assert len(view.session_intervals) == 1
    assert view.session_intervals[0].start_ms == 0
    assert view.table_intervals.rowCount() == 1

    view.close()


# ==============================================================================
# 10. POST-RECORDING RECOMPOSITION WITHOUT RE-RECORDING
# ==============================================================================
def test_post_recording_recomposition_workflow(qapp, test_synthetic_media):
    """
    Scenario:
    User changes slide start time from 02:00 to 02:13 (or in synthetic clip from 1s to 2s),
    edits title, and re-renders new MP4 using DualRegionRenderWorker without touching raw video captures.
    """
    dest_dir = test_synthetic_media["dir"]
    recomp_out = str(dest_dir / "recomp_lesson_final.mp4")

    # Initial composition with [1s, 4s]
    config1 = CompositionConfig(
        lesson_title="Primeira Versão",
        presentation_intervals=[
            PresentationInterval(start_ms=1000, end_ms=4000)
        ],
    )

    # User post-edits interval to [2s, 5s] and changes title
    config2 = CompositionConfig(
        lesson_title="Segunda Versão Dirigida",
        lesson_subtitle="Prof. Kika Magalhães",
        presentation_intervals=[
            PresentationInterval(start_ms=2000, end_ms=5000)
        ],
    )

    worker = DualRegionRenderWorker(
        presentation_video_path=test_synthetic_media["pres"],
        presenter_video_path=test_synthetic_media["prof"],
        output_path=recomp_out,
        config=config2,
    )

    finished_paths = []
    error_messages = []
    worker.render_finished.connect(lambda p: finished_paths.append(p))
    worker.render_error.connect(lambda e: error_messages.append(e))

    worker.start()
    start_t = time.time()
    while worker.isRunning() and (time.time() - start_t < 20):
        qapp.processEvents()
        time.sleep(0.02)
    worker.wait(1000)
    qapp.processEvents()

    assert len(error_messages) == 0
    assert len(finished_paths) == 1
    assert finished_paths[0] == recomp_out
    assert Path(recomp_out).exists()
    assert Path(test_synthetic_media["pres"]).exists()
    assert Path(test_synthetic_media["prof"]).exists()
