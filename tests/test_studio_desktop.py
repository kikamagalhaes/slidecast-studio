"""Desktop studio regression: scene projection must not crash (QInputDialog)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_record_class_view_studio_scenes(qtbot=None):
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.ui.views.record_class_view import RecordClassView
    view = RecordClassView()
    assert hasattr(view, "btn_pdf_slots") and hasattr(view, "pen_overlay")
    view.studio["quiz"] = {"question": "Q?", "options": ["A", "B"], "correct": 1, "revealed": True}
    view._show_scene("quiz")
    view._show_scene("whiteboard")
    assert view.studio_scene == "whiteboard"
