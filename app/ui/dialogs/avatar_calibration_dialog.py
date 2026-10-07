import os
import sys
import time
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap, QImage, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QProgressBar,
    QMessageBox,
    QFrame,
    QFileDialog,
    QTabWidget,
    QRadioButton,
    QButtonGroup,
    QScrollArea,
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtMultimedia import (
    QCamera,
    QMediaDevices,
    QMediaCaptureSession,
    QMediaRecorder,
    QAudioInput,
    QMediaFormat,
)
from PySide6.QtMultimediaWidgets import QVideoWidget

from app.core.clone_manager import (
    create_clone,
    list_clones,
    get_clone,
    get_active_clone,
    delete_clone,
    get_clones_dir,
)
from app.core.config_manager import (
    get_elevenlabs_api_key,
    set_elevenlabs_api_key,
    get_replicate_api_key,
    set_replicate_api_key,
    get_avatar_engine,
    set_avatar_engine,
    set_active_clone_id,
)
from app.core.ffmpeg_utils import get_video_duration

CALIBRATION_PROMPT = (
    "Olá a todos! Sejam muito bem-vindos a esta videoaula.\n\n"
    "Estou gravando esta amostra para calibrar o meu clone digital com a máxima naturalidade. "
    "Durante as nossas aulas, vamos analisar cada slide com calma e atenção, explorando os conceitos "
    "de forma didática, clara e objetiva.\n\n"
    "Acompanhem as informações na tela, façam suas anotações e contem comigo para guiá-los "
    "em cada etapa do aprendizado com total dedicação e profissionalismo!"
)


