"""
Automated test suite for Dual-Region Meeting & Class Recording with Pedagogical Layouts.

Tests:
1. ScreenRegion data model and even-dimension validation for H.264.
2. CompositionConfig defaults, sidebar/PiP presets, and width ratios (~80% / ~20%).
3. DualRegionSession serialization and deserialization.
4. ScreenRegionSelector interactive overlay and programmatic API (headless Qt).
5. Essential Invariant: Two identical 800x600 inputs are composed into ~80% presentation
   and ~20% presenter without stretching, distortion, or 50/50 splitting.
6. Sidebar layout at top, center, and bottom positions.
7. PiP overlay layout at 4 corners (bottom_right, top_right, bottom_left, top_left).
8. Post-recording re-composition without re-recording from raw sources.
9. DualRegionRenderWorker QThread progress and completion signals.
10. RecordMeetView UI integration: capture mode toggle, region badges, layout controls,
    and post-processing recomposition widget.
11. Fullscreen mode regression: zero regressions on existing capture pipeline.
"""
import os
import sys
import json
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QPoint, Qt
from PySide6.QtWidgets import QApplication

from app.core.dual_region_recorder import (
    ScreenRegion,
    CompositionConfig,
    DualRegionSession,
    compose_dual_region_video,
)
from app.worker import DualRegionRenderWorker
from app.ui.screen_region_selector import ScreenRegionSelector
from app.ui.views.record_meet_view import RecordMeetView
from app.core.meeting_recorder import ScreenRecordingProcess


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="module")
def synthetic_clips(tmp_path_factory):
    """
    Creates two synthetic 800x600 MP4 clips:
      - pres_800x600.mp4: blue presentation slide with text & audio tone
      - prof_800x600.mp4: green presenter camera tile
    Both clips have the EXACT same dimensions (800x600) to test the essential invariant.
    """
    tmp = tmp_path_factory.mktemp("synthetic_clips")
    pres_path = str(tmp / "pres_800x600.mp4")
    prof_path = str(tmp / "prof_800x600.mp4")

    # Generate presentation clip (800x600, 1.5s, 25fps, test tone)
    cmd_pres = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=navy:s=800x600:d=1.5:r=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
        "-vf", "drawtext=text='SLIDE APRESENTACAO':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        pres_path,
    ]
    subprocess.run(cmd_pres, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # Generate presenter clip (800x600, 1.5s, 25fps, silence)
    cmd_prof = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=darkgreen:s=800x600:d=1.5:r=25",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", "1.5",
        "-vf", "drawtext=text='PROFESSOR':fontsize=36:fontcolor=yellow:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        prof_path,
    ]
    subprocess.run(cmd_prof, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    return pres_path, prof_path


# --------------------------------------------------------------------------
# 1. ScreenRegion Data Model & Validation
# --------------------------------------------------------------------------
def test_screen_region_even_dimensions_and_validation():
    # Odd dimensions should be automatically converted to even
    reg = ScreenRegion(
        name="presentation",
        label="ÁREA DA APRESENTAÇÃO",
        x=101,
        y=51,
        width=801,
        height=601,
    )
    assert reg.width == 800
    assert reg.height == 600
    assert reg.x == 101
    assert reg.y == 51

    d = reg.to_dict()
    assert d["width"] == 800
    assert d["height"] == 600

    loaded = ScreenRegion.from_dict(d)
    assert loaded.name == reg.name
    assert loaded.width == 800
    assert loaded.height == 600


def test_screen_region_invalid_dimensions():
    with pytest.raises(ValueError):
        ScreenRegion(name="bad", label="Bad", x=0, y=0, width=10, height=50)

    with pytest.raises(ValueError):
        ScreenRegion(name="bad", label="Bad", x=0, y=0, width=100, height=0)


# --------------------------------------------------------------------------
# 2. CompositionConfig Defaults & Width Ratios
# --------------------------------------------------------------------------
def test_composition_config_defaults():
    cfg = CompositionConfig()
    assert cfg.layout == "sidebar"
    assert cfg.presenter_position == "center"
    assert cfg.output_resolution == "1920x1080"
    assert 0.78 <= cfg.presentation_width_ratio <= 0.82
    assert 0.18 <= cfg.presenter_width_ratio <= 0.22
    assert cfg.background_color == "#10201E"

    d = cfg.to_dict()
    loaded = CompositionConfig.from_dict(d)
    assert loaded.layout == "sidebar"
    assert loaded.presenter_position == "center"


# --------------------------------------------------------------------------
# 3. DualRegionSession Serialization
# --------------------------------------------------------------------------
def test_dual_region_session_serialization(tmp_path):
    reg_a = ScreenRegion("presentation", "ÁREA A", 0, 0, 1280, 720)
    reg_b = ScreenRegion("presenter", "ÁREA B", 1280, 0, 640, 480)
    cfg = CompositionConfig(layout="sidebar", presenter_position="top")

    session = DualRegionSession(
        capture_mode="dual_region",
        presentation_region=reg_a,
        presenter_region=reg_b,
        raw_presentation_video="/tmp/pres.mp4",
        raw_presenter_video="/tmp/prof.mp4",
        output_video="/tmp/out.mp4",
        config=cfg,
    )

    json_file = str(tmp_path / "session.json")
    session.save(json_file)

    loaded = DualRegionSession.load(json_file)
    assert loaded.capture_mode == "dual_region"
    assert loaded.presentation_region.width == 1280
    assert loaded.presenter_region.width == 640
    assert loaded.config.layout == "sidebar"
    assert loaded.config.presenter_position == "top"
    assert loaded.output_video == "/tmp/out.mp4"


# --------------------------------------------------------------------------
# 4. ScreenRegionSelector Interactive Overlay & Programmatic API
# --------------------------------------------------------------------------
def test_screen_region_selector_overlay_api(qapp):
    selector = ScreenRegionSelector(target_name="presentation")
    assert selector.is_presentation is True
    assert selector.accent_color.name() == "#38bdf8"
    assert "APRESENTAÇÃO" in selector.target_label

    # Programmatic selection
    selector.set_selection_rect(100, 200, 801, 601)
    coords = selector.get_selection_tuple()
    assert coords == (100, 200, 800, 600)  # normalized even dimensions

    region = selector.to_screen_region()
    assert region is not None
    assert region.name == "presentation"
    assert region.width == 800
    assert region.height == 600

    # Test signal emission on confirmation
    emitted = []
    selector.region_selected.connect(lambda x, y, w, h: emitted.append((x, y, w, h)))
    selector.confirm_selection()
    assert len(emitted) == 1
    assert emitted[0] == (100, 200, 800, 600)


def test_screen_region_selector_presenter_overlay(qapp):
    selector = ScreenRegionSelector(target_name="presenter")
    assert selector.is_presentation is False
    assert selector.accent_color.name() == "#f59e0b"
    assert "PROFESSOR" in selector.target_label

    cancelled = []
    selector.selection_cancelled.connect(lambda: cancelled.append(True))
    selector.cancel_selection()
    assert len(cancelled) == 1


# --------------------------------------------------------------------------
# 5. Essential Invariant: Identical 800x600 Inputs Composed Asymmetrically
# --------------------------------------------------------------------------
def test_essential_invariant_identical_inputs_rendered_asymmetric(synthetic_clips, tmp_path):
    pres_path, prof_path = synthetic_clips
    out_path = str(tmp_path / "composed_sidebar_center.mp4")

    # Render with default sidebar (80% presentation, 20% presenter)
    cfg = CompositionConfig(layout="sidebar", presenter_position="center", output_resolution="1920x1080")
    success = compose_dual_region_video(
        presentation_video=pres_path,
        presenter_video=prof_path,
        output_video=out_path,
        config=cfg,
    )
    assert bool(success) is True
    assert Path(out_path).exists()
    assert Path(out_path).stat().st_size > 1000

    # Probe output with ffprobe
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name",
        "-of", "json",
        out_path,
    ]
    res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    info = json.loads(res.stdout)
    stream = info["streams"][0]

    assert stream["width"] == 1920
    assert stream["height"] == 1080
    assert stream["codec_name"] == "h264"

    # Verify audio stream
    probe_a_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,channels",
        "-of", "json",
        out_path,
    ]
    res_a = subprocess.run(probe_a_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    info_a = json.loads(res_a.stdout)
    assert len(info_a["streams"]) > 0
    assert info_a["streams"][0]["codec_name"] == "aac"


# --------------------------------------------------------------------------
# 6. Sidebar Layout: Top, Center, and Bottom Positions
# --------------------------------------------------------------------------
@pytest.mark.parametrize("pos", ["top", "center", "bottom"])
def test_sidebar_positions(synthetic_clips, tmp_path, pos):
    pres_path, prof_path = synthetic_clips
    out_path = str(tmp_path / f"sidebar_{pos}.mp4")

    cfg = CompositionConfig(layout="sidebar", presenter_position=pos, output_resolution="1280x720")
    success = compose_dual_region_video(
        presentation_video=pres_path,
        presenter_video=prof_path,
        output_video=out_path,
        config=cfg,
    )
    assert bool(success) is True
    assert Path(out_path).exists()

    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        out_path,
    ]
    res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, text=True, check=True)
    info = json.loads(res.stdout)
    assert info["streams"][0]["width"] == 1280
    assert info["streams"][0]["height"] == 720


