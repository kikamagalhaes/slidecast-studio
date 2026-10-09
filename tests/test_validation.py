"""Unit tests for app.web.validation (pure helpers, no FastAPI needed)."""

import uuid

import pytest

from app.web.validation import (
    ValidationError,
    assert_pdf_signature,
    display_name,
    get_max_upload_bytes,
    parse_project_id,
    project_dir,
    validate_durations,
    validate_fps,
    validate_resolution,
    validate_upload_filename,
)


def test_parse_project_id_accepts_uuid4():
    value = str(uuid.uuid4())
    assert parse_project_id(value) == value


def test_parse_project_id_rejects_garbage():
    for bad in ("", "not-a-uuid", "..", "../x", "1234", "a" * 36):
        with pytest.raises(ValidationError):
            parse_project_id(bad)


def test_parse_project_id_rejects_non_v4():
    with pytest.raises(ValidationError):
        parse_project_id(str(uuid.uuid1()))


def test_project_dir_stays_contained(tmp_path):
    storage = tmp_path / "storage"
    pid = str(uuid.uuid4())
    result = project_dir(storage, pid)
    assert result == storage.resolve() / "projects" / pid


def test_project_dir_rejects_traversal(tmp_path):
    with pytest.raises(ValidationError):
        project_dir(tmp_path, "..")


def test_validate_upload_filename_pdf():
    assert validate_upload_filename("slides.pdf", "pdf") == ".pdf"
    assert validate_upload_filename("SLIDES.PDF", "pdf") == ".pdf"
    with pytest.raises(ValidationError):
        validate_upload_filename("slides.mp3", "pdf")
    with pytest.raises(ValidationError):
        validate_upload_filename("", "pdf")


def test_validate_upload_filename_audio():
    assert validate_upload_filename("narr.mp3", "audio") == ".mp3"
    assert validate_upload_filename("narr.WAV", "audio") == ".wav"
    with pytest.raises(ValidationError):
        validate_upload_filename("narr.pdf", "audio")
    with pytest.raises(ValidationError):
        validate_upload_filename("noextension", "audio")


def test_validate_durations_ok():
    assert validate_durations([2.5, 3.0], 2) == [2.5, 3.0]


def test_validate_durations_rejects():
    with pytest.raises(ValidationError):
        validate_durations([], 2)
    with pytest.raises(ValidationError):
        validate_durations([1.0], 2)  # count mismatch
    with pytest.raises(ValidationError):
        validate_durations([1.0, -2.0], 2)  # negative
    with pytest.raises(ValidationError):
        validate_durations([1.0, 99999.0], 2)  # absurd
    with pytest.raises(ValidationError):
        validate_durations([1.0, "x"], 2)  # non-numeric


def test_validate_resolution_ok():
    assert validate_resolution(1920, 1080) == (1920, 1080)
    assert validate_resolution(320, 240) == (320, 240)


def test_validate_resolution_rejects():
    with pytest.raises(ValidationError):
        validate_resolution(1919, 1080)  # odd width breaks H.264
    with pytest.raises(ValidationError):
        validate_resolution(1920, 1081)  # odd height breaks H.264
    with pytest.raises(ValidationError):
        validate_resolution(0, 1080)
    with pytest.raises(ValidationError):
        validate_resolution(5000, 1080)


def test_validate_fps():
    assert validate_fps(30) == 30
    for bad in (0, -1, 61, 120):
        with pytest.raises(ValidationError):
            validate_fps(bad)


def test_display_name_truncates():
    assert display_name("a.pdf", "x") == "a.pdf"
    assert display_name("", "fallback") == "fallback"
    long_name = "n" * 200 + ".pdf"
    short = display_name(long_name, "x")
    assert len(short) == 120
    assert short.endswith("…")


def test_assert_pdf_signature(tmp_path):
    good = tmp_path / "a.pdf"
    good.write_bytes(b"%PDF-1.7 rest of file")
    assert_pdf_signature(good)  # no raise
    bad = tmp_path / "b.pdf"
    bad.write_text("plain text pretending to be a pdf", encoding="utf-8")
    with pytest.raises(ValidationError, match="assinatura"):
        assert_pdf_signature(bad)
    with pytest.raises(ValidationError):
        assert_pdf_signature(tmp_path / "missing.pdf")


def test_get_max_upload_bytes_default_and_env(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    assert get_max_upload_bytes() == 500 * 1024 * 1024
    monkeypatch.setenv("MAX_UPLOAD_MB", "10")
    assert get_max_upload_bytes() == 10 * 1024 * 1024
    monkeypatch.setenv("MAX_UPLOAD_MB", "bogus")
    assert get_max_upload_bytes() == 500 * 1024 * 1024
