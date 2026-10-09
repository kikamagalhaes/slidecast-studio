"""Capture-device enumeration: pure parsers + best-effort probes (no hardware)."""

import app.core.meeting_recorder as recorder
from app.core.meeting_recorder import (
    ScreenRecordingProcess,
    default_pulse_source,
    describe_capture_devices,
    list_linux_cameras,
    parse_dshow_devices,
    parse_pactl_default_source,
    parse_pactl_short_sources,
)

PACTL_SHORT = (
    "0\talsa_output.pci-0000.monitor\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tSUSPENDED\n"
    "1\talsa_input.usb-Mic.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tRUNNING\n"
    "garbage line without tabs\n"
)

PACTL_INFO = (
    "Server String: /run/user/1000/pulse/native\n"
    "Default Sink: alsa_output.pci-0000.analog-stereo\n"
    "Default Source: alsa_input.usb-Mic.analog-stereo\n"
)

DSHOW_LIST = """\
[dshow @ 0x1] DirectShow video devices (some may be both video and audio devices)
[dshow @ 0x1]  "Integrated Camera"
[dshow @ 0x1]     Alternative name "@device_pnp_XXX"
[dshow @ 0x1] DirectShow audio devices
[dshow @ 0x1]  "Microphone (Realtek Audio)"
[dshow @ 0x1]     Alternative name "@device_pnp_YYY"
[dshow @ 0x1]  "virtual-audio-capturer"
"""


def test_parse_pactl_short_sources():
    sources = parse_pactl_short_sources(PACTL_SHORT)
    assert [s["name"] for s in sources] == [
        "alsa_output.pci-0000.monitor",
        "alsa_input.usb-Mic.analog-stereo",
    ]
    assert sources[1]["state"] == "RUNNING"
    assert parse_pactl_short_sources("") == []


def test_parse_pactl_default_source():
    assert parse_pactl_default_source(PACTL_INFO) == "alsa_input.usb-Mic.analog-stereo"
    assert parse_pactl_default_source("no default here") is None


def test_parse_dshow_devices():
    devices = parse_dshow_devices(DSHOW_LIST)
    assert devices["video"] == ["Integrated Camera"]
    assert devices["audio"] == ["Microphone (Realtek Audio)", "virtual-audio-capturer"]
    assert parse_dshow_devices("") == {"video": [], "audio": []}


def test_default_pulse_source_env_override(monkeypatch):
    monkeypatch.setenv("SLIDECAST_PULSE_SOURCE", "my-source")
    assert default_pulse_source() == "my-source"


def test_default_pulse_source_probes_pactl(monkeypatch):
    monkeypatch.delenv("SLIDECAST_PULSE_SOURCE", raising=False)
    monkeypatch.setattr(recorder, "_run_capture", lambda argv, timeout=5.0: PACTL_INFO)
    assert default_pulse_source() == "alsa_input.usb-Mic.analog-stereo"


def test_default_pulse_source_without_pactl(monkeypatch):
    monkeypatch.delenv("SLIDECAST_PULSE_SOURCE", raising=False)
    monkeypatch.setattr(recorder, "_run_capture", lambda argv, timeout=5.0: None)
    assert default_pulse_source() is None


def test_list_linux_cameras(tmp_path):
    (tmp_path / "video0").touch()
    (tmp_path / "video1").touch()
    (tmp_path / "sda").touch()
    assert list_linux_cameras(str(tmp_path)) == [
        str(tmp_path / "video0"),
        str(tmp_path / "video1"),
    ]
    assert list_linux_cameras(str(tmp_path / "missing")) == []


def test_effective_camera_device_drops_missing_dev_nodes(tmp_path):
    rec = ScreenRecordingProcess(str(tmp_path / "out.mp4"), camera_device="/dev/video-none")
    assert rec._effective_camera_device() is None
    rec2 = ScreenRecordingProcess(str(tmp_path / "out.mp4"), camera_device=None)
    assert rec2._effective_camera_device() is None
    rec3 = ScreenRecordingProcess(str(tmp_path / "out.mp4"), camera_device="0")
    assert rec3._effective_camera_device() == "0"  # non-/dev ids pass through


def test_dshow_audio_input_env_override(monkeypatch, tmp_path):
    rec = ScreenRecordingProcess(str(tmp_path / "out.mp4"))
    monkeypatch.delenv("SLIDECAST_DSHOW_AUDIO", raising=False)
    assert rec._dshow_audio_input() == "audio=virtual-audio-capturer"
    monkeypatch.setenv("SLIDECAST_DSHOW_AUDIO", "Stereo Mix")
    assert rec._dshow_audio_input() == "audio=Stereo Mix"


def test_start_requires_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "get_ffmpeg_paths", lambda: (None, None))
    rec = ScreenRecordingProcess(str(tmp_path / "out.mp4"))
    try:
        rec.start()
    except RuntimeError as exc:
        assert "FFmpeg" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_describe_capture_devices_shape():
    info = describe_capture_devices()
    assert set(info) == {"platform", "audio", "video", "default_audio"}
    assert isinstance(info["audio"], list)
    assert isinstance(info["video"], list)
