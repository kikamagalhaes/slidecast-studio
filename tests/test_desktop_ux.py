"""User-facing regressions: live theme, persisted edits, real import/render/error/cancel."""
import copy
import shutil
import json
import os
import time
import wave
import math
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
import pymupdf
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
from app.ui.styles import ThemeManager, LIGHT, DARK
from app.ui.views.create_video_view import CreateVideoView
from app.core.multitrack import MultimediaProject, probe_audio_track, inspect_video


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def media(tmp_path):
    pdf = tmp_path / "Aula com acentos e espaços.pdf"
    doc = pymupdf.open()
    for number in range(3):
        page = doc.new_page(width=960, height=540)
        page.insert_text((60, 110), f"Aula {number+1}", fontsize=42)
    doc.save(pdf)
    doc.close()
    audio = []
    for i in range(4):
        path = tmp_path / f"Áudio {i+1}.wav"
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(b"".join(struct.pack("<h", int(2000*math.sin(2*math.pi*(200+i*100)*n/8000))) for n in range(8000*(i+1))))
        audio.append(str(path))
    return str(pdf), audio


def wait(qapp, predicate, seconds=30):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Tempo limite esperando o Qt/FFmpeg")


@pytest.fixture
def editor(qapp):
    view = CreateVideoView()
    yield view
    if view.worker and view.worker.isRunning():
        view.worker.cancel()
        wait(qapp, lambda: view.worker is None)
    if view.import_worker:
        wait(qapp, lambda: view.import_worker is None)
    view.player.stop()
    view.close()


def populate(view, media):
    pdf, audio = media
    view.project.set_visual_source("pdf", pdf, slide_durations=[.5, .75, .75])
    for i, path in enumerate(audio):
        view.project.add_track(probe_audio_track(path, name=f"Faixa {i+1}", volume=.2*(i+1), offset=.1*i))
    view.project.export_settings = {"resolution": [320,180], "fps": 5, "output_path": ""}
    view.refresh()


def test_theme_contrast_tokens():
    def luminance(value):
        v = [int(value[i:i+2],16)/255 for i in (1,3,5)]
        v = [x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in v]
        return sum(a*b for a,b in zip(v,(.2126,.7152,.0722)))
    for palette in (LIGHT,DARK):
        for fg in ("text","secondary","muted","disabled","primary","danger","warning","success","track1","track2","track3","track4"):
            for bg in ("bg","surface","field","surface_alt"):
                x,y = sorted((luminance(palette[fg]),luminance(palette[bg])))
                assert (y+.05)/(x+.05)>=4.5, (fg,bg,(y+.05)/(x+.05))
        for bg in ("primary","danger","warning","success"):
            x,y = sorted((luminance(palette["on_primary"]),luminance(palette[bg])))
            assert (y+.05)/(x+.05)>=4.5


def test_live_theme_preserves_project_controls_and_modal(qapp, editor, media, tmp_path):
    populate(editor,media)
    editor.track_widgets[2].spin_volume.setValue(75)
    editor.track_widgets[1].chk_mute.setChecked(True)
    editor.track_widgets[3].spin_offset.setValue(1.25)
    editor.page_spin.setValue(2)
    before = copy.deepcopy(editor.project.to_dict())
    settings = QSettings(str(tmp_path/"theme.ini"), QSettings.IniFormat)
    manager = ThemeManager(qapp, settings)
    dialog = QInputDialog(editor)
    dialog.setTextValue("Aula aberta")
    dialog.show()
    for theme in ("dark","light","dark"):
        manager.set_theme(theme)
        qapp.processEvents()
        assert editor.project.to_dict() == before
        assert editor.page_spin.value()==2
        assert dialog.textValue()=="Aula aberta"
    assert settings.value("appearance/theme")=="dark"
    assert ThemeManager(qapp, settings).name=="dark"
    dialog.close()


def test_four_tracks_limit_labels_and_model(editor,media):
    populate(editor,media)
    assert not editor.add_audio_button.isEnabled()
    assert "4 faixas" in editor.limit_label.text()
    editor.import_file("audio",media[1][0])
    assert len(editor.project.tracks)==4
    assert "quatro" in editor.feedback.text()
    editor.track_widgets[0].spin_volume.setValue(125)
    editor.track_widgets[0].spin_offset.setValue(.5)
    editor.track_widgets[0].chk_mute.setChecked(True)
    assert editor.project.tracks[0].volume==1.25
    assert editor.project.tracks[0].offset==.5
    assert editor.project.tracks[0].mute is True
    assert "cortada" in editor.track_widgets[3].file_label.toolTip()
    editor.remove_track(editor.project.tracks[0].id)
    assert editor.add_audio_button.isEnabled()


