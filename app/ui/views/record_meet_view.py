from app.ui.styles import apply_style
import logging
import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import Qt, QTimer, Signal, QThread, QRect
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
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from app.core.ffmpeg_utils import format_duration, get_video_duration
from app.core.pdf_processor import inspect_pdf, render_thumbnail
from app.core.subtitles_generator import generate_subtitles_with_gemini, SUPPORTED_LANGUAGES
from app.core.meeting_recorder import ScreenRecordingProcess, extract_audio_from_video, generate_meeting_notes
from app.core.ebook_generator import generate_class_ebook
from app.core.dual_region_recorder import (
    ScreenRegion,
    CompositionConfig,
    DualRegionSession,
    DualRegionRecordingProcess,
    PresentationInterval,
    format_ms_to_time,
    parse_time_to_ms,
    normalize_and_validate_intervals,
    detect_slide_intervals_heuristic,
    probe_video_dimensions,
)
from app.worker import DualRegionRenderWorker
from app.ui.screen_region_selector import ScreenRegionSelector
from app.ui.floating_camera_widget import FloatingCameraWidget
from app.ui.class_timeline_widget import ClassTimelineWidget
from PySide6.QtMultimedia import QMediaDevices, QCameraDevice

logger = logging.getLogger(__name__)


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
                        logger.warning("Aviso extraindo slides: %s", e)

                if self.enable_ebook:
                    self.progress_changed.emit(50.0, "Criando E-book Didático com slides intercalados via IA...")
                    clean_slug = "".join(c for c in self.title.lower().replace(" ", "_") if c.isalnum() or c in "_-")[:25] or "ebook_aula"
                    ebook_path = str(temp_dir / f"{clean_slug}_{int(time.time())}.pdf")

                    def callback(pct, msg):
                        # Core reports 0.0-1.0; this view's bar uses 0-100.
                        self.progress_changed.emit(pct * 100.0, msg)

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
                        logger.warning("Aviso gerando legendas: %s", e)

                self.progress_changed.emit(100.0, "Aula processada e e-book finalizado!")

            self.processing_finished.emit(results)

        except Exception as e:
            self.processing_error.emit(str(e))


