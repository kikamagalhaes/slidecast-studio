"""Desktop multimedia editor, a local client of Muse's existing engine contract."""
from __future__ import annotations

import copy
import logging
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt, Signal, QThread, QUrl, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap, QDesktopServices
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QFileDialog, QMessageBox,
    QScrollArea, QSplitter, QStackedWidget, QSlider, QProgressBar, QSizePolicy,
)

from app.core.multitrack import MultimediaProject, probe_audio_track, MAX_AUDIO_TRACKS, SUPPORTED_AUDIO_EXTENSIONS
from app.core.pdf_processor import inspect_pdf, render_thumbnail
from app.core.ffmpeg_utils import format_duration, get_ffmpeg_paths
from app.worker import MultimediaRenderWorker
from app.ui.audio_track_widget import AudioTrackItemWidget
from app.ui.audio_timeline import AudioTimeline
from app.ui.styles import apply_style

logger = logging.getLogger(__name__)
AUDIO_FILTER = "Áudio (" + " ".join("*" + ext for ext in sorted(SUPPORTED_AUDIO_EXTENSIONS)) + ")"


def label(text, kind=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if kind:
        widget.setProperty("class", kind)
    return widget


def button(text, callback, kind=None):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if kind:
        widget.setProperty("class", kind)
    widget.clicked.connect(callback)
    return widget


class PreviewImage(QWidget):
    def __init__(self):
        super().__init__()
        self.pixmap = QPixmap()
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAccessibleName("Prévia da página do PDF")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#10201E"))
        if self.pixmap.isNull():
            painter.setPen(QColor("#F5F2E8"))
            painter.drawText(self.rect().adjusted(24, 10, -24, -10), Qt.AlignCenter | Qt.TextWordWrap,
                             "Sua próxima aula começa aqui.\n\nSelecione um PDF ou vídeo MP4.")
        else:
            size = self.pixmap.size().scaled(self.size(), Qt.KeepAspectRatio)
            left, top = (self.width()-size.width())//2, (self.height()-size.height())//2
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(left, top, size.width(), size.height(), self.pixmap)


class ImportWorker(QThread):
    loaded = Signal(object, str)
    failed = Signal(str)

    def __init__(self, project, operation, path, track_id=None, parent=None):
        super().__init__(parent)
        self.project = copy.deepcopy(project)
        self.operation, self.path, self.track_id = operation, path, track_id

    def run(self):
        try:
            project = self.project
            if self.operation in ("pdf", "video"):
                project.set_visual_source(self.operation, self.path)
            elif self.operation == "open":
                project = MultimediaProject.load_from_file(self.path)
                # Reject unreadable sources without destroying the currently open project.
                if project.visual_source_path and Path(project.visual_source_path).is_file():
                    durations = list(project.slide_durations)
                    project.set_visual_source(project.visual_source_type, project.visual_source_path,
                                              slide_durations=durations)
            else:
                track = probe_audio_track(self.path)
                if self.track_id:
                    old = project.get_track(self.track_id)
                    for key in ("id", "name", "volume", "mute", "offset", "fade_in", "fade_out", "loop"):
                        setattr(track, key, getattr(old, key))
                    project.tracks[project.tracks.index(old)] = track
                else:
                    track.name = ("Narração", "Música de fundo", "Sonoplastia", "Complemento")[len(project.tracks)]
                    project.add_track(track)
            self.loaded.emit(project, self.path)
        except Exception:
            logger.exception("Falha na importação de mídia/projeto")
            noun = "projeto" if self.operation == "open" else "arquivo de áudio" if self.operation == "audio" else "arquivo"
            self.failed.emit(f"Não foi possível ler este {noun}. Confira o formato e se ele abre no seu computador. O projeto atual foi preservado.")


class CreateVideoView(QWidget):
    back_to_home = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = MultimediaProject(title="Minha próxima aula")
        self.project_path = None
        self.dirty = False
        self.worker = None
        self.import_worker = None
        self.preview_path = None
        self.result_path = None
        self._preview_mode = False
        self._refreshing = False
        self._temp = tempfile.TemporaryDirectory(prefix="slidecast-preview-")
        self.track_widgets = []
        self.setAcceptDrops(True)
        self._build_ui()
        self.refresh()

    @property
    def busy(self):
        return bool((self.worker and self.worker.isRunning()) or (self.import_worker and self.import_worker.isRunning()))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(button("← Voltar ao Menu Inicial", self.back_to_home.emit))
        header.addWidget(label("Criar vídeo", "section-title"))
        header.addStretch()
        self.open_button = button("Abrir projeto", self.open_dialog)
        self.save_button = button("Salvar projeto", self.save_dialog)
        header.addWidget(self.open_button)
        header.addWidget(self.save_button)
        layout.addLayout(header)
        names = QHBoxLayout()
        self.title_edit = QLineEdit(self.project.title)
        self.title_edit.setAccessibleName("Nome do projeto")
        self.title_edit.setMaximumWidth(400)
        self.title_edit.textEdited.connect(self._title_changed)
        names.addWidget(self.title_edit)
        self.save_status = label("Novo projeto", "muted")
        names.addWidget(self.save_status)
        names.addStretch()
        names.addWidget(label("PDF ou MP4 · até 4 áudios · exportação local", "muted"))
        layout.addLayout(names)

        self.editing = QWidget()
        content = QVBoxLayout(self.editing)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        sources = QHBoxLayout()
        self.pdf_button = button("PDF  ·  Criar vídeo a partir de páginas", lambda: self.source_dialog("pdf"))
        self.video_button = button("MP4  ·  Adicionar áudio a um vídeo", lambda: self.source_dialog("video"))
        for b in (self.pdf_button, self.video_button):
            b.setCheckable(True)
            sources.addWidget(b, 1)
        content.addLayout(sources)
        top = QSplitter(Qt.Horizontal)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_caption = label("PRÉVIA DA IMAGEM", "muted")
        preview_layout.addWidget(self.preview_caption)
        self.preview_stack = QStackedWidget()
        self.image_preview = PreviewImage()
        self.video_preview = QVideoWidget()
        self.video_preview.setMinimumHeight(160)
        self.preview_stack.addWidget(self.image_preview)
        self.preview_stack.addWidget(self.video_preview)
        preview_layout.addWidget(self.preview_stack, 1)
        player_bar = QHBoxLayout()
        self.play_button = button("▶ Reproduzir", self.toggle_play)
        self.play_button.setEnabled(False)
        player_bar.addWidget(self.play_button)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setAccessibleName("Posição da prévia renderizada")
        self.seek.setEnabled(False)
        self.seek.sliderMoved.connect(lambda val: self.player.setPosition(val))
        player_bar.addWidget(self.seek, 1)
        self.player_time = label("00:00 / 00:00", "muted")
        player_bar.addWidget(self.player_time)
        preview_layout.addLayout(player_bar)
        top.addWidget(preview_panel)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_preview)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(lambda dur: self.seek.setRange(0, dur))
        self.player.playbackStateChanged.connect(lambda state: self.play_button.setText("Pausar" if state == QMediaPlayer.PlayingState else "▶ Reproduzir"))
        self.player.errorOccurred.connect(lambda *_: self._message("Não foi possível reproduzir a prévia neste sistema. Você pode abrir o MP4 gerado em outro player.", "warning"))

        inspector = QFrame()
        inspector.setProperty("class", "card")
        inspector.setMinimumWidth(290)
        inspector.setMaximumWidth(390)
        info = QVBoxLayout(inspector)
        info.setContentsMargins(16, 12, 16, 12)
        info.addWidget(label("Fonte e exportação", "section-title"))
        self.source_label = label("Nenhuma fonte selecionada", "muted")
        self.source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.addWidget(self.source_label)
        self.original_audio = label("")
        apply_style(self.original_audio, "color: @warning@; font-size: 12px;")
        info.addWidget(self.original_audio)
        self.pdf_controls = QWidget()
        pages = QHBoxLayout(self.pdf_controls)
        pages.setContentsMargins(0, 0, 0, 0)
        pages.addWidget(QLabel("Página"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setAccessibleName("Página do PDF na prévia")
        self.page_spin.valueChanged.connect(self.show_page)
        pages.addWidget(self.page_spin)
        pages.addWidget(QLabel("Tempo"))
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(.1, 7200)
        self.duration_spin.setDecimals(2)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setAccessibleName("Duração da página em segundos")
        self.duration_spin.valueChanged.connect(self._duration_changed)
        pages.addWidget(self.duration_spin)
        info.addWidget(self.pdf_controls)
        self.balance_button = button("Dividir páginas pelo áudio da faixa 1", self.balance_pages)
        info.addWidget(self.balance_button)
        export_row = QHBoxLayout()
        self.resolution = QComboBox()
        self.resolution.setAccessibleName("Resolução de saída")
        for name, value in (("Full HD · 1920 × 1080", [1920, 1080]), ("HD · 1280 × 720", [1280, 720]), ("4K · 3840 × 2160", [3840, 2160]), ("Vertical · 1080 × 1920", [1080, 1920])):
            self.resolution.addItem(name, value)
        self.resolution.currentIndexChanged.connect(self._export_changed)
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(30)
        self.fps.setSuffix(" fps")
        self.fps.setAccessibleName("Quadros por segundo")
        self.fps.valueChanged.connect(self._export_changed)
        export_row.addWidget(self.resolution, 1)
        export_row.addWidget(self.fps)
        info.addLayout(export_row)
        self.total_label = label("MP4 · duração a definir", "muted")
        info.addWidget(self.total_label)
        info.addStretch()
        top.addWidget(inspector)
        top.setStretchFactor(0, 1)
        top.setSizes([700, 330])
        content.addWidget(top)

        audio_header = QHBoxLayout()
        audio_header.addWidget(label("Suas faixas de áudio", "section-title"))
        self.track_count = label("0 de 4", "muted")
        audio_header.addWidget(self.track_count)
        audio_header.addStretch()
        audio_header.addWidget(QLabel("Zoom"))
        self.zoom = QComboBox()
        self.zoom.setAccessibleName("Zoom da linha do tempo")
        for text, value in (("Ajustar", 1), ("2×", 2), ("4×", 4), ("8×", 8)):
            self.zoom.addItem(text, value)
        self.zoom.currentIndexChanged.connect(self._zoom_changed)
        audio_header.addWidget(self.zoom)
        self.add_audio_button = button("+ Adicionar áudio", self.audio_dialog)
        audio_header.addWidget(self.add_audio_button)
        content.addLayout(audio_header)
        self.limit_label = label("Narração, música, sonoplastia e complementos. Arraste um áudio para importar.", "muted")
        content.addWidget(self.limit_label)
        lanes = QSplitter(Qt.Horizontal)
        self.track_container = QWidget()
        self.tracks_layout = QVBoxLayout(self.track_container)
        self.tracks_layout.setContentsMargins(0, 38, 8, 0)
        self.tracks_layout.setSpacing(8)
        self.tracks_layout.setAlignment(Qt.AlignTop)
        self.empty_tracks = label("Adicione sua narração.\nDepois, combine música e efeitos.", "muted")
        self.empty_tracks.setMinimumHeight(104)
        self.tracks_layout.addWidget(self.empty_tracks)
        self.track_container.setMinimumWidth(460)
        lanes.addWidget(self.track_container)
        self.timeline = AudioTimeline(self.project)
        self.timeline.track_selected.connect(self._select_track)
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setWidget(self.timeline)
        self.timeline_scroll.setMinimumWidth(220)
        lanes.addWidget(self.timeline_scroll)
        lanes.setSizes([520, 660])
        content.addWidget(lanes)
        layout.addWidget(self.editing)
        self.feedback = label("")
        self.feedback.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.feedback)
        bottom = QHBoxLayout()
        self.preview_button = button("Gerar prévia com áudio", lambda: self.start_render(preview=True))
        self.export_button = button("Exportar MP4", lambda: self.start_render(preview=False), "primary")
        self.cancel_button = button("Cancelar processamento", self.cancel_render, "danger")
        self.cancel_button.hide()
        self.open_result = button("Abrir vídeo", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.result_path or "")))
        self.open_folder = button("Abrir pasta", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.result_path).parent))))
        self.open_result.hide()
        self.open_folder.hide()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bottom.addWidget(self.preview_button)
        bottom.addWidget(self.progress, 1)
        bottom.addStretch()
        bottom.addWidget(self.open_result)
        bottom.addWidget(self.open_folder)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.export_button)
        layout.addLayout(bottom)
        layout.addStretch()

    def _message(self, text, kind="muted"):
        self.feedback.setText(text)
        apply_style(self.feedback, f"color: @{kind}@;")

    def _set_busy(self, busy):
        self.editing.setEnabled(not busy)
        for w in (self.open_button, self.save_button, self.title_edit, self.preview_button, self.export_button):
            w.setEnabled(not busy)
        self.cancel_button.setVisible(busy and bool(self.worker and self.worker.isRunning()))
        self.progress.setVisible(busy)
        if not busy:
            self.refresh_validation()

    def _changed(self, media=True):
        if self._refreshing:
            return
        self.dirty = True
        self.save_status.setText("● Alterações não salvas")
        if media:
            self.player.stop()
            self.preview_path = None
            self.play_button.setEnabled(False)
            self.seek.setEnabled(False)
            self.timeline.position = 0
            self.show_page()
        self.refresh_validation()

    def _title_changed(self, text):
        self.project.title = text.strip() or "Projeto SlideCast"
        self._changed(media=False)

    def _duration_changed(self, value):
        index = self.page_spin.value()-1
        if not self._refreshing and 0 <= index < len(self.project.slide_durations):
            self.project.slide_durations[index] = value
            self._changed()

    def _export_changed(self):
        if self._refreshing:
            return
        self.project.export_settings["resolution"] = list(self.resolution.currentData())
        self.project.export_settings["fps"] = self.fps.value()
        self._changed()

    def _zoom_changed(self):
        self.timeline.setMinimumWidth(max(400, self.timeline_scroll.viewport().width()) * self.zoom.currentData())

    def _select_track(self, track_id):
        for row in self.track_widgets:
            if row.track.id == track_id:
                row.edit_name.setFocus()

    def source_dialog(self, kind):
        # Selection only changes once a valid file has been imported.
        self.pdf_button.setChecked(self.project.visual_source_type == "pdf" and bool(self.project.visual_source_path))
        self.video_button.setChecked(self.project.visual_source_type == "video" and bool(self.project.visual_source_path))
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar fonte visual", "", "Apresentação PDF (*.pdf)" if kind == "pdf" else "Vídeo MP4 (*.mp4)")
        if path:
            self.import_file(kind, path)

    def import_file(self, operation, path, track_id=None):
        if self.busy:
            return
        if operation == "audio" and not track_id and len(self.project.tracks) >= MAX_AUDIO_TRACKS:
            self._message("Você já tem quatro faixas. Remova ou substitua uma delas para adicionar outro áudio.", "warning")
            return
        if operation in ("pdf", "video") and self.project.visual_source_path:
            reply = QMessageBox.question(self, "Substituir fonte visual?", "As faixas de áudio serão mantidas. Os tempos das páginas serão definidos para a nova fonte. Continuar?", QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.player.stop()
        self._message("Lendo o arquivo e conferindo a mídia…")
        self.progress.setRange(0, 0)
        worker = ImportWorker(self.project, operation, path, track_id, self)
        self.import_worker = worker
        worker.loaded.connect(lambda project, file: self._imported(project, operation, file))
        worker.failed.connect(lambda msg: self._message(msg, "danger"))
        worker.finished.connect(lambda: self._set_busy(False))
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "import_worker", None))
        worker.start()
        self._set_busy(True)

    def _imported(self, project, operation, path):
        self.project = project
        self.preview_path = None
        self.refresh()
        if operation == "open":
            self.project_path = path
            self.dirty = False
            self.save_status.setText("Projeto aberto · alterações preservadas")
        else:
            self._changed()
        self._message("Arquivo importado. " + ("Suas faixas foram mantidas." if operation in ("pdf", "video") else ""), "success")
        self.refresh_validation()

    def audio_dialog(self, track_id=None):
        if isinstance(track_id, bool):
            track_id = None
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar arquivo de áudio", "", AUDIO_FILTER)
        if path:
            self.import_file("audio", path, track_id)

    def remove_track(self, track_id):
        self.project.remove_track(track_id)
        self.refresh_tracks()
        self._changed()

    def refresh_tracks(self):
        for row in self.track_widgets:
            self.tracks_layout.removeWidget(row)
            row.deleteLater()
        self.track_widgets = []
        self.empty_tracks.setVisible(not self.project.tracks)
        for index, track in enumerate(self.project.tracks):
            row = AudioTrackItemWidget(track, index, self)
            row.track_changed.connect(lambda _id: self._changed())
            row.remove_requested.connect(self.remove_track)
            row.replace_requested.connect(self.audio_dialog)
            self.tracks_layout.addWidget(row)
            self.track_widgets.append(row)
        self.timeline.project = self.project
        self.timeline.refresh()
        self.track_count.setText(f"{len(self.project.tracks)} de 4")
        full = len(self.project.tracks) == MAX_AUDIO_TRACKS
        self.add_audio_button.setEnabled(not full)
        self.limit_label.setText("Limite de 4 faixas atingido. Use Trocar ou Remover para incluir outro áudio." if full else "Narração, música, sonoplastia e complementos. Arraste um áudio para importar.")

    def refresh(self):
        self._refreshing = True
        p = self.project
        self.title_edit.setText(p.title)
        is_pdf = p.visual_source_type == "pdf"
        self.pdf_button.setChecked(is_pdf and bool(p.visual_source_path))
        self.video_button.setChecked(not is_pdf and bool(p.visual_source_path))
        self.pdf_controls.setVisible(is_pdf and bool(p.slide_durations))
        self.balance_button.setVisible(is_pdf)
        self.balance_button.setEnabled(bool(p.tracks and p.slide_durations))
        self.page_spin.setRange(1, max(1, len(p.slide_durations)))
        self.source_label.setText(Path(p.visual_source_path).name if p.visual_source_path else "Nenhuma fonte selecionada")
        self.source_label.setToolTip(p.visual_source_path or "")
        if is_pdf and p.slide_durations:
            self.source_label.setText(self.source_label.text()+f"\n{len(p.slide_durations)} páginas · PDF")
        elif p.video_info:
            self.source_label.setText(self.source_label.text()+f"\n{p.video_info.resolution_str} · {p.video_info.formatted_duration}")
        self.original_audio.setText("O vídeo já tem som. O áudio original não será incluído." if p.video_info and p.video_info.has_audio else "")
        self.original_audio.setVisible(bool(p.video_info and p.video_info.has_audio))
        resolution = p.export_settings.get("resolution", [1920, 1080])
        index = self.resolution.findData(list(resolution))
        if index < 0:
            self.resolution.addItem(f"Original · {resolution[0]} × {resolution[1]}", list(resolution))
            index = self.resolution.count()-1
        self.resolution.setCurrentIndex(index)
        self.fps.setValue(p.export_settings.get("fps", 30))
        self.refresh_tracks()
        self._refreshing = False
        self.show_page()
        self.refresh_validation()

    def show_page(self, *_):
        p = self.project
        if self.preview_path:
            return
        self.preview_caption.setText("PRÉVIA DA IMAGEM · gere uma prévia para conferir a mistura de áudio")
        if p.visual_source_type == "pdf":
            self.preview_stack.setCurrentWidget(self.image_preview)
            index = self.page_spin.value()-1
            self.duration_spin.blockSignals(True)
            if 0 <= index < len(p.slide_durations):
                self.duration_spin.setValue(p.slide_durations[index])
            self.duration_spin.blockSignals(False)
            pix = QPixmap()
            if p.visual_source_path and Path(p.visual_source_path).is_file():
                try:
                    pix.loadFromData(render_thumbnail(p.visual_source_path, index, max_dimension=1100))
                except Exception:
                    self._message("Não foi possível mostrar esta página. Confira o arquivo PDF.", "warning")
            self.image_preview.pixmap = pix
            self.image_preview.update()
        elif p.visual_source_path and Path(p.visual_source_path).is_file():
            self.preview_stack.setCurrentWidget(self.video_preview)
            self.audio_output.setMuted(True)
            self.player.setSource(QUrl.fromLocalFile(p.visual_source_path))
            # Decode a real source frame with Qt; the original audio stays muted.
            self.player.play()
            QTimer.singleShot(250, self._pause_source)

    def _pause_source(self):
        if not self.preview_path:
            self.player.pause()
            self.play_button.setText("▶ Reproduzir")

    def refresh_validation(self):
        total = self.project.calculate_total_duration()
        valid, messages = self.project.validate()
        valid = valid and bool(get_ffmpeg_paths()[0]) and not self.busy
        self.export_button.setEnabled(valid)
        self.preview_button.setEnabled(valid)
        self.total_label.setText(f"MP4 · {format_duration(total)} de vídeo")
        self.timeline.refresh()
        self.balance_button.setEnabled(bool(self.project.tracks and self.project.slide_durations))
        for row in self.track_widgets:
            row.total = total
            row.update_status(total)
        if messages and self.project.visual_source_path:
            self._message("\n".join(messages), "warning" if valid else "danger")
        elif self.project.visual_source_path and not self.project.tracks:
            self._message("Sem faixas de áudio: o vídeo será exportado sem som.", "warning")

    def balance_pages(self):
        if self.project.tracks and self.project.slide_durations:
            duration = self.project.tracks[0].effective_end()/len(self.project.slide_durations)
            if duration < .1:
                self._message("O áudio é curto demais para distribuir entre todas as páginas.", "warning")
                return
            self.project.slide_durations = [duration]*len(self.project.slide_durations)
            self.show_page()
            self._changed()

    def confirm_discard(self):
        if self.busy:
            self._message("Aguarde o processamento ou cancele a renderização antes de fechar o projeto.", "warning")
            return False
        if not self.dirty:
            return True
        reply = QMessageBox.question(self, "Salvar alterações?", "Este projeto tem alterações não salvas.", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if reply == QMessageBox.Save:
            return self.save_dialog()
        return reply == QMessageBox.Discard

    def save_dialog(self):
        path = self.project_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Salvar projeto", "minha-aula.slidecast", "Projeto SlideCast (*.slidecast)")
        if not path:
            return False
        if not path.lower().endswith(".slidecast"):
            path += ".slidecast"
        try:
            self.project.save_to_file(path)
        except Exception:
            logger.exception("Falha ao salvar projeto")
            self._message("Não foi possível salvar. Escolha uma pasta com permissão de escrita.", "danger")
            return False
        self.project_path, self.dirty = path, False
        self.save_status.setText("✓ Projeto salvo")
        self.save_status.setToolTip(path)
        return True

    def open_dialog(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Abrir projeto", "", "Projeto SlideCast (*.slidecast *.json)")
        if path:
            self.import_file("open", path)

    def start_render(self, preview=False, output_path=None):
        if self.busy:
            return
        valid, messages = self.project.validate()
        if not valid:
            self._message("\n".join(messages), "danger")
            return
        if preview:
            output_path = str(Path(self._temp.name)/"previa.mp4")
        elif not output_path:
            output_path, _ = QFileDialog.getSaveFileName(self, "Exportar vídeo MP4", self.project.export_settings.get("output_path") or "minha-aula.mp4", "Vídeo MP4 (*.mp4)")
        if not output_path:
            return
        if not output_path.lower().endswith(".mp4"):
            output_path += ".mp4"
        inputs = [self.project.visual_source_path] + [t.file_path for t in self.project.tracks]
        if any(path and Path(path).resolve() == Path(output_path).resolve() for path in inputs):
            self._message("Escolha outro nome para o vídeo final. O arquivo de origem precisa ser preservado.", "danger")
            return
        self.player.stop()
        self.player.setSource(QUrl())
        self.preview_path = None
        self.play_button.setEnabled(False)
        self.seek.setEnabled(False)
        if not preview:
            self.project.export_settings["output_path"] = output_path
            self._changed(media=False)
        snapshot = copy.deepcopy(self.project)
        if preview:
            w,h = snapshot.export_settings["resolution"]
            snapshot.export_settings["resolution"] = [640, max(2, round(640*h/w/2)*2)] if w >= h else [max(2,round(360*w/h/2)*2),360]
            snapshot.export_settings["fps"] = min(15, snapshot.export_settings["fps"])
        self._preview_mode = preview
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.open_result.hide()
        self.open_folder.hide()
        worker = MultimediaRenderWorker(snapshot, output_path, parent=self)
        self.worker = worker
        worker.progress_changed.connect(self._render_progress)
        worker.render_finished.connect(self._render_complete)
        worker.render_error.connect(self._render_error)
        worker.render_cancelled.connect(lambda: self._message("Processamento cancelado. Seu projeto continua disponível.", "warning"))
        worker.finished.connect(self._worker_finished)
        worker.start()
        self._set_busy(True)
        self._message("Gerando prévia com a mistura real de áudio…" if preview else "Preparando seu vídeo…")

    def _worker_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self._set_busy(False)

    def _render_progress(self, fraction, message):
        self.progress.setValue(round(fraction*100))
        self._message(f"{round(fraction*100)}% · {message}")

    def _render_error(self, message):
        logger.error("Renderização: %s", message)
        self._message("Não foi possível gerar o vídeo. Confira os arquivos, o espaço livre e a pasta de destino. Seu projeto foi preservado.", "danger")

    def _render_complete(self, path):
        if not Path(path).is_file() or not Path(path).stat().st_size:
            self._render_error("Saída ausente")
            return
        self.preview_path = path
        self.preview_stack.setCurrentWidget(self.video_preview)
        self.audio_output.setMuted(False)
        self.audio_output.setVolume(1.0)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.play_button.setEnabled(True)
        self.seek.setEnabled(True)
        self.preview_caption.setText("PRÉVIA COM ÁUDIO · mesma mistura usada na exportação")
        self._message("Prévia pronta. Reproduza para conferir os áudios." if self._preview_mode else f"Vídeo gerado · {path}", "success")
        if not self._preview_mode:
            self.result_path = path
            self.open_result.show()
            self.open_folder.show()

    def toggle_play(self):
        if self.preview_path:
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    def _position_changed(self, ms):
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        self.player_time.setText(f"{format_duration(ms/1000)} / {format_duration(self.player.duration()/1000)}")
        if self.preview_path:
            self.timeline.position = ms/1000
            self.timeline.update()

    def cancel_render(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self._message("Cancelando… aguarde a finalização do processo.")

    def dragEnterEvent(self, event):
        if not self.busy and event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = event.mimeData().urls()[0].toLocalFile()
        ext = Path(path).suffix.lower()
        if ext in (".pdf", ".mp4"):
            self.import_file("pdf" if ext == ".pdf" else "video", path)
        elif ext in SUPPORTED_AUDIO_EXTENSIONS:
            self.import_file("audio", path)
        else:
            self._message("Formato incompatível. Importe PDF, MP4 ou um áudio MP3, WAV, M4A, AAC, OGG, FLAC ou WebM.", "danger")
        event.acceptProposedAction()
