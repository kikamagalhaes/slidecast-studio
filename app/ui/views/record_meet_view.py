import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import Qt, QTimer, Signal, QThread
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
    QTabWidget,
    QButtonGroup,
    QRadioButton,
)

from app.core.ffmpeg_utils import format_duration
from app.core.pdf_processor import inspect_pdf, render_thumbnail
from app.core.subtitles_generator import generate_subtitles_with_gemini, SUPPORTED_LANGUAGES
from app.core.meeting_recorder import ScreenRecordingProcess, extract_audio_from_video, generate_meeting_notes
from app.core.ebook_generator import generate_class_ebook
from app.ui.floating_camera_widget import FloatingCameraWidget
from PySide6.QtMultimedia import QMediaDevices, QCameraDevice


class MeetPostProcessWorker(QThread):
    progress_changed = Signal(float, str)
    processing_finished = Signal(dict)
    processing_error = Signal(str)

    def __init__(
        self,
        mode: int,  # 1: Meeting, 2: Class
        video_path: str,
        title: str,
        teacher: str,
        pdf_path: Optional[str],
        enable_ebook: bool,
        enable_subtitles: bool,
        subtitles_lang: str,
    ):
        super().__init__()
        self.mode = mode
        self.video_path = video_path
        self.title = title
        self.teacher = teacher
        self.pdf_path = pdf_path
        self.enable_ebook = enable_ebook
        self.enable_subtitles = enable_subtitles
        self.subtitles_lang = subtitles_lang

    def run(self):
        try:
            results = {"mode": self.mode, "video_path": self.video_path}
            temp_dir = Path.home() / "SlideCast_Materials"
            temp_dir.mkdir(parents=True, exist_ok=True)
            audio_path = str(temp_dir / f"extracted_audio_{int(time.time())}.aac")

            self.progress_changed.emit(15.0, "Extraindo áudio da gravação para análise inteligente...")
            extract_audio_from_video(self.video_path, audio_path)

            if self.mode == 1:
                # Mode 1: Meeting - Transcription and Summary
                self.progress_changed.emit(40.0, "Analisando falas e gerando transcrição com Gemini...")
                notes = generate_meeting_notes(audio_path, self.title)
                results["summary"] = notes.get("summary", "")
                results["transcription"] = notes.get("transcription", "")
                self.progress_changed.emit(100.0, "Resumo e transcrição concluídos!")

            else:
                # Mode 2: Class - E-book with interleaved slides
                slide_images: List[str] = []

                if self.pdf_path and Path(self.pdf_path).exists():
                    self.progress_changed.emit(35.0, "Extraindo slides da apresentação em alta resolução...")
                    try:
                        info = inspect_pdf(self.pdf_path)
                        for idx in range(info.page_count):
                            img_bytes = render_thumbnail(self.pdf_path, idx, max_dimension=1280)
                            img_p = str(temp_dir / f"meet_slide_{idx:03d}.png")
                            with open(img_p, "wb") as f:
                                f.write(img_bytes)
                            slide_images.append(img_p)
                    except Exception as e:
                        print(f"Aviso extraindo slides: {e}")

                if self.enable_ebook:
                    self.progress_changed.emit(50.0, "Criando E-book Didático com slides intercalados via IA...")
                    clean_slug = "".join(c for c in self.title.lower().replace(" ", "_") if c.isalnum() or c in "_-")[:25] or "ebook_aula"
                    ebook_path = str(temp_dir / f"{clean_slug}_{int(time.time())}.pdf")

                    def callback(pct, msg):
                        self.progress_changed.emit(pct, msg)

                    final_ebook = generate_class_ebook(
                        title=self.title,
                        teacher=self.teacher,
                        audio_path=audio_path,
                        slide_images=slide_images,
                        output_pdf_path=ebook_path,
                        progress_callback=callback,
                    )
                    results["ebook_path"] = final_ebook

                if self.enable_subtitles:
                    self.progress_changed.emit(85.0, "Gerando legendas inteligentes com o Gemini...")
                    srt_path = str(temp_dir / f"meet_sub_{int(time.time())}.srt")
                    try:
                        generate_subtitles_with_gemini(
                            audio_path=audio_path,
                            output_srt_path=srt_path,
                            target_language=self.subtitles_lang,
                            progress_callback=lambda msg: self.progress_changed.emit(88.0, msg),
                        )
                        results["subtitles_path"] = srt_path
                    except Exception as e:
                        print(f"Aviso gerando legendas: {e}")

                self.progress_changed.emit(100.0, "Aula processada e e-book finalizado!")

            self.processing_finished.emit(results)

        except Exception as e:
            self.processing_error.emit(str(e))