def test_real_async_import_invalid_file_preserves_state(qapp,editor,media,tmp_path):
    editor.import_file("pdf",media[0])
    wait(qapp,lambda: editor.import_worker is None)
    assert len(editor.project.slide_durations)==3
    editor.import_file("audio",media[1][0])
    wait(qapp,lambda: editor.import_worker is None)
    assert len(editor.project.tracks)==1
    before=editor.project.to_dict()
    broken=tmp_path/"quebrado.wav"
    broken.write_text("não é áudio")
    editor.import_file("audio",str(broken))
    wait(qapp,lambda: editor.import_worker is None)
    assert editor.project.to_dict()==before
    assert "Não foi possível" in editor.feedback.text()


def test_save_reopen_preserves_exact_values_and_legacy(qapp,editor,media,tmp_path,monkeypatch):
    populate(editor,media)
    editor.project.tracks[1].mute=True
    editor.project.tracks[2].offset=.7
    editor.project_path=str(tmp_path/"aula.slidecast")
    editor.dirty=True
    assert editor.save_dialog()
    expected=editor.project.to_dict()
    editor.project=MultimediaProject()
    editor.import_file("open",str(tmp_path/"aula.slidecast"))
    wait(qapp,lambda: editor.import_worker is None)
    assert editor.project.to_dict()==expected
    assert not editor.dirty
    legacy=tmp_path/"antigo.json"
    legacy.write_text(json.dumps({"schema_version":1,"pdf_path":media[0],"audio_path":media[1][0],"slide_durations":[1,2,3]}))
    editor.import_file("open",str(legacy))
    wait(qapp,lambda: editor.import_worker is None)
    assert editor.project.slide_durations==[1,2,3]
    assert len(editor.project.tracks)==1


def test_source_replacement_preserves_tracks_and_invalid_source(qapp,editor,media,tmp_path,monkeypatch):
    populate(editor,media)
    tracks=copy.deepcopy([t.to_dict() for t in editor.project.tracks])
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k: QMessageBox.Yes)
    editor.import_file("pdf",media[0])
    wait(qapp,lambda: editor.import_worker is None)
    assert [t.to_dict() for t in editor.project.tracks]==tracks
    before=editor.project.to_dict()
    bad=tmp_path/"errado.pdf";bad.write_text("bad")
    editor.import_file("pdf",str(bad))
    wait(qapp,lambda: editor.import_worker is None)
    assert editor.project.to_dict()==before


def test_export_preview_mp4_audio_warning_and_cancel(qapp,editor,media,tmp_path,monkeypatch):
    populate(editor,media)
    output=tmp_path/"vídeo pronto.mp4"
    editor.start_render(output_path=str(output))
    wait(qapp,lambda: editor.worker is None,60)
    assert output.is_file(), editor.feedback.text()
    assert editor.result_path==str(output)
    assert 1.8 <= inspect_video(str(output)).duration <= 2.5
    assert editor.play_button.isEnabled()
    evidence = os.environ.get("SLIDECAST_EVIDENCE_DIR")
    if evidence:
        folder = Path(evidence); folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, folder / "exportacao-pdf-quatro-faixas.mp4")
        editor.resize(1280, 1000); editor.show(); qapp.processEvents()
        editor.grab().save(str(folder / "editor-exportacao-concluida.png"))
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k: QMessageBox.Yes)
    editor.import_file("video",str(output))
    wait(qapp,lambda: editor.import_worker is None)
    assert editor.project.video_info.has_audio
    assert "não será incluído" in editor.original_audio.text()
    old=editor.project.to_dict()
    editor.start_render(preview=True)
    wait(qapp,lambda: editor.worker is None,60)
    assert editor.preview_path and Path(editor.preview_path).is_file()
    assert editor.project.to_dict()==old
    if evidence:
        shutil.copy2(editor.preview_path, folder / "previa-mp4-quatro-faixas.mp4")
        qapp.processEvents()
        editor.grab().save(str(folder / "editor-mp4-previa-concluida.png"))
    assert editor.play_button.isEnabled()
    editor.start_render(output_path=str(output))
    assert "origem" in editor.feedback.text()
    assert editor.worker is None
    editor.project.set_visual_source("pdf",media[0],slide_durations=[400,400,400])
    editor.refresh()
    cancelled=tmp_path/"cancelado.mp4"
    editor.start_render(output_path=str(cancelled))
    editor.cancel_render()
    wait(qapp,lambda: editor.worker is None,60)
    assert "cancelado" in editor.feedback.text().lower()
    assert editor.cancel_button.isEnabled()
    assert not cancelled.exists()


def test_unsaved_cancel_keeps_project(editor,media,monkeypatch):
    populate(editor,media)
    editor._changed()
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k: QMessageBox.Cancel)
    assert not editor.confirm_discard()
    assert len(editor.project.tracks)==4
