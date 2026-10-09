import logging
import os
import sys
import time
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap, QImage, QKeyEvent
from PySide6.QtMultimedia import (
    QMediaDevices,
    QAudioInput,
    QAudioOutput,
    QMediaCaptureSession,
    QMediaRecorder,
    QCamera,
    QMediaPlayer,
    QMediaFormat,
)
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QCheckBox,
    QFrame,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QScrollArea,
    QProgressBar,
    QSizePolicy,
    QButtonGroup,
    QRadioButton,
)

import pymupdf

from app.core.ffmpeg_utils import format_duration, get_video_duration
from app.core.config_manager import get_gemini_api_key
from app.core.pdf_processor import inspect_pdf, render_thumbnail, PresentationInfo
from app.core.subtitles_generator import SUPPORTED_LANGUAGES
from app.core.meeting_recorder import ScreenRecordingProcess
from app.core.clone_manager import get_active_clone, list_clones
from app.ui.teleprompter_widget import TeleprompterWidget
from app.ui.dialogs.generate_cover_dialog import GenerateCoverDialog
from app.ui.dialogs.avatar_calibration_dialog import AvatarCalibrationDialog
from app.ui.dialogs.clone_engine_selection_dialog import CloneEngineSelectionDialog
from app.ui.voice_prompt_button import VoicePromptButton
from app.ui.views.class_panels import (
    build_result_view,
    build_setup_view,
    build_studio_view,
)
from app.ui.workers.class_render_workers import (
    ClassVideoRenderWorker,
    CloneLessonRenderWorker,
    TutorialPostProcessWorker,
)

logger = logging.getLogger(__name__)


