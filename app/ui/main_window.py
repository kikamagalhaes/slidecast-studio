import logging
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QProgressBar,
    QScrollArea,
    QMessageBox,
    QFileDialog,
    QButtonGroup,
    QRadioButton,
    QFrame,
    QInputDialog,
    QStackedWidget,
)

from app.core.ffmpeg_utils import get_ffmpeg_paths, format_duration
from app.core.pdf_processor import inspect_pdf, render_thumbnail, PresentationInfo
from app.core.audio_processor import get_audio_info, AudioInfo
from app.core.config_manager import get_gemini_api_key, set_gemini_api_key
from app.core.multitrack import (
    MultimediaProject,
    AudioTrack,
    VideoInfo,
    inspect_video,
    probe_audio_track,
    MAX_AUDIO_TRACKS,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
)
from app.ui.widgets import DropAreaWidget, SlideThumbWidget
from app.ui.audio_track_widget import AudioTrackItemWidget
from app.ui.styles import DARK_THEME_QSS
from app.worker import VideoRenderWorker, AISyncWorker, MultimediaRenderWorker
from app.ui.views import (
    RecordClassView,
    RecordMeetView,
    RecordPodcastView,
    GenerateMaterialsView,
)
from app.ui.dialogs.generate_cover_dialog import GenerateCoverDialog
from app.ui.home_cards import MainView, build_home_menu

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SlideCast - Criador de Vídeos a partir de PDF e Áudio")
        self.resize(1060, 840)
        self.setMinimumSize(900, 680)

        self.pdf_info: Optional[PresentationInfo] = None
        self.audio_info: Optional[AudioInfo] = None
        self.video_info: Optional[VideoInfo] = None
        self.project: MultimediaProject = MultimediaProject()
        self.slide_durations: List[float] = []
        self.slide_widgets: List[SlideThumbWidget] = []
        self.track_widgets: List[AudioTrackItemWidget] = []
        self.worker: Optional[VideoRenderWorker] = None
        self.ai_worker: Optional[AISyncWorker] = None

        self._build_ui()
        self._check_ffmpeg()
        self._check_gemini_status()

    def _build_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)

        self.home_view = self._build_home_view()
        self.create_video_view = self._build_create_video_view()
        self.record_class_view = RecordClassView(self)
        self.record_class_view.back_to_home.connect(lambda: self.stack.setCurrentIndex(MainView.HOME))
        self.record_meet_view = RecordMeetView(self)
        self.record_meet_view.back_to_home.connect(lambda: self.stack.setCurrentIndex(MainView.HOME))
        self.record_podcast_view = RecordPodcastView(self)
        self.record_podcast_view.back_to_home.connect(lambda: self.stack.setCurrentIndex(MainView.HOME))
        self.generate_materials_view = GenerateMaterialsView(self)
        self.generate_materials_view.back_to_home.connect(lambda: self.stack.setCurrentIndex(MainView.HOME))

        # Inter-module shortcuts from materials generator
        self.generate_materials_view.send_to_create_video.connect(self._on_material_sent_to_create_video)
        self.generate_materials_view.send_to_record_class.connect(self._on_material_sent_to_record_class)

        self.stack.addWidget(self.home_view)               # Index 0
        self.stack.addWidget(self.create_video_view)        # Index 1
        self.stack.addWidget(self.record_class_view)        # Index 2
        self.stack.addWidget(self.record_meet_view)         # Index 3
        self.stack.addWidget(self.record_podcast_view)      # Index 4
        self.stack.addWidget(self.generate_materials_view)  # Index 5

        self.stack.setCurrentIndex(MainView.HOME)

    def _build_home_view(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(22)

        # 1. Header
        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)

        lbl_app_title = QLabel("SlideCast Studio")
        lbl_app_title.setProperty("class", "title")

        lbl_app_sub = QLabel(
            "Estúdio Integrado de Produção de Vídeos, Aulas e Gravações de Reuniões."
        )
        lbl_app_sub.setProperty("class", "subtitle")

        title_box.addWidget(lbl_app_title)
        title_box.addWidget(lbl_app_sub)
        header_layout.addLayout(title_box)

        header_layout.addStretch()

        self.btn_gemini_key = QPushButton("🔑 Chave Gemini API")
        self.btn_gemini_key.setCursor(Qt.PointingHandCursor)
        self.btn_gemini_key.setToolTip("Configurar chave gratuita de API do Google Gemini")
        self.btn_gemini_key.clicked.connect(self._open_gemini_key_dialog)
        header_layout.addWidget(self.btn_gemini_key, alignment=Qt.AlignVCenter)

        self.lbl_gemini_status = QLabel("Gemini: --")
        self.lbl_gemini_status.setProperty("class", "badge")
        header_layout.addWidget(self.lbl_gemini_status, alignment=Qt.AlignVCenter)

        self.lbl_ffmpeg_status = QLabel("Verificando FFmpeg...")
        self.lbl_ffmpeg_status.setProperty("class", "badge")
        header_layout.addWidget(self.lbl_ffmpeg_status, alignment=Qt.AlignVCenter)

        layout.addLayout(header_layout)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #242938; max-height: 1px;")
        layout.addWidget(sep)

        # Welcome Section
        welcome_box = QVBoxLayout()
        welcome_box.setSpacing(4)
        lbl_prompt = QLabel("O que você deseja fazer hoje?")
        lbl_prompt.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        lbl_desc = QLabel("Escolha um dos modos de trabalho abaixo para começar:")
        lbl_desc.setStyleSheet("font-size: 13px; color: #94a3b8;")
        welcome_box.addWidget(lbl_prompt)
        welcome_box.addWidget(lbl_desc)
        layout.addLayout(welcome_box)

        menu_layout = build_home_menu(self.stack.setCurrentIndex)
        layout.addLayout(menu_layout, stretch=1)

        return widget

    def _build_create_video_view(self) -> QWidget:
        widget = QWidget()
        page_layout = QVBoxLayout(widget)
        page_layout.setContentsMargins(24, 18, 24, 18)
        page_layout.setSpacing(14)

        # Top Navigation Bar with Back Button
        nav_bar = QHBoxLayout()
        btn_back = QPushButton("← Voltar ao Menu Inicial")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.clicked.connect(lambda: self.stack.setCurrentIndex(MainView.HOME))

        lbl_screen_title = QLabel("1. Criador de Vídeos a partir de PDF e Áudio")
        lbl_screen_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #38bdf8;")

        nav_bar.addWidget(btn_back)
        nav_bar.addWidget(lbl_screen_title)
        nav_bar.addStretch()

        btn_save_proj = QPushButton("💾 Salvar Projeto")
        btn_save_proj.setCursor(Qt.PointingHandCursor)
        btn_save_proj.setStyleSheet("font-size: 11px; padding: 5px 12px; background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 6px;")
        btn_save_proj.clicked.connect(self._save_project_dialog)

        btn_open_proj = QPushButton("📂 Abrir Projeto")
        btn_open_proj.setCursor(Qt.PointingHandCursor)
        btn_open_proj.setStyleSheet("font-size: 11px; padding: 5px 12px; background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 6px;")
        btn_open_proj.clicked.connect(self._open_project_dialog)

        nav_bar.addWidget(btn_save_proj)
        nav_bar.addWidget(btn_open_proj)
        page_layout.addLayout(nav_bar)

        # Step Navigation Bar (Clickable screens without scrollbars)
        self.cv_step_bar = QHBoxLayout()
        self.cv_step_bar.setSpacing(8)
        self.cv_step_buttons = []
        cv_step_labels = [
            "1. 📁 Arquivos (Visual & Áudios)",
            "2. ⏱️ Linha do Tempo & Sincronização",
            "3. 🎬 Exportação & Gerar Vídeo",
        ]
        for idx, text in enumerate(cv_step_labels):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self._switch_cv_step(i))
            self.cv_step_bar.addWidget(btn)
            self.cv_step_buttons.append(btn)
        page_layout.addLayout(self.cv_step_bar)

        self.cv_step_stack = QStackedWidget()

        # Page 1: Arquivos de Entrada
        page1 = QWidget()
        p1_lay = QVBoxLayout(page1)
        p1_lay.setContentsMargins(0, 8, 0, 0)
        p1_lay.setSpacing(12)

        # Page 2: Sincronização dos Slides / Linha do Tempo
        page2 = QWidget()
        p2_lay = QVBoxLayout(page2)
        p2_lay.setContentsMargins(0, 8, 0, 0)
        p2_lay.setSpacing(12)

        # Page 3: Exportação e Gerar Vídeo
        page3 = QWidget()
        p3_lay = QVBoxLayout(page3)
        p3_lay.setContentsMargins(0, 8, 0, 0)
        p3_lay.setSpacing(12)

        # --- Section: Input Files (Visual Source and Audio Tracks) ---
        inputs_frame = QFrame()
        inputs_frame.setProperty("class", "card")
        inputs_layout = QVBoxLayout(inputs_frame)
        inputs_layout.setContentsMargins(16, 16, 16, 16)
        inputs_layout.setSpacing(14)

        sec_header = QHBoxLayout()
        sec_title = QLabel("1. Selecione a Fonte Visual e as Faixas de Áudio")
        sec_title.setProperty("class", "section-title")
        sec_header.addWidget(sec_title)
        sec_header.addStretch()

        btn_ai_slides = QPushButton("🪄 Não tem slides? Criar com IA (Módulo 5)")
        btn_ai_slides.setCursor(Qt.PointingHandCursor)
        btn_ai_slides.setStyleSheet("font-size: 11px; padding: 5px 12px; background-color: #1e1b4b; border: 1px solid #4338ca; color: #c7d2fe; border-radius: 6px;")
        btn_ai_slides.clicked.connect(lambda: self.stack.setCurrentIndex(MainView.GENERATE_MATERIALS))
        sec_header.addWidget(btn_ai_slides)

        inputs_layout.addLayout(sec_header)

        # Visual Source Selection (PDF or Video MP4)
        src_row = QHBoxLayout()
        src_row.setSpacing(16)
        lbl_source_prompt = QLabel("Fonte Visual:")
        lbl_source_prompt.setStyleSheet("font-weight: 600; color: #cbd5e1; font-size: 13px;")

        self.radio_source_pdf = QRadioButton("Apresentação de Slides (PDF)")
        self.radio_source_pdf.setChecked(True)
        self.radio_source_pdf.setCursor(Qt.PointingHandCursor)

        self.radio_source_video = QRadioButton("Vídeo de Origem (MP4)")
        self.radio_source_video.setCursor(Qt.PointingHandCursor)

        self.source_type_group = QButtonGroup()
        self.source_type_group.addButton(self.radio_source_pdf)
        self.source_type_group.addButton(self.radio_source_video)
        self.radio_source_pdf.toggled.connect(self._on_source_type_changed)

        src_row.addWidget(lbl_source_prompt)
        src_row.addWidget(self.radio_source_pdf)
        src_row.addWidget(self.radio_source_video)
        src_row.addStretch()
        inputs_layout.addLayout(src_row)

        drop_row = QHBoxLayout()
        drop_row.setSpacing(16)

        # PDF Drop Widget
        self.pdf_drop = DropAreaWidget(
            title="Apresentação de Slides (PDF)",
            subtitle="Arraste e solte o arquivo .pdf aqui ou clique abaixo",
            icon_text="📊",
            file_filter="Apresentações PDF (*.pdf)",
            valid_extensions=[".pdf"],
        )
        self.pdf_drop.file_selected.connect(self._on_pdf_selected)
        self.pdf_drop.file_removed.connect(self._on_pdf_removed)

        # Video Drop Widget (MP4)
        self.video_drop = DropAreaWidget(
            title="Vídeo de Origem (MP4)",
            subtitle="Arraste e solte o arquivo de vídeo (.mp4, .mov, .mkv, .webm)",
            icon_text="🎬",
            file_filter="Vídeos (*.mp4 *.mov *.mkv *.webm)",
            valid_extensions=[".mp4", ".mov", ".mkv", ".webm"],
        )
        self.video_drop.file_selected.connect(self._on_video_selected)
        self.video_drop.file_removed.connect(self._on_video_removed)
        self.video_drop.hide()

        # Audio Drop Widget (Quick Drop for Track 1)
        self.audio_drop = DropAreaWidget(
            title="Arquivo de Áudio / Narração (Faixa 1)",
            subtitle="Arraste e solte o áudio principal (.mp3, .wav, .m4a, etc.)",
            icon_text="🎙️",
            file_filter="Arquivos de Áudio (*.mp3 *.wav *.m4a *.aac *.ogg *.flac *.wma *.webm)",
            valid_extensions=[".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".webm"],
        )
        self.audio_drop.file_selected.connect(self._on_audio_selected)
        self.audio_drop.file_removed.connect(self._on_audio_removed)

        # Container for visual drop
        self.visual_drop_box = QWidget()
        vdb_lay = QVBoxLayout(self.visual_drop_box)
        vdb_lay.setContentsMargins(0, 0, 0, 0)
        vdb_lay.addWidget(self.pdf_drop)
        vdb_lay.addWidget(self.video_drop)

        drop_row.addWidget(self.visual_drop_box, stretch=1)
        drop_row.addWidget(self.audio_drop, stretch=1)
        inputs_layout.addLayout(drop_row)

        # Multitrack Audio Panel (up to 4 tracks)
        multitrack_frame = QFrame()
        multitrack_frame.setStyleSheet("background: #0f172a; border: 1px solid #1e293b; border-radius: 8px;")
        mt_layout = QVBoxLayout(multitrack_frame)
        mt_layout.setContentsMargins(12, 10, 12, 10)
        mt_layout.setSpacing(8)

        mt_header = QHBoxLayout()
        lbl_mt_title = QLabel("🎵 Trilhas de Áudio (até 4 faixas independentes)")
        lbl_mt_title.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")

        self.btn_add_audio_track = QPushButton("+ Adicionar Faixa de Áudio")
        self.btn_add_audio_track.setCursor(Qt.PointingHandCursor)
        self.btn_add_audio_track.setStyleSheet(
            "QPushButton { background: #0284c7; color: #ffffff; font-weight: 600; "
            "padding: 5px 12px; border: none; border-radius: 6px; font-size: 12px; } "
            "QPushButton:hover { background: #0369a1; }"
        )
        self.btn_add_audio_track.clicked.connect(self._add_audio_track_dialog)

        mt_header.addWidget(lbl_mt_title)
        mt_header.addStretch()
        mt_header.addWidget(self.btn_add_audio_track)
        mt_layout.addLayout(mt_header)

        self.tracks_list_container = QWidget()
        self.tracks_list_layout = QVBoxLayout(self.tracks_list_container)
        self.tracks_list_layout.setContentsMargins(0, 0, 0, 0)
        self.tracks_list_layout.setSpacing(6)
        mt_layout.addWidget(self.tracks_list_container)

        self.lbl_no_tracks = QLabel("Nenhuma faixa de áudio adicionada. O vídeo pode ser gerado mudo ou com até 4 faixas.")
        self.lbl_no_tracks.setStyleSheet("color: #64748b; font-style: italic; font-size: 12px; padding: 4px;")
        mt_layout.addWidget(self.lbl_no_tracks)

        inputs_layout.addWidget(multitrack_frame)
        p1_lay.addWidget(inputs_frame)
        p1_lay.addStretch()

        s1_nav = QHBoxLayout()
        s1_nav.addStretch()
        btn_next_s1 = QPushButton("Continuar para Linha do Tempo / Sincronização ▶")
        btn_next_s1.setProperty("class", "primary")
        btn_next_s1.setCursor(Qt.PointingHandCursor)
        btn_next_s1.clicked.connect(lambda: self._switch_cv_step(1))
        s1_nav.addWidget(btn_next_s1)
        p1_lay.addLayout(s1_nav)

        # --- Section: Slides Timeline & Synchronization ---
        self.sync_frame = QFrame()
        self.sync_frame.setProperty("class", "card")
        sync_layout = QVBoxLayout(self.sync_frame)
        sync_layout.setContentsMargins(16, 16, 16, 16)
        sync_layout.setSpacing(12)

        sync_header = QHBoxLayout()
        sync_title = QLabel("2. Sincronização dos Slides")
        sync_title.setProperty("class", "section-title")
        sync_header.addWidget(sync_title)
        sync_header.addStretch()

        # Timing mode radio buttons
        self.radio_equal = QRadioButton("Dividir tempo igualmente pelo áudio")
        self.radio_equal.setChecked(True)
        self.radio_custom = QRadioButton("Personalizar por slide")
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.radio_equal)
        self.mode_group.addButton(self.radio_custom)
        self.radio_equal.toggled.connect(self._on_timing_mode_changed)

        sync_header.addWidget(self.radio_equal)
        sync_header.addWidget(self.radio_custom)
        sync_layout.addLayout(sync_header)

        # Stats bar
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self.lbl_slides_count = QLabel("Slides: 0")
        self.lbl_slides_count.setProperty("class", "badge")

        self.lbl_audio_time = QLabel("Duração do Áudio: --:--")
        self.lbl_audio_time.setProperty("class", "badge")

        self.lbl_slides_total_time = QLabel("Total dos Slides: 0.0s")
        self.lbl_slides_total_time.setProperty("class", "badge")

        self.btn_auto_balance = QPushButton("Ajustar ao Áudio")
        self.btn_auto_balance.setCursor(Qt.PointingHandCursor)
        self.btn_auto_balance.clicked.connect(self._balance_slides_to_audio)

        # AI Smart Sync Button
        self.btn_ai_sync = QPushButton("✨ Sincronizar com IA")
        self.btn_ai_sync.setCursor(Qt.PointingHandCursor)
        self.btn_ai_sync.setToolTip("Deixar o Gemini analisar o áudio e definir os tempos de cada slide automaticamente")
        self.btn_ai_sync.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #a855f7);
                color: #ffffff;
                font-weight: 600;
                padding: 6px 14px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #9333ea);
            }
            QPushButton:disabled {
                background-color: #262b3a;
                color: #64748b;
            }
        """)
        self.btn_ai_sync.clicked.connect(self._start_ai_sync)

        self.lbl_ai_status = QLabel("")
        self.lbl_ai_status.setStyleSheet("color: #c084fc; font-weight: 500; font-size: 12px;")

        stats_row.addWidget(self.lbl_slides_count)
        stats_row.addWidget(self.lbl_audio_time)
        stats_row.addWidget(self.lbl_slides_total_time)
        stats_row.addWidget(self.btn_auto_balance)
        stats_row.addWidget(self.btn_ai_sync)
        stats_row.addWidget(self.lbl_ai_status)
        stats_row.addStretch()

        sync_layout.addLayout(stats_row)

        # Horizontal scroll area for slide cards
        self.slides_scroll = QScrollArea()
        self.slides_scroll.setFixedHeight(190)
        self.slides_scroll.setWidgetResizable(True)
        self.slides_container = QWidget()
        self.slides_layout = QHBoxLayout(self.slides_container)
        self.slides_layout.setContentsMargins(8, 8, 8, 8)
        self.slides_layout.setSpacing(12)
        self.slides_layout.setAlignment(Qt.AlignLeft)
        self.slides_scroll.setWidget(self.slides_container)

        self.lbl_no_slides = QLabel("Carregue uma apresentação em PDF para visualizar e ajustar os slides.")
        self.lbl_no_slides.setAlignment(Qt.AlignCenter)
        self.lbl_no_slides.setStyleSheet("color: #64748b; font-style: italic; padding: 20px;")
        self.slides_layout.addWidget(self.lbl_no_slides)

        sync_layout.addWidget(self.slides_scroll)
        p2_lay.addWidget(self.sync_frame, stretch=1)

        # Video Timeline Frame (when visual source is MP4)
        self.video_timeline_frame = QFrame()
        self.video_timeline_frame.setProperty("class", "card")
        vtl_layout = QVBoxLayout(self.video_timeline_frame)
        vtl_layout.setContentsMargins(16, 16, 16, 16)
        vtl_layout.setSpacing(12)

        vtl_title = QLabel("2. Linha do Tempo do Vídeo de Origem")
        vtl_title.setProperty("class", "section-title")
        vtl_layout.addWidget(vtl_title)

        self.lbl_video_timeline_info = QLabel("Carregue um arquivo de vídeo MP4 na etapa 1.")
        self.lbl_video_timeline_info.setStyleSheet("color: #cbd5e1; font-size: 13px; line-height: 1.5; padding: 10px;")
        vtl_layout.addWidget(self.lbl_video_timeline_info)
        vtl_layout.addStretch()

        self.video_timeline_frame.hide()
        p2_lay.addWidget(self.video_timeline_frame, stretch=1)

        s2_nav = QHBoxLayout()
        btn_prev_s2 = QPushButton("◀ Voltar para Arquivos")
        btn_prev_s2.setCursor(Qt.PointingHandCursor)
        btn_prev_s2.clicked.connect(lambda: self._switch_cv_step(0))
        btn_next_s2 = QPushButton("Continuar para Configurações & Gerar Vídeo ▶")
        btn_next_s2.setProperty("class", "primary")
        btn_next_s2.setCursor(Qt.PointingHandCursor)
        btn_next_s2.clicked.connect(lambda: self._switch_cv_step(2))
        s2_nav.addWidget(btn_prev_s2)
        s2_nav.addStretch()
        s2_nav.addWidget(btn_next_s2)
        p2_lay.addLayout(s2_nav)

        # --- Section: Output & Export Settings ---
        export_frame = QFrame()
        export_frame.setProperty("class", "card")
        export_layout = QVBoxLayout(export_frame)
        export_layout.setContentsMargins(16, 16, 16, 16)
        export_layout.setSpacing(12)

        exp_title = QLabel("3. Configurações do Vídeo e Destino")
        exp_title.setProperty("class", "section-title")
        export_layout.addWidget(exp_title)

        opts_row = QHBoxLayout()
        opts_row.setSpacing(16)

        # Destination file path
        path_box = QVBoxLayout()
        path_box.setSpacing(4)
        lbl_dest = QLabel("Salvar Vídeo Como:")
        lbl_dest.setStyleSheet("font-weight: 500;")

        path_input_row = QHBoxLayout()
        path_input_row.setSpacing(8)
        self.edit_output_path = QLineEdit()
        self.edit_output_path.setPlaceholderText("Selecione o destino do vídeo...")
        self.btn_browse_output = QPushButton("Escolher...")
        self.btn_browse_output.clicked.connect(self._browse_output_path)

        path_input_row.addWidget(self.edit_output_path)
        path_input_row.addWidget(self.btn_browse_output)
        path_box.addWidget(lbl_dest)
        path_box.addLayout(path_input_row)

        # Resolution dropdown
        res_box = QVBoxLayout()
        res_box.setSpacing(4)
        lbl_res = QLabel("Resolução do Vídeo:")
        lbl_res.setStyleSheet("font-weight: 500;")

        self.combo_resolution = QComboBox()
        self.combo_resolution.addItem("1080p Full HD (1920x1080)", (1920, 1080))
        self.combo_resolution.addItem("720p HD (1280x720)", (1280, 720))
        self.combo_resolution.addItem("4K Ultra HD (3840x2160)", (3840, 2160))
        self.combo_resolution.addItem("Quadrado 1080x1080", (1080, 1080))

        res_box.addWidget(lbl_res)
        res_box.addWidget(self.combo_resolution)

        # FPS selector
        fps_box = QVBoxLayout()
        fps_box.setSpacing(4)
        lbl_fps = QLabel("Quadros por Segundo:")
        lbl_fps.setStyleSheet("font-weight: 500;")

        self.combo_fps = QComboBox()
        self.combo_fps.addItem("30 FPS (Padrão)", 30)
        self.combo_fps.addItem("24 FPS (Cinemático)", 24)
        self.combo_fps.addItem("60 FPS", 60)

        fps_box.addWidget(lbl_fps)
        fps_box.addWidget(self.combo_fps)

        opts_row.addLayout(path_box, stretch=3)
        opts_row.addLayout(res_box, stretch=1)
        opts_row.addLayout(fps_box, stretch=1)
        export_layout.addLayout(opts_row)

        p3_lay.addWidget(export_frame)

        # --- Section: Bottom Action & Progress Bar ---
        bottom_frame = QFrame()
        bottom_frame.setProperty("class", "card")
        bottom_layout = QVBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(16, 12, 16, 12)
        bottom_layout.setSpacing(10)

        # Action Buttons Row
        action_row = QHBoxLayout()
        action_row.setSpacing(12)

        self.btn_generate = QPushButton("🎬 Gerar Vídeo")
        self.btn_generate.setProperty("class", "primary")
        self.btn_generate.setFixedHeight(46)
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.setEnabled(False)
        self.btn_generate.clicked.connect(self._start_video_generation)

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setProperty("class", "danger")
        self.btn_cancel.setFixedHeight(46)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.hide()
        self.btn_cancel.clicked.connect(self._cancel_video_generation)

        action_row.addWidget(self.btn_generate, stretch=1)
        action_row.addWidget(self.btn_cancel)
        bottom_layout.addLayout(action_row)

        # Progress elements
        self.progress_container = QWidget()
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(4)

        self.lbl_status = QLabel("Pronto para iniciar.")
        self.lbl_status.setStyleSheet("font-weight: 500; color: #94a3b8;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        prog_layout.addWidget(self.lbl_status)
        prog_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(self.progress_container)
        self.progress_container.hide()

        p3_lay.addWidget(bottom_frame)
        p3_lay.addStretch()

        s3_nav = QHBoxLayout()
        btn_prev_s3 = QPushButton("◀ Voltar para Sincronização")
        btn_prev_s3.setCursor(Qt.PointingHandCursor)
        btn_prev_s3.clicked.connect(lambda: self._switch_cv_step(1))
        s3_nav.addWidget(btn_prev_s3)
        s3_nav.addStretch()
        p3_lay.addLayout(s3_nav)

        # Assemble step pages into step stack
        self.cv_step_stack.addWidget(page1)
        self.cv_step_stack.addWidget(page2)
        self.cv_step_stack.addWidget(page3)
        page_layout.addWidget(self.cv_step_stack, stretch=1)
        self._switch_cv_step(0)

        return widget

    def _switch_cv_step(self, idx: int):
        self.cv_step_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.cv_step_buttons):
            if i == idx:
                btn.setStyleSheet(
                    "background: #0284c7; color: #ffffff; font-weight: 700; "
                    "border: 1.5px solid #38bdf8; padding: 8px 14px; border-radius: 8px;"
                )
            else:
                btn.setStyleSheet(
                    "background: #1a1e28; color: #94a3b8; font-weight: 600; "
                    "border: 1px solid #2d3343; padding: 8px 14px; border-radius: 8px;"
                )
        if idx == 1:
            if hasattr(self, "radio_source_pdf") and self.radio_source_pdf.isChecked():
                self.sync_frame.show()
                self.video_timeline_frame.hide()
            elif hasattr(self, "video_timeline_frame"):
                self.sync_frame.hide()
                self.video_timeline_frame.show()

    def _check_ffmpeg(self):
        ffmpeg_path, _ = get_ffmpeg_paths()
        if ffmpeg_path:
            self.lbl_ffmpeg_status.setText("✓ FFmpeg Detectado")
            self.lbl_ffmpeg_status.setProperty("class", "badge-success")
        else:
            self.lbl_ffmpeg_status.setText("⚠ FFmpeg Não Encontrado")
            self.lbl_ffmpeg_status.setProperty("class", "badge-warning")
        self.lbl_ffmpeg_status.style().unpolish(self.lbl_ffmpeg_status)
        self.lbl_ffmpeg_status.style().polish(self.lbl_ffmpeg_status)

    def _check_gemini_status(self):
        key = get_gemini_api_key()
        if key:
            # Mask key for privacy
            masked = key[:4] + "..." + key[-4:] if len(key) > 8 else "***"
            self.lbl_gemini_status.setText(f"✓ Gemini Ativo ({masked})")
            self.lbl_gemini_status.setProperty("class", "badge-success")
        else:
            self.lbl_gemini_status.setText("Gemini: Não configurado")
            self.lbl_gemini_status.setProperty("class", "badge")
        self.lbl_gemini_status.style().unpolish(self.lbl_gemini_status)
        self.lbl_gemini_status.style().polish(self.lbl_gemini_status)

    def _open_gemini_key_dialog(self):
        current_key = get_gemini_api_key() or ""
        key, ok = QInputDialog.getText(
            self,
            "Chave de API do Google Gemini",
            "Cole sua chave de API gratuita do Google Gemini:\n(Obtenha gratuitamente em: https://aistudio.google.com/)",
            text=current_key,
        )
        if ok:
            key_clean = key.strip()
            if key_clean:
                set_gemini_api_key(key_clean)
                QMessageBox.information(
                    self,
                    "Chave Salva",
                    "Chave da API do Google Gemini salva com sucesso!\n"
                    "Agora você pode usar o botão '✨ Sincronizar com IA'.",
                )
            else:
                set_gemini_api_key("")
                QMessageBox.information(self, "Chave Removida", "A chave foi removida.")
            self._check_gemini_status()

    def _on_source_type_changed(self, is_pdf: bool):
        if is_pdf:
            self.pdf_drop.show()
            self.video_drop.hide()
            self.sync_frame.show()
            self.video_timeline_frame.hide()
            self.project.visual_source_type = "pdf"
            if self.pdf_info:
                self.project.set_visual_source("pdf", self.pdf_info.file_path, slide_durations=self.slide_durations)
        else:
            self.pdf_drop.hide()
            self.video_drop.show()
            self.sync_frame.hide()
            self.video_timeline_frame.show()
            self.project.visual_source_type = "video"
            if self.video_info:
                self.project.set_visual_source("video", self.video_info.file_path)
        self._update_durations_label()
        self._update_default_output_path()
        self._update_generate_button_state()

    def _on_video_selected(self, file_path: str):
        try:
            self.video_info = inspect_video(file_path)
            self.project.set_visual_source("video", file_path)
            audio_status = "Áudio original: detectado (ignorado por padrão)" if self.video_info.has_audio else "Vídeo mudo (sem áudio)"
            info_text = (
                f"Duração: {self.video_info.formatted_duration} • "
                f"{self.video_info.resolution_str} @ {self.video_info.fps}fps\n{audio_status}"
            )
            self.video_drop.update_info(info_text)
            self.lbl_video_timeline_info.setText(
                f"Vídeo de Origem Selecionado:\n\n"
                f"• Arquivo: {Path(file_path).name}\n"
                f"• Resolução: {self.video_info.resolution_str} ({self.video_info.codec_name})\n"
                f"• Taxa de Quadros: {self.video_info.fps} fps\n"
                f"• Duração Mestra: {self.video_info.formatted_duration} ({self.video_info.duration:.2f}s)\n"
                f"• {audio_status}\n\n"
                f"A duração total da exportação é controlada pelo vídeo mestre. "
                f"As faixas de áudio adicionadas serão mixadas e sincronizadas a esta linha do tempo."
            )
            self._update_durations_label()
            self._update_default_output_path()
            self._update_generate_button_state()
        except Exception as e:
            QMessageBox.critical(self, "Erro ao carregar Vídeo", f"Não foi possível abrir o vídeo:\n{e}")
            self.video_drop.clear_file()

    def _on_video_removed(self):
        self.video_info = None
        self.project.visual_source_path = None
        self.project.video_info = None
        self.lbl_video_timeline_info.setText("Carregue um arquivo de vídeo MP4 na etapa 1.")
        self._update_durations_label()
        self._update_generate_button_state()

    def _add_audio_track_dialog(self):
        if len(self.project.tracks) >= MAX_AUDIO_TRACKS:
            QMessageBox.warning(
                self,
                "Limite Atingido",
                f"O limite máximo de {MAX_AUDIO_TRACKS} faixas de áudio já foi atingido.",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Adicionar Faixa de Áudio",
            "",
            "Arquivos de Áudio (*.mp3 *.wav *.m4a *.aac *.ogg *.flac *.webm *.wma)",
        )
        if file_path:
            self._add_audio_track(file_path)

    def _add_audio_track(self, file_path: str, name: Optional[str] = None):
        try:
            track = probe_audio_track(file_path, name=name)
            self.project.add_track(track)
            self._refresh_audio_tracks_ui()
            self._update_durations_label()
            self._update_generate_button_state()
        except Exception as e:
            QMessageBox.critical(self, "Erro na Faixa de Áudio", f"Não foi possível adicionar a faixa:\n{e}")

    def _remove_audio_track(self, track_id: str):
        self.project.remove_track(track_id)
        self._refresh_audio_tracks_ui()
        self._update_durations_label()
        self._update_generate_button_state()

    def _on_track_changed(self, track_id: str):
        self._update_durations_label()
        self._update_generate_button_state()

    def _refresh_audio_tracks_ui(self):
        for w in self.track_widgets:
            w.deleteLater()
        self.track_widgets.clear()

        tracks = self.project.tracks
        if not tracks:
            self.lbl_no_tracks.show()
        else:
            self.lbl_no_tracks.hide()
            for idx, t in enumerate(tracks):
                w = AudioTrackItemWidget(t, index=idx, parent=self.tracks_list_container)
                w.track_changed.connect(self._on_track_changed)
                w.remove_requested.connect(self._remove_audio_track)
                self.tracks_list_layout.addWidget(w)
                self.track_widgets.append(w)

    def _save_project_dialog(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Projeto SlideCast",
            "meu_projeto.slidecast",
            "Projeto SlideCast (*.slidecast *.json)",
        )
        if file_path:
            try:
                if self.radio_source_pdf.isChecked() and self.pdf_info:
                    self.project.set_visual_source("pdf", self.pdf_info.file_path, slide_durations=self.slide_durations)
                elif self.radio_source_video.isChecked() and self.video_info:
                    self.project.set_visual_source("video", self.video_info.file_path)
                self.project.export_settings["output_path"] = self.edit_output_path.text().strip()
                res_tuple = self.combo_resolution.currentData()
                if res_tuple:
                    self.project.export_settings["resolution"] = list(res_tuple)
                self.project.export_settings["fps"] = self.combo_fps.currentData() or 30

                self.project.save_to_file(file_path)
                QMessageBox.information(self, "Projeto Salvo", f"Projeto salvo com sucesso em:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Erro ao Salvar", f"Não foi possível salvar o projeto:\n{e}")

    def _open_project_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir Projeto SlideCast",
            "",
            "Projeto SlideCast (*.slidecast *.json)",
        )
        if file_path:
            try:
                proj = MultimediaProject.load_from_file(file_path)
                self._load_project(proj)
                QMessageBox.information(self, "Projeto Carregado", f"Projeto '{proj.title}' carregado com sucesso!")
            except Exception as e:
                QMessageBox.critical(self, "Erro ao Abrir", f"Não foi possível abrir o projeto:\n{e}")

    def _load_project(self, proj: MultimediaProject):
        self.project = proj
        if proj.visual_source_type == "pdf" and proj.visual_source_path and Path(proj.visual_source_path).is_file():
            self.radio_source_pdf.setChecked(True)
            self.pdf_drop.set_file(proj.visual_source_path)
            self._on_pdf_selected(proj.visual_source_path)
            if proj.slide_durations and len(proj.slide_durations) == len(self.slide_durations):
                self.slide_durations = list(proj.slide_durations)
                self.radio_custom.setChecked(True)
                for i, card in enumerate(self.slide_widgets):
                    card.set_duration(self.slide_durations[i])
        elif proj.visual_source_type == "video" and proj.visual_source_path and Path(proj.visual_source_path).is_file():
            self.radio_source_video.setChecked(True)
            self.video_drop.set_file(proj.visual_source_path)
            self._on_video_selected(proj.visual_source_path)

        self._refresh_audio_tracks_ui()
        if proj.tracks:
            t1 = proj.tracks[0]
            if Path(t1.file_path).is_file():
                try:
                    self.audio_info = get_audio_info(t1.file_path)
                    self.audio_drop.set_file(t1.file_path)
                    self.audio_drop.update_info(f"Duração: {self.audio_info.formatted_duration}")
                except Exception:
                    pass

        out_p = proj.export_settings.get("output_path")
        if out_p:
            self.edit_output_path.setText(str(out_p))
        self._update_durations_label()
        self._update_generate_button_state()

    def _on_pdf_selected(self, file_path: str):
        try:
            self.pdf_info = inspect_pdf(file_path)
            self.pdf_drop.update_info(f"{self.pdf_info.page_count} slides detectados")
            self._render_slide_previews()
            self.project.set_visual_source("pdf", file_path, slide_durations=self.slide_durations)
            self._update_durations()
            self._update_default_output_path()
            self._update_generate_button_state()
        except Exception as e:
            QMessageBox.critical(self, "Erro ao carregar PDF", f"Não foi possível abrir o PDF:\n{e}")
            self.pdf_drop.clear_file()

    def _on_pdf_removed(self):
        self.pdf_info = None
        self.project.visual_source_path = None
        self._clear_slide_previews()
        self._update_durations()
        self._update_generate_button_state()

    def _on_audio_selected(self, file_path: str):
        try:
            self.audio_info = get_audio_info(file_path)
            info_text = f"Duração: {self.audio_info.formatted_duration}"
            if self.audio_info.sample_rate:
                info_text += f" • {self.audio_info.sample_rate // 1000} kHz"
            self.audio_drop.update_info(info_text)
            self.lbl_audio_time.setText(f"Duração do Áudio: {self.audio_info.formatted_duration}")

            # Keep project tracks in sync: update Track 1 or add Track 1
            if not self.project.tracks:
                self._add_audio_track(file_path, name="Narração Principal")
            else:
                self.project.tracks[0].file_path = str(Path(file_path).resolve())
                self.project.tracks[0].duration = self.audio_info.duration
                self.project.tracks[0].sample_rate = self.audio_info.sample_rate
                self.project.tracks[0].channels = self.audio_info.channels
                self._refresh_audio_tracks_ui()

            self._update_durations()
            self._update_default_output_path()
            self._update_generate_button_state()
        except Exception as e:
            QMessageBox.critical(self, "Erro ao carregar Áudio", f"Não foi possível ler o arquivo de áudio:\n{e}")
            self.audio_drop.clear_file()

    def _on_audio_removed(self):
        self.audio_info = None
        if self.project.tracks:
            self.project.tracks.pop(0)
            self._refresh_audio_tracks_ui()
        self.lbl_audio_time.setText("Duração do Áudio: --:--")
        self._update_durations()
        self._update_generate_button_state()

    def _clear_slide_previews(self):
        for widget in self.slide_widgets:
            widget.deleteLater()
        self.slide_widgets.clear()
        self.slide_durations.clear()
        self.lbl_slides_count.setText("Slides: 0")
        self.lbl_slides_total_time.setText("Total dos Slides: 0.0s")
        self.lbl_no_slides.show()

    def _render_slide_previews(self):
        if not self.pdf_info:
            return

        self._clear_slide_previews()
        self.lbl_no_slides.hide()
        self.lbl_slides_count.setText(f"Slides: {self.pdf_info.page_count}")

        # Initialize slide durations
        count = self.pdf_info.page_count
        audio_dur = self.audio_info.duration if self.audio_info else 0.0
        default_dur = (audio_dur / count) if (count > 0 and audio_dur > 0) else 5.0
        self.slide_durations = [default_dur] * count

        # Render preview thumbnails for each slide
        for i in range(count):
            try:
                thumb_bytes = render_thumbnail(self.pdf_info.file_path, i, max_dimension=200)
                card = SlideThumbWidget(i, thumb_bytes, default_dur, self.slides_container)
                card.duration_changed.connect(self._on_slide_duration_changed)
                card.spin_duration.setEnabled(self.radio_custom.isChecked())
                self.slides_layout.addWidget(card)
                self.slide_widgets.append(card)
            except Exception as e:
                logger.warning("Erro ao renderizar thumbnail %s: %s", i, e)

        self._update_durations_label()

    def _on_timing_mode_changed(self, equal_mode: bool):
        is_custom = not equal_mode
        for card in self.slide_widgets:
            card.spin_duration.setEnabled(is_custom)
        if equal_mode:
            self._balance_slides_to_audio()

    def _on_slide_duration_changed(self, slide_index: int, new_val: float):
        if 0 <= slide_index < len(self.slide_durations):
            self.slide_durations[slide_index] = new_val
            self._update_durations_label()

    def _balance_slides_to_audio(self):
        if not self.pdf_info or not self.audio_info:
            return
        count = self.pdf_info.page_count
        if count == 0:
            return
        equal_dur = self.audio_info.duration / count
        self.slide_durations = [equal_dur] * count
        for card in self.slide_widgets:
            card.set_duration(equal_dur)
        self._update_durations_label()

    def _start_ai_sync(self):
        if not self.pdf_info:
            QMessageBox.warning(self, "Aviso", "Por favor, carregue a apresentação em PDF primeiro.")
            return
        if not self.audio_info:
            QMessageBox.warning(self, "Aviso", "Por favor, carregue o arquivo de áudio da narração primeiro.")
            return

        api_key = get_gemini_api_key()
        if not api_key:
            reply = QMessageBox.question(
                self,
                "Chave do Gemini Necessária",
                "Para sincronizar com IA, é necessário informar sua chave gratuita da API do Google Gemini.\n\n"
                "Deseja configurar sua chave agora?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._open_gemini_key_dialog()
                api_key = get_gemini_api_key()
                if not api_key:
                    return
            else:
                return

        # Disable AI button and show status
        self.btn_ai_sync.setEnabled(False)
        self.lbl_ai_status.setText("Iniciando IA...")

        self.ai_worker = AISyncWorker(
            pdf_path=self.pdf_info.file_path,
            audio_path=self.audio_info.file_path,
            total_audio_duration=self.audio_info.duration,
            api_key=api_key,
            parent=self,
        )
        self.ai_worker.status_changed.connect(self._on_ai_status_changed)
        self.ai_worker.sync_finished.connect(self._on_ai_sync_finished)
        self.ai_worker.sync_error.connect(self._on_ai_sync_error)
        self.ai_worker.start()

    def _on_ai_status_changed(self, msg: str):
        self.lbl_ai_status.setText(msg)

    def _on_ai_sync_finished(self, durations: List[float]):
        self.btn_ai_sync.setEnabled(True)
        self.lbl_ai_status.setText("✓ Sincronizado com IA!")

        # Switch to custom timing mode to allow user to inspect and edit the AI-generated durations
        self.radio_custom.setChecked(True)
        self.slide_durations = durations
        for i, card in enumerate(self.slide_widgets):
            if i < len(durations):
                card.set_duration(durations[i])
        self._update_durations_label()

        QMessageBox.information(
            self,
            "Sincronização por IA Concluída",
            f"O Gemini analisou a narração e ajustou o tempo dos {len(durations)} slides!\n\n"
            "Os tempos foram atualizados nos cartões abaixo. Você pode inspecionar e fazer ajustes finos se desejar.",
        )

    def _on_ai_sync_error(self, err_msg: str):
        self.btn_ai_sync.setEnabled(True)
        self.lbl_ai_status.setText("")
        QMessageBox.critical(
            self,
            "Erro na Sincronização por IA",
            f"Não foi possível sincronizar os slides com o Gemini:\n\n{err_msg}",
        )

    def _update_durations(self):
        if self.pdf_info and self.audio_info and self.radio_equal.isChecked():
            self._balance_slides_to_audio()
        else:
            self._update_durations_label()

    def _update_durations_label(self):
        is_pdf = getattr(self, "radio_source_pdf", None) is None or self.radio_source_pdf.isChecked()
        if is_pdf:
            total_sec = sum(self.slide_durations)
            self.lbl_slides_total_time.setText(f"Total dos Slides: {format_duration(total_sec)}")
            if self.audio_info:
                diff = abs(total_sec - self.audio_info.duration)
                if diff <= 0.2:
                    self.lbl_slides_total_time.setProperty("class", "badge-success")
                else:
                    self.lbl_slides_total_time.setProperty("class", "badge-warning")
                self.lbl_slides_total_time.style().unpolish(self.lbl_slides_total_time)
                self.lbl_slides_total_time.style().polish(self.lbl_slides_total_time)
        else:
            total_sec = self.video_info.duration if self.video_info else 0.0
            self.lbl_slides_total_time.setText(f"Duração do Vídeo: {format_duration(total_sec)}")

    def _update_default_output_path(self):
        if not self.edit_output_path.text().strip():
            if getattr(self, "radio_source_pdf", None) is not None and self.radio_source_pdf.isChecked() and self.pdf_info:
                pdf_p = Path(self.pdf_info.file_path)
                default_out = pdf_p.with_suffix(".mp4")
                self.edit_output_path.setText(str(default_out))
            elif getattr(self, "radio_source_video", None) is not None and self.radio_source_video.isChecked() and self.video_info:
                vid_p = Path(self.video_info.file_path)
                default_out = vid_p.with_name(f"{vid_p.stem}_mix.mp4")
                self.edit_output_path.setText(str(default_out))
            elif self.pdf_info:
                pdf_p = Path(self.pdf_info.file_path)
                default_out = pdf_p.with_suffix(".mp4")
                self.edit_output_path.setText(str(default_out))

    def _browse_output_path(self):
        initial = self.edit_output_path.text().strip()
        if not initial:
            if self.pdf_info:
                initial = str(Path(self.pdf_info.file_path).with_suffix(".mp4"))
            elif self.video_info:
                vid_p = Path(self.video_info.file_path)
                initial = str(vid_p.with_name(f"{vid_p.stem}_mix.mp4"))

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Vídeo Como",
            initial,
            "Vídeo MP4 (*.mp4)",
        )
        if file_path:
            if not file_path.lower().endswith(".mp4"):
                file_path += ".mp4"
            self.edit_output_path.setText(file_path)
            self._update_generate_button_state()

    def _update_generate_button_state(self):
        has_out = bool(self.edit_output_path.text().strip())
        is_pdf = getattr(self, "radio_source_pdf", None) is None or self.radio_source_pdf.isChecked()
        if is_pdf:
            can_generate = (
                self.pdf_info is not None
                and len(self.slide_durations) > 0
                and has_out
            )
        else:
            can_generate = (
                self.video_info is not None
                and self.video_info.duration > 0
                and has_out
            )
        self.btn_generate.setEnabled(can_generate)

    def _start_video_generation(self):
        ffmpeg_path, _ = get_ffmpeg_paths()
        if not ffmpeg_path:
            QMessageBox.critical(
                self,
                "FFmpeg Ausente",
                "O FFmpeg não foi encontrado no seu computador.\n\n"
                "Para gerar o vídeo, instale o FFmpeg ou baixe o executável ffmpeg e coloque na mesma pasta do aplicativo.",
            )
            return

        out_path = self.edit_output_path.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Por favor, defina o local onde o vídeo será salvo.")
            return

        # Disable main controls during render
        self.btn_generate.hide()
        self.btn_cancel.show()
        self.progress_container.show()
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Preparando renderização...")
        self.pdf_drop.setEnabled(False)
        if hasattr(self, "video_drop"):
            self.video_drop.setEnabled(False)
        self.audio_drop.setEnabled(False)
        self.slides_scroll.setEnabled(False)

        res_tuple: Tuple[int, int] = self.combo_resolution.currentData()
        fps_val: int = self.combo_fps.currentData()

        # Synchronize project state
        self.project.export_settings["resolution"] = [res_tuple[0], res_tuple[1]]
        self.project.export_settings["fps"] = fps_val
        self.project.export_settings["output_path"] = out_path

        is_pdf = getattr(self, "radio_source_pdf", None) is None or self.radio_source_pdf.isChecked()
        if is_pdf and self.pdf_info:
            self.project.set_visual_source("pdf", self.pdf_info.file_path, slide_durations=self.slide_durations)
        elif not is_pdf and self.video_info:
            self.project.set_visual_source("video", self.video_info.file_path)

        # Fallback single audio to Track 1 if no tracks were added but audio_info exists
        if not self.project.tracks and self.audio_info and Path(self.audio_info.file_path).is_file():
            self._add_audio_track(self.audio_info.file_path, name="Narração Principal")

        # Start QThread MultimediaRenderWorker
        self.worker = MultimediaRenderWorker(
            project=self.project,
            output_path=out_path,
            parent=self,
        )
        self.worker.progress_changed.connect(self._on_render_progress)
        self.worker.render_finished.connect(self._on_render_finished)
        self.worker.render_error.connect(self._on_render_error)
        self.worker.render_cancelled.connect(self._on_render_cancelled)
        self.worker.start()

    def _on_render_progress(self, frac: float, msg: str):
        val = int(frac * 100)
        self.progress_bar.setValue(val)
        self.lbl_status.setText(msg)

    def _cancel_video_generation(self):
        if self.worker and self.worker.isRunning():
            self.lbl_status.setText("Cancelando...")
            self.worker.cancel()

    def _reset_ui_after_render(self):
        self.btn_generate.show()
        self.btn_cancel.hide()
        self.pdf_drop.setEnabled(True)
        if hasattr(self, "video_drop"):
            self.video_drop.setEnabled(True)
        self.audio_drop.setEnabled(True)
        self.slides_scroll.setEnabled(True)
        self._update_generate_button_state()

    def _on_render_cancelled(self):
        self._reset_ui_after_render()
        self.lbl_status.setText("Geração cancelada.")
        QMessageBox.information(self, "Cancelado", "A criação do vídeo foi cancelada.")

    def _on_render_error(self, err_msg: str):
        self._reset_ui_after_render()
        self.lbl_status.setText("Erro na renderização.")
        QMessageBox.critical(self, "Erro na Geração", f"Ocorreu um erro durante a criação do vídeo:\n\n{err_msg}")

    def _on_render_finished(self, out_path: str):
        self._reset_ui_after_render()
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Vídeo concluído com sucesso!")

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Vídeo Concluído!")
        msg_box.setText(f"O vídeo foi gerado com sucesso em:\n{out_path}")
        msg_box.setIcon(QMessageBox.Information)

        btn_play = msg_box.addButton("▶ Assistir Vídeo", QMessageBox.ActionRole)
        btn_open_folder = msg_box.addButton("📁 Abrir Pasta", QMessageBox.ActionRole)
        btn_close = msg_box.addButton("Fechar", QMessageBox.RejectRole)

        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == btn_play:
            self._open_file(out_path)
        elif clicked == btn_open_folder:
            self._open_folder(out_path)

    def _open_file(self, path: str):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o arquivo automaticamente:\n{e}")

    def _open_folder(self, file_path: str):
        folder = str(Path(file_path).parent.resolve())
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", folder])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            QMessageBox.warning(self, "Aviso", f"Não foi possível abrir a pasta:\n{e}")

    def _on_material_sent_to_create_video(self, pdf_path: str):
        self.stack.setCurrentIndex(MainView.CREATE_VIDEO)
        self.pdf_drop.set_file(pdf_path)
        self._on_pdf_selected(pdf_path)

    def _on_material_sent_to_record_class(self, pdf_path: str):
        try:
            self.record_class_view.pdf_info = inspect_pdf(pdf_path)
            self.record_class_view.lbl_pdf_status.setText(
                f"✓ {Path(pdf_path).name} ({self.record_class_view.pdf_info.page_count} slides)"
            )
            self.record_class_view.lbl_pdf_status.setStyleSheet("color: #10b981; font-weight: 600;")
        except Exception as e:
            pass
        self.stack.setCurrentIndex(MainView.RECORD_CLASS)