class RecordMeetView(QWidget):
    back_to_home = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_mode = 1  # 1: Meeting, 2: Class
        self.capture_mode = "full_screen"  # "full_screen" or "dual_region"
        self.presentation_region: Optional[ScreenRegion] = None
        self.presenter_region: Optional[ScreenRegion] = None
        self.dual_recorder_process: Optional[DualRegionRecordingProcess] = None
        self.dual_session: Optional[DualRegionSession] = None
        self.pres_raw_path: Optional[str] = None
        self.prof_raw_path: Optional[str] = None
        self.comp_config = CompositionConfig()
        self.recorder_process: Optional[ScreenRecordingProcess] = None
        self.recorded_video_path: Optional[str] = None
        self.selected_pdf_path: Optional[str] = None
        self.results_data: dict = {}
        self.floating_camera: Optional[FloatingCameraWidget] = None

        # Classroom Timeline Direction State
        self.session_intervals: List[PresentationInterval] = []
        self.live_marker_start_ms: Optional[int] = None
        self.live_markers_log: List[dict] = []
        self.total_recorded_duration_ms: int = 0

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
        apply_style(title, "font-size: 16px; font-weight: 700; color: @success@;")

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
        apply_style(lbl_mtitle, "font-size: 16px; font-weight: 700; color: @text@;")
        mb_layout.addWidget(lbl_mtitle)

        modes_row = QHBoxLayout()
        modes_row.setSpacing(16)

        # Mode 1 Radio Card
        self.radio_mode1 = QRadioButton("1. Modo Reunião Completa (Daily / Alinhamento / Trabalho)")
        apply_style(self.radio_mode1, "font-weight: 700; color: @primary@; font-size: 13px;")
        self.radio_mode1.setChecked(True)
        self.radio_mode1.toggled.connect(self._on_mode_changed)

        # Mode 2 Radio Card
        self.radio_mode2 = QRadioButton("2. Modo Aula no Meet (Foco no Professor & E-book da Aula)")
        apply_style(self.radio_mode2, "font-weight: 700; color: @track2@; font-size: 13px;")

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
        apply_style(self.lbl_mode_desc, "color: @muted@; font-size: 12px; line-height: 1.4;")
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
        apply_style(lbl_role, "font-weight: 700; color: @text@; font-size: 13px;")

        role_row = QHBoxLayout()
        self.radio_teacher_self = QRadioButton("👤 Eu mesma sou a Professora (Dando a aula)")
        apply_style(self.radio_teacher_self, "font-weight: 700; color: @success@; font-size: 13px;")
        self.radio_teacher_self.setChecked(True)
        self.radio_teacher_self.toggled.connect(self._on_teacher_role_changed)

        self.radio_teacher_remote = QRadioButton("👨‍🏫 Outro Professor (Assistindo a aula de terceiro no Meet)")
        apply_style(self.radio_teacher_remote, "font-weight: 700; color: @track2@; font-size: 13px;")

        self.teacher_role_group = QButtonGroup(self)
        self.teacher_role_group.addButton(self.radio_teacher_self)
        self.teacher_role_group.addButton(self.radio_teacher_remote)

        role_row.addWidget(self.radio_teacher_self)
        role_row.addWidget(self.radio_teacher_remote)
        role_row.addStretch()

        self.lbl_teacher_role_hint = QLabel(
            "💡 Sua câmera será gravada na videoaula, capturando seus slides na tela, seu microfone e as dúvidas dos alunos no Meet."
        )
        apply_style(self.lbl_teacher_role_hint, "color: @primary@; font-size: 12px;")
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
        apply_style(self.box_my_camera, "background-color: @surface_alt@; border: 1px solid @border_strong@; border-radius: 8px;")
        bmc_layout = QVBoxLayout(self.box_my_camera)
        bmc_layout.setContentsMargins(14, 12, 14, 12)
        bmc_layout.setSpacing(10)

        self.chk_my_cam = QCheckBox("Habilitar gravação da minha Câmera / Webcam na videoaula")
        apply_style(self.chk_my_cam, "font-weight: 700; color: @text@;")
        self.chk_my_cam.setChecked(True)

        cam_config_row = QHBoxLayout()
        cam_config_row.setSpacing(12)

        cam_dev_box = QVBoxLayout()
        cam_hdr = QHBoxLayout()
        lbl_cdev = QLabel("Dispositivo de Câmera:")
        btn_refresh_meet_cam = QPushButton("🔄 Atualizar")
        btn_refresh_meet_cam.setCursor(Qt.PointingHandCursor)
        btn_refresh_meet_cam.setToolTip("Atualizar lista de câmeras conectadas")
        apply_style(btn_refresh_meet_cam, "background: @surface_alt@; color: @primary@; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px;")
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
        apply_style(self.btn_floating_cam, "background: @primary@; color: @text@; font-weight: 600; padding: 6px 14px; border-radius: 6px;")
        self.btn_floating_cam.setToolTip("Abre uma janela de vídeo da sua câmera que fica sempre no topo da tela para você se ver enquanto ministra a aula")
        self.btn_floating_cam.clicked.connect(self._toggle_floating_camera)

        lbl_float_hint = QLabel("Arraste e posicione na tela onde preferir durante a transmissão do Meet.")
        apply_style(lbl_float_hint, "color: @muted@; font-size: 11px;")

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
        apply_style(self.lbl_pdf_status, "color: @muted@; font-size: 12px;")
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

        # Capture Mode Card (Fullscreen vs Dual-Region)
        cap_card = QFrame()
        cap_card.setProperty("class", "card")
        cc_layout = QVBoxLayout(cap_card)
        cc_layout.setContentsMargins(18, 16, 18, 16)
        cc_layout.setSpacing(12)

        cap_title = QLabel("Formato de Captura de Vídeo:")
        apply_style(cap_title, "font-size: 15px; font-weight: 700; color: @text@;")
        cc_layout.addWidget(cap_title)

        cap_mode_row = QHBoxLayout()
        cap_mode_row.setSpacing(16)

        self.radio_cap_fullscreen = QRadioButton("🖥️ Gravar Tela Inteira (Padrão)")
        apply_style(self.radio_cap_fullscreen, "font-weight: 700; color: @primary@; font-size: 13px;")
        self.radio_cap_fullscreen.setChecked(True)
        self.radio_cap_fullscreen.toggled.connect(self._on_capture_mode_changed)

        self.radio_cap_dual = QRadioButton("📐 Apresentação + Professor (Selecionar 2 Áreas na Tela)")
        apply_style(self.radio_cap_dual, "font-weight: 700; color: @track2@; font-size: 13px;")

        self.cap_mode_group = QButtonGroup(self)
        self.cap_mode_group.addButton(self.radio_cap_fullscreen)
        self.cap_mode_group.addButton(self.radio_cap_dual)

        cap_mode_row.addWidget(self.radio_cap_fullscreen)
        cap_mode_row.addWidget(self.radio_cap_dual)
        cap_mode_row.addStretch()
        cc_layout.addLayout(cap_mode_row)

        # Fullscreen config options
        self.box_fullscreen_config = QWidget()
        bfc_lay = QHBoxLayout(self.box_fullscreen_config)
        bfc_lay.setContentsMargins(0, 4, 0, 0)
        lbl_fres = QLabel("Resolução de Captura da Tela:")
        self.combo_capture_area = QComboBox()
        self.combo_capture_area.addItem("Tela Inteira (1920x1080 Full HD)", "1920x1080")
        self.combo_capture_area.addItem("Resolução HD (1280x720)", "1280x720")
        bfc_lay.addWidget(lbl_fres)
        bfc_lay.addWidget(self.combo_capture_area)
        bfc_lay.addStretch()
        cc_layout.addWidget(self.box_fullscreen_config)

        # Dual-Region config card
        self.box_dual_config = QFrame()
        apply_style(self.box_dual_config, "background-color: @surface_alt@; border: 1px solid @border_strong@; border-radius: 8px;")
        bdc_lay = QVBoxLayout(self.box_dual_config)
        bdc_lay.setContentsMargins(14, 14, 14, 14)
        bdc_lay.setSpacing(12)

        lbl_dual_desc = QLabel(
            "Selecione com o mouse o retângulo do slide e o retângulo do professor na sua tela. "
            "O SlideCast grava os dois simultaneamente e compõe automaticamente a aula em alta definição, "
            "com a apresentação grande e o professor na lateral."
        )
        lbl_dual_desc.setWordWrap(True)
        apply_style(lbl_dual_desc, "color: @muted@; font-size: 12px; line-height: 1.4;")
        bdc_lay.addWidget(lbl_dual_desc)

        # Areas selection row
        areas_row = QHBoxLayout()
        areas_row.setSpacing(14)

        # Area A: Presentation
        box_area_a = QFrame()
        apply_style(box_area_a, "background-color: @surface@; border: 1.5px solid #38bdf8; border-radius: 6px; padding: 10px;")
        baa_lay = QVBoxLayout(box_area_a)
        baa_lay.setSpacing(8)
        lbl_aa_title = QLabel("Área A — Apresentação (Slides)")
        apply_style(lbl_aa_title, "font-weight: 700; color: #38bdf8; font-size: 13px;")
        self.lbl_pres_region_status = QLabel("Nenhuma área selecionada")
        apply_style(self.lbl_pres_region_status, "color: @muted@; font-size: 12px;")
        self.btn_select_pres = QPushButton("📐 Selecionar Área da Apresentação")
        self.btn_select_pres.setCursor(Qt.PointingHandCursor)
        apply_style(self.btn_select_pres, "background-color: #38bdf8; color: #10201e; font-weight: 700; padding: 6px 12px; border-radius: 6px;")
        self.btn_select_pres.clicked.connect(lambda: self._select_area("presentation"))
        baa_lay.addWidget(lbl_aa_title)
        baa_lay.addWidget(self.lbl_pres_region_status)
        baa_lay.addWidget(self.btn_select_pres)

        # Area B: Presenter
        box_area_b = QFrame()
        apply_style(box_area_b, "background-color: @surface@; border: 1.5px solid #f59e0b; border-radius: 6px; padding: 10px;")
        bab_lay = QVBoxLayout(box_area_b)
        bab_lay.setSpacing(8)
        lbl_ab_title = QLabel("Área B — Professor (Vídeo / Câmera)")
        apply_style(lbl_ab_title, "font-weight: 700; color: #f59e0b; font-size: 13px;")
        self.lbl_prof_region_status = QLabel("Nenhuma área selecionada")
        apply_style(self.lbl_prof_region_status, "color: @muted@; font-size: 12px;")
        self.btn_select_prof = QPushButton("📐 Selecionar Área do Professor")
        self.btn_select_prof.setCursor(Qt.PointingHandCursor)
        apply_style(self.btn_select_prof, "background-color: #f59e0b; color: #10201e; font-weight: 700; padding: 6px 12px; border-radius: 6px;")
        self.btn_select_prof.clicked.connect(lambda: self._select_area("presenter"))
        bab_lay.addWidget(lbl_ab_title)
        bab_lay.addWidget(self.lbl_prof_region_status)
        bab_lay.addWidget(self.btn_select_prof)

        areas_row.addWidget(box_area_a, stretch=1)
        areas_row.addWidget(box_area_b, stretch=1)
        bdc_lay.addLayout(areas_row)

        # Layout & Position controls row
        dual_cfg_row = QHBoxLayout()
        dual_cfg_row.setSpacing(12)

        lbl_dl = QLabel("Layout Pedagógico:")
        self.combo_dual_layout = QComboBox()
        self.combo_dual_layout.addItem("Professor na Lateral (Recomendado - 80% / 20%)", "sidebar")
        self.combo_dual_layout.addItem("Professor Sobreposto no Slide (PiP)", "overlay_pip")
        self.combo_dual_layout.currentIndexChanged.connect(self._on_dual_layout_changed)

        lbl_dp = QLabel("Posição:")
        self.combo_dual_pos = QComboBox()
        self.combo_dual_pos.addItem("Centro (Equilíbrio Padrão)", "center")
        self.combo_dual_pos.addItem("Topo", "top")
        self.combo_dual_pos.addItem("Embaixo", "bottom")

        lbl_dr = QLabel("Resolução:")
        self.combo_dual_res = QComboBox()
        self.combo_dual_res.addItem("1920x1080 (Full HD 16:9)", "1920x1080")
        self.combo_dual_res.addItem("1280x720 (HD 16:9)", "1280x720")

        self.btn_reset_dual_regions = QPushButton("🔄 Refazer Seleções")
        self.btn_reset_dual_regions.setCursor(Qt.PointingHandCursor)
        self.btn_reset_dual_regions.clicked.connect(self._reset_dual_regions)

        dual_cfg_row.addWidget(lbl_dl)
        dual_cfg_row.addWidget(self.combo_dual_layout)
        dual_cfg_row.addWidget(lbl_dp)
        dual_cfg_row.addWidget(self.combo_dual_pos)
        dual_cfg_row.addWidget(lbl_dr)
        dual_cfg_row.addWidget(self.combo_dual_res)
        dual_cfg_row.addWidget(self.btn_reset_dual_regions)
        dual_cfg_row.addStretch()

        bdc_lay.addLayout(dual_cfg_row)

        lbl_invariant_note = QLabel(
            "💡 Regra de Composição: Mesmo que você selecione dois retângulos do mesmo tamanho na tela, "
            "o SlideCast compõe os slides grandes (~80%) e o professor menor na lateral (~20%), sem distorção."
        )
        apply_style(lbl_invariant_note, "color: @primary@; font-size: 11px; font-weight: 600;")
        bdc_lay.addWidget(lbl_invariant_note)

        cc_layout.addWidget(self.box_dual_config)
        self.box_dual_config.hide()

        self.fc_layout.addWidget(cap_card)

        # Mode 2 specific Checkbox: E-book with interleaved slides
        self.chk_gen_ebook = QCheckBox("📚 Gerar E-book Didático / Apostila da Aula em PDF com Slides Intercalados")
        apply_style(self.chk_gen_ebook, "font-weight: 700; color: @track2@;")
        self.chk_gen_ebook.setChecked(True)
        self.fc_layout.addWidget(self.chk_gen_ebook)
        self.chk_gen_ebook.hide()

        # Mode 2 specific Checkbox: Subtitles
        self.box_subs = QWidget()
        bs_layout = QHBoxLayout(self.box_subs)
        bs_layout.setContentsMargins(0, 0, 0, 0)
        self.chk_subs = QCheckBox("Gerar Legendas no Vídeo com IA (Gemini)")
        apply_style(self.chk_subs, "color: @text@;")
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
        apply_style(self.btn_start_rec, "font-size: 15px; font-weight: 700;")
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
                apply_style(btn, "background: @success@; color: @on_primary@; font-weight: 700; "
                    "border: 1px solid @border@; padding: 8px 14px; border-radius: 8px;")
            else:
                apply_style(btn, "background: @surface_alt@; color: @muted@; font-weight: 600; "
                    "border: 1px solid @border_strong@; padding: 8px 14px; border-radius: 8px;")

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
        apply_style(self.lbl_rec_pulse, "font-size: 20px; font-weight: 800; color: @danger@;")
        self.lbl_rec_pulse.setAlignment(Qt.AlignCenter)

        self.lbl_rec_time = QLabel("00:00")
        apply_style(self.lbl_rec_time, "font-size: 32px; font-weight: 800; color: @text@; "
            "background-color: @surface_alt@; padding: 8px 24px; border-radius: 8px;")
        self.lbl_rec_time.setAlignment(Qt.AlignCenter)

        lbl_info = QLabel("A tela e o áudio da reunião estão sendo capturados com perfeição.\nQuando a reunião ou aula terminar, clique abaixo:")
        apply_style(lbl_info, "color: @muted@; font-size: 13px; line-height: 1.5;")
        lbl_info.setAlignment(Qt.AlignCenter)

        # Live Marker Controls (Method B)
        self.box_live_markers = QFrame()
        apply_style(self.box_live_markers, "background-color: @surface_alt@; border: 1px solid @border_strong@; border-radius: 8px; padding: 12px;")
        blm_lay = QVBoxLayout(self.box_live_markers)
        blm_lay.setSpacing(8)

        lbl_markers_title = QLabel("⏱️ Direção ao Vivo da Aula (Marcar Intervalos de Slides):")
        apply_style(lbl_markers_title, "font-size: 13px; font-weight: 700; color: @primary@;")
        blm_lay.addWidget(lbl_markers_title)

        m_btns_row = QHBoxLayout()
        m_btns_row.setSpacing(12)

        self.btn_mark_pres_start = QPushButton("▶ Apresentação Começou")
        self.btn_mark_pres_start.setCursor(Qt.PointingHandCursor)
        apply_style(self.btn_mark_pres_start, "background-color: #10b981; color: #ffffff; font-weight: 700; padding: 8px 18px; border-radius: 6px;")
        self.btn_mark_pres_start.clicked.connect(self._on_mark_presentation_start)

        self.btn_mark_pres_end = QPushButton("⏹ Apresentação Terminou")
        self.btn_mark_pres_end.setCursor(Qt.PointingHandCursor)
        self.btn_mark_pres_end.setEnabled(False)
        apply_style(self.btn_mark_pres_end, "background-color: #6366f1; color: #ffffff; font-weight: 700; padding: 8px 18px; border-radius: 6px;")
        self.btn_mark_pres_end.clicked.connect(self._on_mark_presentation_end)

        m_btns_row.addWidget(self.btn_mark_pres_start)
        m_btns_row.addWidget(self.btn_mark_pres_end)
        m_btns_row.addStretch()
        blm_lay.addLayout(m_btns_row)

        self.lbl_marker_status = QLabel("Nenhum marcador registrado (toda a aula será direcionada ou configurada ao final)")
        apply_style(self.lbl_marker_status, "color: @muted@; font-size: 12px;")
        blm_lay.addWidget(self.lbl_marker_status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)
        btn_row.setAlignment(Qt.AlignCenter)

        btn_stop = QPushButton("⏹ Concluir Gravação & Processar IA")
        btn_stop.setProperty("class", "primary")
        btn_stop.setFixedHeight(46)
        btn_stop.setCursor(Qt.PointingHandCursor)
        apply_style(btn_stop, "font-size: 14px; font-weight: 700; padding: 0 28px;")
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
        c_layout.addWidget(self.box_live_markers)
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
        apply_style(lbl_rtitle, "font-size: 18px; font-weight: 700; color: @success@;")
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
        apply_style(self.lbl_proc_status, "color: @primary@; font-weight: 600;")
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
        apply_style(self.lbl_video_info, "font-weight: 600; color: @text@;")
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

        # Dual-Region Timeline Direction & Re-composition Section
        self.box_dual_recompose = QFrame()
        self.box_dual_recompose.setProperty("class", "card")
        apply_style(self.box_dual_recompose, "background-color: @surface_alt@; border: 1px solid @border_strong@; border-radius: 8px;")
        bdr_layout = QVBoxLayout(self.box_dual_recompose)
        bdr_layout.setContentsMargins(16, 14, 16, 14)
        bdr_layout.setSpacing(10)

        lbl_recomp_title = QLabel("🎬 Direção da Aula & Linha do Tempo (Composição Sem Regravar)")
        apply_style(lbl_recomp_title, "font-size: 15px; font-weight: 700; color: @primary@;")
        lbl_recomp_desc = QLabel(
            "Alterne automaticamente entre o Professor em Destaque (abertura, intervalos e encerramento) "
            "e os Slides Grandes com Professor na Lateral (~80% / ~20%) durante a apresentação. "
            "Você pode editar os intervalos, títulos e posições e re-renderizar sem regravar nada."
        )
        lbl_recomp_desc.setWordWrap(True)
        apply_style(lbl_recomp_desc, "color: @muted@; font-size: 12px; line-height: 1.4;")

        # Title and Subtitle inputs
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        lbl_dt = QLabel("Título da Aula:")
        apply_style(lbl_dt, "font-weight: 600; font-size: 12px;")
        self.edit_timeline_title = QLineEdit()
        self.edit_timeline_title.setPlaceholderText("Ex: Aula Magna - Direito Constitucional")
        lbl_ds = QLabel("Subtítulo:")
        apply_style(lbl_ds, "font-weight: 600; font-size: 12px;")
        self.edit_timeline_subtitle = QLineEdit()
        self.edit_timeline_subtitle.setPlaceholderText("Ex: Prof. Kika Magalhães · Módulo I")
        title_row.addWidget(lbl_dt)
        title_row.addWidget(self.edit_timeline_title, stretch=2)
        title_row.addWidget(lbl_ds)
        title_row.addWidget(self.edit_timeline_subtitle, stretch=2)

        # Quality inspection badge (Honest scaling policy)
        self.lbl_prof_quality_badge = QLabel("Inspecionando resolução da câmera do professor...")
        apply_style(self.lbl_prof_quality_badge, "background-color: @surface@; border: 1px solid @border@; border-radius: 6px; padding: 6px 12px; font-size: 12px; color: @track2@;")

        # Visual Timeline Widget
        self.timeline_widget = ClassTimelineWidget()
        self.timeline_widget.time_selected.connect(self._on_timeline_time_selected)

        # Needle position layout indicator
        self.lbl_needle_layout = QLabel("Layout no cursor (00:00): Professor em Destaque (Centralizado)")
        apply_style(self.lbl_needle_layout, "color: @primary@; font-weight: 600; font-size: 12px;")

        # Manual Interval adder (Method A) & Presets
        int_ctrl_row = QHBoxLayout()
        int_ctrl_row.setSpacing(8)

        lbl_add_int = QLabel("Novo Intervalo de Slides:")
        apply_style(lbl_add_int, "font-weight: 600; font-size: 12px;")
        self.edit_int_start = QLineEdit()
        self.edit_int_start.setPlaceholderText("Início (02:00)")
        self.edit_int_start.setFixedWidth(100)
        self.edit_int_end = QLineEdit()
        self.edit_int_end.setPlaceholderText("Fim (36:00)")
        self.edit_int_end.setFixedWidth(100)

        self.btn_add_interval = QPushButton("➕ Adicionar Intervalo")
        self.btn_add_interval.setCursor(Qt.PointingHandCursor)
        apply_style(self.btn_add_interval, "background-color: @primary@; color: @on_primary@; font-weight: 700; padding: 6px 12px; border-radius: 6px;")
        self.btn_add_interval.clicked.connect(self._on_add_manual_interval)

        self.btn_preset_all_prof = QPushButton("👤 100% Professor")
        self.btn_preset_all_prof.setCursor(Qt.PointingHandCursor)
        self.btn_preset_all_prof.clicked.connect(self._on_preset_all_prof)

        self.btn_preset_all_slides = QPushButton("🖥️ 100% Slides")
        self.btn_preset_all_slides.setCursor(Qt.PointingHandCursor)
        self.btn_preset_all_slides.clicked.connect(self._on_preset_all_slides)

        self.btn_preset_heuristic = QPushButton("✨ Sugerir com Heurística Local")
        self.btn_preset_heuristic.setCursor(Qt.PointingHandCursor)
        self.btn_preset_heuristic.clicked.connect(self._on_preset_heuristic)

        int_ctrl_row.addWidget(lbl_add_int)
        int_ctrl_row.addWidget(self.edit_int_start)
        int_ctrl_row.addWidget(self.edit_int_end)
        int_ctrl_row.addWidget(self.btn_add_interval)
        int_ctrl_row.addSpacing(10)
        int_ctrl_row.addWidget(self.btn_preset_all_prof)
        int_ctrl_row.addWidget(self.btn_preset_all_slides)
        int_ctrl_row.addWidget(self.btn_preset_heuristic)
        int_ctrl_row.addStretch()

        # Intervals table
        self.table_intervals = QTableWidget(0, 6)
        self.table_intervals.setHorizontalHeaderLabels(["#", "Início", "Fim", "Duração", "Origem", "Ações"])
        self.table_intervals.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_intervals.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_intervals.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_intervals.setMaximumHeight(130)
        self.table_intervals.setSelectionBehavior(QTableWidget.SelectRows)

        # Recompose options row
        recomp_ctrl_row = QHBoxLayout()
        recomp_ctrl_row.setSpacing(10)

        lbl_rl = QLabel("Layout dos Slides:")
        self.combo_recomp_layout = QComboBox()
        self.combo_recomp_layout.addItem("Professor na Lateral (~80% / ~20%)", "sidebar")
        self.combo_recomp_layout.addItem("Professor Sobreposto (PiP)", "overlay_pip")
        self.combo_recomp_layout.currentIndexChanged.connect(self._on_recomp_layout_changed)

        lbl_rp = QLabel("Posição:")
        self.combo_recomp_pos = QComboBox()
        self._populate_recomp_positions("sidebar")

        lbl_rr = QLabel("Resolução:")
        self.combo_recomp_res = QComboBox()
        self.combo_recomp_res.addItem("1920x1080 (Full HD 16:9)", "1920x1080")
        self.combo_recomp_res.addItem("1280x720 (HD 16:9)", "1280x720")

        self.btn_recompose = QPushButton("🎬 Renderizar Vídeo com Direção de Linha do Tempo")
        self.btn_recompose.setProperty("class", "primary")
        self.btn_recompose.setCursor(Qt.PointingHandCursor)
        self.btn_recompose.clicked.connect(self._on_recompose_clicked)

        recomp_ctrl_row.addWidget(lbl_rl)
        recomp_ctrl_row.addWidget(self.combo_recomp_layout)
        recomp_ctrl_row.addWidget(lbl_rp)
        recomp_ctrl_row.addWidget(self.combo_recomp_pos)
        recomp_ctrl_row.addWidget(lbl_rr)
        recomp_ctrl_row.addWidget(self.combo_recomp_res)
        recomp_ctrl_row.addWidget(self.btn_recompose)
        recomp_ctrl_row.addStretch()

        bdr_layout.addWidget(lbl_recomp_title)
        bdr_layout.addWidget(lbl_recomp_desc)
        bdr_layout.addLayout(title_row)
        bdr_layout.addWidget(self.lbl_prof_quality_badge)
        bdr_layout.addWidget(self.timeline_widget)
        bdr_layout.addWidget(self.lbl_needle_layout)
        bdr_layout.addLayout(int_ctrl_row)
        bdr_layout.addWidget(self.table_intervals)
        bdr_layout.addLayout(recomp_ctrl_row)

        tv_layout.addWidget(self.box_dual_recompose)
        self.box_dual_recompose.hide()

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
        apply_style(self.lbl_ebook_info, "font-size: 15px; font-weight: 700; color: @track2@;")

        lbl_edesc = QLabel(
            "A apostila contém todos os capítulos estruturados didaticamente, "
            "com os slides apresentados intercalados com explicações aprofundadas, "
            "pontos-chave e questões de fixação para os alunos."
        )
        lbl_edesc.setWordWrap(True)
        apply_style(lbl_edesc, "color: @muted@; font-size: 13px; line-height: 1.5;")

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
            apply_style(self.lbl_teacher_role_hint, "color: @success@; font-size: 12px;")
        else:
            self.lbl_prof.setText("Nome do Professor(a) Remoto:")
            self.box_my_camera.hide()
            self.lbl_teacher_role_hint.setText(
                "💡 A apresentação e a câmera do professor remoto serão capturadas a partir da tela do Google Meet, preservando a privacidade dos outros alunos."
            )
            apply_style(self.lbl_teacher_role_hint, "color: @track2@; font-size: 12px;")

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
            apply_style(self.lbl_pdf_status, "color: @success@; font-weight: 600;")

    def _on_capture_mode_changed(self):
        if self.radio_cap_dual.isChecked():
            self.capture_mode = "dual_region"
            self.box_dual_config.show()
            self.box_fullscreen_config.hide()
        else:
            self.capture_mode = "full_screen"
            self.box_dual_config.hide()
            self.box_fullscreen_config.show()

    def _select_area(self, role: str):
        initial_rect = None
        if role == "presentation" and self.presentation_region:
            r = self.presentation_region
            initial_rect = QRect(r.x, r.y, r.width, r.height)
        elif role == "presenter" and self.presenter_region:
            r = self.presenter_region
            initial_rect = QRect(r.x, r.y, r.width, r.height)

        self.selector = ScreenRegionSelector(target_name=role, initial_rect=initial_rect)
        if role == "presentation":
            self.selector.region_selected.connect(self._on_presentation_selected)
        else:
            self.selector.region_selected.connect(self._on_presenter_selected)
        self.selector.show()

    def _on_presentation_selected(self, x: int, y: int, w: int, h: int):
        self.presentation_region = ScreenRegion(
            name="presentation",
            label="ÁREA DA APRESENTAÇÃO",
            x=x,
            y=y,
            width=w,
            height=h,
        )
        self.lbl_pres_region_status.setText(f"✓ {w}×{h} px em ({x}, {y})")
        apply_style(self.lbl_pres_region_status, "color: @primary@; font-weight: 700; font-size: 12px;")

    def _on_presenter_selected(self, x: int, y: int, w: int, h: int):
        self.presenter_region = ScreenRegion(
            name="presenter",
            label="ÁREA DO PROFESSOR",
            x=x,
            y=y,
            width=w,
            height=h,
        )
        self.lbl_prof_region_status.setText(f"✓ {w}×{h} px em ({x}, {y})")
        apply_style(self.lbl_prof_region_status, "color: @warning@; font-weight: 700; font-size: 12px;")

    def _reset_dual_regions(self):
        self.presentation_region = None
        self.presenter_region = None
        self.lbl_pres_region_status.setText("Nenhuma área selecionada")
        apply_style(self.lbl_pres_region_status, "color: @muted@; font-size: 12px;")
        self.lbl_prof_region_status.setText("Nenhuma área selecionada")
        apply_style(self.lbl_prof_region_status, "color: @muted@; font-size: 12px;")

    def _on_dual_layout_changed(self, idx: int):
        layout_type = self.combo_dual_layout.currentData() or "sidebar"
        self.combo_dual_pos.blockSignals(True)
        self.combo_dual_pos.clear()
        if layout_type == "sidebar":
            self.combo_dual_pos.addItem("Centro (Equilíbrio Padrão)", "center")
            self.combo_dual_pos.addItem("Topo", "top")
            self.combo_dual_pos.addItem("Embaixo", "bottom")
        else:
            self.combo_dual_pos.addItem("Canto Inferior Direito (Padrão)", "bottom_right")
            self.combo_dual_pos.addItem("Canto Superior Direito", "top_right")
            self.combo_dual_pos.addItem("Canto Inferior Esquerdo", "bottom_left")
            self.combo_dual_pos.addItem("Canto Superior Esquerdo", "top_left")
        self.combo_dual_pos.blockSignals(False)

    def _populate_recomp_positions(self, layout_type: str):
        self.combo_recomp_pos.blockSignals(True)
        self.combo_recomp_pos.clear()
        if layout_type == "sidebar":
            self.combo_recomp_pos.addItem("Centro (Equilíbrio Padrão)", "center")
            self.combo_recomp_pos.addItem("Topo", "top")
            self.combo_recomp_pos.addItem("Embaixo", "bottom")
        else:
            self.combo_recomp_pos.addItem("Canto Inferior Direito (Padrão)", "bottom_right")
            self.combo_recomp_pos.addItem("Canto Superior Direito", "top_right")
            self.combo_recomp_pos.addItem("Canto Inferior Esquerdo", "bottom_left")
            self.combo_recomp_pos.addItem("Canto Superior Esquerdo", "top_left")
        self.combo_recomp_pos.blockSignals(False)

    def _on_recomp_layout_changed(self, idx: int):
        layout_type = self.combo_recomp_layout.currentData() or "sidebar"
        self._populate_recomp_positions(layout_type)

    def _get_current_elapsed_seconds(self) -> float:
        if self.radio_cap_dual.isChecked() and self.dual_recorder_process:
            return self.dual_recorder_process.get_elapsed_seconds()
        elif self.recorder_process:
            return self.recorder_process.get_elapsed_seconds()
        return 0.0

    def _on_mark_presentation_start(self):
        elapsed_sec = self._get_current_elapsed_seconds()
        elapsed_ms = int(elapsed_sec * 1000)
        self.live_marker_start_ms = elapsed_ms
        self.live_markers_log.append({
            "event": "start",
            "time_ms": elapsed_ms,
            "time_str": format_ms_to_time(elapsed_ms),
        })
        self.btn_mark_pres_start.setEnabled(False)
        self.btn_mark_pres_end.setEnabled(True)
        self.lbl_marker_status.setText(f"🟢 Slides ativos desde {format_ms_to_time(elapsed_ms)}...")
        apply_style(self.lbl_marker_status, "color: @success@; font-weight: 600; font-size: 12px;")

    def _on_mark_presentation_end(self):
        if self.live_marker_start_ms is None:
            return
        elapsed_sec = self._get_current_elapsed_seconds()
        elapsed_ms = int(elapsed_sec * 1000)
        if elapsed_ms <= self.live_marker_start_ms:
            elapsed_ms = self.live_marker_start_ms + 1000
        new_int = PresentationInterval(
            start_ms=self.live_marker_start_ms,
            end_ms=elapsed_ms,
            origin="live_marker",
        )
        self.session_intervals.append(new_int)
        self.live_markers_log.append({
            "event": "end",
            "time_ms": elapsed_ms,
            "time_str": format_ms_to_time(elapsed_ms),
        })
        self.live_marker_start_ms = None
        self.btn_mark_pres_start.setEnabled(True)
        self.btn_mark_pres_end.setEnabled(False)
        self.lbl_marker_status.setText(f"✓ {len(self.session_intervals)} intervalo(s) de apresentação registrado(s)")
        apply_style(self.lbl_marker_status, "color: @primary@; font-weight: 600; font-size: 12px;")

    def _on_timeline_time_selected(self, ms: int):
        label = self.timeline_widget.get_layout_label_at_ms(ms)
        self.lbl_needle_layout.setText(f"Layout no cursor ({format_ms_to_time(ms)}): {label}")

    def _on_add_manual_interval(self):
        s_txt = self.edit_int_start.text().strip()
        e_txt = self.edit_int_end.text().strip()
        if not s_txt or not e_txt:
            QMessageBox.warning(self, "Campos Obrigatórios", "Informe o tempo de início e fim no formato mm:ss (ex: 02:00 e 36:00).")
            return
        try:
            start_ms = parse_time_to_ms(s_txt)
            end_ms = parse_time_to_ms(e_txt)
        except ValueError as e:
            QMessageBox.warning(self, "Formato Inválido", f"Erro no formato de tempo:\n{e}")
            return

        if end_ms <= start_ms:
            QMessageBox.warning(self, "Intervalo Inválido", "O tempo final deve ser maior que o tempo inicial.")
            return

        # Check overlap
        for existing in self.session_intervals:
            if max(start_ms, existing.start_ms) < min(end_ms, existing.end_ms):
                QMessageBox.warning(
                    self,
                    "Intervalo Sobreposto",
                    f"O intervalo {s_txt} - {e_txt} sobrepõe o intervalo existente "
                    f"{existing.start_time_str} - {existing.end_time_str}.\n"
                    "Intervalos de slides não podem se sobrepor."
                )
                return

        new_interval = PresentationInterval(
            start_ms=start_ms,
            end_ms=end_ms,
            origin="manual",
        )
        self.session_intervals.append(new_interval)
        self._refresh_intervals_ui()
        self.edit_int_start.clear()
        self.edit_int_end.clear()

    def _on_remove_interval(self, idx: int):
        if 0 <= idx < len(self.session_intervals):
            self.session_intervals.pop(idx)
            self._refresh_intervals_ui()

    def _on_preset_all_prof(self):
        self.session_intervals.clear()
        self._refresh_intervals_ui()

    def _on_preset_all_slides(self):
        dur = self.total_recorded_duration_ms or 60000
        self.session_intervals = [
            PresentationInterval(start_ms=0, end_ms=dur, origin="manual")
        ]
        self._refresh_intervals_ui()

    def _on_preset_heuristic(self):
        if not self.pres_raw_path or not Path(self.pres_raw_path).exists():
            QMessageBox.warning(self, "Aviso", "Gravação bruta da apresentação indisponível para análise.")
            return

        suggested = detect_slide_intervals_heuristic(self.pres_raw_path)
        if not suggested:
            QMessageBox.information(
                self,
                "Heurística Local",
                "Nenhum intervalo evidente de slides foi detectado de forma automática.\n"
                "Você pode adicionar os intervalos manualmente usando os campos acima."
            )
            return

        msg_lines = [f"• {format_ms_to_time(i.start_ms)} até {format_ms_to_time(i.end_ms)}" for i in suggested]
        reply = QMessageBox.question(
            self,
            "Aplicar Intervalos Sugeridos?",
            f"A heurística detectou {len(suggested)} intervalo(s) candidato(s):\n\n" +
            "\n".join(msg_lines) +
            "\n\nDeseja substituir os intervalos atuais por estas sugestões?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.session_intervals = suggested
            self._refresh_intervals_ui()

    def _refresh_intervals_ui(self):
        # Sort intervals chronologically
        self.session_intervals = sorted(self.session_intervals, key=lambda x: x.start_ms)
        self.timeline_widget.set_intervals(self.session_intervals)

        self.table_intervals.setRowCount(len(self.session_intervals))
        for idx, interval in enumerate(self.session_intervals):
            item_idx = QTableWidgetItem(f"#{idx + 1}")
            item_idx.setTextAlignment(Qt.AlignCenter)
            self.table_intervals.setItem(idx, 0, item_idx)

            item_start = QTableWidgetItem(format_ms_to_time(interval.start_ms))
            item_start.setTextAlignment(Qt.AlignCenter)
            self.table_intervals.setItem(idx, 1, item_start)

            item_end = QTableWidgetItem(format_ms_to_time(interval.end_ms))
            item_end.setTextAlignment(Qt.AlignCenter)
            self.table_intervals.setItem(idx, 2, item_end)

            item_dur = QTableWidgetItem(format_ms_to_time(interval.duration_ms))
            item_dur.setTextAlignment(Qt.AlignCenter)
            self.table_intervals.setItem(idx, 3, item_dur)

            origin_label = "Manual"
            if interval.origin == "live_marker":
                origin_label = "Marcador Ao Vivo"
            elif interval.origin == "auto_suggestion":
                origin_label = "Heurística IA"
            item_origin = QTableWidgetItem(origin_label)
            item_origin.setTextAlignment(Qt.AlignCenter)
            self.table_intervals.setItem(idx, 4, item_origin)

            btn_remove = QPushButton("🗑️ Remover")
            btn_remove.setCursor(Qt.PointingHandCursor)
            apply_style(btn_remove, "background-color: @danger@; color: #ffffff; padding: 2px 8px; border-radius: 4px; font-size: 11px;")
            btn_remove.clicked.connect(lambda _, i=idx: self._on_remove_interval(i))
            self.table_intervals.setCellWidget(idx, 5, btn_remove)

    def _update_timeline_ui(self):
        if not self.pres_raw_path or not Path(self.pres_raw_path).exists():
            return

        try:
            dur_sec = get_video_duration(self.pres_raw_path)
            if dur_sec and dur_sec > 0:
                self.total_recorded_duration_ms = int(dur_sec * 1000)
        except Exception:
            pass

        self.timeline_widget.set_duration_ms(self.total_recorded_duration_ms)

        curr_title = getattr(self.comp_config, "lesson_title", "") or (self.edit_title.text().strip() if hasattr(self, "edit_title") else "") or "Aula Magna"
        curr_subtitle = getattr(self.comp_config, "lesson_subtitle", "") or (self.edit_teacher.text().strip() if hasattr(self, "edit_teacher") else "") or "SlideCast Studio"
        self.edit_timeline_title.setText(curr_title)
        self.edit_timeline_subtitle.setText(curr_subtitle)

        prof_w, prof_h = probe_video_dimensions(self.prof_raw_path)
        if prof_w <= 480:
            self.lbl_prof_quality_badge.setText(
                f"📐 Câmera do Professor: {prof_w}×{prof_h} px · Política de Nitidez: "
                "Ampliação contida em até 1.5× no palco #10201E (sem esticar ou pixelar)"
            )
            apply_style(self.lbl_prof_quality_badge, "background-color: @surface@; border: 1.5px solid @warning@; color: @warning@; padding: 6px 12px; border-radius: 6px; font-weight: 600; font-size: 12px;")
        else:
            self.lbl_prof_quality_badge.setText(
                f"📐 Câmera do Professor: {prof_w}×{prof_h} px (Alta Definição) · Palco Broadcast #10201E Ativo"
            )
            apply_style(self.lbl_prof_quality_badge, "background-color: @surface@; border: 1.5px solid @success@; color: @success@; padding: 6px 12px; border-radius: 6px; font-weight: 600; font-size: 12px;")

        self._refresh_intervals_ui()

    def _on_recompose_clicked(self):
        if not self.pres_raw_path or not self.prof_raw_path or not Path(self.pres_raw_path).exists() or not Path(self.prof_raw_path).exists():
            QMessageBox.warning(
                self,
                "Gravações Originais Indisponíveis",
                "As trilhas brutas da apresentação e do professor não foram encontradas para re-renderização."
            )
            return

        layout_type = self.combo_recomp_layout.currentData() or "sidebar"
        pos = self.combo_recomp_pos.currentData() or "center"
        res = self.combo_recomp_res.currentData() or "1920x1080"
        title = self.edit_timeline_title.text().strip() or (self.edit_title.text().strip() if hasattr(self, "edit_title") else "") or "Aula Magna"
        subtitle = self.edit_timeline_subtitle.text().strip() or (self.edit_teacher.text().strip() if hasattr(self, "edit_teacher") else "") or "SlideCast Studio"

        self.comp_config = CompositionConfig(
            layout=layout_type,
            presenter_position=pos,
            output_resolution=res,
            lesson_title=title,
            lesson_subtitle=subtitle,
            presentation_intervals=list(self.session_intervals),
        )

        dest_dir = Path(self.pres_raw_path).parent
        ts = int(time.time())
        new_output = str(dest_dir / f"recomp_{layout_type}_{pos}_{ts}.mp4")

        self.btn_recompose.setEnabled(False)
        self.proc_progress.setValue(10)
        self.lbl_proc_status.setText(f"Re-renderizando layout ({layout_type} - {pos})...")
        apply_style(self.lbl_proc_status, "color: @primary@; font-weight: 700;")

        self.recomp_worker = DualRegionRenderWorker(
            presentation_video_path=self.pres_raw_path,
            presenter_video_path=self.prof_raw_path,
            output_path=new_output,
            config=self.comp_config,
        )
        self.recomp_worker.progress_changed.connect(lambda pct, msg: self._on_worker_progress(pct, f"Re-renderizando: {msg}"))
        self.recomp_worker.render_finished.connect(self._on_recomp_finished)
        self.recomp_worker.render_error.connect(self._on_recomp_error)
        self.recomp_worker.start()

    def _on_recomp_finished(self, new_output_path: str):
        self.btn_recompose.setEnabled(True)
        self.recorded_video_path = new_output_path
        self.results_data["video_path"] = new_output_path
        self.lbl_video_info.setText(f"Vídeo re-renderizado em: {new_output_path}")
        self.lbl_proc_status.setText("✓ Novo layout renderizado com sucesso!")
        apply_style(self.lbl_proc_status, "color: @success@; font-weight: 700;")
        self.proc_progress.setValue(100)

        if self.dual_session:
            self.dual_session.output_video = new_output_path
            self.dual_session.config = self.comp_config
            self.dual_session.lesson_title = self.comp_config.lesson_title
            self.dual_session.lesson_subtitle = self.comp_config.lesson_subtitle
            session_file = Path(new_output_path).with_suffix(".session.json")
            try:
                self.dual_session.save(str(session_file))
            except Exception:
                pass

        QMessageBox.information(
            self,
            "Layout Re-renderizado",
            f"O vídeo foi renderizado no novo layout com sucesso!\nSalvo em:\n{new_output_path}"
        )

    def _on_recomp_error(self, err: str):
        self.btn_recompose.setEnabled(True)
        self.lbl_proc_status.setText("Erro ao re-renderizar layout.")
        apply_style(self.lbl_proc_status, "color: @danger@; font-weight: 700;")
        QMessageBox.critical(self, "Erro na Renderização", f"Falha ao re-renderizar o vídeo:\n{err}")

    def _prepare_and_start_recording(self):
        # Reset timeline and live marker state
        self.session_intervals = []
        self.live_marker_start_ms = None
        self.live_markers_log = []
        self.btn_mark_pres_start.setEnabled(True)
        self.btn_mark_pres_end.setEnabled(False)
        self.lbl_marker_status.setText("Nenhum marcador registrado (toda a aula será direcionada ou configurada ao final)")
        apply_style(self.lbl_marker_status, "color: @muted@; font-size: 12px;")

        if self.radio_cap_dual.isChecked():
            if not self.presentation_region or not self.presenter_region:
                QMessageBox.warning(
                    self,
                    "Áreas Não Selecionadas",
                    "Por favor, selecione as duas áreas na tela antes de iniciar:\n\n"
                    "1. Área da Apresentação (Slides)\n"
                    "2. Área do Professor (Vídeo/Câmera)",
                )
                return

        dest_dir = Path.home() / "SlideCast_Materials" / "meet_recordings"
        dest_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        title_slug = self.edit_title.text().strip().lower().replace(" ", "_") or "meet"
        clean_slug = "".join(c for c in title_slug if c.isalnum() or c in "_-")[:25]
        self.recorded_video_path = str(dest_dir / f"{clean_slug}_{timestamp}.mp4")

        # Dual Region Capture Mode
        if self.radio_cap_dual.isChecked():
            self.pres_raw_path = str(dest_dir / f"{clean_slug}_{timestamp}_raw_pres.mp4")
            self.prof_raw_path = str(dest_dir / f"{clean_slug}_{timestamp}_raw_prof.mp4")

            layout_type = self.combo_dual_layout.currentData() or "sidebar"
            pos = self.combo_dual_pos.currentData() or "center"
            res = self.combo_dual_res.currentData() or "1920x1080"
            lesson_title = self.edit_title.text().strip() or "Aula Magna"
            lesson_subtitle = self.edit_teacher.text().strip() or "SlideCast Studio"

            self.comp_config = CompositionConfig(
                layout=layout_type,
                presenter_position=pos,
                output_resolution=res,
                lesson_title=lesson_title,
                lesson_subtitle=lesson_subtitle,
                presentation_intervals=list(self.session_intervals),
            )

            self.dual_session = DualRegionSession(
                capture_mode="dual_region",
                presentation_region=self.presentation_region,
                presenter_region=self.presenter_region,
                raw_presentation_video=self.pres_raw_path,
                raw_presenter_video=self.prof_raw_path,
                output_video=self.recorded_video_path,
                config=self.comp_config,
                lesson_title=lesson_title,
                lesson_subtitle=lesson_subtitle,
                live_markers=list(self.live_markers_log),
            )

            # 3-second countdown dialog to switch to Google Meet tab
            msg = QMessageBox(self)
            msg.setWindowTitle("Iniciando Gravação")
            msg.setText(
                "Iniciando gravação das duas áreas em 3 segundos...\n\n"
                "Alterne para a janela do Google Meet ou apresentação agora!\n"
                "As duas áreas serão capturadas simultaneamente em alta fidelidade."
            )
            msg.setIcon(QMessageBox.Information)
            msg.setStandardButtons(QMessageBox.Ok)
            QTimer.singleShot(2000, msg.accept)
            msg.exec()

            self.dual_recorder_process = DualRegionRecordingProcess(
                presentation_region=self.presentation_region,
                presenter_region=self.presenter_region,
                output_presentation_path=self.pres_raw_path,
                output_presenter_path=self.prof_raw_path,
                fps=25,
            )
            self.dual_recorder_process.start()

            self.lbl_rec_pulse.setText("🔴 GRAVANDO APRESENTAÇÃO + PROFESSOR (2 ÁREAS)")
            self.box_live_markers.show()
            self.timer.start()
            self.stack.setCurrentIndex(1)
            return

        # Full-screen mode (existing preserved flow)
        self.box_live_markers.hide()
        cam_dev_str = None
        cam_pos_str = "bottom_right"

        if self.active_mode == 2 and self.radio_teacher_self.isChecked() and self.chk_my_cam.isChecked():
            cam_pos_str = self.combo_cam_pos.currentData() or "bottom_right"
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
        elapsed = 0.0
        if self.radio_cap_dual.isChecked() and self.dual_recorder_process:
            elapsed = self.dual_recorder_process.get_elapsed_seconds()
        elif self.recorder_process:
            elapsed = self.recorder_process.get_elapsed_seconds()
        self.lbl_rec_time.setText(format_duration(elapsed))

    def _cancel_recording(self):
        if self.floating_camera and self.floating_camera.isVisible():
            self.floating_camera.stop_camera()
            self.floating_camera.hide()
            self.btn_floating_cam.setText("📷 Ativar Janela Flutuante da Câmera na Tela")

        self.timer.stop()
        if self.radio_cap_dual.isChecked() and self.dual_recorder_process:
            self.dual_recorder_process.stop()
            for p in [self.pres_raw_path, self.prof_raw_path, self.recorded_video_path]:
                if p and Path(p).exists():
                    try:
                        Path(p).unlink()
                    except Exception:
                        pass
        elif self.recorder_process:
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

        elapsed_sec = self._get_current_elapsed_seconds()
        self.total_recorded_duration_ms = int(elapsed_sec * 1000)

        # Auto-close open live marker if any
        if self.live_marker_start_ms is not None:
            end_ms = max(self.live_marker_start_ms + 1000, self.total_recorded_duration_ms)
            self.session_intervals.append(
                PresentationInterval(
                    start_ms=self.live_marker_start_ms,
                    end_ms=end_ms,
                    origin="live_marker",
                )
            )
            self.live_markers_log.append({
                "event": "end",
                "time_ms": end_ms,
                "time_str": format_ms_to_time(end_ms),
            })
            self.live_marker_start_ms = None

        if self.session_intervals and self.total_recorded_duration_ms > 0:
            try:
                self.session_intervals = normalize_and_validate_intervals(
                    self.session_intervals,
                    total_duration_ms=self.total_recorded_duration_ms,
                )
            except Exception as e:
                logger.warning("Interval normalization warning: %s", e)

        if self.radio_cap_dual.isChecked() and self.dual_recorder_process:
            self.dual_recorder_process.stop()
            self.stack.setCurrentIndex(2)
            self.proc_progress.setValue(10)
            self.lbl_proc_status.setText("Compondo vídeo da aula com direção de linha do tempo...")
            self.tab_widget.hide()

            layout_type = self.combo_dual_layout.currentData() or "sidebar"
            pos = self.combo_dual_pos.currentData() or "center"
            res = self.combo_dual_res.currentData() or "1920x1080"
            lesson_title = self.edit_title.text().strip() or "Aula Magna"
            lesson_subtitle = self.edit_teacher.text().strip() or "SlideCast Studio"

            self.comp_config = CompositionConfig(
                layout=layout_type,
                presenter_position=pos,
                output_resolution=res,
                lesson_title=lesson_title,
                lesson_subtitle=lesson_subtitle,
                presentation_intervals=list(self.session_intervals),
            )
            if self.dual_session:
                self.dual_session.config = self.comp_config
                self.dual_session.lesson_title = lesson_title
                self.dual_session.lesson_subtitle = lesson_subtitle
                self.dual_session.live_markers = list(self.live_markers_log)

            self.render_worker = DualRegionRenderWorker(
                presentation_video_path=self.pres_raw_path,
                presenter_video_path=self.prof_raw_path,
                output_path=self.recorded_video_path,
                config=self.comp_config,
            )
            self.render_worker.progress_changed.connect(lambda pct, msg: self._on_worker_progress(pct * 0.4, f"Compondo vídeo: {msg}"))
            self.render_worker.render_finished.connect(self._on_dual_render_finished)
            self.render_worker.render_error.connect(self._on_processing_error)
            self.render_worker.start()
            return

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
            enable_ebook=self.chk_gen_ebook.isChecked() if self.active_mode == 2 else False,
            enable_subtitles=self.chk_subs.isChecked() if self.active_mode == 2 else False,
            subtitles_lang=self.combo_slang.currentData() or "pt",
        )
        self.worker.progress_changed.connect(self._on_worker_progress)
        self.worker.processing_finished.connect(self._on_processing_finished)
        self.worker.processing_error.connect(self._on_processing_error)
        self.worker.start()

    def _on_dual_render_finished(self, output_path: str):
        # Save session file alongside output
        if self.dual_session:
            self.dual_session.output_video = output_path
            self.dual_session.config = self.comp_config
            self.dual_session.lesson_title = self.comp_config.lesson_title
            self.dual_session.lesson_subtitle = self.comp_config.lesson_subtitle
            session_file = Path(output_path).with_suffix(".session.json")
            try:
                self.dual_session.save(str(session_file))
            except Exception:
                pass

        self.proc_progress.setValue(45)
        self.lbl_proc_status.setText("Vídeo composto! Analisando conteúdo com inteligência artificial...")

        self.worker = MeetPostProcessWorker(
            mode=self.active_mode,
            video_path=output_path,
            title=self.edit_title.text().strip() or "Aula / Reunião Google Meet",
            teacher=self.edit_teacher.text().strip() or "Professor Responsável",
            pdf_path=self.selected_pdf_path,
            enable_ebook=self.chk_gen_ebook.isChecked() if self.active_mode == 2 else False,
            enable_subtitles=self.chk_subs.isChecked() if self.active_mode == 2 else False,
            subtitles_lang=self.combo_slang.currentData() or "pt",
        )
        self.worker.progress_changed.connect(lambda pct, msg: self._on_worker_progress(45 + pct * 0.55, msg))
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
        apply_style(self.lbl_proc_status, "color: @success@; font-weight: 700;")

        vpath = results.get("video_path") or self.recorded_video_path
        self.lbl_video_info.setText(f"Vídeo gravado em: {vpath}")

        # Show recomposition box if dual raw sources exist
        if self.pres_raw_path and self.prof_raw_path and Path(self.pres_raw_path).exists() and Path(self.prof_raw_path).exists():
            self.box_dual_recompose.show()
            self._update_timeline_ui()
        else:
            self.box_dual_recompose.hide()

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
        apply_style(self.lbl_proc_status, "color: @danger@; font-weight: 700;")
        QMessageBox.critical(self, "Aviso", f"Erro no processamento da gravação:\n{err}")

    def _open_recorded_video(self):
        p = self.results_data.get("video_path") or self.recorded_video_path
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
        p = self.results_data.get("video_path") or self.recorded_video_path
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