class RecordClassView(QWidget):
    back_to_home = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_info: Optional[PresentationInfo] = None
        self.cover_image_path: Optional[str] = None
        self.bgm_path: Optional[str] = None
        self.output_video_path: Optional[str] = None
        self.worker = None

        # Mode: "slides" or "screen" (tutorial de aplicativo)
        self.visual_mode: str = "slides"
        self.presenter_mode: str = "live"  # "live" or "clone"
        self.active_clone_data: Optional[dict] = get_active_clone()
        self.screen_recorder: Optional[ScreenRecordingProcess] = None
        self.screen_tutorial_video_path: Optional[str] = None

        # Publication Format & Vinhetas
        self.video_format: str = "youtube"  # 'youtube' (16:9), 'shorts' (9:16), 'reels' (9:16)
        self.vertical_layout: str = "presenter"  # 'presenter' (foco no apresentador) ou 'split_slides' (com slides)
        self.intro_mode: str = "auto"       # 'auto', 'custom', 'none'
        self.intro_video_path: Optional[str] = None
        self.outro_mode: str = "auto"       # 'auto', 'custom', 'none'
        self.outro_video_path: Optional[str] = None

        # Live Recording State
        self.current_slide_idx = 0
        self.is_recording = False
        self.record_start_time = 0.0
        self.slide_start_time = 0.0
        self.recorded_slide_durations: List[float] = []

        # Recording session & recorder
        self.capture_session = QMediaCaptureSession(self)
        self.audio_input = QAudioInput(self)
        self.capture_session.setAudioInput(self.audio_input)
        self.recorder = QMediaRecorder(self)
        self.capture_session.setRecorder(self.recorder)

        # Timer for recording duration
        self.record_timer = QTimer(self)
        self.record_timer.setInterval(200)
        self.record_timer.timeout.connect(self._update_record_time_display)

        # Human voice recording/import for Clone Lesson (Step 4)
        self.custom_human_audio_path: Optional[str] = None
        self.is_voice_recording = False
        self.voice_record_start_time = 0.0

        self.voice_capture_session = QMediaCaptureSession(self)
        self.voice_audio_input = QAudioInput(self)
        self.voice_capture_session.setAudioInput(self.voice_audio_input)
        self.voice_recorder = QMediaRecorder(self)
        self.voice_capture_session.setRecorder(self.voice_recorder)

        self.voice_timer = QTimer(self)
        self.voice_timer.setInterval(200)
        self.voice_timer.timeout.connect(self._update_voice_timer_display)

        self.preview_player: Optional[QMediaPlayer] = None
        self.preview_audio_output: Optional[QAudioOutput] = None

        self._build_ui()
        self._refresh_active_clone_ui()
        self._refresh_audio_and_video_devices()

        # Connect dynamic hardware change signals
        try:
            QMediaDevices.videoInputsChanged.connect(self._refresh_audio_and_video_devices)
            QMediaDevices.audioInputsChanged.connect(self._refresh_audio_and_video_devices)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_audio_and_video_devices()
        self._refresh_active_clone_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)

        self.setup_view = build_setup_view(self)
        self.studio_view = build_studio_view(self)
        self.result_view = build_result_view(self)

        self.stack.addWidget(self.setup_view)   # Index 0: Configuração
        self.stack.addWidget(self.studio_view)  # Index 1: Estúdio ao Vivo
        self.stack.addWidget(self.result_view)  # Index 2: Vídeo Concluído

        self.stack.setCurrentIndex(0)

    def _update_presenter_cards_style(self):
        if not hasattr(self, "card_pres_live") or not hasattr(self, "card_pres_clone"):
            return
        if self.radio_pres_live.isChecked():
            self.card_pres_live.setStyleSheet(
                "QFrame#cardPresLive { background-color: #1e1b4b; border: 2px solid #818cf8; border-radius: 10px; }"
            )
            self.card_pres_clone.setStyleSheet(
                "QFrame#cardPresClone { background-color: #0f172a; border: 1.5px solid #2d3748; border-radius: 10px; }"
            )
        else:
            self.card_pres_live.setStyleSheet(
                "QFrame#cardPresLive { background-color: #0f172a; border: 1.5px solid #2d3748; border-radius: 10px; }"
            )
            self.card_pres_clone.setStyleSheet(
                "QFrame#cardPresClone { background-color: #2e1065; border: 2px solid #c084fc; border-radius: 10px; }"
            )

    def _update_format_cards_style(self):
        items = [
            (getattr(self, "card_fmt_yt", None), getattr(self, "radio_fmt_yt", None)),
            (getattr(self, "card_fmt_shorts", None), getattr(self, "radio_fmt_shorts", None)),
            (getattr(self, "card_fmt_reels", None), getattr(self, "radio_fmt_reels", None)),
        ]
        for card, radio in items:
            if card and radio:
                if radio.isChecked():
                    card.setStyleSheet(
                        "QFrame { background-color: #1e1b4b; border: 2px solid #818cf8; border-radius: 10px; }"
                    )
                else:
                    card.setStyleSheet(
                        "QFrame { background-color: #161922; border: 1.5px solid #2d3748; border-radius: 10px; }"
                    )

    def _on_video_format_changed(self):
        if self.radio_fmt_yt.isChecked():
            self.video_format = "youtube"
            if hasattr(self, "box_vert_layout"):
                self.box_vert_layout.hide()
        elif self.radio_fmt_shorts.isChecked():
            self.video_format = "shorts"
            if hasattr(self, "box_vert_layout"):
                self.box_vert_layout.show()
        elif self.radio_fmt_reels.isChecked():
            self.video_format = "reels"
            if hasattr(self, "box_vert_layout"):
                self.box_vert_layout.show()
        self._update_format_cards_style()

    def _on_vertical_layout_changed(self):
        if hasattr(self, "radio_vlayout_presenter") and self.radio_vlayout_presenter.isChecked():
            self.vertical_layout = "presenter"
        else:
            self.vertical_layout = "split_slides"

    def _pick_custom_intro(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Vinheta de Abertura",
            "",
            "Vídeos (*.mp4 *.mov *.mkv *.webm *.avi)",
        )
        if file_path:
            self.intro_video_path = file_path
            self.lbl_intro_file.setText(f"✓ {Path(file_path).name}")
            self.lbl_intro_file.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
            self.radio_intro_custom.setChecked(True)
            self.intro_mode = "custom"
        elif not self.intro_video_path:
            self.radio_intro_auto.setChecked(True)
            self.intro_mode = "auto"

    def _pick_custom_outro(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Vinheta de Encerramento",
            "",
            "Vídeos (*.mp4 *.mov *.mkv *.webm *.avi)",
        )
        if file_path:
            self.outro_video_path = file_path
            self.lbl_outro_file.setText(f"✓ {Path(file_path).name}")
            self.lbl_outro_file.setStyleSheet("color: #c084fc; font-weight: 600; font-size: 11px;")
            self.radio_outro_custom.setChecked(True)
            self.outro_mode = "custom"
        elif not self.outro_video_path:
            self.radio_outro_auto.setChecked(True)
            self.outro_mode = "auto"

    def _on_intro_mode_changed(self):
        if self.radio_intro_auto.isChecked():
            self.intro_mode = "auto"
        elif self.radio_intro_custom.isChecked():
            if not self.intro_video_path:
                self._pick_custom_intro()
            else:
                self.intro_mode = "custom"
        else:
            self.intro_mode = "none"

    def _on_outro_mode_changed(self):
        if self.radio_outro_auto.isChecked():
            self.outro_mode = "auto"
        elif self.radio_outro_custom.isChecked():
            if not self.outro_video_path:
                self._pick_custom_outro()
            else:
                self.outro_mode = "custom"
        else:
            self.outro_mode = "none"

    def _switch_step(self, idx: int):
        self.step_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.step_buttons):
            if i == idx:
                btn.setStyleSheet(
                    "background: #4f46e5; color: #ffffff; font-weight: 700; "
                    "border: 1.5px solid #818cf8; padding: 8px 12px; border-radius: 8px; font-size: 12px;"
                )
            else:
                btn.setStyleSheet(
                    "background: #1a1e28; color: #94a3b8; font-weight: 600; "
                    "border: 1px solid #2d3343; padding: 8px 12px; border-radius: 8px; font-size: 12px;"
                )

    # ----------------------------------------------------
    # EVENTS & HANDLERS
    # ----------------------------------------------------
    def _on_format_changed(self):
        if self.radio_slides.isChecked():
            self.visual_mode = "slides"
            self.lbl_format_desc.setText(
                "Apresente seus slides em PDF com narração sincronizada."
            )
            self.card_slides.show()
            self.box_screen_res.hide()
            self.box_presenter_mode.show()
            self._on_presenter_mode_changed()
        else:
            self.visual_mode = "screen"
            self.lbl_format_desc.setText(
                "Grave a tela do computador (tutorial de aplicativos, softwares e demonstrações) com microfone e teleprompter."
            )
            self.card_slides.hide()
            self.box_screen_res.show()
            self.box_presenter_mode.hide()
            self.card_clone_status.hide()
            if hasattr(self, "card_clone_dev_hint"):
                self.card_clone_dev_hint.hide()
            self.card_dev.show()
            self.btn_enter_studio.show()
            self.btn_generate_clone_lesson.hide()
            self.ct_title.setText("4. Roteiro da Aula para o Teleprompter (Opcional)")
            self.ct_sub.setText("Cole o roteiro abaixo. Ele rolará no topo da tela durante a gravação para você ler olhando para a câmera:")
        self._update_presenter_cards_style()

    def _on_presenter_mode_changed(self):
        self._update_presenter_cards_style()
        if self.visual_mode != "slides":
            return
        if self.radio_pres_clone.isChecked():
            self.presenter_mode = "clone"
            self.card_clone_status.show()
            self.card_dev.hide()
            if hasattr(self, "card_clone_dev_hint"):
                self.card_clone_dev_hint.show()
            self.btn_enter_studio.hide()
            self.btn_generate_clone_lesson.show()
            self.ct_title.setText("4. Roteiro / Texto Falado pelo Clone IA")
            self.ct_sub.setText("Escreva ou dite abaixo o texto da aula. A IA sintetizará sua voz e animará seu avatar perfeitamente sobre os slides:")
        else:
            self.presenter_mode = "live"
            self.card_clone_status.hide()
            self.card_dev.show()
            if hasattr(self, "card_clone_dev_hint"):
                self.card_clone_dev_hint.hide()
            self.btn_enter_studio.show()
            self.btn_generate_clone_lesson.hide()
            self.ct_title.setText("4. Roteiro da Aula para o Teleprompter (Opcional)")
            self.ct_sub.setText("Cole o roteiro abaixo. Ele rolará no topo da tela durante a gravação para você ler olhando para a câmera:")

    def _refresh_audio_and_video_devices(self):
        # Refresh Mics
        curr_mic_data = self.combo_mics.currentData() if hasattr(self, "combo_mics") else None
        if hasattr(self, "combo_mics"):
            self.combo_mics.blockSignals(True)
            self.combo_mics.clear()
            audio_devs = QMediaDevices.audioInputs()
            if audio_devs:
                for d in audio_devs:
                    self.combo_mics.addItem(f"🎙️ {d.description()}", d)
                if curr_mic_data:
                    idx = self.combo_mics.findData(curr_mic_data)
                    if idx >= 0:
                        self.combo_mics.setCurrentIndex(idx)
            else:
                self.combo_mics.addItem("Microfone Padrão do Sistema", None)
            self.combo_mics.blockSignals(False)

        # Refresh Cams
        curr_cam_data = self.combo_cams.currentData() if hasattr(self, "combo_cams") else None
        if hasattr(self, "combo_cams"):
            self.combo_cams.blockSignals(True)
            self.combo_cams.clear()
            video_devs = QMediaDevices.videoInputs()
            if video_devs:
                for cam in video_devs:
                    self.combo_cams.addItem(f"📹 {cam.description()}", cam)
                if curr_cam_data:
                    idx = self.combo_cams.findData(curr_cam_data)
                    if idx >= 0:
                        self.combo_cams.setCurrentIndex(idx)
            else:
                # Fallback inspection on Linux
                v4l_path = Path("/sys/class/video4linux")
                v4l_found = []
                if v4l_path.exists():
                    for dev in sorted(v4l_path.glob("video*")):
                        name_file = dev / "name"
                        if name_file.exists():
                            dev_name = name_file.read_text().strip()
                            v4l_found.append(f"{dev_name} ({dev.name})")

                if v4l_found:
                    self.combo_cams.addItem(f"📹 {v4l_found[0]}", None)
                else:
                    self.combo_cams.addItem("Nenhuma câmera detectada", None)
            self.combo_cams.blockSignals(False)

    def _refresh_active_clone_ui(self):
        clone = get_active_clone()
        if clone:
            self.active_clone_data = clone
            name = clone.get("name", "Meu Clone IA")
            engine = clone.get("engine", "local")
            eng_badge = "🌐 Nuvem (ElevenLabs)" if engine == "cloud" else "💻 Local Gratuito (Neural Edge-TTS)"
            self.lbl_clone_name.setText(name)
            self.lbl_clone_engine.setText(f"Motor: {eng_badge}")

            face_p = clone.get("face_path")
            if face_p and os.path.exists(face_p):
                pix = QPixmap(face_p)
                if not pix.isNull():
                    scaled = pix.scaled(48, 48, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    self.lbl_clone_face.setPixmap(scaled)
                else:
                    self.lbl_clone_face.setText("🎭")
            else:
                self.lbl_clone_face.setText("🎭")
        else:
            self.active_clone_data = None
            self.lbl_clone_name.setText("Nenhum Clone Calibrado")
            self.lbl_clone_engine.setText("Clique ao lado para calibrar em 15 segundos")
            self.lbl_clone_face.setText("➕")

    def _open_clone_calibration(self):
        dlg = AvatarCalibrationDialog(self)
        dlg.clone_updated.connect(lambda _: self._refresh_active_clone_ui())
        dlg.exec()
        self._refresh_active_clone_ui()

    def _start_clone_generation(self):
        if not self.pdf_info:
            QMessageBox.warning(
                self,
                "PDF Necessário",
                "Por favor, selecione o arquivo PDF dos slides da aula antes de gerar a videoaula com seu clone.",
            )
            return

        clone = get_active_clone()
        if not clone:
            reply = QMessageBox.question(
                self,
                "Calibrar Clone Digital",
                "Você ainda não calibrou o seu Clone Digital.\nDeseja abrir o estúdio de calibração do clone agora?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._open_clone_calibration()
            return

        script = self.edit_script.toPlainText().strip()
        is_tts = self.radio_audio_tts.isChecked() if hasattr(self, "radio_audio_tts") else True
        if is_tts and not script:
            QMessageBox.warning(
                self,
                "Roteiro Necessário",
                "Como você escolheu sintetizar a voz com IA, por favor, digite ou dite o texto do roteiro da aula.",
            )
            return
        elif not is_tts:
            if not self.custom_human_audio_path or not os.path.exists(self.custom_human_audio_path):
                QMessageBox.warning(
                    self,
                    "Áudio de Voz Necessário",
                    "Por favor, grave sua voz pelo microfone ou selecione um arquivo de áudio (MP3/WAV) antes de gerar a videoaula.",
                )
                return

        if not self.bgm_path:
            reply = QMessageBox.question(
                self,
                "Fundo Musical Suave",
                "Deseja adicionar uma música de fundo suave a esta videoaula?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                file_path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Selecionar Música de Fundo",
                    "",
                    "Áudios (*.mp3 *.wav *.m4a *.aac *.ogg)",
                )
                if file_path:
                    self.bgm_path = file_path

        # Open lip-sync technology selection dialog (Cloud vs Local Neural vs Fast Local)
        dlg = CloneEngineSelectionDialog(self)
        if not dlg.exec():
            return
        chosen_engine = dlg.get_selected_engine()

        pdf_p = Path(self.pdf_info.file_path)
        if self.video_format in ("shorts", "reels"):
            suffix = f"{self.video_format}_{self.vertical_layout}"
        else:
            suffix = f"{self.video_format}"
        out_path = str(pdf_p.parent / f"{pdf_p.stem}_aula_clone_ia_{suffix}.mp4")

        self.stack.setCurrentIndex(2)
        self.lbl_result_icon.setText("⏳")
        self.lbl_result_title.setText("Gerando Videoaula com Meu Clone Digital IA...")
        self.lbl_result_status.setText("Processando fala e animando avatar sincronizado...")
        self.render_progress_bar.setValue(0)
        self.result_btn_container.hide()

        sub_lang = self.combo_sub_lang.currentData() or "pt"
        active_custom_audio = self.custom_human_audio_path if not is_tts else None
        self.worker = CloneLessonRenderWorker(
            pdf_path=self.pdf_info.file_path,
            script_text=script,
            output_path=out_path,
            clone_data=clone,
            class_title=self.edit_title.text().strip(),
            teacher_name=self.edit_teacher.text().strip(),
            cover_image=self.cover_image_path,
            bgm_path=self.bgm_path,
            enable_subtitles=self.chk_subtitles.isChecked(),
            subtitle_lang=sub_lang,
            engine_mode=chosen_engine,
            custom_audio_path=active_custom_audio,
            video_format=self.video_format,
            vertical_layout=self.vertical_layout,
            intro_mode=self.intro_mode,
            intro_video_path=self.intro_video_path,
            outro_mode=self.outro_mode,
            outro_video_path=self.outro_video_path,
            custom_bg_path=self.custom_bg_path,
            parent=self,
        )
        self.worker.progress_changed.connect(self._on_render_progress)
        self.worker.render_finished.connect(self._on_render_finished)
        self.worker.render_error.connect(self._on_render_error)
        self.worker.render_cancelled.connect(self._on_render_cancelled)
        self.btn_cancel_render.show()
        self.worker.start()

    def _on_audio_source_changed(self):
        if self.radio_audio_tts.isChecked():
            self.panel_audio_tts.show()
            self.panel_audio_record.hide()
            self.panel_audio_import.hide()
        elif self.radio_audio_record.isChecked():
            self.panel_audio_tts.hide()
            self.panel_audio_record.show()
            self.panel_audio_import.hide()
        else:
            self.panel_audio_tts.hide()
            self.panel_audio_record.hide()
            self.panel_audio_import.show()

    def _toggle_voice_recording(self):
        if not self.is_voice_recording:
            import tempfile
            temp_audio = str(Path(tempfile.gettempdir()) / f"teacher_voice_{int(time.time())}.m4a")
            self.custom_human_audio_path = temp_audio

            media_format = QMediaFormat()
            media_format.setFileFormat(QMediaFormat.FileFormat.MPEG4)
            media_format.setAudioCodec(QMediaFormat.AudioCodec.AAC)
            self.voice_recorder.setMediaFormat(media_format)
            self.voice_recorder.setOutputLocation(QUrl.fromLocalFile(temp_audio))
            self.voice_recorder.record()

            self.is_voice_recording = True
            self.voice_record_start_time = time.time()
            self.voice_timer.start()

            self.btn_record_voice.setText("⏹ Concluir Gravação")
            self.btn_record_voice.setStyleSheet(
                "background: #dc2626; color: #ffffff; font-weight: 700; font-size: 12px; padding: 7px 16px; border-radius: 6px;"
            )
            self.lbl_voice_status.setText("🔴 Gravando sua voz... Leia o roteiro com calma no seu ritmo.")
            self.lbl_voice_status.setStyleSheet("color: #ef4444; font-weight: 700; font-size: 11px;")
            self.btn_play_voice.setEnabled(False)
        else:
            self.voice_timer.stop()
            self.voice_recorder.stop()
            self.is_voice_recording = False

            self.btn_record_voice.setText("🔄 Gravar Novamente")
            self.btn_record_voice.setStyleSheet(
                "background: #1e293b; color: #38bdf8; font-weight: 600; font-size: 12px; padding: 7px 16px; border-radius: 6px;"
            )
            QTimer.singleShot(300, self._on_voice_recording_finished)

    def _on_voice_recording_finished(self):
        if self.custom_human_audio_path and os.path.exists(self.custom_human_audio_path):
            dur = get_video_duration(self.custom_human_audio_path)
            self.lbl_voice_status.setText(f"✓ Voz humana gravada: {format_duration(dur)} - Pronta para a aula!")
            self.lbl_voice_status.setStyleSheet("color: #10b981; font-weight: 700; font-size: 11px;")
            self.btn_play_voice.setEnabled(True)
            self.btn_play_voice.setText("▶ Ouvir Gravação")

    def _update_voice_timer_display(self):
        if self.is_voice_recording:
            elapsed = time.time() - self.voice_record_start_time
            self.lbl_voice_timer.setText(format_duration(elapsed))

    def _pick_human_audio_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Gravação de Voz da Aula",
            "",
            "Áudios (*.mp3 *.wav *.m4a *.aac *.ogg *.flac)",
        )
        if file_path:
            self.custom_human_audio_path = file_path
            dur = get_video_duration(file_path)
            self.lbl_import_audio_status.setText(f"✓ {Path(file_path).name} ({format_duration(dur)})")
            self.lbl_import_audio_status.setStyleSheet("color: #10b981; font-weight: 700; font-size: 11px;")
            self.btn_play_imported.setEnabled(True)
            self.btn_play_imported.setText("▶ Ouvir Áudio")

    def _play_preview_audio(self):
        if not self.custom_human_audio_path or not os.path.exists(self.custom_human_audio_path):
            return
        if not hasattr(self, "preview_player") or self.preview_player is None:
            self.preview_player = QMediaPlayer(self)
            self.preview_audio_output = QAudioOutput(self)
            self.preview_player.setAudioOutput(self.preview_audio_output)
            self.preview_audio_output.setVolume(1.0)
            self.preview_player.playbackStateChanged.connect(self._on_preview_playback_state_changed)

        if self.preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.preview_player.pause()
            self.btn_play_voice.setText("▶ Ouvir Gravação")
            self.btn_play_imported.setText("▶ Ouvir Áudio")
        else:
            self.preview_player.setSource(QUrl.fromLocalFile(self.custom_human_audio_path))
            self.preview_player.play()
            self.btn_play_voice.setText("⏸ Pausar")
            self.btn_play_imported.setText("⏸ Pausar")

    def _on_preview_playback_state_changed(self, state):
        if state != QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play_voice.setText("▶ Ouvir Gravação")
            self.btn_play_imported.setText("▶ Ouvir Áudio")

    def _generate_cover_ai(self):
        topic = self.edit_title.text().strip() or "Capa para Aula Online"
        dlg = GenerateCoverDialog(self, default_topic=topic, default_aspect="16:9")
        if dlg.exec():
            generated = dlg.get_generated_image_path()
            if generated:
                self.cover_image_path = generated
                self.lbl_cover_status.setText(f"✓ Capa IA: {Path(generated).name}")
                self.lbl_cover_status.setStyleSheet("color: #10b981; font-weight: 600;")

    def _pick_cover_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Imagem de Capa (16:9 / 1280x720 recomendado)",
            "",
            "Imagens (*.png *.jpg *.jpeg *.webp)",
        )
        if file_path:
            self.cover_image_path = file_path
            self.lbl_cover_status.setText(f"✓ {Path(file_path).name}")
            self.lbl_cover_status.setStyleSheet("color: #10b981; font-weight: 600;")

    def _pick_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Apresentação de Slides (PDF)",
            "",
            "Arquivos PDF (*.pdf)",
        )
        if file_path:
            try:
                self.pdf_info = inspect_pdf(file_path)
                self.lbl_pdf_status.setText(f"✓ {self.pdf_info.file_name} ({self.pdf_info.page_count} slides)")
                self.lbl_pdf_status.setStyleSheet("color: #10b981; font-weight: 600;")
            except Exception as e:
                QMessageBox.critical(self, "Erro no PDF", f"Falha ao abrir PDF:\n{e}")

    def _pick_txt_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Roteiro da Aula",
            "",
            "Arquivos de Texto (*.txt *.md)",
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
                self.edit_script.setPlainText(text)
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível ler o arquivo:\n{e}")

    def _pick_bgm(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Música de Fundo",
            "",
            "Arquivos de Áudio (*.mp3 *.wav *.m4a *.aac *.ogg)",
        )
        if file_path:
            self.bgm_path = file_path
            self.lbl_bgm_status.setText(f"✓ {Path(file_path).name}")
            self.lbl_bgm_status.setStyleSheet("color: #10b981; font-weight: 600;")

    def _enter_live_studio(self):
        if self.visual_mode == "slides":
            if not self.pdf_info:
                QMessageBox.warning(
                    self,
                    "PDF Necessário",
                    "Por favor, selecione o arquivo PDF dos slides da aula antes de entrar no estúdio.",
                )
                return
            self.nav_slide_bar_widget.show()
            self.lbl_live_slide.setStyleSheet("")
            self.current_slide_idx = 0
            self._update_slide_display()
        else:
            # Screen Tutorial Mode
            self.nav_slide_bar_widget.hide()
            self.lbl_live_slide.setPixmap(QPixmap())
            self.lbl_live_slide.setText(
                "🖥️ MODO TUTORIAL DE APLICATIVO ATIVO\n\n"
                "1. Ao clicar em '🔴 Iniciar Gravação', haverá uma contagem de 3 segundos.\n"
                "2. Alterne para a janela do aplicativo ou programa que deseja demonstrar.\n"
                "3. O microfone e o Teleprompter (se preenchido) estarão disponíveis.\n"
                "4. Ao terminar, clique em '⏹ Finalizar Aula & Gerar Vídeo'."
            )
            self.lbl_live_slide.setStyleSheet(
                "color: #a78bfa; font-size: 15px; font-weight: 600; line-height: 1.6; padding: 24px;"
            )

        # Prepare teleprompter text
        script = self.edit_script.toPlainText().strip()
        if script:
            self.prompter.set_script_text(script)
            self.prompter.show()
        else:
            self.prompter.hide()

        # Set selected audio device
        selected_audio_dev = self.combo_mics.currentData()
        if selected_audio_dev:
            self.audio_input.setDevice(selected_audio_dev)

        # Reset indicators
        self.lbl_rec_indicator.setText("⚪ Não Gravando")
        self.lbl_rec_indicator.setStyleSheet("font-weight: 700; color: #94a3b8; font-size: 13px;")
        self.lbl_rec_timer.setText("00:00:00")
        self.btn_rec_start.setEnabled(True)
        self.btn_rec_pause.setEnabled(False)
        self.btn_rec_finish.setEnabled(False)

        # Switch to live studio
        self.stack.setCurrentIndex(1)

    def _leave_studio(self):
        if self.is_recording:
            reply = QMessageBox.question(
                self,
                "Gravação em Andamento",
                "A aula está sendo gravada. Deseja cancelar a gravação e voltar à configuração?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._stop_recording_discard()

        self.stack.setCurrentIndex(0)

    def _toggle_prompter_visibility(self):
        if self.prompter.isVisible():
            self.prompter.hide()
            self.btn_studio_toggle_prompter.setText("📝 Teleprompter Oculto")
        else:
            self.prompter.show()
            self.btn_studio_toggle_prompter.setText("📝 Teleprompter Visível")

    def _update_slide_display(self):
        if not self.pdf_info:
            return
        total = self.pdf_info.page_count
        self.lbl_slide_counter.setText(f"Slide {self.current_slide_idx + 1} de {total}")

        try:
            png_bytes = render_thumbnail(
                self.pdf_info.file_path,
                self.current_slide_idx,
                max_dimension=1080,
            )
            qimg = QImage.fromData(png_bytes)
            pix = QPixmap.fromImage(qimg)
            # Scale smoothly to display frame
            scaled = pix.scaled(
                self.slide_display_frame.size() - Qt.QSize(20, 20),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.lbl_live_slide.setPixmap(scaled)
        except Exception as e:
            logger.warning("Erro ao renderizar slide ao vivo: %s", e)

    def _go_next_slide(self):
        if not self.pdf_info:
            return
        if self.current_slide_idx < self.pdf_info.page_count - 1:
            if self.is_recording:
                now = time.time()
                dur = now - self.slide_start_time
                self.recorded_slide_durations.append(dur)
                self.slide_start_time = now

            self.current_slide_idx += 1
            self._update_slide_display()

    def _go_prev_slide(self):
        if self.current_slide_idx > 0:
            if self.is_recording:
                now = time.time()
                dur = now - self.slide_start_time
                self.recorded_slide_durations.append(dur)
                self.slide_start_time = now

            self.current_slide_idx -= 1
            self._update_slide_display()

    def _start_recording(self):
        if self.visual_mode == "screen":
            timestamp = int(time.time())
            title_text = self.edit_title.text().strip()
            safe_title = "".join(c for c in title_text if c.isalnum() or c in (" ", "_", "-")).strip() or "tutorial"
            safe_title = safe_title.replace(" ", "_")

            save_dir = Path.home() / "Videos"
            if not save_dir.exists():
                save_dir = Path.home()
            raw_vid = str(save_dir / f"{safe_title}_{timestamp}_raw.mp4")
            self.screen_tutorial_video_path = raw_vid

            res_data = self.combo_screen_res.currentData() or "1920x1080"
            self.screen_recorder = ScreenRecordingProcess(
                output_video_path=raw_vid,
                video_size=res_data,
                fps=25,
            )

            # 3-second countdown dialog
            msg = QMessageBox(self)
            msg.setWindowTitle("Preparar para Gravar")
            msg.setText(
                "⏳ Iniciando gravação em 3 segundos...\n\n"
                "Alterne agora para a janela do aplicativo que você deseja demonstrar!"
            )
            msg.setIcon(QMessageBox.Information)
            msg.setStandardButtons(QMessageBox.Ok)
            QTimer.singleShot(2500, msg.accept)
            msg.exec()

            self.screen_recorder.start()
            self.is_recording = True
            self.record_start_time = time.time()

            self.lbl_rec_indicator.setText("🔴 GRAVANDO TELA DO TUTORIAL")
            self.lbl_rec_indicator.setStyleSheet("font-weight: 800; color: #ef4444; font-size: 13px;")
            self.record_timer.start()

            self.btn_rec_start.setEnabled(False)
            self.btn_rec_pause.setEnabled(False)
            self.btn_rec_finish.setEnabled(True)
        else:
            import tempfile
            self.audio_temp_path = str(Path(tempfile.gettempdir()) / f"class_audio_{int(time.time())}.m4a")
            self.recorder.setOutputLocation(QUrl.fromLocalFile(self.audio_temp_path))

            self.recorder.record()
            self.is_recording = True
            self.record_start_time = time.time()
            self.slide_start_time = time.time()
            self.recorded_slide_durations = []

            self.lbl_rec_indicator.setText("🔴 GRAVANDO AULA")
            self.lbl_rec_indicator.setStyleSheet("font-weight: 800; color: #ef4444; font-size: 13px;")
            self.record_timer.start()

            self.btn_rec_start.setEnabled(False)
            self.btn_rec_pause.setEnabled(True)
            self.btn_rec_finish.setEnabled(True)

    def _pause_recording(self):
        if self.visual_mode == "screen":
            return
        if self.is_recording:
            self.recorder.pause()
            self.is_recording = False
            self.lbl_rec_indicator.setText("⏸ PAUSADO")
            self.lbl_rec_indicator.setStyleSheet("font-weight: 800; color: #f59e0b; font-size: 13px;")
            self.btn_rec_pause.setText("▶ Retomar")
        else:
            self.recorder.record()
            self.is_recording = True
            self.lbl_rec_indicator.setText("🔴 GRAVANDO AULA")
            self.lbl_rec_indicator.setStyleSheet("font-weight: 800; color: #ef4444; font-size: 13px;")
            self.btn_rec_pause.setText("⏸ Pausar")

    def _update_record_time_display(self):
        if self.is_recording:
            elapsed = time.time() - self.record_start_time
            self.lbl_rec_timer.setText(format_duration(elapsed))

    def _stop_recording_discard(self):
        self.record_timer.stop()
        if self.visual_mode == "screen":
            if self.screen_recorder:
                raw_path = self.screen_recorder.stop()
                self.screen_recorder = None
                if raw_path and os.path.exists(raw_path):
                    try:
                        os.remove(raw_path)
                    except Exception:
                        pass
        else:
            self.recorder.stop()

        self.is_recording = False
        self.lbl_rec_indicator.setText("⚪ Não Gravando")
        self.lbl_rec_indicator.setStyleSheet("color: #94a3b8;")
        self.btn_rec_start.setEnabled(True)
        self.btn_rec_pause.setEnabled(False)
        self.btn_rec_finish.setEnabled(False)

    def _finish_recording(self):
        if self.visual_mode == "screen":
            self.record_timer.stop()
            self.is_recording = False
            raw_video = ""
            if self.screen_recorder:
                raw_video = self.screen_recorder.stop()
                self.screen_recorder = None
            elif self.screen_tutorial_video_path:
                raw_video = self.screen_tutorial_video_path

            # If background music was not chosen, ask if user wants it now
            if not self.bgm_path:
                reply = QMessageBox.question(
                    self,
                    "Fundo Musical Suave",
                    "Deseja adicionar uma música de fundo suave a este tutorial?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    file_path, _ = QFileDialog.getOpenFileName(
                        self,
                        "Selecionar Música de Fundo",
                        "",
                        "Áudios (*.mp3 *.wav *.m4a *.aac *.ogg)",
                    )
                    if file_path:
                        self.bgm_path = file_path

            raw_p = Path(raw_video)
            final_video_name = raw_p.stem.replace("_raw", "") + ".mp4"
            final_out_path = str(raw_p.parent / final_video_name)

            self.stack.setCurrentIndex(2)
            self.lbl_result_icon.setText("⏳")
            self.lbl_result_title.setText("Processando seu Tutorial...")
            self.render_progress_bar.setValue(0)
            self.result_btn_container.hide()

            sub_lang = self.combo_sub_lang.currentData()
            self.worker = TutorialPostProcessWorker(
                raw_video_path=raw_video,
                output_path=final_out_path,
                bgm_path=self.bgm_path,
                enable_subtitles=self.chk_subtitles.isChecked(),
                subtitle_lang=sub_lang,
                parent=self,
            )
            self.worker.progress_changed.connect(self._on_render_progress)
            self.worker.render_finished.connect(self._on_render_finished)
            self.worker.render_error.connect(self._on_render_error)
            self.worker.render_cancelled.connect(self._on_render_cancelled)
            self.btn_cancel_render.show()
            self.worker.start()
            return

        # Slides mode:
        now = time.time()
        last_dur = now - self.slide_start_time
        self.recorded_slide_durations.append(last_dur)

        self.record_timer.stop()
        self.recorder.stop()
        self.is_recording = False

        # If background music was not chosen, ask if user wants it now
        if not self.bgm_path:
            reply = QMessageBox.question(
                self,
                "Fundo Musical Suave",
                "Deseja adicionar uma música de fundo suave a esta videoaula?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                file_path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Selecionar Música de Fundo",
                    "",
                    "Áudios (*.mp3 *.wav *.m4a *.aac *.ogg)",
                )
                if file_path:
                    self.bgm_path = file_path

        # Generate target video path
        pdf_p = Path(self.pdf_info.file_path)
        if self.video_format in ("shorts", "reels"):
            suffix = f"{self.video_format}_{self.vertical_layout}"
        else:
            suffix = f"{self.video_format}"
        out_path = str(pdf_p.parent / f"{pdf_p.stem}_aula_gravada_{suffix}.mp4")

        # Map slide durations
        count = self.pdf_info.page_count
        if len(self.recorded_slide_durations) < count:
            # fill remainder
            while len(self.recorded_slide_durations) < count:
                self.recorded_slide_durations.append(5.0)
        elif len(self.recorded_slide_durations) > count:
            self.recorded_slide_durations = self.recorded_slide_durations[:count]

        # Switch to Result View and start worker
        self.stack.setCurrentIndex(2)
        self.lbl_result_icon.setText("⏳")
        self.lbl_result_title.setText("Renderizando sua Videoaula...")
        self.render_progress_bar.setValue(0)
        self.result_btn_container.hide()

        sub_lang = self.combo_sub_lang.currentData()
        self.worker = ClassVideoRenderWorker(
            pdf_path=self.pdf_info.file_path,
            durations=self.recorded_slide_durations,
            audio_path=self.audio_temp_path,
            output_path=out_path,
            class_title=self.edit_title.text().strip(),
            teacher_name=self.edit_teacher.text().strip(),
            cover_image=self.cover_image_path,
            bgm_path=self.bgm_path,
            enable_subtitles=self.chk_subtitles.isChecked(),
            subtitle_lang=sub_lang,
            video_format=self.video_format,
            vertical_layout=self.vertical_layout,
            intro_mode=self.intro_mode,
            intro_video_path=self.intro_video_path,
            outro_mode=self.outro_mode,
            outro_video_path=self.outro_video_path,
            parent=self,
        )
        self.worker.progress_changed.connect(self._on_render_progress)
        self.worker.render_finished.connect(self._on_render_finished)
        self.worker.render_error.connect(self._on_render_error)
        self.worker.render_cancelled.connect(self._on_render_cancelled)
        self.btn_cancel_render.show()
        self.worker.start()

    def _on_render_progress(self, frac: float, msg: str):
        val = int(frac * 100)
        self.render_progress_bar.setValue(val)
        self.lbl_result_status.setText(msg)

    def _cancel_render(self):
        if self.worker is not None:
            self.worker.cancel()
            self.lbl_result_status.setText("Cancelando renderização...")

    def _on_render_cancelled(self):
        self.output_video_path = None
        self.btn_cancel_render.hide()
        self.lbl_result_icon.setText("⏹")
        self.lbl_result_title.setText("Renderização Cancelada")
        self.lbl_result_status.setText("A renderização foi cancelada. Ajuste e tente novamente.")
        self.result_btn_container.show()

    def _on_render_finished(self, video_path: str):
        self.output_video_path = video_path
        self.btn_cancel_render.hide()
        self.render_progress_bar.setValue(100)
        self.lbl_result_icon.setText("🎉")
        if self.visual_mode == "screen":
            self.lbl_result_title.setText("Tutorial Gravado com Sucesso!")
        else:
            self.lbl_result_title.setText("Videoaula Gerada com Sucesso!")
        self.lbl_result_status.setText(f"Arquivo salvo em:\n{video_path}")
        self.result_btn_container.show()

    def _on_render_error(self, err: str):
        self.btn_cancel_render.hide()
        self.lbl_result_icon.setText("❌")
        self.lbl_result_title.setText("Erro na Renderização")
        self.lbl_result_status.setText(f"Ocorreu um erro:\n{err}")
        QMessageBox.critical(self, "Erro", f"Falha ao gerar vídeo:\n{err}")

    def _play_generated_video(self):
        if self.output_video_path and os.path.exists(self.output_video_path):
            try:
                if sys.platform == "win32":
                    os.startfile(self.output_video_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", self.output_video_path])
                else:
                    subprocess.Popen(["xdg-open", self.output_video_path])
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o player:\n{e}")

    def _open_output_folder(self):
        if self.output_video_path:
            folder = str(Path(self.output_video_path).parent.resolve())
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer", folder])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir a pasta:\n{e}")

    def _reset_for_new_class(self):
        self.stack.setCurrentIndex(0)

    # Keyboard navigation during live studio
    def keyPressEvent(self, event: QKeyEvent):
        if self.stack.currentIndex() == 1:  # In studio
            if event.key() == Qt.Key_Right:
                self._go_next_slide()
                event.accept()
                return
            elif event.key() == Qt.Key_Left:
                self._go_prev_slide()
                event.accept()
                return
            elif event.key() == Qt.Key_Space:
                # Toggle teleprompter play/pause with spacebar
                self.prompter.toggle_play()
                event.accept()
                return
        super().keyPressEvent(event)
