"""Tests for clone profiles with an isolated config dir (real ffmpeg)."""

import shutil
import subprocess

import pytest

import app.core.clone_manager as clone_manager

ffmpeg_available = shutil.which("ffmpeg") is not None


@pytest.fixture()
def clones_home(tmp_path, monkeypatch):
    monkeypatch.setattr(clone_manager, "get_config_dir", lambda: tmp_path / "cfg")
    state = {"active": None}
    monkeypatch.setattr(clone_manager, "get_active_clone_id", lambda: state["active"])
    monkeypatch.setattr(clone_manager, "set_active_clone_id", lambda v: state.update(active=v))
    return tmp_path


def make_sample_video(path):
    cmd = [
        shutil.which("ffmpeg"), "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "3", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return str(path)


@pytest.mark.skipif(not ffmpeg_available, reason="ffmpeg not installed")
def test_clone_lifecycle(clones_home):
    sample = make_sample_video(clones_home / "sample.mp4")
    meta = clone_manager.create_clone("Meu Clone", sample)
    assert meta["name"] == "Meu Clone"
    assert meta["id"]

    from pathlib import Path

    assert Path(meta["video_path"]).exists()
    assert Path(meta["voice_path"]).exists()
    assert Path(meta["face_path"]).exists()

    clones = clone_manager.list_clones()
    assert [c["id"] for c in clones] == [meta["id"]]
    assert clone_manager.get_clone(meta["id"])["name"] == "Meu Clone"
    assert clone_manager.get_active_clone()["id"] == meta["id"]

    updated = clone_manager.update_clone_metadata(meta["id"], {"elevenlabs_voice_id": "v1"})
    assert updated["elevenlabs_voice_id"] == "v1"

    clone_manager.delete_clone(meta["id"])
    assert clone_manager.list_clones() == []
    assert clone_manager.get_clone(meta["id"]) is None
    assert clone_manager.get_active_clone() is None


def test_clone_helpers_on_empty_store(clones_home):
    assert clone_manager.list_clones() == []
    assert clone_manager.get_clone("missing") is None
    assert clone_manager.get_active_clone() is None
    assert clone_manager.update_clone_metadata("missing", {"a": 1}) is None
    clone_manager.delete_clone("missing")  # no crash


def test_create_clone_rejects_garbage_video(clones_home, tmp_path):
    if not ffmpeg_available:
        pytest.skip("ffmpeg not installed")
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError):
        clone_manager.create_clone("Bad", str(bad))