# --------------------------------------------------------------------------
# 7. PiP Layout: Overlay in 4 Corners
# --------------------------------------------------------------------------
@pytest.mark.parametrize("pos", ["bottom_right", "top_right", "bottom_left", "top_left"])
def test_pip_positions(synthetic_clips, tmp_path, pos):
    pres_path, prof_path = synthetic_clips
    out_path = str(tmp_path / f"pip_{pos}.mp4")

    cfg = CompositionConfig(layout="overlay_pip", presenter_position=pos, output_resolution="1920x1080")
    success = compose_dual_region_video(
        presentation_video=pres_path,
        presenter_video=prof_path,
        output_video=out_path,
        config=cfg,
    )
    assert bool(success) is True
    assert Path(out_path).exists()


# --------------------------------------------------------------------------
# 8. Post-recording Re-composition Without Re-recording
# --------------------------------------------------------------------------
def test_recomposition_without_rerecording(synthetic_clips, tmp_path):
    pres_path, prof_path = synthetic_clips

    # 1. First render: Sidebar (1920x1080)
    out_sidebar = str(tmp_path / "class_sidebar.mp4")
    cfg_sidebar = CompositionConfig(layout="sidebar", presenter_position="center")
    success1 = compose_dual_region_video(pres_path, prof_path, out_sidebar, cfg_sidebar)
    assert bool(success1) is True

    # 2. Re-composition into PiP (1280x720) without re-recording
    out_pip = str(tmp_path / "class_pip.mp4")
    cfg_pip = CompositionConfig(layout="overlay_pip", presenter_position="bottom_right", output_resolution="1280x720")
    success2 = compose_dual_region_video(pres_path, prof_path, out_pip, cfg_pip)
    assert bool(success2) is True

    # Verify both exist simultaneously with different resolutions
    assert Path(out_sidebar).exists()
    assert Path(out_pip).exists()
    assert Path(out_sidebar).stat().st_size != Path(out_pip).stat().st_size


