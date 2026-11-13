"""Gravação ao vivo do podcast: finalizar sem áudio não pode renderizar.

Regressão: o render começava no mesmo instante do stop() do gravador,
antes de o Qt fechar o arquivo de áudio — a gravação ao vivo quebrava.
Agora o render só começa após o gravador parar de verdade, e a falta de
áudio vira erro visível em vez de render falho/silencioso.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_finish_without_audio_shows_error_and_starts_no_worker(qapp, tmp_path):
    from app.ui.views.record_podcast_view import RecordPodcastView

    view = RecordPodcastView()
    view.temp_audio_file = str(tmp_path / "nao-gravou.m4a")
    view._finish_recording()  # gravador já parado -> vai direto p/ a checagem

    assert view.worker is None
    assert view.lbl_result_title.text() == "Gravação sem áudio"
    assert view._pending_render is False


def test_enter_live_studio_does_not_crash(qapp, tmp_path):
    """Regressão: entrar no estúdio quebrava com Qt.QSize (inexistente)."""
    from PIL import Image

    from app.ui.views.record_podcast_view import RecordPodcastView

    view = RecordPodcastView()
    cover = tmp_path / "capa.png"
    Image.new("RGB", (200, 200), (10, 20, 30)).save(cover)
    view._set_cover(str(cover))
    view._enter_live_studio()
    assert view.stack.currentIndex() == 1


def test_prerecorded_audio_goes_straight_to_render(qapp, tmp_path):
    """Áudio pré-gravado: sem estúdio, o render começa com o arquivo enviado."""
    from PIL import Image

    from app.ui.views.record_podcast_view import RecordPodcastView

    view = RecordPodcastView()
    cover = tmp_path / "capa.png"
    Image.new("RGB", (300, 300), (20, 40, 60)).save(cover)
    view._set_cover(str(cover))
    audio = tmp_path / "episodio.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 200)
    view.prerecorded_audio_path = str(audio)
    view.btn_render_pre.setEnabled(True)
    view._render_prerecorded()

    assert view.stack.currentIndex() == 2
    assert view.worker is not None
    view.worker.cancel()
    view.worker.wait(3000)


def test_cover_format_and_preset_recolor(qapp, tmp_path):
    from PIL import Image

    from app.ui.views.record_podcast_view import RecordPodcastView

    view = RecordPodcastView()
    view._pick_preset("estudio", str(tmp_path / "preset.png"))
    assert view.current_preset_id == "estudio"
    view.preset_bg_color = "#5b21b6"
    view._recolor_current_preset()
    assert view.cover_image_path.endswith("cores_suas.png")
    view.cover_format = "widescreen"
    view._refresh_cover_preview()
    with Image.open(view.composed_cover_path) as img:
        assert img.size == (1920, 1080)


def test_finish_with_empty_audio_file_shows_error(qapp, tmp_path):
    from app.ui.views.record_podcast_view import RecordPodcastView

    view = RecordPodcastView()
    empty = tmp_path / "vazio.m4a"
    empty.write_bytes(b"")
    view.temp_audio_file = str(empty)
    view._finish_recording()

    assert view.worker is None
    assert view.lbl_result_title.text() == "Gravação sem áudio"
