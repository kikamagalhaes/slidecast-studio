"""Application shell. Editing and recording keep independent state when navigating."""
from pathlib import Path
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtMultimedia import QMediaRecorder
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QComboBox, QStackedWidget, QScrollArea, QMessageBox,
    QInputDialog, QLineEdit,
)
from app.core.config_manager import get_gemini_api_key, set_gemini_api_key
from app.core.ffmpeg_utils import get_ffmpeg_paths
from app.core.pdf_processor import inspect_pdf
from app.ui.styles import theme_manager, apply_style
from app.ui.home_cards import MainView, build_home_menu
from app.ui.views import RecordClassView, RecordMeetView, RecordPodcastView, GenerateMaterialsView
from app.ui.views.create_video_view import CreateVideoView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SlideCast Studio")
        self.resize(1360, 920)
        self.setMinimumSize(760, 520)
        self.theme_manager = theme_manager()
        self._build_ui()
        self._check_ffmpeg()
        self._check_gemini_status()
        self._check_license_status()
        shortcut = QShortcut(QKeySequence.Save, self)
        shortcut.activated.connect(self._save_active)
        shortcut_open = QShortcut(QKeySequence.Open, self)
        shortcut_open.activated.connect(self._open_editor)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QFrame()
        header.setObjectName("appHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(24, 12, 24, 12)
        brand = QPushButton("◧  SlideCast Studio")
        brand.setAccessibleName("SlideCast Studio, ir para início")
        apply_style(brand, "border: none; color: @primary@; font-size: 19px; font-weight: 700;")
        brand.clicked.connect(lambda: self.navigate(MainView.HOME))
        row.addWidget(brand)
        row.addSpacing(20)
        self.navigation = QComboBox()
        self.navigation.setAccessibleName("Área de trabalho")
        for title in ("Início", "Criar vídeo", "Gravar aula", "Gravar tela / reunião", "Podcast", "Materiais da aula"):
            self.navigation.addItem(title)
        self.navigation.activated.connect(self.navigate)
        row.addWidget(self.navigation)
        row.addStretch()
        row.addWidget(QLabel("Aparência"))
        self.theme_combo = QComboBox()
        self.theme_combo.setAccessibleName("Tema da interface")
        self.theme_combo.addItem("Claro", "light")
        self.theme_combo.addItem("Escuro", "dark")
        self.theme_combo.setCurrentIndex(0 if self.theme_manager.name == "light" else 1)
        self.theme_combo.currentIndexChanged.connect(lambda: self.theme_manager.set_theme(self.theme_combo.currentData()))
        self.theme_manager.changed.connect(self._theme_changed)
        row.addWidget(self.theme_combo)
        root.addWidget(header)
        self.stack = QStackedWidget()
        self.stack.currentChanged.connect(self.navigation.setCurrentIndex)
        root.addWidget(self.stack, 1)
        self.home_view = self._build_home_view()
        self.create_video_view = CreateVideoView(self)
        self.record_class_view = RecordClassView(self)
        self.record_meet_view = RecordMeetView(self)
        self.record_podcast_view = RecordPodcastView(self)
        self.generate_materials_view = GenerateMaterialsView(self)
        for view in (self.home_view, self.create_video_view, self.record_class_view,
                     self.record_meet_view, self.record_podcast_view, self.generate_materials_view):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(view)
            scroll.setMinimumSize(0, 0)
            self.stack.addWidget(scroll)
            if hasattr(view, "back_to_home"):
                view.back_to_home.connect(lambda: self.navigate(MainView.HOME))
        self.generate_materials_view.send_to_create_video.connect(self._on_material_sent_to_create_video)
        self.generate_materials_view.send_to_record_class.connect(self._on_material_sent_to_record_class)
        self.stack.setCurrentIndex(MainView.HOME)
        self.home_view.setFocusPolicy(Qt.StrongFocus)
        self.home_view.setFocus(Qt.OtherFocusReason)

    def _theme_changed(self, name):
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(0 if name == "light" else 1)
        self.theme_combo.blockSignals(False)

    def _build_home_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(20)
        eyebrow = QLabel("SEU ESTÚDIO. SUAS IDEIAS.")
        apply_style(eyebrow, "color: @primary@; font-size: 12px; font-weight: 700;")
        layout.addWidget(eyebrow)
        title = QLabel("O que vamos criar hoje?")
        apply_style(title, "font-size: 34px; font-weight: 700; color: @text@;")
        layout.addWidget(title)
        subtitle = QLabel("Dê vida ao que você ensina. Prepare um vídeo, grave uma aula ou compartilhe sua voz.")
        subtitle.setWordWrap(True)
        subtitle.setProperty("class", "subtitle")
        layout.addWidget(subtitle)
        layout.addLayout(build_home_menu(self.navigate))
        layout.addStretch(1)
        footer = QHBoxLayout()
        self.lbl_ffmpeg_status = QLabel()
        footer.addWidget(self.lbl_ffmpeg_status)
        footer.addSpacing(16)
        self.lbl_license_status = QLabel()
        footer.addWidget(self.lbl_license_status)
        self.btn_license = QPushButton("Licença")
        self.btn_license.clicked.connect(self._open_license_dialog)
        footer.addWidget(self.btn_license)
        footer.addStretch()
        self.lbl_gemini_status = QLabel()
        self.lbl_gemini_status.setProperty("class", "muted")
        footer.addWidget(self.lbl_gemini_status)
        self.btn_gemini_key = QPushButton("Configurar IA opcional")
        self.btn_gemini_key.clicked.connect(self._open_gemini_key_dialog)
        footer.addWidget(self.btn_gemini_key)
        layout.addLayout(footer)
        return widget

    def _check_license_status(self):
        from app.core.license_manager import get_license_manager
        from app.core.license_models import LicenseStatus
        mgr = get_license_manager()
        status = mgr.status
        if status == LicenseStatus.ACTIVE:
            self.lbl_license_status.setText("✓ Licença ativa")
            self.lbl_license_status.setProperty("class", "badge-success")
        elif status == LicenseStatus.NO_CONNECTION:
            self.lbl_license_status.setText("✓ Licença offline")
            self.lbl_license_status.setProperty("class", "badge-neutral")
        else:
            self.lbl_license_status.setText("Modo gratuito")
            self.lbl_license_status.setProperty("class", "badge-warning")

    def _open_license_dialog(self):
        from app.ui.dialogs.license_dialog import LicenseDialog
        dlg = LicenseDialog(self)
        dlg.license_updated.connect(self._check_license_status)
        dlg.exec_()

    def _check_ffmpeg(self):
        ready = bool(get_ffmpeg_paths()[0])
        self.lbl_ffmpeg_status.setText("✓ Exportação local disponível" if ready else "FFmpeg ausente · exportação indisponível")
        self.lbl_ffmpeg_status.setProperty("class", "badge-success" if ready else "badge-warning")

    def _check_gemini_status(self):
        self.lbl_gemini_status.setText("IA opcional configurada" if get_gemini_api_key() else "Recursos de IA opcionais")

    def _open_gemini_key_dialog(self):
        key, accepted = QInputDialog.getText(self, "IA opcional · Google Gemini",
            "Estes recursos usam um serviço online. PDF, áudio e exportação local funcionam sem esta chave.\nChave de API:",
            QLineEdit.Password, get_gemini_api_key() or "")
        if accepted:
            set_gemini_api_key(key.strip())
            self._check_gemini_status()

    def _recording_active(self):
        return any(recorder.recorderState() != QMediaRecorder.StoppedState for recorder in self.findChildren(QMediaRecorder)) or any(
            bool(getattr(view, "is_recording", False) or getattr(view, "is_voice_recording", False))
            for view in (self.record_class_view, self.record_meet_view, self.record_podcast_view)
        )

    def navigate(self, index):
        if index != self.stack.currentIndex() and self._recording_active():
            QMessageBox.information(self, "Gravação em andamento", "Finalize a gravação nos controles do estúdio antes de trocar de área.")
            self.navigation.setCurrentIndex(self.stack.currentIndex())
            return
        self.stack.setCurrentIndex(index)
        if index != MainView.CREATE_VIDEO:
            self.create_video_view.player.pause()

    def _save_active(self):
        if self.stack.currentIndex() == MainView.CREATE_VIDEO and not self.create_video_view.busy:
            self.create_video_view.save_dialog()

    def _open_editor(self):
        self.navigate(MainView.CREATE_VIDEO)
        if self.stack.currentIndex() == MainView.CREATE_VIDEO:
            self.create_video_view.open_dialog()

    def _on_material_sent_to_create_video(self, pdf_path):
        self.navigate(MainView.CREATE_VIDEO)
        self.create_video_view.import_file("pdf", pdf_path)

    def _on_material_sent_to_record_class(self, pdf_path):
        try:
            view = self.record_class_view
            view.pdf_info = inspect_pdf(pdf_path)
            view.lbl_pdf_status.setText(f"✓ {Path(pdf_path).name} · {view.pdf_info.page_count} páginas")
            apply_style(view.lbl_pdf_status, "color: @success@; font-weight: 600;")
            self.navigate(MainView.RECORD_CLASS)
        except Exception:
            QMessageBox.warning(self, "Não foi possível abrir", "Confira o PDF gerado e tente novamente.")

    def closeEvent(self, event):
        if self._recording_active() or any(worker.isRunning() for worker in self.findChildren(QThread)):
            QMessageBox.information(self, "Trabalho em andamento", "Finalize a gravação ou cancele o processamento antes de fechar o SlideCast.")
            event.ignore()
            return
        if not self.create_video_view.confirm_discard():
            event.ignore()
            return
        self.create_video_view.player.stop()
        event.accept()