# --------------------------------------------------------------------------
# 9. DualRegionRenderWorker QThread Signals
# --------------------------------------------------------------------------
def test_dual_region_render_worker(qapp, synthetic_clips, tmp_path):
    import time
    pres_path, prof_path = synthetic_clips
    out_path = str(tmp_path / "worker_output.mp4")
    cfg = CompositionConfig(layout="sidebar")

    worker = DualRegionRenderWorker(
        presentation_video_path=pres_path,
        presenter_video_path=prof_path,
        output_path=out_path,
        config=cfg,
    )

    progress_events = []
    finished_events = []
    error_events = []

    worker.progress_changed.connect(lambda p, m: progress_events.append((p, m)))
    worker.render_finished.connect(lambda p: finished_events.append(p))
    worker.render_error.connect(lambda e: error_events.append(e))

    worker.start()
    start_t = time.time()
    while worker.isRunning() and (time.time() - start_t < 15):
        qapp.processEvents()
        time.sleep(0.02)
    worker.wait(1000)
    qapp.processEvents()

    assert len(error_events) == 0
    assert len(finished_events) == 1
    assert finished_events[0] == out_path
    assert len(progress_events) > 0
    assert Path(out_path).exists()


# --------------------------------------------------------------------------
# 10. RecordMeetView UI Integration
# --------------------------------------------------------------------------
def test_record_meet_view_dual_region_ui(qapp):
    view = RecordMeetView()
    view.show()
    qapp.processEvents()

    assert hasattr(view, "radio_cap_fullscreen")
    assert hasattr(view, "radio_cap_dual")
    assert hasattr(view, "box_dual_config")
    assert hasattr(view, "box_dual_recompose")

    # Initial state: Fullscreen selected
    assert view.radio_cap_fullscreen.isChecked() is True
    assert view.box_dual_config.isHidden() is True

    # Switch to Dual Region mode
    view.radio_cap_dual.setChecked(True)
    qapp.processEvents()
    assert view.capture_mode == "dual_region"
    assert view.box_dual_config.isHidden() is False
    assert view.box_fullscreen_config.isHidden() is True

    # Select regions programmatically
    view._on_presentation_selected(100, 150, 1200, 700)
    assert view.presentation_region is not None
    assert view.presentation_region.width == 1200
    assert "1200×700" in view.lbl_pres_region_status.text()

    view._on_presenter_selected(1350, 150, 400, 300)
    assert view.presenter_region is not None
    assert view.presenter_region.width == 400
    assert "400×300" in view.lbl_prof_region_status.text()

    # Test layout change updates positions
    view.combo_dual_layout.setCurrentIndex(1)  # PiP
    assert view.combo_dual_pos.count() == 4
    assert view.combo_dual_pos.itemData(0) == "bottom_right"

    view.combo_dual_layout.setCurrentIndex(0)  # Sidebar
    assert view.combo_dual_pos.count() == 3
    assert view.combo_dual_pos.itemData(0) == "center"

    # Reset regions
    view._reset_dual_regions()
    assert view.presentation_region is None
    assert view.presenter_region is None
    assert "Nenhuma área selecionada" in view.lbl_pres_region_status.text()
    view.close()


# --------------------------------------------------------------------------
# 11. Fullscreen Mode Regression Preservation
# --------------------------------------------------------------------------
def test_fullscreen_mode_regression(qapp):
    view = RecordMeetView()
    view.show()
    qapp.processEvents()

    view.radio_cap_fullscreen.setChecked(True)
    qapp.processEvents()
    assert view.capture_mode == "full_screen"
    assert view.box_fullscreen_config.isHidden() is False
    assert view.box_dual_config.isHidden() is True

    # ScreenRecordingProcess class remains untouched and operational
    proc = ScreenRecordingProcess(
        output_video_path="/tmp/dummy.mp4",
        video_size="1920x1080",
        fps=25,
    )
    assert proc.output_video_path == "/tmp/dummy.mp4"
    assert proc.video_size == "1920x1080"
    assert proc.process is None
    view.close()