class RecordMeetView(QWidget):
    back_to_home = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_mode = 1  # 1: Meeting, 2: Class
        self.recorder_process: Optional[ScreenRecordingProcess] = None
        self.recorded_video_path: Optional[str] = None
        self.selected_pdf_path: Optional[str] = None
        self.results_data: dict = {}
        self.floating_camera: Optional[FloatingCameraWidget] = None

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._update_record_timer)

        self._build_ui()
        self._refresh_camera_devices()

        try:
            QMediaDevices.videoInputsChanged.connect(self._refresh_camera_devices)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_camera_devices()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)

        self.setup_view = self._build_setup_view()
        self.recording_view = self._build_recording_view()
        self.result_view = self._build_result_view()

        self.stack.addWidget(self.setup_view)      # Index 0
        self.stack.addWidget(self.recording_view)  # Index 1
        self.stack.addWidget(self.result_view)     # Index 2

        self.stack.setCurrentIndex(0)

    # ----------------------------------------------------
    # SCREEN 0: SETUP & MODE SELECTION
    # ----------------------------------------------------
    def _build_setup_view(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(14)

        # Nav bar
        nav = QHBoxLayout()
        btn_back = QPushButton("← Voltar ao Menu Inicial")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.clicked.connect(self.back_to_home.emit)

        title = QLabel("👥 3. Gravar Reunião do Meet - Captura com IA")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #34d399;")

        nav.addWidget(btn_back)
        nav.addWidget(title)
        nav.addStretch()
        layout.addLayout(nav)

        # Step Navigation Bar (Clickable screens without scrollbars)
        self.step_bar = QHBoxLayout()
        self.step_bar.setSpacing(8)
        self.step_buttons = []
        step_labels = [
            "1. 🎯 Modo & Objetivo da Reunião",
            "2. 🎥 Dispositivos & Gravação",
        ]
        for idx, text in enumerate(step_labels):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self._switch_step(i))
            self.step_bar.addWidget(btn)
            self.step_buttons.append(btn)
        layout.addLayout(self.step_bar)

        self.step_stack = QStackedWidget()

        # Page 1: Modo e Objetivo
        page1 = QWidget()
        p1_lay = QVBoxLayout(page1)
        p1_lay.setContentsMargins(0, 8, 0, 0)
        p1_lay.setSpacing(12)

        # Page 2: Dispositivos e Gravação
        page2 = QWidget()
        p2_lay = QVBoxLayout(page2)
        p2_lay.setContentsMargins(0, 8, 0, 0)
        p2_lay.setSpacing(12)

        # Mode Selection Header
        mode_box = QFrame()
        mode_box.setProperty("class", "card")
        mb_layout = QVBoxLayout(mode_box)
        mb_layout.setContentsMargins(18, 16, 18, 16)
        mb_layout.setSpacing(14)

        lbl_mtitle = QLabel("Selecione o Objetivo da Gravação:")
        lbl_mtitle.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        mb_layout.addWidget(lbl_mtitle)

        modes_row = QHBoxLayout()
        modes_row.setSpacing(16)

        # Mode 1 Radio Card
        self.radio_mode1 = QRadioButton("1. Modo Reunião Completa (Daily / Alinhamento / Trabalho)")
        self.radio_mode1.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
        self.radio_mode1.setChecked(True)
        self.radio_mode1.toggled.connect(self._on_mode_changed)

        # Mode 2 Radio Card
        self.radio_mode2 = QRadioButton("2. Modo Aula no Meet (Foco no Professor & E-book da Aula)")
        self.radio_mode2.setStyleSheet("font-weight: 700; color: #a78bfa; font-size: 13px;")

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_mode1)
        self.mode_group.addButton(self.radio_mode2)

        modes_row.addWidget(self.radio_mode1)
        modes_row.addWidget(self.radio_mode2)
        mb_layout.addLayout(modes_row)

        self.lbl_mode_desc = QLabel(
            "Grave tudo o que acontece na tela e o som dos participantes. Ao final, "
            "o Gemini gera a transcrição integral e um resumo executivo com pauta, decisões e tarefas."
        )
        self.lbl_mode_desc.setWordWrap(True)
        self.lbl_mode_desc.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        mb_layout.addWidget(self.lbl_mode_desc)

        p1_lay.addWidget(mode_box)

        # Step 1 Details Card
        card_step1 = QFrame()
        card_step1.setProperty("class", "card")
        c1_layout = QVBoxLayout(card_step1)
        c1_layout.setContentsMargins(18, 16, 18, 16)
        c1_layout.setSpacing(12)

        sec_title = QLabel("Detalhes da Reunião / Aula")
        sec_title.setProperty("class", "section-title")
        c1_layout.addWidget(sec_title)

        # Common inputs: Title
        row_title = QHBoxLayout()
        lbl_t = QLabel("Título da Reunião / Aula:")
        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("Ex: Reunião de Planejamento Estratégico ou Aula de História")
        row_title.addWidget(lbl_t)
        row_title.addWidget(self.edit_title)
        c1_layout.addLayout(row_title)

        # Mode 2 specific: Teacher Role Selection (Self vs Remote)
        self.box_teacher_role = QWidget()
        btr_layout = QVBoxLayout(self.box_teacher_role)
        btr_layout.setContentsMargins(0, 0, 0, 0)
        btr_layout.setSpacing(8)

        lbl_role = QLabel("Quem está ministrando a aula no Meet?")
        lbl_role.setStyleSheet("font-weight: 700; color: #ffffff; font-size: 13px;")

        role_row = QHBoxLayout()
        self.radio_teacher_self = QRadioButton("👤 Eu mesma sou a Professora (Dando a aula)")
        self.radio_teacher_self.setStyleSheet("font-weight: 700; color: #34d399; font-size: 13px;")
        self.radio_teacher_self.setChecked(True)
        self.radio_teacher_self.toggled.connect(self._on_teacher_role_changed)

        self.radio_teacher_remote = QRadioButton("👨‍🏫 Outro Professor (Assistindo a aula de terceiro no Meet)")
        self.radio_teacher_remote.setStyleSheet("font-weight: 700; color: #a78bfa; font-size: 13px;")

        self.teacher_role_group = QButtonGroup(self)
        self.teacher_role_group.addButton(self.radio_teacher_self)
        self.teacher_role_group.addButton(self.radio_teacher_remote)

        role_row.addWidget(self.radio_teacher_self)
        role_row.addWidget(self.radio_teacher_remote)
        role_row.addStretch()

        self.lbl_teacher_role_hint = QLabel(
            "💡 Sua câmera será gravada na videoaula, capturando seus slides na tela, seu microfone e as dúvidas dos alunos no Meet."
        )
        self.lbl_teacher_role_hint.setStyleSheet("color: #38bdf8; font-size: 12px;")
        self.lbl_teacher_role_hint.setWordWrap(True)

        btr_layout.addWidget(lbl_role)
        btr_layout.addLayout(role_row)
        btr_layout.addWidget(self.lbl_teacher_role_hint)
        c1_layout.addWidget(self.box_teacher_role)
        self.box_teacher_role.hide()

        # Step 2 Configuration Form Card
        self.form_card = QFrame()
        self.form_card.setProperty("class", "card")
        self.fc_layout = QVBoxLayout(self.form_card)
        self.fc_layout.setContentsMargins(18, 16, 18, 16)
        self.fc_layout.setSpacing(12)

        sec2_title = QLabel("Dispositivos de Entrada & Recursos com IA")
        sec2_title.setProperty("class", "section-title")
        self.fc_layout.addWidget(sec2_title)

        # Mode 2 specific: Camera settings when teacher is self
        self.box_my_camera = QFrame()
        self.box_my_camera.setStyleSheet("background-color: #161c28; border: 1px solid #2e384d; border-radius: 8px;")
        bmc_layout = QVBoxLayout(self.box_my_camera)
        bmc_layout.setContentsMargins(14, 12, 14, 12)
        bmc_layout.setSpacing(10)

        self.chk_my_cam = QCheckBox("Habilitar gravação da minha Câmera / Webcam na videoaula")
        self.chk_my_cam.setStyleSheet("font-weight: 700; color: #f8fafc;")
        self.chk_my_cam.setChecked(True)

        cam_config_row = QHBoxLayout()
        cam_config_row.setSpacing(12)

        cam_dev_box = QVBoxLayout()
        cam_hdr = QHBoxLayout()
        lbl_cdev = QLabel("Dispositivo de Câmera:")
        btn_refresh_meet_cam = QPushButton("🔄 Atualizar")
        btn_refresh_meet_cam.setCursor(Qt.PointingHandCursor)
        btn_refresh_meet_cam.setToolTip("Atualizar lista de câmeras conectadas")
        btn_refresh_meet_cam.setStyleSheet(
            "background: #1e293b; color: #38bdf8; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px;"
        )
        btn_refresh_meet_cam.clicked.connect(self._refresh_camera_devices)
        cam_hdr.addWidget(lbl_cdev)
        cam_hdr.addStretch()
        cam_hdr.addWidget(btn_refresh_meet_cam)

        self.combo_my_cam = QComboBox()
        cam_dev_box.addLayout(cam_hdr)
        cam_dev_box.addWidget(self.combo_my_cam)

        pos_box = QVBoxLayout()
        lbl_cpos = QLabel("Posição da Câmera no Vídeo:")
        self.combo_cam_pos = QComboBox()
        self.combo_cam_pos.addItem("Canto Inferior Direito (PIP Padrão)", "bottom_right")
        self.combo_cam_pos.addItem("Canto Superior Direito", "top_right")
        self.combo_cam_pos.addItem("Canto Inferior Esquerdo", "bottom_left")
        self.combo_cam_pos.addItem("Canto Superior Esquerdo", "top_left")
        pos_box.addWidget(lbl_cpos)
        pos_box.addWidget(self.combo_cam_pos)

        cam_config_row.addLayout(cam_dev_box, stretch=1)
        cam_config_row.addLayout(pos_box, stretch=1)

        cam_btn_row = QHBoxLayout()
        self.btn_floating_cam = QPushButton("📷 Ativar Janela Flutuante da Câmera na Tela")
        self.btn_floating_cam.setCursor(Qt.PointingHandCursor)
        self.btn_floating_cam.setStyleSheet("background: #312e81; color: #c7d2fe; font-weight: 600; padding: 6px 14px; border-radius: 6px;")
        self.btn_floating_cam.setToolTip("Abre uma janela de vídeo da sua câmera que fica sempre no topo da tela para você se ver enquanto ministra a aula")
        self.btn_floating_cam.clicked.connect(self._toggle_floating_camera)

        lbl_float_hint = QLabel("Arraste e posicione na tela onde preferir durante a transmissão do Meet.")
        lbl_float_hint.setStyleSheet("color: #94a3b8; font-size: 11px;")

        cam_btn_row.addWidget(self.btn_floating_cam)
        cam_btn_row.addWidget(lbl_float_hint)
        cam_btn_row.addStretch()

        bmc_layout.addWidget(self.chk_my_cam)
        bmc_layout.addLayout(cam_config_row)
        bmc_layout.addLayout(cam_btn_row)
        self.fc_layout.addWidget(self.box_my_camera)
        self.box_my_camera.hide()

        # Mode 2 specific: Teacher name
        self.box_teacher = QWidget()
        bt_layout = QHBoxLayout(self.box_teacher)
        bt_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_prof = QLabel("Nome do Professor(a):")
        self.edit_teacher = QLineEdit()
        self.edit_teacher.setText("Prof. Kika Magalhães")
        self.edit_teacher.setPlaceholderText("Ex: Prof. Kika Magalhães")
        bt_layout.addWidget(self.lbl_prof)
        bt_layout.addWidget(self.edit_teacher)
        c1_layout.addWidget(self.box_teacher)
        self.box_teacher.hide()

        # Mode 2 specific: PDF presentation upload for pristine eBook slides
        self.box_pdf = QWidget()
        bp_layout = QHBoxLayout(self.box_pdf)
        bp_layout.setContentsMargins(0, 0, 0, 0)
        bp_layout.setSpacing(12)
        btn_pick_pdf = QPushButton("Carregar Apresentação PDF (Opcional)...")
        btn_pick_pdf.setCursor(Qt.PointingHandCursor)
        btn_pick_pdf.clicked.connect(self._pick_pdf_presentation)
        self.lbl_pdf_status = QLabel("Opcional: fornece os slides vetoriais para o E-book")
        self.lbl_pdf_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
        bp_layout.addWidget(btn_pick_pdf)
        bp_layout.addWidget(self.lbl_pdf_status)
        bp_layout.addStretch()
        c1_layout.addWidget(self.box_pdf)
        self.box_pdf.hide()

        p1_lay.addWidget(card_step1)
        p1_lay.addStretch()

        s1_nav = QHBoxLayout()
        s1_nav.addStretch()
        btn_next_s1 = QPushButton("Continuar para Dispositivos & Gravação ▶")
        btn_next_s1.setProperty("class", "primary")
        btn_next_s1.setCursor(Qt.PointingHandCursor)
        btn_next_s1.clicked.connect(lambda: self._switch_step(1))
        s1_nav.addWidget(btn_next_s1)
        p1_lay.addLayout(s1_nav)

        # Capture Options
        row_cap = QHBoxLayout()
        lbl_cap = QLabel("Área de Captura:")
        self.combo_capture_area = QComboBox()
        self.combo_capture_area.addItem("Tela Inteira (1920x1080 Full HD)", "1920x1080")
        self.combo_capture_area.addItem("Resolução HD (1280x720)", "1280x720")
        row_cap.addWidget(lbl_cap)
        row_cap.addWidget(self.combo_capture_area)
        row_cap.addStretch()
        self.fc_layout.addLayout(row_cap)

        # Mode 2 specific Checkbox: E-book with interleaved slides
        self.chk_gen_ebook = QCheckBox("📚 Gerar E-book Didático / Apostila da Aula em PDF com Slides Intercalados")
        self.chk_gen_ebook.setStyleSheet("font-weight: 700; color: #a78bfa;")
        self.chk_gen_ebook.setChecked(True)
        self.fc_layout.addWidget(self.chk_gen_ebook)
        self.chk_gen_ebook.hide()

        # Mode 2 specific Checkbox: Subtitles
        self.box_subs = QWidget()
        bs_layout = QHBoxLayout(self.box_subs)
        bs_layout.setContentsMargins(0, 0, 0, 0)
        self.chk_subs = QCheckBox("Gerar Legendas no Vídeo com IA (Gemini)")
        self.chk_subs.setStyleSheet("color: #f8fafc;")
        lbl_slang = QLabel("Idioma:")
        self.combo_slang = QComboBox()
        for c, n in SUPPORTED_LANGUAGES.items():
            self.combo_slang.addItem(n, c)
        bs_layout.addWidget(self.chk_subs)
        bs_layout.addWidget(lbl_slang)
        bs_layout.addWidget(self.combo_slang)
        bs_layout.addStretch()
        self.fc_layout.addWidget(self.box_subs)
        self.box_subs.hide()

        p2_lay.addWidget(self.form_card)
        p2_lay.addStretch()

        # Start Recording Button
        self.btn_start_rec = QPushButton("🔴 Iniciar Gravação do Google Meet (3s para alternar de janela)")
        self.btn_start_rec.setProperty("class", "primary")
        self.btn_start_rec.setFixedHeight(50)
        self.btn_start_rec.setCursor(Qt.PointingHandCursor)
        self.btn_start_rec.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.btn_start_rec.clicked.connect(self._prepare_and_start_recording)
        p2_lay.addWidget(self.btn_start_rec)

        s2_nav = QHBoxLayout()
        btn_prev_s2 = QPushButton("◀ Passo Anterior")
        btn_prev_s2.setCursor(Qt.PointingHandCursor)
        btn_prev_s2.clicked.connect(lambda: self._switch_step(0))
        s2_nav.addWidget(btn_prev_s2)
        s2_nav.addStretch()
        p2_lay.addLayout(s2_nav)

        # Assemble step pages into step stack
        self.step_stack.addWidget(page1)
        self.step_stack.addWidget(page2)
        layout.addWidget(self.step_stack, stretch=1)
        self._switch_step(0)

        return widget

    def _switch_step(self, idx: int):
        self.step_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.step_buttons):
            if i == idx:
                btn.setStyleSheet(
                    "background: #059669; color: #ffffff; font-weight: 700; "
                    "border: 1.5px solid #34d399; padding: 8px 14px; border-radius: 8px;"
                )
            else:
                btn.setStyleSheet(
                    "background: #1a1e28; color: #94a3b8; font-weight: 600; "
                    "border: 1px solid #2d3343; padding: 8px 14px; border-radius: 8px;"
                )

    # ----------------------------------------------------
    # SCREEN 1: RECORDING CONTROLS
    # ----------------------------------------------------
    def _build_recording_view(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setProperty("class", "card")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(40, 36, 40, 36)
        c_layout.setSpacing(18)
        c_layout.setAlignment(Qt.AlignCenter)

        self.lbl_rec_pulse = QLabel("🔴 GRAVANDO GOOGLE MEET AO VIVO")
        self.lbl_rec_pulse.setStyleSheet("font-size: 20px; font-weight: 800; color: #ef4444;")
        self.lbl_rec_pulse.setAlignment(Qt.AlignCenter)

        self.lbl_rec_time = QLabel("00:00")
        self.lbl_rec_time.setStyleSheet(
            "font-size: 32px; font-weight: 800; color: #ffffff; "
            "background-color: #12151f; padding: 8px 24px; border-radius: 8px;"
        )
        self.lbl_rec_time.setAlignment(Qt.AlignCenter)

        lbl_info = QLabel("A tela e o áudio da reunião estão sendo capturados com perfeição.\nQuando a reunião ou aula terminar, clique abaixo:")
        lbl_info.setStyleSheet("color: #94a3b8; font-size: 13px; line-height: 1.5;")
        lbl_info.setAlignment(Qt.AlignCenter)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)
        btn_row.setAlignment(Qt.AlignCenter)

        btn_stop = QPushButton("⏹ Concluir Gravação & Processar IA")
        btn_stop.setProperty("class", "primary")
        btn_stop.setFixedHeight(46)
        btn_stop.setCursor(Qt.PointingHandCursor)
        btn_stop.setStyleSheet("font-size: 14px; font-weight: 700; padding: 0 28px;")
        btn_stop.clicked.connect(self._finish_and_process)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setFixedHeight(46)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self._cancel_recording)

        btn_row.addWidget(btn_stop)
        btn_row.addWidget(btn_cancel)

        c_layout.addWidget(self.lbl_rec_pulse)
        c_layout.addWidget(self.lbl_rec_time)
        c_layout.addWidget(lbl_info)
        c_layout.addLayout(btn_row)

        layout.addWidget(card)
        return widget

    # ----------------------------------------------------
    # SCREEN 2: RESULTS (Meeting Notes or Class E-book)
    # ----------------------------------------------------
    def _build_result_view(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(14)

        # Header
        header = QHBoxLayout()
        lbl_rtitle = QLabel("🎉 Gravação do Meet Concluída!")
        lbl_rtitle.setStyleSheet("font-size: 18px; font-weight: 700; color: #34d399;")
        header.addWidget(lbl_rtitle)
        header.addStretch()

        btn_new = QPushButton("← Nova Gravação")
        btn_new.setCursor(Qt.PointingHandCursor)
        btn_new.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        header.addWidget(btn_new)
        layout.addLayout(header)

        # Progress bar during background processing
        self.proc_progress = QProgressBar()
        self.proc_progress.setRange(0, 100)
        self.proc_progress.setValue(0)
        self.proc_progress.setFixedHeight(18)
        self.lbl_proc_status = QLabel("Processando arquivo gravado com inteligência artificial...")
        self.lbl_proc_status.setStyleSheet("color: #38bdf8; font-weight: 600;")
        layout.addWidget(self.lbl_proc_status)
        layout.addWidget(self.proc_progress)

        # Tab widget for Mode 1 (Meeting Notes & Transcription) vs Mode 2 (E-book)
        self.tab_widget = QTabWidget()
        self.tab_widget.hide()

        # Tab 1: Video File
        tab_video = QWidget()
        tv_layout = QVBoxLayout(tab_video)
        tv_layout.setContentsMargins(16, 16, 16, 16)
        tv_layout.setSpacing(14)

        self.lbl_video_info = QLabel("Vídeo gravado:")
        self.lbl_video_info.setStyleSheet("font-weight: 600; color: #f8fafc;")
        btn_v_row = QHBoxLayout()
        btn_play_v = QPushButton("▶ Assistir Vídeo")
        btn_play_v.setProperty("class", "primary")
        btn_play_v.setCursor(Qt.PointingHandCursor)
        btn_play_v.clicked.connect(self._open_recorded_video)

        btn_folder_v = QPushButton("📁 Abrir Pasta")
        btn_folder_v.setCursor(Qt.PointingHandCursor)
        btn_folder_v.clicked.connect(self._open_recorded_folder)

        btn_v_row.addWidget(btn_play_v)
        btn_v_row.addWidget(btn_folder_v)
        btn_v_row.addStretch()

        tv_layout.addWidget(self.lbl_video_info)
        tv_layout.addLayout(btn_v_row)
        tv_layout.addStretch()
        self.tab_widget.addTab(tab_video, "🎬 Vídeo da Gravação")

        # Tab 2: Resumo Executivo (Mode 1)
        tab_sum = QWidget()
        ts_layout = QVBoxLayout(tab_sum)
        ts_layout.setContentsMargins(12, 12, 12, 12)
        self.text_summary = QTextEdit()
        self.text_summary.setReadOnly(True)
        ts_layout.addWidget(self.text_summary)
        self.tab_widget.addTab(tab_sum, "📌 Resumo Executivo da Reunião")

        # Tab 3: Transcrição Integral (Mode 1)
        tab_tx = QWidget()
        tt_layout = QVBoxLayout(tab_tx)
        tt_layout.setContentsMargins(12, 12, 12, 12)
        self.text_transcription = QTextEdit()
        self.text_transcription.setReadOnly(True)
        tt_layout.addWidget(self.text_transcription)
        self.tab_widget.addTab(tab_tx, "📝 Transcrição Completa")

        # Tab 4: E-book Didático da Aula (Mode 2)
        self.tab_ebook = QWidget()
        te_layout = QVBoxLayout(self.tab_ebook)
        te_layout.setContentsMargins(16, 16, 16, 16)
        te_layout.setSpacing(14)

        self.lbl_ebook_info = QLabel("📚 E-book Didático / Apostila da Aula Gerada com Sucesso!")
        self.lbl_ebook_info.setStyleSheet("font-size: 15px; font-weight: 700; color: #a78bfa;")

        lbl_edesc = QLabel(
            "A apostila contém todos os capítulos estruturados didaticamente, "
            "com os slides apresentados intercalados com explicações aprofundadas, "
            "pontos-chave e questões de fixação para os alunos."
        )
        lbl_edesc.setWordWrap(True)
        lbl_edesc.setStyleSheet("color: #94a3b8; font-size: 13px; line-height: 1.5;")

        btn_e_row = QHBoxLayout()
        btn_e_row.setSpacing(12)

        btn_open_ebook = QPushButton("📄 Abrir E-book PDF")
        btn_open_ebook.setProperty("class", "primary")
        btn_open_ebook.setCursor(Qt.PointingHandCursor)
        btn_open_ebook.clicked.connect(self._open_ebook_file)

        btn_save_ebook = QPushButton("💾 Salvar Como...")
        btn_save_ebook.setCursor(Qt.PointingHandCursor)
        btn_save_ebook.clicked.connect(self._save_ebook_as)

        btn_e_row.addWidget(btn_open_ebook)
        btn_e_row.addWidget(btn_save_ebook)
        btn_e_row.addStretch()

        te_layout.addWidget(self.lbl_ebook_info)
        te_layout.addWidget(lbl_edesc)
        te_layout.addLayout(btn_e_row)
        te_layout.addStretch()
        self.tab_widget.addTab(self.tab_ebook, "📚 E-book Didático (Apostila)")

        layout.addWidget(self.tab_widget, stretch=1)
        return widget

    # ----------------------------------------------------
    # HANDLERS & LOGIC
    # ----------------------------------------------------
    def _refresh_camera_devices(self):
        if not hasattr(self, "combo_my_cam"):
            return
        curr_data = self.combo_my_cam.currentData()
        self.combo_my_cam.blockSignals(True)
        self.combo_my_cam.clear()
        video_devs = QMediaDevices.videoInputs()
        if video_devs:
            for d in video_devs:
                self.combo_my_cam.addItem(f"📹 {d.description()}", d)
            if curr_data:
                idx = self.combo_my_cam.findData(curr_data)
                if idx >= 0:
                    self.combo_my_cam.setCurrentIndex(idx)
        else:
            v4l_path = Path("/sys/class/video4linux")
            v4l_found = []
            if v4l_path.exists():
                for dev in sorted(v4l_path.glob("video*")):
                    name_file = dev / "name"
                    if name_file.exists():
                        dev_name = name_file.read_text().strip()
                        v4l_found.append(f"{dev_name} ({dev.name})")

            if v4l_found:
                self.combo_my_cam.addItem(f"📹 {v4l_found[0]}", None)
            else:
                self.combo_my_cam.addItem("Câmera / Webcam Padrão do Sistema", None)
        self.combo_my_cam.blockSignals(False)

    def _on_mode_changed(self):
        if self.radio_mode1.isChecked():
            self.active_mode = 1
            self.lbl_mode_desc.setText(
                "Grave tudo o que acontece na tela e o som dos participantes. Ao final, "
                "o Gemini gera a transcrição integral e um resumo executivo com pauta, decisões e tarefas."
            )
            self.box_teacher_role.hide()
            self.box_my_camera.hide()
            self.box_teacher.hide()
            self.box_pdf.hide()
            self.chk_gen_ebook.hide()
            self.box_subs.hide()
        else:
            self.active_mode = 2
            self.lbl_mode_desc.setText(
                "Grave a aula transmitida no Meet focando na apresentação do professor. "
                "Ao final, gera o vídeo em Full HD pronto para o YouTube e um E-book Didático (Apostila) "
                "completo em PDF com todos os slides intercalados com os textos didáticos!"
            )
            self.box_teacher_role.show()
            self.box_teacher.show()
            self.box_pdf.show()
            self.chk_gen_ebook.show()
            self.box_subs.show()
            self._on_teacher_role_changed()

    def _on_teacher_role_changed(self):
        if self.radio_teacher_self.isChecked():
            if not self.edit_teacher.text().strip():
                self.edit_teacher.setText("Prof. Kika Magalhães")
            self.lbl_prof.setText("Seu Nome como Professora:")
            self.box_my_camera.show()
            self.lbl_teacher_role_hint.setText(
                "💡 Sua câmera será gravada na videoaula, capturando seus slides na tela, seu microfone e as dúvidas dos alunos no Meet."
            )
            self.lbl_teacher_role_hint.setStyleSheet("color: #34d399; font-size: 12px;")
        else:
            self.lbl_prof.setText("Nome do Professor(a) Remoto:")
            self.box_my_camera.hide()
            self.lbl_teacher_role_hint.setText(
                "💡 A apresentação e a câmera do professor remoto serão capturadas a partir da tela do Google Meet, preservando a privacidade dos outros alunos."
            )
            self.lbl_teacher_role_hint.setStyleSheet("color: #a78bfa; font-size: 12px;")

    def _toggle_floating_camera(self):
        if not self.floating_camera:
            self.floating_camera = FloatingCameraWidget()

        if self.floating_camera.isVisible():
            self.floating_camera.stop_camera()
            self.floating_camera.hide()
            self.btn_floating_cam.setText("📷 Ativar Janela Flutuante da Câmera na Tela")
        else:
            cam_dev = self.combo_my_cam.currentData()
            self.floating_camera.start_camera(cam_dev)
            self.floating_camera.show()
            self.btn_floating_cam.setText("📷 Ocultar Janela Flutuante da Câmera")

    def _pick_pdf_presentation(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Apresentação de Slides (PDF)",
            "",
            "Arquivos PDF (*.pdf)",
        )
        if file_path:
            self.selected_pdf_path = file_path
            self.lbl_pdf_status.setText(f"✓ {Path(file_path).name}")
            self.lbl_pdf_status.setStyleSheet("color: #10b981; font-weight: 600;")

    def _prepare_and_start_recording(self):
        dest_dir = Path.home() / "SlideCast_Materials" / "meet_recordings"
        dest_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        title_slug = self.edit_title.text().strip().lower().replace(" ", "_") or "meet"
        clean_slug = "".join(c for c in title_slug if c.isalnum() or c in "_-")[:25]
        self.recorded_video_path = str(dest_dir / f"{clean_slug}_{timestamp}.mp4")

        # Determine camera capture parameters
        cam_dev_str = None
        cam_pos_str = "bottom_right"

        if self.active_mode == 2 and self.radio_teacher_self.isChecked() and self.chk_my_cam.isChecked():
            cam_pos_str = self.combo_cam_pos.currentData() or "bottom_right"
            # If floating camera is not already visible on screen, pass device to FFmpeg
            if not (self.floating_camera and self.floating_camera.isVisible()):
                selected_dev = self.combo_my_cam.currentData()
                if selected_dev and hasattr(selected_dev, "id"):
                    cam_dev_str = selected_dev.id().data().decode("utf-8", errors="ignore")
                elif sys.platform == "win32":
                    cam_dev_str = "video"
                else:
                    if Path("/dev/video0").exists():
                        cam_dev_str = "/dev/video0"

        # 3-second countdown dialog to switch to Google Meet tab
        msg = QMessageBox(self)
        msg.setWindowTitle("Iniciando Gravação")
        if self.active_mode == 2 and self.radio_teacher_self.isChecked():
            msg.setText(
                "Iniciando gravação da sua aula em 3 segundos...\n\n"
                "Sua câmera e apresentação serão capturadas.\nAlterne para o Google Meet ou para seus slides agora!"
            )
        else:
            msg.setText("A gravação começará em 3 segundos.\n\nAlterne para a janela do Google Meet agora!")
        msg.setIcon(QMessageBox.Information)
        msg.setStandardButtons(QMessageBox.Ok)
        QTimer.singleShot(2000, msg.accept)
        msg.exec()

        resolution = self.combo_capture_area.currentData() or "1920x1080"
        self.recorder_process = ScreenRecordingProcess(
            output_video_path=self.recorded_video_path,
            video_size=resolution,
            fps=25,
            camera_device=cam_dev_str,
            camera_position=cam_pos_str,
        )
        self.recorder_process.start()

        if self.active_mode == 2:
            if self.radio_teacher_self.isChecked():
                self.lbl_rec_pulse.setText("🔴 GRAVANDO AULA NO MEET (MINHA CÂMERA ATIVA)")
            else:
                self.lbl_rec_pulse.setText("🔴 GRAVANDO AULA NO MEET (PROFESSOR REMOTO)")
        else:
            self.lbl_rec_pulse.setText("🔴 GRAVANDO GOOGLE MEET AO VIVO")

        self.timer.start()
        self.stack.setCurrentIndex(1)

    def _update_record_timer(self):
        if self.recorder_process:
            elapsed = self.recorder_process.get_elapsed_seconds()
            self.lbl_rec_time.setText(format_duration(elapsed))

    def _cancel_recording(self):
        if self.floating_camera and self.floating_camera.isVisible():
            self.floating_camera.stop_camera()
            self.floating_camera.hide()
            self.btn_floating_cam.setText("📷 Ativar Janela Flutuante da Câmera na Tela")

        if self.recorder_process:
            self.timer.stop()
            self.recorder_process.stop()
            if self.recorded_video_path and Path(self.recorded_video_path).exists():
                try:
                    Path(self.recorded_video_path).unlink()
                except Exception:
                    pass
        self.stack.setCurrentIndex(0)

    def _finish_and_process(self):
        if self.floating_camera and self.floating_camera.isVisible():
            self.floating_camera.stop_camera()
            self.floating_camera.hide()
            self.btn_floating_cam.setText("📷 Ativar Janela Flutuante da Câmera na Tela")

        self.timer.stop()
        if self.recorder_process:
            self.recorder_process.stop()

        # Switch to results view
        self.stack.setCurrentIndex(2)
        self.proc_progress.setValue(10)
        self.lbl_proc_status.setText("Iniciando análise com inteligência artificial...")
        self.tab_widget.hide()

        # Launch worker
        self.worker = MeetPostProcessWorker(
            mode=self.active_mode,
            video_path=self.recorded_video_path,
            title=self.edit_title.text().strip() or "Aula / Reunião Google Meet",
            teacher=self.edit_teacher.text().strip() or "Professor Responsável",
            pdf_path=self.selected_pdf_path,
            enable_ebook=self.chk_gen_ebook.isChecked(),
            enable_subtitles=self.chk_subs.isChecked(),
            subtitles_lang=self.combo_slang.currentData() or "pt",
        )
        self.worker.progress_changed.connect(self._on_worker_progress)
        self.worker.processing_finished.connect(self._on_processing_finished)
        self.worker.processing_error.connect(self._on_processing_error)
        self.worker.start()

    def _on_worker_progress(self, pct: float, msg: str):
        self.proc_progress.setValue(int(pct))
        self.lbl_proc_status.setText(msg)

    def _on_processing_finished(self, results: dict):
        self.results_data = results
        self.proc_progress.setValue(100)
        self.lbl_proc_status.setText("✓ Concluído com sucesso!")
        self.lbl_proc_status.setStyleSheet("color: #10b981; font-weight: 700;")

        self.lbl_video_info.setText(f"Vídeo gravado em: {results.get('video_path')}")

        if self.active_mode == 1:
            self.text_summary.setPlainText(results.get("summary", ""))
            self.text_transcription.setPlainText(results.get("transcription", ""))
            self.tab_widget.setTabVisible(1, True)
            self.tab_widget.setTabVisible(2, True)
            self.tab_widget.setTabVisible(3, False)
            self.tab_widget.setCurrentIndex(1)
        else:
            ebook_p = results.get("ebook_path")
            if ebook_p:
                self.lbl_ebook_info.setText(f"✓ E-book Gerado em:\n{ebook_p}")
            self.tab_widget.setTabVisible(1, False)
            self.tab_widget.setTabVisible(2, False)
            self.tab_widget.setTabVisible(3, True)
            self.tab_widget.setCurrentIndex(3)

        self.tab_widget.show()

    def _on_processing_error(self, err: str):
        self.lbl_proc_status.setText("Erro durante o processamento.")
        self.lbl_proc_status.setStyleSheet("color: #ef4444; font-weight: 700;")
        QMessageBox.critical(self, "Aviso", f"Erro no processamento da gravação:\n{err}")

    def _open_recorded_video(self):
        p = self.results_data.get("video_path")
        if p and Path(p).exists():
            try:
                if sys.platform == "win32":
                    os.startfile(p)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", p])
                else:
                    subprocess.Popen(["xdg-open", p])
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o vídeo:\n{e}")

    def _open_recorded_folder(self):
        p = self.results_data.get("video_path")
        if p and Path(p).exists():
            folder = str(Path(p).parent.resolve())
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer", folder])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir a pasta:\n{e}")

    def _open_ebook_file(self):
        p = self.results_data.get("ebook_path")
        if p and Path(p).exists():
            try:
                if sys.platform == "win32":
                    os.startfile(p)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", p])
                else:
                    subprocess.Popen(["xdg-open", p])
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o PDF:\n{e}")

    def _save_ebook_as(self):
        p = self.results_data.get("ebook_path")
        if not p or not Path(p).exists():
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar E-book da Aula em PDF",
            str(Path.home() / Path(p).name),
            "Arquivos PDF (*.pdf)",
        )
        if dest:
            import shutil
            shutil.copy2(p, dest)
            QMessageBox.information(self, "Arquivo Salvo", f"O E-book foi salvo com sucesso em:\n{dest}")
