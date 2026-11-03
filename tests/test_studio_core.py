"""Shared studio core: 3 PDFs, temporary ink, scenes, portable projects."""
from app.core import studio


def test_three_pdfs_keep_independent_pages():
    s = studio.set_pdf(studio.new_studio_state(), 2, "b.pdf", 10)
    s = studio.set_pdf_page(s, 4, slot=2)
    s = studio.switch_pdf(s, 1)
    assert s["pdfs"][1]["page"] == 4 and s["active_pdf"] == 1
    s = studio.switch_pdf(s, 2)
    assert s["pdfs"][1]["page"] == 4


def test_temp_pen_expires_perm_stays():
    s = studio.add_stroke(studio.new_studio_state(), [(0, 0), (1, 1)], kind="temp", now=1000)
    s = studio.add_stroke(s, [(0, 0), (0, 1)], kind="perm", now=1000)
    assert len(studio.visible_strokes(s, now=1004)) == 2
    visible = studio.visible_strokes(s, now=1006)
    assert len(visible) == 1 and visible[0]["kind"] == "perm"


def test_scene_timeline_and_project_roundtrip(tmp_path):
    s = studio.set_scene(studio.new_studio_state(), "quiz", at=12.5)
    assert studio.scene_at(s, 20)["scene"] == "quiz"
    back = studio.import_project(studio.export_project(s, "Aula"))
    assert back["scene"] == "quiz"
    studio.render_scene_card_png("bible", {"reference": "João 1:1", "text": "No princípio era o Verbo", "version": "Teste"}, tmp_path / "c.png")
    assert (tmp_path / "c.png").stat().st_size > 1000


def test_quiz_validation():
    import pytest
    with pytest.raises(ValueError):
        studio.validate_quiz({"question": "x", "options": ["só uma"]})
