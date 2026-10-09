"""Desktop smoke tests (offscreen Qt): build MainWindow, click every card."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QPushButton

from app.ui.home_cards import MENU_CARDS, MainView, build_home_menu, build_menu_card
from app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _click_button_text(root, text):
    for button in root.findChildren(QPushButton):
        if button.text() == text:
            button.click()
            return True
    return False


def test_menu_specs_cover_all_views():
    assert [spec.target for spec in MENU_CARDS] == [
        MainView.CREATE_VIDEO,
        MainView.RECORD_CLASS,
        MainView.RECORD_MEET,
        MainView.RECORD_PODCAST,
        MainView.GENERATE_MATERIALS,
    ]


def test_build_home_menu_layout_shape(qapp):
    layout = build_home_menu(lambda view: None)
    assert layout.count() == 2  # two rows
    assert layout.itemAt(0).layout().count() == 3
    assert layout.itemAt(1).layout().count() == 2


def test_build_menu_card_wires_handler(qapp):
    hits = []
    card = build_menu_card(MENU_CARDS[0], lambda: hits.append(1))
    assert _click_button_text(card, MENU_CARDS[0].button_text)
    assert hits == [1]


def test_record_class_panels_build(qapp):
    """The extracted panel builders wire the class view without errors."""
    window = MainWindow()
    try:
        view = window.record_class_view
        assert view.setup_view is not None
        assert view.studio_view is not None
        assert view.result_view is not None
        assert view.stack.count() == 3
    finally:
        window.close()


def test_cancel_buttons_wired_and_safe_without_worker(qapp):
    window = MainWindow()
    try:
        for view in (window.record_class_view, window.record_podcast_view):
            assert view.btn_cancel_render.text() == "⏹ Cancelar Renderização"
            assert view.btn_cancel_render.isHidden()
            view._cancel_render()  # no worker yet: must not crash
            view._on_render_cancelled()
            assert view.output_video_path is None
            assert view.lbl_result_title.text() == "Renderização Cancelada"
    finally:
        window.close()


def test_render_workers_expose_cancel(qapp):
    from app.ui.views.record_podcast_view import PodcastVideoRenderWorker
    from app.ui.workers.class_render_workers import (
        ClassVideoRenderWorker,
        CloneLessonRenderWorker,
        TutorialPostProcessWorker,
    )

    workers = [
        CloneLessonRenderWorker(pdf_path="p", script_text="s", output_path="o", clone_data={}),
        ClassVideoRenderWorker(pdf_path="p", durations=[1.0], audio_path="a", output_path="o"),
        TutorialPostProcessWorker(raw_video_path="r", output_path="o"),
        PodcastVideoRenderWorker(
            cover_image="c",
            audio_path="a",
            output_path="o",
            bgm_path=None,
            waveform_color="0x38bdf8",
            enable_subtitles=False,
            subtitles_language="pt",
        ),
    ]
    for worker in workers:
        assert worker._cancelled is False
        worker.cancel()
        assert worker._cancelled is True


def test_main_window_navigates_every_card(qapp):
    window = MainWindow()
    try:
        window.show()
        assert window.stack.currentIndex() == MainView.HOME
        for spec in MENU_CARDS:
            window.stack.setCurrentIndex(MainView.HOME)
            assert _click_button_text(window.home_view, spec.button_text), spec.button_text
            assert window.stack.currentIndex() == spec.target
        # The create-video back button returns home.
        window.stack.setCurrentIndex(MainView.CREATE_VIDEO)
        assert _click_button_text(window.create_video_view, "← Voltar ao Menu Inicial")
        assert window.stack.currentIndex() == MainView.HOME
    finally:
        window.close()