class AvatarCalibrationDialog(QDialog):
    """
    Dialog to record a 20-60 second calibration video reading a teleprompter,
    or import an existing video clip to create a digital avatar clone.
    Supports both Cloud Engine (ElevenLabs + Replicate) and Local Engine (Edge-TTS).
    """
    clone_updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Estúdio de Calibração do Clone Digital (Avatar IA)")
        self.resize(840, 720)
        self.setMinimumSize(740, 580)

        # Recording state
        self.is_recording = False
        self.recorded_video_path: Optional[str] = None
        self.record_start_time = 0.0
        self.target_record_duration = 60.0  # seconds (default 60s for rich natural motion)

        # Multimedia objects
        self.camera: Optional[QCamera] = None
        self.audio_input: Optional[QAudioInput] = None
        self.capture_session = QMediaCaptureSession(self)
        self.recorder = QMediaRecorder(self)
        self.recorder.errorOccurred.connect(self._on_recorder_error)
        self.capture_session.setRecorder(self.recorder)

        # Timer for calibration countdown
        self.calib_timer = QTimer(self)
        self.calib_timer.setInterval(100)
        self.calib_timer.timeout.connect(self._on_timer_tick)

        self._media_initialized = False
        self._build_ui()
        self._refresh_saved_clones_list()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._media_initialized:
            self._media_initialized = True
            QTimer.singleShot(60, self._init_camera_and_audio)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # Header
        top_header = QHBoxLayout()
        header_v = QVBoxLayout()
        lbl_title = QLabel("🎭 Criar e Calibrar Meu Clone Digital (Avatar IA)")
        lbl_title.setStyleSheet("font-size: 19px; font-weight: 800; color: #a78bfa;")
        lbl_desc = QLabel(
            "Grave uma amostra de ~15 segundos lendo o texto indicado ou importe um vídeo curto. "
            "A IA salvará sua imagem e voz para ministrar aulas automaticamente no seu lugar!"
        )
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header_v.addWidget(lbl_title)
        header_v.addWidget(lbl_desc)
        top_header.addLayout(header_v)
        top_header.addStretch()
        root.addLayout(top_header)

        # Tabs: Step 1 (Gravação / Importação), Step 2 (Configuração do Clone), Step 3 (Clones Salvos)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2d3748;
                border-radius: 8px;
                background-color: #12151f;
                padding: 12px;
            }
            QTabBar::tab {
                background: #1a202c;
                color: #94a3b8;
                font-weight: 600;
                padding: 8px 18px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #312e81;
                color: #ffffff;
                border-bottom: 2px solid #818cf8;
            }
        """)

        self.tab_record = self._build_record_tab()
        self.tab_config = self._build_config_tab()
        self.tab_manage = self._build_manage_tab()

        self.tabs.addTab(self.tab_record, "1. 🎥 Gravação & Teleprompter")
        self.tabs.addTab(self.tab_config, "2. ⚙️ Motores de IA & Perfil")
        self.tabs.addTab(self.tab_manage, "3. 👥 Meus Clones Salvos")

        root.addWidget(self.tabs, stretch=1)

        # Bottom Close Button
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        btn_close = QPushButton("Fechar")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.close)
        bottom_bar.addWidget(btn_close)
        root.addLayout(bottom_bar)

    # ----------------------------------------------------
    # TAB 1: RECORD & TELEPROMPTER
    # ----------------------------------------------------
    def _build_record_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # Device selection row
        dev_row = QHBoxLayout()
        dev_row.setSpacing(10)

        lbl_cam = QLabel("Câmera:")
        lbl_cam.setStyleSheet("font-weight: 600; color: #cbd5e1;")
        self.combo_cams = QComboBox()
        self.combo_cams.currentIndexChanged.connect(self._on_camera_changed)

        btn_refresh_devs = QPushButton("🔄 Atualizar")
        btn_refresh_devs.setCursor(Qt.PointingHandCursor)
        btn_refresh_devs.setToolTip("Clique para recarregar dispositivos caso tenha acabado de conectar uma webcam USB")
        btn_refresh_devs.setStyleSheet(
            "background: #1e293b; color: #38bdf8; font-weight: 600; font-size: 11px; padding: 4px 10px; border-radius: 6px;"
        )
        btn_refresh_devs.clicked.connect(self._init_camera_and_audio)

        lbl_mic = QLabel("Microfone:")
        lbl_mic.setStyleSheet("font-weight: 600; color: #cbd5e1;")
        self.combo_mics = QComboBox()
        self.combo_mics.currentIndexChanged.connect(self._on_mic_changed)

        dev_row.addWidget(lbl_cam)
        dev_row.addWidget(self.combo_cams, stretch=2)
        dev_row.addWidget(btn_refresh_devs)
        dev_row.addSpacing(10)
        dev_row.addWidget(lbl_mic)
        dev_row.addWidget(self.combo_mics, stretch=2)
        layout.addLayout(dev_row)

        # Video Preview & Teleprompter Area
        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        # Left: Live camera preview
        cam_frame = QFrame()
        cam_frame.setStyleSheet("background-color: #0b0f19; border: 1.5px solid #2d3748; border-radius: 8px;")
        cf_layout = QVBoxLayout(cam_frame)
        cf_layout.setContentsMargins(4, 4, 4, 4)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(320, 220)
        cf_layout.addWidget(self.video_widget)

        self.lbl_cam_status = QLabel("Carregando câmera...")
        self.lbl_cam_status.setAlignment(Qt.AlignCenter)
        self.lbl_cam_status.setStyleSheet("color: #64748b; font-size: 11px;")
        cf_layout.addWidget(self.lbl_cam_status)

        content_row.addWidget(cam_frame, stretch=1)

        # Right: Teleprompter Card
        prompter_card = QFrame()
        prompter_card.setStyleSheet("""
            QFrame {
                background-color: #0f172a;
                border: 2px solid #6366f1;
                border-radius: 8px;
            }
        """)
        pc_layout = QVBoxLayout(prompter_card)
        pc_layout.setContentsMargins(14, 12, 14, 12)
        pc_layout.setSpacing(8)

        lbl_tp_title = QLabel("📜 Teleprompter (Sugestão de Apoio ou Improvise Livremente)")
        lbl_tp_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #38bdf8; border: none;")
        pc_layout.addWidget(lbl_tp_title)

        lbl_tp_prompt = QLabel(f'"{CALIBRATION_PROMPT}"')
        lbl_tp_prompt.setWordWrap(True)
        lbl_tp_prompt.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #f8fafc; line-height: 1.5; "
            "padding: 10px; background: #1e1b4b; border-radius: 6px; border: 1px solid #4338ca;"
        )
        pc_layout.addWidget(lbl_tp_prompt, stretch=1)

        lbl_tp_hint = QLabel(
            "💡 Dica de Ouro: Você NÃO precisa seguir o texto! Pode improvisar falando naturalmente como em uma aula real. "
            "A IA analisa sua expressividade, movimentos naturais e articulação espontânea dos lábios, não as palavras exatas."
        )
        lbl_tp_hint.setWordWrap(True)
        lbl_tp_hint.setStyleSheet("font-size: 11px; color: #38bdf8; border: none; font-weight: 500; line-height: 1.4;")
        pc_layout.addWidget(lbl_tp_hint)

        content_row.addWidget(prompter_card, stretch=1)
        layout.addLayout(content_row)

        # Timer & Progress bar
        timer_box = QVBoxLayout()
        timer_box.setSpacing(6)

        # Duration selection row
        dur_row = QHBoxLayout()
        dur_row.setSpacing(10)
        lbl_dur = QLabel("⏱️ Duração da Amostra:")
        lbl_dur.setStyleSheet("font-weight: 600; color: #cbd5e1; font-size: 12px;")

        self.combo_duration = QComboBox()
        self.combo_duration.addItem("⏱️ 30 segundos (Rápida)", 30.0)
        self.combo_duration.addItem("⏱️ 60 segundos / 1 min (Recomendada - Excelente Variedade)", 60.0)
        self.combo_duration.addItem("⏱️ 90 segundos / 1m30s (Estendida - Alta Riqueza)", 90.0)
        self.combo_duration.addItem("⏱️ 120 segundos / 2 min (Completa - Máximo Repertório)", 120.0)
        self.combo_duration.addItem("⏱️ Gravação Livre (Grave quanto quiser e clique em Parar)", 999.0)
        self.combo_duration.setCurrentIndex(1)
        self.combo_duration.currentIndexChanged.connect(self._on_duration_changed)
        self.combo_duration.setStyleSheet("background: #1e293b; color: #f8fafc; padding: 4px 8px; border-radius: 6px;")

        lbl_dur_hint = QLabel("💡 Amostras de 60s a 120s capturam um repertório riquíssimo de movimentos, eliminando repetições.")
        lbl_dur_hint.setStyleSheet("color: #38bdf8; font-size: 11px;")

        dur_row.addWidget(lbl_dur)
        dur_row.addWidget(self.combo_duration)
        dur_row.addWidget(lbl_dur_hint)
        dur_row.addStretch()
        timer_box.addLayout(dur_row)

        timer_hdr = QHBoxLayout()
        self.lbl_timer_status = QLabel("Pronto para gravar (Duração recomendada: 60 segundos)")
        self.lbl_timer_status.setStyleSheet("font-weight: 600; color: #94a3b8;")
        self.lbl_timer_val = QLabel("00:00 / 01:00")
        self.lbl_timer_val.setStyleSheet("font-size: 15px; font-weight: 800; color: #38bdf8;")
        timer_hdr.addWidget(self.lbl_timer_status)
        timer_hdr.addStretch()
        timer_hdr.addWidget(self.lbl_timer_val)
        timer_box.addLayout(timer_hdr)

        self.progress_calib = QProgressBar()
        self.progress_calib.setRange(0, 100)
        self.progress_calib.setValue(0)
        self.progress_calib.setFixedHeight(12)
        self.progress_calib.setStyleSheet("""
            QProgressBar {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #ec4899);
                border-radius: 5px;
            }
        """)
        timer_box.addWidget(self.progress_calib)
        layout.addLayout(timer_box)

        # Action Buttons row
        action_row = QHBoxLayout()
        action_row.setSpacing(12)

        self.btn_record_start = QPushButton("🔴 Iniciar Gravação de 60 Segundos")
        self.btn_record_start.setStyleSheet(
            "background: #dc2626; color: #ffffff; font-weight: 700; font-size: 13px; "
            "padding: 10px 18px; border-radius: 8px;"
        )
        self.btn_record_start.setCursor(Qt.PointingHandCursor)
        self.btn_record_start.clicked.connect(self._start_calibration_recording)

        self.btn_record_stop = QPushButton("⏹ Parar Gravação")
        self.btn_record_stop.setEnabled(False)
        self.btn_record_stop.setCursor(Qt.PointingHandCursor)
        self.btn_record_stop.clicked.connect(self._stop_calibration_recording)

        btn_import_video = QPushButton("📁 Ou Importar Vídeo Pronto (.mp4, .mov)...")
        btn_import_video.setCursor(Qt.PointingHandCursor)
        btn_import_video.setToolTip("Importe um vídeo curto que você já tenha gravado com seu celular ou webcam.")
        btn_import_video.clicked.connect(self._import_existing_video)

        action_row.addWidget(self.btn_record_start)
        action_row.addWidget(self.btn_record_stop)
        action_row.addStretch()
        action_row.addWidget(btn_import_video)
        layout.addLayout(action_row)

        return widget

    # ----------------------------------------------------
    # TAB 2: CLONE CONFIGURATION & ENGINES
    # ----------------------------------------------------
    def _build_config_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(16)

        # Profile info
        card_profile = QFrame()
        card_profile.setProperty("class", "card")
        cp_layout = QVBoxLayout(card_profile)
        cp_layout.setContentsMargins(16, 14, 16, 14)
        cp_layout.setSpacing(10)

        lbl_cp_title = QLabel("👤 Nome do Perfil do Clone:")
        lbl_cp_title.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 13px;")
        self.edit_clone_name = QLineEdit()
        self.edit_clone_name.setPlaceholderText("Ex: Prof. Kika Magalhães")
        self.edit_clone_name.setText("Prof. Kika Magalhães")
        self.edit_clone_name.setStyleSheet("padding: 8px 10px; font-size: 13px;")
        cp_layout.addWidget(lbl_cp_title)
        cp_layout.addWidget(self.edit_clone_name)

        # Video status preview
        self.lbl_selected_video_status = QLabel("Nenhum vídeo calibrado no momento.")
        self.lbl_selected_video_status.setStyleSheet("color: #f59e0b; font-size: 12px; font-weight: 600;")
        cp_layout.addWidget(self.lbl_selected_video_status)
        layout.addWidget(card_profile)

        # Engine selector
        card_engine = QFrame()
        card_engine.setProperty("class", "card")
        ce_layout = QVBoxLayout(card_engine)
        ce_layout.setContentsMargins(16, 16, 16, 16)
        ce_layout.setSpacing(14)

        lbl_eng_title = QLabel("⚙️ Selecione o Motor de Inteligência Artificial:")
        lbl_eng_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #38bdf8;")
        ce_layout.addWidget(lbl_eng_title)

        lbl_eng_sub = QLabel(
            "Escolha se deseja utilizar o processamento em nuvem de alta fidelidade ou o motor local gratuito:"
        )
        lbl_eng_sub.setWordWrap(True)
        lbl_eng_sub.setStyleSheet("color: #94a3b8; font-size: 12px; margin-bottom: 2px;")
        ce_layout.addWidget(lbl_eng_sub)

        # Radio 1: Cloud Engine (Replicate + ElevenLabs)
        top_cloud = QHBoxLayout()
        self.radio_cloud = QRadioButton("🌐 Opção A: Motor em Nuvem / Alta Fidelidade (Replicate + ElevenLabs)")
        self.radio_cloud.setStyleSheet("font-weight: 700; color: #a78bfa; font-size: 13px;")
        badge_cloud = QLabel("⭐ ALTA FIDELIDADE")
        badge_cloud.setStyleSheet(
            "background: #4338ca; color: #a5b4fc; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px;"
        )
        top_cloud.addWidget(self.radio_cloud)
        top_cloud.addStretch()
        top_cloud.addWidget(badge_cloud)
        ce_layout.addLayout(top_cloud)

        lbl_cloud_desc = QLabel(
            "• Sincronia labial neural fonema a fonema perfeita em português (mesma tecnologia de avatares profissionais).\n"
            "• Renderização rápida (15 a 45 segundos) processada em supercomputadores com GPU em nuvem.\n"
            "• Requer chave de API do Replicate (gratuita para testes)."
        )
        lbl_cloud_desc.setWordWrap(True)
        lbl_cloud_desc.setStyleSheet("color: #cbd5e1; font-size: 12px; margin-left: 20px; line-height: 1.4;")
        ce_layout.addWidget(lbl_cloud_desc)

        # Cloud API inputs box (PROMINENT & CLEAR)
        self.box_cloud_keys = QFrame()
        self.box_cloud_keys.setStyleSheet("""
            QFrame {
                background: #0f172a;
                border: 2px solid #6366f1;
                border-radius: 10px;
            }
        """)
        bck_layout = QVBoxLayout(self.box_cloud_keys)
        bck_layout.setContentsMargins(14, 14, 14, 14)
        bck_layout.setSpacing(10)

        lbl_keys_title = QLabel("🔑 ONDE COLOCAR A SUA CHAVE / TOKEN DE IA:")
        lbl_keys_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #a5b4fc; border: none;")
        bck_layout.addWidget(lbl_keys_title)

        # Field 1: Replicate Token
        lbl_rep = QLabel("1. Token de API do Replicate (Essencial para Sincronia Labial da Imagem):")
        lbl_rep.setStyleSheet("font-size: 12px; font-weight: 700; color: #38bdf8; border: none;")
        bck_layout.addWidget(lbl_rep)

        rep_row = QHBoxLayout()
        rep_row.setSpacing(8)
        self.edit_replicate_key = QLineEdit()
        self.edit_replicate_key.setPlaceholderText("Cole aqui seu token que começa com r8_...")
        self.edit_replicate_key.setText(get_replicate_api_key() or "")
        self.edit_replicate_key.setStyleSheet(
            "background: #1e293b; color: #f8fafc; font-family: monospace; font-size: 12px; "
            "padding: 8px 10px; border-radius: 6px; border: 1px solid #475569;"
        )
        self.edit_replicate_key.textChanged.connect(self._on_replicate_text_changed)

        self.btn_paste_rep = QPushButton("📋 Colar Token")
        self.btn_paste_rep.setCursor(Qt.PointingHandCursor)
        self.btn_paste_rep.setStyleSheet(
            "background: #4f46e5; color: #ffffff; font-weight: 700; font-size: 11px; padding: 7px 12px; border-radius: 6px;"
        )
        self.btn_paste_rep.clicked.connect(self._paste_replicate_token)

        self.btn_toggle_rep = QPushButton("👁️")
        self.btn_toggle_rep.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_rep.setToolTip("Mostrar ou ocultar token")
        self.btn_toggle_rep.setStyleSheet(
            "background: #334155; color: #f8fafc; font-size: 13px; padding: 7px 10px; border-radius: 6px;"
        )
        self.btn_toggle_rep.clicked.connect(self._toggle_replicate_visibility)

        self.btn_get_rep = QPushButton("🌐 Pegar Token no Replicate")
        self.btn_get_rep.setCursor(Qt.PointingHandCursor)
        self.btn_get_rep.setStyleSheet(
            "background: #0284c7; color: #ffffff; font-weight: 700; font-size: 11px; padding: 7px 12px; border-radius: 6px;"
        )
        self.btn_get_rep.clicked.connect(self._open_replicate_web)

        rep_row.addWidget(self.edit_replicate_key, stretch=3)
        rep_row.addWidget(self.btn_paste_rep)
        rep_row.addWidget(self.btn_toggle_rep)
        rep_row.addWidget(self.btn_get_rep)
        bck_layout.addLayout(rep_row)

        lbl_rep_hint = QLabel(
            "💡 <b>Como obter o token:</b> Clique no botão azul acima para abrir o <b>replicate.com</b>. "
            "Crie uma conta gratuita (com Google/GitHub), copie o código que começa com <code>r8_</code> e clique em <b>'Colar Token'</b>."
        )
        lbl_rep_hint.setWordWrap(True)
        lbl_rep_hint.setStyleSheet("color: #94a3b8; font-size: 11px; border: none; margin-bottom: 6px;")
        bck_layout.addWidget(lbl_rep_hint)

        # Field 2: ElevenLabs Key (Optional)
        lbl_el = QLabel("2. Chave ElevenLabs API (Opcional - apenas se desejar voz clonada sintética):")
        lbl_el.setStyleSheet("font-size: 12px; font-weight: 600; color: #94a3b8; border: none; margin-top: 4px;")
        bck_layout.addWidget(lbl_el)

        el_row = QHBoxLayout()
        el_row.setSpacing(8)
        self.edit_eleven_key = QLineEdit()
        self.edit_eleven_key.setPlaceholderText("sk_... (opcional, deixe vazio se for gravar sua própria voz)")
        self.edit_eleven_key.setText(get_elevenlabs_api_key() or "")
        self.edit_eleven_key.setStyleSheet(
            "background: #1e293b; color: #f8fafc; font-family: monospace; font-size: 12px; "
            "padding: 8px 10px; border-radius: 6px; border: 1px solid #475569;"
        )
        self.edit_eleven_key.textChanged.connect(self._on_eleven_text_changed)

        self.btn_paste_el = QPushButton("📋 Colar")
        self.btn_paste_el.setCursor(Qt.PointingHandCursor)
        self.btn_paste_el.setStyleSheet(
            "background: #334155; color: #cbd5e1; font-weight: 600; font-size: 11px; padding: 7px 10px; border-radius: 6px;"
        )
        self.btn_paste_el.clicked.connect(self._paste_eleven_key)

        self.btn_toggle_el = QPushButton("👁️")
        self.btn_toggle_el.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_el.setStyleSheet(
            "background: #334155; color: #f8fafc; font-size: 13px; padding: 7px 10px; border-radius: 6px;"
        )
        self.btn_toggle_el.clicked.connect(self._toggle_eleven_visibility)

        self.btn_get_el = QPushButton("🌐 ElevenLabs.io")
        self.btn_get_el.setCursor(Qt.PointingHandCursor)
        self.btn_get_el.setStyleSheet(
            "background: #1e293b; color: #94a3b8; font-size: 11px; padding: 7px 10px; border-radius: 6px; border: 1px solid #475569;"
        )
        self.btn_get_el.clicked.connect(self._open_elevenlabs_web)

        el_row.addWidget(self.edit_eleven_key, stretch=3)
        el_row.addWidget(self.btn_paste_el)
        el_row.addWidget(self.btn_toggle_el)
        el_row.addWidget(self.btn_get_el)
        bck_layout.addLayout(el_row)

        lbl_el_hint = QLabel(
            "💡 <b>Nota:</b> Se você optar por gravar sua própria voz humana natural no Passo 4 ou importar MP3/WAV, a chave da ElevenLabs NÃO é necessária!"
        )
        lbl_el_hint.setWordWrap(True)
        lbl_el_hint.setStyleSheet("color: #64748b; font-size: 11px; border: none;")
        bck_layout.addWidget(lbl_el_hint)

        ce_layout.addWidget(self.box_cloud_keys)

        # Radio 2: Local / Free Engine
        top_local = QHBoxLayout()
        self.radio_local = QRadioButton("💻 Opção B: Motor Local / 100% Gratuito (Sem custos de API)")
        self.radio_local.setStyleSheet("font-weight: 700; color: #10b981; font-size: 13px;")
        badge_local = QLabel("🌿 100% GRATUITO")
        badge_local.setStyleSheet(
            "background: #065f46; color: #6ee7b7; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px;"
        )
        top_local.addWidget(self.radio_local)
        top_local.addStretch()
        top_local.addWidget(badge_local)
        ce_layout.addLayout(top_local)

        lbl_local_desc = QLabel(
            "• Síntese neural brasileira ultra-rápida (Edge-TTS) ou uso da sua própria voz humana gravada.\n"
            "• Sincronia contínua e suave da sua imagem de referência com a fala (sem cortes ou saltos).\n"
            "• 0 custos por minuto, sem necessidade de cartão de crédito ou chaves de API."
        )
        lbl_local_desc.setWordWrap(True)
        lbl_local_desc.setStyleSheet("color: #cbd5e1; font-size: 12px; margin-left: 20px; line-height: 1.4;")
        ce_layout.addWidget(lbl_local_desc)

        # Local Voice choice
        self.box_local_voice = QFrame()
        self.box_local_voice.setStyleSheet("background: #0f172a; border-radius: 8px; padding: 6px; border: 1px solid #1e293b;")
        blv_layout = QHBoxLayout(self.box_local_voice)
        blv_layout.setContentsMargins(12, 10, 12, 10)
        lbl_lv = QLabel("Voz Neural Padrão em Português:")
        lbl_lv.setStyleSheet("font-weight: 600; color: #cbd5e1; font-size: 12px;")
        self.combo_local_voice = QComboBox()
        self.combo_local_voice.addItem("Francisca (Feminina - Natural e Clara)", "pt-BR-FranciscaNeural")
        self.combo_local_voice.addItem("Brenda (Feminina - Dinâmica)", "pt-BR-BrendaNeural")
        self.combo_local_voice.addItem("Antonio (Masculino - Didático)", "pt-BR-AntonioNeural")
        self.combo_local_voice.addItem("Donato (Masculino - Formal)", "pt-BR-DonatoNeural")
        self.combo_local_voice.setStyleSheet("background: #1e293b; color: #ffffff; padding: 6px 10px; border-radius: 6px;")

        blv_layout.addWidget(lbl_lv)
        blv_layout.addWidget(self.combo_local_voice, stretch=1)
        ce_layout.addWidget(self.box_local_voice)

        # Engine button group
        self.engine_group = QButtonGroup(self)
        self.engine_group.addButton(self.radio_cloud)
        self.engine_group.addButton(self.radio_local)

        curr_eng = get_avatar_engine()
        if curr_eng == "cloud":
            self.radio_cloud.setChecked(True)
        else:
            self.radio_local.setChecked(True)

        self.radio_cloud.toggled.connect(self._on_engine_toggled)
        self.radio_local.toggled.connect(self._on_engine_toggled)
        self._on_engine_toggled(self.radio_cloud.isChecked())

        layout.addWidget(card_engine)

        # Save Button
        self.btn_save_clone = QPushButton("💾 Processar e Salvar Clone Digital")
        self.btn_save_clone.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #7c3aed); "
            "color: #ffffff; font-weight: 800; font-size: 14px; padding: 12px 20px; border-radius: 8px;"
        )
        self.btn_save_clone.setCursor(Qt.PointingHandCursor)
        self.btn_save_clone.clicked.connect(self._save_and_activate_clone)
        layout.addWidget(self.btn_save_clone)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    # ----------------------------------------------------
    # TAB 3: MANAGE SAVED CLONES
    # ----------------------------------------------------
    def _build_manage_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        lbl_title = QLabel("👥 Clones Digitais Salvos:")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        layout.addWidget(lbl_title)

        self.list_clones_widget = QListWidget()
        self.list_clones_widget.setStyleSheet("""
            QListWidget {
                background-color: #0b0f19;
                border: 1.5px solid #2d3748;
                border-radius: 8px;
                padding: 6px;
            }
            QListWidget::item {
                background: #1a202c;
                color: #e2e8f0;
                padding: 10px;
                border-radius: 6px;
                margin-bottom: 6px;
            }
            QListWidget::item:selected {
                background: #312e81;
                border: 1px solid #818cf8;
            }
        """)
        layout.addWidget(self.list_clones_widget, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_set_active = QPushButton("✓ Ativar Clone Selecionado")
        self.btn_set_active.setProperty("class", "primary")
        self.btn_set_active.setCursor(Qt.PointingHandCursor)
        self.btn_set_active.clicked.connect(self._set_selected_clone_active)

        self.btn_del_clone = QPushButton("🗑 Excluir Clone")
        self.btn_del_clone.setStyleSheet("background: #991b1b; color: #ffffff;")
        self.btn_del_clone.setCursor(Qt.PointingHandCursor)
        self.btn_del_clone.clicked.connect(self._delete_selected_clone)

        btn_row.addWidget(self.btn_set_active)
        btn_row.addWidget(self.btn_del_clone)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return widget

    # ----------------------------------------------------
    # HARDWARE & MEDIA INITIALIZATION
    # ----------------------------------------------------
    def _init_camera_and_audio(self):
        # Video inputs
        cams = QMediaDevices.videoInputs()
        self.combo_cams.blockSignals(True)
        self.combo_cams.clear()
        if cams:
            for cam in cams:
                self.combo_cams.addItem(f"📹 {cam.description()}", cam)
            self.combo_cams.blockSignals(False)
            self._start_camera(cams[0])
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
                self.lbl_cam_status.setText(f"Detectada no sistema: {v4l_found[0]}. Clique em Atualizar.")
                self.lbl_cam_status.setStyleSheet("color: #38bdf8; font-size: 11px;")
            else:
                self.combo_cams.addItem("Nenhuma câmera detectada", None)
                self.lbl_cam_status.setText("Câmera não detectada (conecte uma webcam USB ou use 'Importar Vídeo')")
                self.lbl_cam_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
            self.combo_cams.blockSignals(False)

        # Audio inputs
        mics = QMediaDevices.audioInputs()
        self.combo_mics.blockSignals(True)
        self.combo_mics.clear()
        if mics:
            for mic in mics:
                self.combo_mics.addItem(f"🎙️ {mic.description()}", mic)
            self.combo_mics.blockSignals(False)
            if not self.audio_input:
                self.audio_input = QAudioInput(self)
                self.capture_session.setAudioInput(self.audio_input)
            self.audio_input.setDevice(mics[0])
        else:
            self.combo_mics.addItem("Microfone padrão", None)
            self.combo_mics.blockSignals(False)

    def _start_camera(self, camera_device):
        if camera_device is None:
            if self.camera:
                try:
                    self.camera.errorOccurred.disconnect()
                except Exception:
                    pass
                try:
                    self.camera.activeChanged.disconnect()
                except Exception:
                    pass
                self.camera.stop()
                self.capture_session.setCamera(None)
                self.camera.deleteLater()
                self.camera = None
            self.lbl_cam_status.setText("Nenhuma câmera selecionada.")
            self.lbl_cam_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
            return

        # If already running on this same device and active, do not restart
        if (
            self.camera is not None
            and hasattr(self.camera, "cameraDevice")
            and self.camera.cameraDevice().id() == camera_device.id()
            and self.camera.isActive()
        ):
            return

        try:
            if self.camera:
                try:
                    self.camera.errorOccurred.disconnect()
                except Exception:
                    pass
                try:
                    self.camera.activeChanged.disconnect()
                except Exception:
                    pass
                self.camera.stop()
                self.capture_session.setCamera(None)
                self.camera.deleteLater()
                self.camera = None

            self.camera = QCamera(camera_device, self)
            self.camera.errorOccurred.connect(self._on_camera_error)
            self.camera.activeChanged.connect(self._on_camera_active_changed)
            self.capture_session.setCamera(self.camera)
            self.capture_session.setVideoOutput(self.video_widget)
            self.camera.start()

            if self.camera.error() == QCamera.Error.NoError:
                self.lbl_cam_status.setText(f"✓ Câmera ativa: {camera_device.description()}")
                self.lbl_cam_status.setStyleSheet("color: #10b981; font-size: 11px;")
            else:
                self.lbl_cam_status.setText(f"Iniciando {camera_device.description()}...")
                self.lbl_cam_status.setStyleSheet("color: #38bdf8; font-size: 11px;")
        except Exception as e:
            self.lbl_cam_status.setText(f"Erro ao iniciar câmera: {e}")
            self.lbl_cam_status.setStyleSheet("color: #ef4444; font-size: 11px;")

    def _on_camera_error(self, error, error_string):
        print(f"[AvatarCalibrationDialog] Camera error: {error} - {error_string}")
        if self.camera and not self.camera.isActive():
            msg = error_string if error_string else "Dispositivo ocupado ou inacessível"
            self.lbl_cam_status.setText(f"⚠️ Câmera: {msg} (Clique em 🔄 Atualizar)")
            self.lbl_cam_status.setStyleSheet("color: #ef4444; font-size: 11px;")

    def _on_camera_active_changed(self, active: bool):
        if active and self.camera:
            cam_desc = self.camera.cameraDevice().description()
            self.lbl_cam_status.setText(f"✓ Câmera ativa: {cam_desc}")
            self.lbl_cam_status.setStyleSheet("color: #10b981; font-size: 11px;")

    def _on_camera_changed(self, idx: int):
        cam = self.combo_cams.itemData(idx)
        self._start_camera(cam)

    def _on_mic_changed(self, idx: int):
        mic = self.combo_mics.itemData(idx)
        if mic and self.audio_input:
            self.audio_input.setDevice(mic)

    def _on_engine_toggled(self, checked: bool):
        is_cloud = self.radio_cloud.isChecked()
        self.box_cloud_keys.setVisible(is_cloud)
        self.box_local_voice.setVisible(not is_cloud)

    def _paste_replicate_token(self):
        clipboard = QGuiApplication.clipboard()
        txt = clipboard.text().strip()
        if txt:
            self.edit_replicate_key.setText(txt)
            set_replicate_api_key(txt)

    def _toggle_replicate_visibility(self):
        if self.edit_replicate_key.echoMode() == QLineEdit.Password:
            self.edit_replicate_key.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_rep.setText("👁️")
        else:
            self.edit_replicate_key.setEchoMode(QLineEdit.Password)
            self.btn_toggle_rep.setText("🙈")

    def _paste_eleven_key(self):
        clipboard = QGuiApplication.clipboard()
        txt = clipboard.text().strip()
        if txt:
            self.edit_eleven_key.setText(txt)
            set_elevenlabs_api_key(txt)

    def _toggle_eleven_visibility(self):
        if self.edit_eleven_key.echoMode() == QLineEdit.Password:
            self.edit_eleven_key.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_el.setText("👁️")
        else:
            self.edit_eleven_key.setEchoMode(QLineEdit.Password)
            self.btn_toggle_el.setText("🙈")

    def _open_replicate_web(self):
        webbrowser.open("https://replicate.com/account/api-tokens")

    def _open_elevenlabs_web(self):
        webbrowser.open("https://elevenlabs.io")

    def _on_replicate_text_changed(self, text: str):
        val = text.strip()
        if val:
            set_replicate_api_key(val)

    def _on_eleven_text_changed(self, text: str):
        val = text.strip()
        if val:
            set_elevenlabs_api_key(val)

    def _on_duration_changed(self):
        dur = float(self.combo_duration.currentData() or 60.0)
        self.target_record_duration = dur
        if dur >= 600:
            self.lbl_timer_val.setText("00:00 / Livre")
            self.btn_record_start.setText("🔴 Iniciar Gravação Livre")
            self.lbl_timer_status.setText("Pronto para gravar (Modo Livre - clique em Parar quando terminar)")
        else:
            mins = int(dur) // 60
            secs = int(dur) % 60
            self.lbl_timer_val.setText(f"00:00 / {mins:02d}:{secs:02d}")
            self.btn_record_start.setText(f"🔴 Iniciar Gravação de {int(dur)}s")
            self.lbl_timer_status.setText(f"Pronto para gravar (Amostra de {int(dur)} segundos)")

    # ----------------------------------------------------
    # RECORDING ACTIONS
    # ----------------------------------------------------
    def _on_recorder_error(self, error, error_string):
        print(f"[AvatarCalibrationDialog] Recorder error: {error} - {error_string}")
        if self.is_recording:
            self.calib_timer.stop()
            self.is_recording = False
            if hasattr(self, "combo_duration"):
                self.combo_duration.setEnabled(True)
            self.btn_record_start.setEnabled(True)
            self.btn_record_stop.setEnabled(False)
            self.lbl_timer_status.setText("⚠️ Falha na gravação da amostra")
            self.lbl_timer_status.setStyleSheet("font-weight: 700; color: #ef4444;")
            QMessageBox.warning(self, "Falha na Gravação", f"Houve um problema durante a gravação:\n{error_string}")

    def _start_calibration_recording(self):
        try:
            if not self.camera or not self.camera.isActive():
                QMessageBox.warning(
                    self,
                    "Câmera Inativa",
                    "A câmera não está pronta para gravação. Verifique a conexão da webcam e clique no botão '🔄 Atualizar'.",
                )
                return

            temp_vid = str(Path(tempfile.gettempdir()) / f"avatar_calib_{int(time.time())}.mp4")
            self.recorded_video_path = temp_vid

            # Setup format with MPEG4 (tested and confirmed 100% working on Linux FFmpeg LGPL)
            media_format = QMediaFormat()
            media_format.setFileFormat(QMediaFormat.FileFormat.MPEG4)
            media_format.setVideoCodec(QMediaFormat.VideoCodec.MPEG4)
            if self.audio_input:
                media_format.setAudioCodec(QMediaFormat.AudioCodec.AAC)
            self.recorder.setMediaFormat(media_format)

            self.recorder.setOutputLocation(QUrl.fromLocalFile(temp_vid))
            self.recorder.record()

            self.is_recording = True
            self.record_start_time = time.time()
            self.calib_timer.start()

            if hasattr(self, "combo_duration"):
                self.combo_duration.setEnabled(False)
            self.btn_record_start.setEnabled(False)
            self.btn_record_stop.setEnabled(True)
            if self.target_record_duration >= 600:
                self.lbl_timer_status.setText("🔴 Gravando amostra livre (fale sua aula e clique em Parar)...")
            else:
                self.lbl_timer_status.setText(f"🔴 Gravando amostra de calibração ({int(self.target_record_duration)}s)...")
            self.lbl_timer_status.setStyleSheet("font-weight: 700; color: #ef4444;")
        except Exception as e:
            QMessageBox.critical(self, "Erro na Gravação", f"Falha ao iniciar gravação da câmera:\n{e}")

    def _on_timer_tick(self):
        if not self.is_recording:
            return
        elapsed = time.time() - self.record_start_time
        target_s = int(self.target_record_duration)
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60

        if target_s >= 600:
            self.lbl_timer_val.setText(f"{mins:02d}:{secs:02d} / Livre")
            self.progress_calib.setValue(min(100, int(((elapsed % 60) / 60.0) * 100)))
        else:
            pct = min(100, int((elapsed / self.target_record_duration) * 100))
            self.progress_calib.setValue(pct)
            t_m = target_s // 60
            t_s = target_s % 60
            self.lbl_timer_val.setText(f"{mins:02d}:{secs:02d} / {t_m:02d}:{t_s:02d}")

        if elapsed >= self.target_record_duration:
            self._stop_calibration_recording()

    def _stop_calibration_recording(self):
        self.calib_timer.stop()
        elapsed = time.time() - self.record_start_time if self.record_start_time > 0 else self.target_record_duration
        if self.is_recording:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.is_recording = False

        if hasattr(self, "combo_duration"):
            self.combo_duration.setEnabled(True)
        self.btn_record_start.setEnabled(True)
        self.btn_record_stop.setEnabled(False)
        self.lbl_timer_status.setText(f"✓ Gravação de {elapsed:.1f}s concluída com sucesso!")
        self.lbl_timer_status.setStyleSheet("font-weight: 700; color: #10b981;")

        # Allow 350ms for the recorder to finalize headers and flush to disk
        QTimer.singleShot(350, self._check_recorded_output)

    def _check_recorded_output(self):
        if self.recorded_video_path and os.path.exists(self.recorded_video_path) and os.path.getsize(self.recorded_video_path) > 1000:
            dur = get_video_duration(self.recorded_video_path)
            self.lbl_selected_video_status.setText(
                f"✓ Vídeo gravado pronto para calibração ({dur:.1f}s de movimentos capturados) - Clique em 'Processar e Salvar Clone'"
            )
            self.lbl_selected_video_status.setStyleSheet("color: #10b981; font-weight: 700;")
            # Advance to config tab automatically
            self.tabs.setCurrentIndex(1)
        else:
            self.lbl_selected_video_status.setText("Aviso: Verifique o arquivo de gravação ou use 'Importar Vídeo'.")
            self.lbl_selected_video_status.setStyleSheet("color: #f59e0b; font-size: 12px; font-weight: 600;")

    def _import_existing_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Vídeo Curto para Calibração do Clone",
            "",
            "Vídeos (*.mp4 *.mov *.webm *.mkv *.avi)",
        )
        if file_path:
            dur = get_video_duration(file_path)
            if dur <= 1.0:
                QMessageBox.warning(
                    self,
                    "Vídeo Muito Curto",
                    "O vídeo selecionado precisa ter pelo menos alguns segundos de duração com sua fala e imagem.",
                )
                return

            self.recorded_video_path = file_path
            self.lbl_selected_video_status.setText(
                f"✓ Vídeo importado: {Path(file_path).name} ({dur:.1f}s) - Pronto para salvar!"
            )
            self.lbl_selected_video_status.setStyleSheet("color: #10b981; font-weight: 700;")
            self.tabs.setCurrentIndex(1)

    # ----------------------------------------------------
    # SAVE & PROCESS CLONE
    # ----------------------------------------------------
    def _save_and_activate_clone(self):
        if not self.recorded_video_path or not os.path.exists(self.recorded_video_path):
            QMessageBox.warning(
                self,
                "Vídeo Necessário",
                "Por favor, grave o vídeo de 15 segundos na Etapa 1 ou importe um vídeo curto antes de salvar o clone.",
            )
            self.tabs.setCurrentIndex(0)
            return

        name = self.edit_clone_name.text().strip() or "Meu Clone IA"
        is_cloud = self.radio_cloud.isChecked()
        engine = "cloud" if is_cloud else "local"

        # Save config keys if cloud selected
        if is_cloud:
            el_key = self.edit_eleven_key.text().strip()
            rep_key = self.edit_replicate_key.text().strip()
            if el_key:
                set_elevenlabs_api_key(el_key)
            if rep_key:
                set_replicate_api_key(rep_key)

        preferred_voice = self.combo_local_voice.currentData() or "pt-BR-FranciscaNeural"
        set_avatar_engine(engine)

        try:
            self.btn_save_clone.setEnabled(False)
            self.btn_save_clone.setText("⏳ Processando rosto e timbre de voz...")

            clone_meta = create_clone(
                name=name,
                raw_video_path=self.recorded_video_path,
                engine=engine,
                preferred_voice=preferred_voice,
            )

            self._refresh_saved_clones_list()
            self.clone_updated.emit(clone_meta)

            QMessageBox.information(
                self,
                "Clone Criado com Sucesso!",
                f"🎉 Parabéns! O clone digital '{name}' foi calibrado e ativado!\n\n"
                f"• Motor Selecionado: {'🌐 Nuvem (ElevenLabs)' if is_cloud else '💻 Local Gratuito (Neural)'}\n"
                f"• Imagem facial e amostra de voz extraídas com sucesso.\n\n"
                f"Agora você pode gerar videoaulas automáticas fornecendo apenas o texto!",
            )
            self.tabs.setCurrentIndex(2)

        except Exception as e:
            QMessageBox.critical(self, "Erro ao Calibrar", f"Falha ao processar clone digital:\n{e}")
        finally:
            self.btn_save_clone.setEnabled(True)
            self.btn_save_clone.setText("💾 Processar e Salvar Clone Digital")

    # ----------------------------------------------------
    # CLONE MANAGEMENT
    # ----------------------------------------------------
    def _refresh_saved_clones_list(self):
        self.list_clones_widget.clear()
        clones = list_clones()
        active = get_active_clone()
        active_id = active.get("id") if active else ""

        for c in clones:
            cid = c.get("id", "")
            cname = c.get("name", "Clone")
            ceng = c.get("engine", "local")
            eng_badge = "🌐 Nuvem" if ceng == "cloud" else "💻 Local"
            created = c.get("created_at", "")
            is_act = " [★ ATIVO]" if cid == active_id else ""

            item_text = f"🎭 {cname}{is_act}\n   Motor: {eng_badge} | Criado em: {created}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, cid)
            self.list_clones_widget.addItem(item)

    def _set_selected_clone_active(self):
        item = self.list_clones_widget.currentItem()
        if not item:
            QMessageBox.warning(self, "Aviso", "Selecione um clone na lista.")
            return
        cid = item.data(Qt.UserRole)
        set_active_clone_id(cid)
        clone = get_clone(cid)
        if clone:
            self.clone_updated.emit(clone)
            self._refresh_saved_clones_list()
            QMessageBox.information(self, "Clone Ativado", f"O clone '{clone.get('name')}' agora é o clone ativo!")

    def _delete_selected_clone(self):
        item = self.list_clones_widget.currentItem()
        if not item:
            QMessageBox.warning(self, "Aviso", "Selecione um clone na lista.")
            return
        cid = item.data(Qt.UserRole)
        clone = get_clone(cid)
        name = clone.get("name", "este clone") if clone else "este clone"

        reply = QMessageBox.question(
            self,
            "Confirmar Exclusão",
            f"Tem certeza de que deseja excluir {name}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            delete_clone(cid)
            self._refresh_saved_clones_list()
            act = get_active_clone()
            if act:
                self.clone_updated.emit(act)

    def _cleanup_media(self):
        if self.is_recording:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.is_recording = False
        if self.camera:
            try:
                self.camera.errorOccurred.disconnect()
            except Exception:
                pass
            try:
                self.camera.activeChanged.disconnect()
            except Exception:
                pass
            try:
                self.camera.stop()
            except Exception:
                pass
            self.capture_session.setCamera(None)
            self.capture_session.setVideoOutput(None)
            self.camera.deleteLater()
            self.camera = None
        if self.audio_input:
            self.capture_session.setAudioInput(None)
            self.audio_input.deleteLater()
            self.audio_input = None
        self._media_initialized = False

    def reject(self):
        self._cleanup_media()
        super().reject()

    def accept(self):
        self._cleanup_media()
        super().accept()

    def closeEvent(self, event):
        self._cleanup_media()
        super().closeEvent(event)
