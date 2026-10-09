"""Panel builders for RecordClassView (setup / studio / result screens).

Extracted verbatim from the view: each builder receives the view instance
as ``view`` and wires widgets onto it, exactly as the former methods did.
"""

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
from app.ui.workers.class_render_workers import (
    ClassVideoRenderWorker,
    CloneLessonRenderWorker,
    TutorialPostProcessWorker,
)


logger = logging.getLogger(__name__)


def build_setup_view(view) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(28, 20, 28, 20)
    layout.setSpacing(14)

    # Nav bar
    nav = QHBoxLayout()
    btn_back = QPushButton("← Voltar ao Menu")
    btn_back.setCursor(Qt.PointingHandCursor)
    btn_back.clicked.connect(view.back_to_home.emit)

    title = QLabel("🎓 Gravar Aula - Configuração Inicial")
    title.setStyleSheet("font-size: 16px; font-weight: 700; color: #a78bfa;")
    nav.addWidget(btn_back)
    nav.addWidget(title)
    nav.addStretch()
    layout.addLayout(nav)

    # Step Navigation Bar (Clickable screens without scrollbars)
    view.step_bar = QHBoxLayout()
    view.step_bar.setSpacing(6)
    view.step_buttons = []
    step_labels = [
        "1. 📝 Info & Formato",
        "2. 🖥️ Apresentador & Slides",
        "3. 🎥 Dispositivos",
        "4. 📜 Roteiro",
        "5. 🎬 Gravação",
    ]
    for idx, text in enumerate(step_labels):
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _, i=idx: view._switch_step(i))
        view.step_bar.addWidget(btn)
        view.step_buttons.append(btn)
    layout.addLayout(view.step_bar)

    view.step_stack = QStackedWidget()

    # ====================================================
    # PAGE 1: Informações da Aula, Formato de Destino & Vinhetas
    # ====================================================
    scroll_p1 = QScrollArea()
    scroll_p1.setWidgetResizable(True)
    scroll_p1.setFrameShape(QFrame.NoFrame)
    scroll_p1.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    page1 = QWidget()
    page1.setStyleSheet("background: transparent;")
    p1_lay = QVBoxLayout(page1)
    p1_lay.setContentsMargins(0, 4, 10, 4)
    p1_lay.setSpacing(14)

    # Card 1: Informações Básicas da Aula
    card_info = QFrame()
    card_info.setProperty("class", "card")
    ci_layout = QVBoxLayout(card_info)
    ci_layout.setContentsMargins(18, 16, 18, 16)
    ci_layout.setSpacing(12)

    ci_title = QLabel("1. Informações Básicas da Aula")
    ci_title.setProperty("class", "section-title")
    ci_layout.addWidget(ci_title)

    grid_info = QHBoxLayout()
    grid_info.setSpacing(16)

    box_title = QVBoxLayout()
    lbl_t = QLabel("Título da Aula:")
    view.edit_title = QLineEdit()
    view.edit_title.setPlaceholderText("Ex: Aula 01 - Introdução aos Conceitos...")
    box_title.addWidget(lbl_t)
    box_title.addWidget(view.edit_title)

    box_prof = QVBoxLayout()
    lbl_p = QLabel("Nome do Professor(a):")
    view.edit_teacher = QLineEdit()
    view.edit_teacher.setPlaceholderText("Ex: Prof. Kika Magalhães")
    box_prof.addWidget(lbl_p)
    box_prof.addWidget(view.edit_teacher)

    grid_info.addLayout(box_title, stretch=2)
    grid_info.addLayout(box_prof, stretch=1)
    ci_layout.addLayout(grid_info)

    # Cover Image Row
    cover_row = QHBoxLayout()
    cover_row.setSpacing(12)

    view.lbl_cover_status = QLabel("Nenhuma imagem de capa selecionada (Opcional)")
    view.lbl_cover_status.setStyleSheet("color: #94a3b8; font-size: 12px;")

    btn_pick_cover = QPushButton("Escolher Capa (16:9 / 1280x720)...")
    btn_pick_cover.setCursor(Qt.PointingHandCursor)
    btn_pick_cover.clicked.connect(view._pick_cover_image)

    btn_gen_cover = QPushButton("✨ Gerar Capa com IA...")
    btn_gen_cover.setCursor(Qt.PointingHandCursor)
    btn_gen_cover.setStyleSheet("background: #4338ca; color: #ffffff; font-weight: 600; padding: 5px 12px; border-radius: 6px;")
    btn_gen_cover.clicked.connect(view._generate_cover_ai)

    lbl_yt_hint = QLabel("💡 A capa será usada na miniatura e na vinheta de abertura automática!")
    lbl_yt_hint.setStyleSheet("color: #38bdf8; font-size: 11px;")

    cover_row.addWidget(btn_pick_cover)
    cover_row.addWidget(btn_gen_cover)
    cover_row.addWidget(view.lbl_cover_status)
    cover_row.addStretch()
    ci_layout.addLayout(cover_row)
    ci_layout.addWidget(lbl_yt_hint)
    p1_lay.addWidget(card_info)

    # Card 2: Formato de Publicação do Vídeo
    card_format_pub = QFrame()
    card_format_pub.setProperty("class", "card")
    cfp_layout = QVBoxLayout(card_format_pub)
    cfp_layout.setContentsMargins(18, 16, 18, 16)
    cfp_layout.setSpacing(12)

    cfp_title = QLabel("2. Formato de Publicação do Vídeo")
    cfp_title.setProperty("class", "section-title")
    cfp_sub = QLabel("Escolha a plataforma de destino para adaptar a proporção e o enquadramento:")
    cfp_sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
    cfp_layout.addWidget(cfp_title)
    cfp_layout.addWidget(cfp_sub)

    fmt_cards_layout = QHBoxLayout()
    fmt_cards_layout.setSpacing(12)

    # YouTube Card
    view.card_fmt_yt = QFrame()
    view.card_fmt_yt.setCursor(Qt.PointingHandCursor)
    cf_yt_lay = QVBoxLayout(view.card_fmt_yt)
    cf_yt_lay.setContentsMargins(14, 12, 14, 12)
    cf_yt_lay.setSpacing(6)

    view.radio_fmt_yt = QRadioButton("📺 YouTube Widescreen (16:9)")
    view.radio_fmt_yt.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
    view.radio_fmt_yt.setChecked(True)

    lbl_yt_res = QLabel("1920x1080 Full HD Horizontal")
    lbl_yt_res.setStyleSheet("color: #cbd5e1; font-size: 11px; font-weight: 600; margin-left: 22px;")

    lbl_yt_desc = QLabel("Padrão para computadores, TVs e canais do YouTube. Slides em tela cheia com avatar PIP no canto inferior direito.")
    lbl_yt_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    lbl_yt_desc.setWordWrap(True)

    cf_yt_lay.addWidget(view.radio_fmt_yt)
    cf_yt_lay.addWidget(lbl_yt_res)
    cf_yt_lay.addWidget(lbl_yt_desc)
    cf_yt_lay.addStretch()

    # YouTube Shorts Card
    view.card_fmt_shorts = QFrame()
    view.card_fmt_shorts.setCursor(Qt.PointingHandCursor)
    cf_sh_lay = QVBoxLayout(view.card_fmt_shorts)
    cf_sh_lay.setContentsMargins(14, 12, 14, 12)
    cf_sh_lay.setSpacing(6)

    view.radio_fmt_shorts = QRadioButton("🔴 YouTube Shorts (9:16)")
    view.radio_fmt_shorts.setStyleSheet("font-weight: 700; color: #f87171; font-size: 13px;")

    lbl_sh_res = QLabel("1080x1920 Vertical Dinâmico")
    lbl_sh_res.setStyleSheet("color: #cbd5e1; font-size: 11px; font-weight: 600; margin-left: 22px;")

    lbl_sh_desc = QLabel("Vídeo vertical para Shorts. Fundo dinâmico desfocado, slide no topo, avatar central e legendas acima da barra de ações.")
    lbl_sh_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    lbl_sh_desc.setWordWrap(True)

    cf_sh_lay.addWidget(view.radio_fmt_shorts)
    cf_sh_lay.addWidget(lbl_sh_res)
    cf_sh_lay.addWidget(lbl_sh_desc)
    cf_sh_lay.addStretch()

    # Instagram Reels Card
    view.card_fmt_reels = QFrame()
    view.card_fmt_reels.setCursor(Qt.PointingHandCursor)
    cf_re_lay = QVBoxLayout(view.card_fmt_reels)
    cf_re_lay.setContentsMargins(14, 12, 14, 12)
    cf_re_lay.setSpacing(6)

    view.radio_fmt_reels = QRadioButton("🟣 Instagram Reels (9:16)")
    view.radio_fmt_reels.setStyleSheet("font-weight: 700; color: #c084fc; font-size: 13px;")

    lbl_re_res = QLabel("1080x1920 com Safe Zone 4:5")
    lbl_re_res.setStyleSheet("color: #cbd5e1; font-size: 11px; font-weight: 600; margin-left: 22px;")

    lbl_re_desc = QLabel("Vídeo vertical com slide e avatar concentrados no centro (área 1080x1350) para nunca cortar na grade ou no feed do Instagram.")
    lbl_re_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    lbl_re_desc.setWordWrap(True)

    cf_re_lay.addWidget(view.radio_fmt_reels)
    cf_re_lay.addWidget(lbl_re_res)
    cf_re_lay.addWidget(lbl_re_desc)
    cf_re_lay.addStretch()

    fmt_cards_layout.addWidget(view.card_fmt_yt, stretch=1)
    fmt_cards_layout.addWidget(view.card_fmt_shorts, stretch=1)
    fmt_cards_layout.addWidget(view.card_fmt_reels, stretch=1)
    cfp_layout.addLayout(fmt_cards_layout)

    view.format_pub_group = QButtonGroup(view)
    view.format_pub_group.addButton(view.radio_fmt_yt)
    view.format_pub_group.addButton(view.radio_fmt_shorts)
    view.format_pub_group.addButton(view.radio_fmt_reels)

    view.card_fmt_yt.mousePressEvent = lambda e: view.radio_fmt_yt.setChecked(True)
    view.card_fmt_shorts.mousePressEvent = lambda e: view.radio_fmt_shorts.setChecked(True)
    view.card_fmt_reels.mousePressEvent = lambda e: view.radio_fmt_reels.setChecked(True)

    view.radio_fmt_yt.toggled.connect(view._on_video_format_changed)
    view.radio_fmt_shorts.toggled.connect(view._on_video_format_changed)
    view.radio_fmt_reels.toggled.connect(view._on_video_format_changed)

    # Vertical Layout Style Panel (Shorts & Reels)
    view.box_vert_layout = QFrame()
    view.box_vert_layout.setStyleSheet(
        "background: #0b0f19; border: 1.5px solid #3b82f6; border-radius: 8px; margin-top: 10px;"
    )
    bvl_lay = QVBoxLayout(view.box_vert_layout)
    bvl_lay.setContentsMargins(14, 12, 14, 12)
    bvl_lay.setSpacing(8)

    lbl_bvl_title = QLabel("📱 Estilo Visual nos Vídeos Verticais (Shorts & Reels):")
    lbl_bvl_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #60a5fa;")
    lbl_bvl_sub = QLabel("Experimente os dois jeitos para descobrir qual estilo você prefere para o seu público:")
    lbl_bvl_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
    bvl_lay.addWidget(lbl_bvl_title)
    bvl_lay.addWidget(lbl_bvl_sub)

    v_opts_row = QHBoxLayout()
    v_opts_row.setSpacing(14)

    # Option A: Presenter Spotlight (Sem slides)
    box_opt_pres = QVBoxLayout()
    box_opt_pres.setSpacing(3)
    view.radio_vlayout_presenter = QRadioButton("👤 Foco no Apresentador & Legendas (Sem Slides)")
    view.radio_vlayout_presenter.setStyleSheet("font-weight: 700; color: #ffffff; font-size: 12px;")
    view.radio_vlayout_presenter.setChecked(True)
    lbl_vlp_desc = QLabel("Destaque total para o clone ou sua imagem na tela vertical com fundo cinematográfico e legendas dinâmicas. Ideal para vídeos curtos e reels virais.")
    lbl_vlp_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    lbl_vlp_desc.setWordWrap(True)
    box_opt_pres.addWidget(view.radio_vlayout_presenter)
    box_opt_pres.addWidget(lbl_vlp_desc)

    # Option B: Split with Slides (Com slides)
    box_opt_split = QVBoxLayout()
    box_opt_split.setSpacing(3)
    view.radio_vlayout_split = QRadioButton("📊 Dividido com Slides (Slide no Topo + Apresentador)")
    view.radio_vlayout_split.setStyleSheet("font-weight: 700; color: #ffffff; font-size: 12px;")
    lbl_vls_desc = QLabel("Exibe o slide na metade superior e o apresentador embaixo. Ideal quando o conteúdo visual e tópicos do slide forem indispensáveis.")
    lbl_vls_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    lbl_vls_desc.setWordWrap(True)
    box_opt_split.addWidget(view.radio_vlayout_split)
    box_opt_split.addWidget(lbl_vls_desc)

    v_opts_row.addLayout(box_opt_pres, stretch=1)
    v_opts_row.addLayout(box_opt_split, stretch=1)
    bvl_lay.addLayout(v_opts_row)

    view.vlayout_group = QButtonGroup(view)
    view.vlayout_group.addButton(view.radio_vlayout_presenter)
    view.vlayout_group.addButton(view.radio_vlayout_split)

    view.radio_vlayout_presenter.toggled.connect(view._on_vertical_layout_changed)
    view.radio_vlayout_split.toggled.connect(view._on_vertical_layout_changed)

    cfp_layout.addWidget(view.box_vert_layout)
    view.box_vert_layout.hide()  # hidden initially because default is youtube 16:9

    p1_lay.addWidget(card_format_pub)

    # Card 3: Vinhetas de Abertura & Encerramento
    card_vinhetas = QFrame()
    card_vinhetas.setProperty("class", "card")
    cv_layout = QVBoxLayout(card_vinhetas)
    cv_layout.setContentsMargins(18, 16, 18, 16)
    cv_layout.setSpacing(12)

    cv_title = QLabel("3. Vinhetas de Abertura & Encerramento")
    cv_title.setProperty("class", "section-title")
    cv_sub = QLabel("Configure como a sua aula deve começar e finalizar:")
    cv_sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
    cv_layout.addWidget(cv_title)
    cv_layout.addWidget(cv_sub)

    vinh_cols = QHBoxLayout()
    vinh_cols.setSpacing(16)

    # Left Column: Abertura (Intro)
    box_intro = QFrame()
    box_intro.setStyleSheet("background: #0f172a; border: 1.5px solid #334155; border-radius: 10px;")
    bi_lay = QVBoxLayout(box_intro)
    bi_lay.setContentsMargins(14, 12, 14, 12)
    bi_lay.setSpacing(8)

    lbl_bi_title = QLabel("🎬 Vinheta de Abertura (Intro)")
    lbl_bi_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #38bdf8;")
    bi_lay.addWidget(lbl_bi_title)

    view.radio_intro_auto = QRadioButton("✨ Cartela Automática da Aula")
    view.radio_intro_auto.setStyleSheet("font-weight: 600; color: #f8fafc;")
    view.radio_intro_auto.setChecked(True)
    lbl_intro_auto_d = QLabel("Gera vinheta moderna de 3.5s com capa, título e professor.")
    lbl_intro_auto_d.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    bi_lay.addWidget(view.radio_intro_auto)
    bi_lay.addWidget(lbl_intro_auto_d)

    view.radio_intro_custom = QRadioButton("📁 Arquivo de Vídeo MP4 / MOV...")
    view.radio_intro_custom.setStyleSheet("font-weight: 600; color: #f8fafc;")
    bi_lay.addWidget(view.radio_intro_custom)

    row_intro_pick = QHBoxLayout()
    row_intro_pick.setContentsMargins(22, 0, 0, 0)
    row_intro_pick.setSpacing(8)
    btn_pick_intro = QPushButton("Escolher Vídeo...")
    btn_pick_intro.setCursor(Qt.PointingHandCursor)
    btn_pick_intro.setStyleSheet("background: #1e293b; color: #38bdf8; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
    btn_pick_intro.clicked.connect(view._pick_custom_intro)
    view.lbl_intro_file = QLabel("Nenhum arquivo selecionado")
    view.lbl_intro_file.setStyleSheet("color: #94a3b8; font-size: 11px;")
    row_intro_pick.addWidget(btn_pick_intro)
    row_intro_pick.addWidget(view.lbl_intro_file, stretch=1)
    bi_lay.addLayout(row_intro_pick)

    view.radio_intro_none = QRadioButton("🚫 Sem Vinheta de Abertura")
    view.radio_intro_none.setStyleSheet("font-weight: 600; color: #f8fafc;")
    lbl_intro_none_d = QLabel("Inicia a aula direto no primeiro slide sem introdução.")
    lbl_intro_none_d.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    bi_lay.addWidget(view.radio_intro_none)
    bi_lay.addWidget(lbl_intro_none_d)
    bi_lay.addStretch()

    view.group_intro = QButtonGroup(view)
    view.group_intro.addButton(view.radio_intro_auto)
    view.group_intro.addButton(view.radio_intro_custom)
    view.group_intro.addButton(view.radio_intro_none)
    view.radio_intro_auto.toggled.connect(view._on_intro_mode_changed)
    view.radio_intro_custom.toggled.connect(view._on_intro_mode_changed)
    view.radio_intro_none.toggled.connect(view._on_intro_mode_changed)

    # Right Column: Encerramento (Outro)
    box_outro = QFrame()
    box_outro.setStyleSheet("background: #0f172a; border: 1.5px solid #334155; border-radius: 10px;")
    bo_lay = QVBoxLayout(box_outro)
    bo_lay.setContentsMargins(14, 12, 14, 12)
    bo_lay.setSpacing(8)

    lbl_bo_title = QLabel("🏁 Vinheta de Encerramento (Final)")
    lbl_bo_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #c084fc;")
    bo_lay.addWidget(lbl_bo_title)

    view.radio_outro_auto = QRadioButton("✨ Cartela Final Automática")
    view.radio_outro_auto.setStyleSheet("font-weight: 600; color: #f8fafc;")
    view.radio_outro_auto.setChecked(True)
    lbl_outro_auto_d = QLabel("Gera tela final de 3.5s com 'Obrigado por assistir!' e chamada para inscrição.")
    lbl_outro_auto_d.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    bo_lay.addWidget(view.radio_outro_auto)
    bo_lay.addWidget(lbl_outro_auto_d)

    view.radio_outro_custom = QRadioButton("📁 Arquivo de Vídeo MP4 / MOV...")
    view.radio_outro_custom.setStyleSheet("font-weight: 600; color: #f8fafc;")
    bo_lay.addWidget(view.radio_outro_custom)

    row_outro_pick = QHBoxLayout()
    row_outro_pick.setContentsMargins(22, 0, 0, 0)
    row_outro_pick.setSpacing(8)
    btn_pick_outro = QPushButton("Escolher Vídeo...")
    btn_pick_outro.setCursor(Qt.PointingHandCursor)
    btn_pick_outro.setStyleSheet("background: #1e293b; color: #c084fc; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
    btn_pick_outro.clicked.connect(view._pick_custom_outro)
    view.lbl_outro_file = QLabel("Nenhum arquivo selecionado")
    view.lbl_outro_file.setStyleSheet("color: #94a3b8; font-size: 11px;")
    row_outro_pick.addWidget(btn_pick_outro)
    row_outro_pick.addWidget(view.lbl_outro_file, stretch=1)
    bo_lay.addLayout(row_outro_pick)

    view.radio_outro_none = QRadioButton("🚫 Sem Vinheta de Encerramento")
    view.radio_outro_none.setStyleSheet("font-weight: 600; color: #f8fafc;")
    lbl_outro_none_d = QLabel("Finaliza o vídeo assim que o conteúdo principal terminar.")
    lbl_outro_none_d.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
    bo_lay.addWidget(view.radio_outro_none)
    bo_lay.addWidget(lbl_outro_none_d)
    bo_lay.addStretch()

    view.group_outro = QButtonGroup(view)
    view.group_outro.addButton(view.radio_outro_auto)
    view.group_outro.addButton(view.radio_outro_custom)
    view.group_outro.addButton(view.radio_outro_none)
    view.radio_outro_auto.toggled.connect(view._on_outro_mode_changed)
    view.radio_outro_custom.toggled.connect(view._on_outro_mode_changed)
    view.radio_outro_none.toggled.connect(view._on_outro_mode_changed)

    vinh_cols.addWidget(box_intro, stretch=1)
    vinh_cols.addWidget(box_outro, stretch=1)
    cv_layout.addLayout(vinh_cols)

    p1_lay.addWidget(card_vinhetas)
    p1_lay.addStretch()

    s1_nav = QHBoxLayout()
    s1_nav.addStretch()
    btn_next_s1 = QPushButton("Continuar para Apresentador & Slides ▶")
    btn_next_s1.setProperty("class", "primary")
    btn_next_s1.setCursor(Qt.PointingHandCursor)
    btn_next_s1.clicked.connect(lambda: view._switch_step(1))
    s1_nav.addWidget(btn_next_s1)
    p1_lay.addLayout(s1_nav)

    scroll_p1.setWidget(page1)

    # ====================================================
    # PAGE 2: Formato Visual & Apresentador (Câmera vs Clone)
    # ====================================================
    page2 = QWidget()
    p2_lay = QVBoxLayout(page2)
    p2_lay.setContentsMargins(0, 8, 0, 0)
    p2_lay.setSpacing(12)

    # Card 1: Formato Visual
    card_format = QFrame()
    card_format.setProperty("class", "card")
    cf_layout = QVBoxLayout(card_format)
    cf_layout.setContentsMargins(18, 14, 18, 14)
    cf_layout.setSpacing(10)

    lbl_f_title = QLabel("1. Formato Visual da Aula")
    lbl_f_title.setProperty("class", "section-title")
    cf_layout.addWidget(lbl_f_title)

    format_row = QHBoxLayout()
    view.radio_slides = QRadioButton("📊 Apresentação de Slides (PDF)")
    view.radio_slides.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
    view.radio_slides.setCursor(Qt.PointingHandCursor)
    view.radio_slides.setChecked(True)
    view.radio_slides.toggled.connect(view._on_format_changed)

    view.radio_screen = QRadioButton("🖥️ Gravação da Tela do Computador (Tutorial de Aplicativo)")
    view.radio_screen.setStyleSheet("font-weight: 700; color: #a78bfa; font-size: 13px;")
    view.radio_screen.setCursor(Qt.PointingHandCursor)

    view.format_group = QButtonGroup(view)
    view.format_group.addButton(view.radio_slides)
    view.format_group.addButton(view.radio_screen)

    format_row.addWidget(view.radio_slides)
    format_row.addWidget(view.radio_screen)
    format_row.addStretch()
    cf_layout.addLayout(format_row)

    view.lbl_format_desc = QLabel(
        "Apresente seus slides em PDF com narração sincronizada."
    )
    view.lbl_format_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
    cf_layout.addWidget(view.lbl_format_desc)

    # Slides Picker (visible when in slides mode)
    view.card_slides = QFrame()
    view.card_slides.setStyleSheet("background: #0f172a; border-radius: 8px; border: 1px dashed #334155;")
    cs_layout = QHBoxLayout(view.card_slides)
    cs_layout.setContentsMargins(12, 8, 12, 8)
    cs_layout.setSpacing(12)

    btn_pick_pdf = QPushButton("📁 Selecionar Arquivo PDF da Aula...")
    btn_pick_pdf.setProperty("class", "primary")
    btn_pick_pdf.setCursor(Qt.PointingHandCursor)
    btn_pick_pdf.clicked.connect(view._pick_pdf)

    view.lbl_pdf_status = QLabel("Nenhum arquivo PDF carregado.")
    view.lbl_pdf_status.setStyleSheet("color: #94a3b8; font-weight: 500;")

    cs_layout.addWidget(btn_pick_pdf)
    cs_layout.addWidget(view.lbl_pdf_status)
    cs_layout.addStretch()
    cf_layout.addWidget(view.card_slides)

    # Resolution selector for screen tutorial mode
    view.box_screen_res = QWidget()
    bs_layout = QHBoxLayout(view.box_screen_res)
    bs_layout.setContentsMargins(0, 0, 0, 0)
    lbl_sres = QLabel("Resolução da Captura da Tela:")
    view.combo_screen_res = QComboBox()
    view.combo_screen_res.addItem("Tela Inteira (1920x1080 Full HD)", "1920x1080")
    view.combo_screen_res.addItem("Resolução HD (1280x720)", "1280x720")
    bs_layout.addWidget(lbl_sres)
    bs_layout.addWidget(view.combo_screen_res)
    bs_layout.addStretch()
    cf_layout.addWidget(view.box_screen_res)
    view.box_screen_res.hide()

    p2_lay.addWidget(card_format)

    # Card 2: Apresentador da Aula (Câmera Real vs Clone IA)
    view.box_presenter_mode = QFrame()
    view.box_presenter_mode.setObjectName("boxPresenterMode")
    view.box_presenter_mode.setStyleSheet("""
        QFrame#boxPresenterMode {
            background-color: #161922;
            border: 1.5px solid #2d3748;
            border-radius: 12px;
        }
    """)
    bpm_layout = QVBoxLayout(view.box_presenter_mode)
    bpm_layout.setContentsMargins(18, 14, 18, 14)
    bpm_layout.setSpacing(10)

    lbl_pm_title = QLabel("2. Como você deseja apresentar esta aula?")
    lbl_pm_title.setProperty("class", "section-title")
    bpm_layout.addWidget(lbl_pm_title)

    # Option A: Câmera Real / Ao Vivo Selection Card
    view.card_pres_live = QFrame()
    view.card_pres_live.setObjectName("cardPresLive")
    view.card_pres_live.setCursor(Qt.PointingHandCursor)
    cpl_layout = QVBoxLayout(view.card_pres_live)
    cpl_layout.setContentsMargins(14, 10, 14, 10)
    cpl_layout.setSpacing(3)

    view.radio_pres_live = QRadioButton("📹 Gravar com Câmera Real / Ao Vivo")
    view.radio_pres_live.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
    view.radio_pres_live.setCursor(Qt.PointingHandCursor)
    view.radio_pres_live.setChecked(True)
    view.radio_pres_live.toggled.connect(view._on_presenter_mode_changed)

    desc_pres_live = QLabel("Grave suas aulas com imagem real pela webcam (Picture-in-Picture) e microfone em tempo real.")
    desc_pres_live.setStyleSheet("font-size: 11px; color: #94a3b8; margin-left: 24px;")
    desc_pres_live.setWordWrap(True)

    cpl_layout.addWidget(view.radio_pres_live)
    cpl_layout.addWidget(desc_pres_live)
    view.card_pres_live.mousePressEvent = lambda e: view.radio_pres_live.setChecked(True)
    bpm_layout.addWidget(view.card_pres_live)

    # Option B: Clone Digital (Avatar IA) Selection Card
    view.card_pres_clone = QFrame()
    view.card_pres_clone.setObjectName("cardPresClone")
    view.card_pres_clone.setCursor(Qt.PointingHandCursor)
    cpc_layout = QVBoxLayout(view.card_pres_clone)
    cpc_layout.setContentsMargins(14, 10, 14, 10)
    cpc_layout.setSpacing(3)

    view.radio_pres_clone = QRadioButton("✨ Apresentar com Meu Clone Digital (Avatar IA - Sem precisar se filmar)")
    view.radio_pres_clone.setStyleSheet("font-size: 13px; font-weight: 700; color: #c084fc;")
    view.radio_pres_clone.setCursor(Qt.PointingHandCursor)

    desc_pres_clone = QLabel("A IA fala com a sua voz e anima seu rosto perfeitamente sincronizado aos slides. Não precisa se filmar!")
    desc_pres_clone.setStyleSheet("font-size: 11px; color: #cbd5e1; margin-left: 24px;")
    desc_pres_clone.setWordWrap(True)

    cpc_layout.addWidget(view.radio_pres_clone)
    cpc_layout.addWidget(desc_pres_clone)
    view.card_pres_clone.mousePressEvent = lambda e: view.radio_pres_clone.setChecked(True)
    bpm_layout.addWidget(view.card_pres_clone)

    view.presenter_group = QButtonGroup(view)
    view.presenter_group.addButton(view.radio_pres_live)
    view.presenter_group.addButton(view.radio_pres_clone)

    # Clone Digital Status & Controls Card inside presenter box
    view.card_clone_status = QFrame()
    view.card_clone_status.setStyleSheet(
        "background: #1e1b4b; border: 1.5px solid #6366f1; border-radius: 8px; padding: 8px;"
    )
    ccs_layout = QHBoxLayout(view.card_clone_status)
    ccs_layout.setContentsMargins(12, 8, 12, 8)
    ccs_layout.setSpacing(12)

    view.lbl_clone_face = QLabel("🎭")
    view.lbl_clone_face.setStyleSheet("font-size: 30px; background: #0f172a; border-radius: 24px; border: 1px solid #4338ca;")
    view.lbl_clone_face.setFixedSize(48, 48)
    view.lbl_clone_face.setAlignment(Qt.AlignCenter)

    clone_info_v = QVBoxLayout()
    clone_info_v.setSpacing(2)
    view.lbl_clone_name = QLabel("Meu Clone Digital")
    view.lbl_clone_name.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
    view.lbl_clone_engine = QLabel("Motor: Local Gratuito (Neural Edge-TTS)")
    view.lbl_clone_engine.setStyleSheet("font-size: 11px; color: #a5b4fc;")
    clone_info_v.addWidget(view.lbl_clone_name)
    clone_info_v.addWidget(view.lbl_clone_engine)

    view.btn_open_calibration = QPushButton("🎭 Calibrar / Gerenciar Clone...")
    view.btn_open_calibration.setCursor(Qt.PointingHandCursor)
    view.btn_open_calibration.setStyleSheet(
        "background: #4338ca; color: #ffffff; font-weight: 700; font-size: 12px; padding: 8px 16px; border-radius: 6px;"
    )
    view.btn_open_calibration.clicked.connect(view._open_clone_calibration)

    ccs_layout.addWidget(view.lbl_clone_face)
    ccs_layout.addLayout(clone_info_v)
    ccs_layout.addStretch()
    ccs_layout.addWidget(view.btn_open_calibration)

    bpm_layout.addWidget(view.card_clone_status)
    view.card_clone_status.hide()

    p2_lay.addWidget(view.box_presenter_mode)
    p2_lay.addStretch()

    s2_nav = QHBoxLayout()
    btn_prev_s2 = QPushButton("◀ Voltar para Informações")
    btn_prev_s2.setCursor(Qt.PointingHandCursor)
    btn_prev_s2.clicked.connect(lambda: view._switch_step(0))

    btn_next_s2 = QPushButton("Continuar para Câmera & Microfone ▶")
    btn_next_s2.setProperty("class", "primary")
    btn_next_s2.setCursor(Qt.PointingHandCursor)
    btn_next_s2.clicked.connect(lambda: view._switch_step(2))

    s2_nav.addWidget(btn_prev_s2)
    s2_nav.addStretch()
    s2_nav.addWidget(btn_next_s2)
    p2_lay.addLayout(s2_nav)

    # ====================================================
    # PAGE 3: Câmera & Microfone (Dispositivos)
    # ====================================================
    page3 = QWidget()
    p3_lay = QVBoxLayout(page3)
    p3_lay.setContentsMargins(0, 8, 0, 0)
    p3_lay.setSpacing(12)

    view.card_dev = QFrame()
    view.card_dev.setProperty("class", "card")
    cd_layout = QVBoxLayout(view.card_dev)
    cd_layout.setContentsMargins(18, 16, 18, 16)
    cd_layout.setSpacing(14)

    cd_title = QLabel("3. Dispositivos de Gravação (Câmera & Microfone)")
    cd_title.setProperty("class", "section-title")
    cd_layout.addWidget(cd_title)

    dev_grid = QHBoxLayout()
    dev_grid.setSpacing(18)

    # Mic
    mic_box = QVBoxLayout()
    lbl_mic = QLabel("Microfone de Gravação:")
    view.combo_mics = QComboBox()
    audio_devs = QMediaDevices.audioInputs()
    if audio_devs:
        for d in audio_devs:
            view.combo_mics.addItem(d.description(), d)
    else:
        view.combo_mics.addItem("Microfone Padrão do Sistema", None)
    mic_box.addWidget(lbl_mic)
    mic_box.addWidget(view.combo_mics)

    # Cam
    cam_box = QVBoxLayout()
    view.chk_enable_camera = QCheckBox("Habilitar Câmera / Webcam")
    view.chk_enable_camera.setStyleSheet("font-weight: 600; color: #f8fafc;")
    view.chk_enable_camera.setChecked(False)
    view.chk_enable_camera.setToolTip("Desmarque para gravar a aula mostrando apenas os slides em tela cheia com a narração.")

    cam_hdr = QHBoxLayout()
    lbl_cam = QLabel("Dispositivo de Câmera:")
    btn_refresh_cams = QPushButton("🔄 Atualizar")
    btn_refresh_cams.setCursor(Qt.PointingHandCursor)
    btn_refresh_cams.setToolTip("Atualizar lista de câmeras conectadas")
    btn_refresh_cams.setStyleSheet("background: #1e293b; color: #38bdf8; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px;")
    btn_refresh_cams.clicked.connect(view._refresh_audio_and_video_devices)
    cam_hdr.addWidget(lbl_cam)
    cam_hdr.addStretch()
    cam_hdr.addWidget(btn_refresh_cams)

    view.combo_cams = QComboBox()
    view.combo_cams.setEnabled(False)

    def _on_cam_toggled(checked: bool):
        view.combo_cams.setEnabled(checked)
        if checked:
            view._refresh_audio_and_video_devices()

    view.chk_enable_camera.toggled.connect(_on_cam_toggled)

    cam_box.addWidget(view.chk_enable_camera)
    cam_box.addLayout(cam_hdr)
    cam_box.addWidget(view.combo_cams)

    dev_grid.addLayout(mic_box, stretch=1)
    dev_grid.addLayout(cam_box, stretch=1)
    cd_layout.addLayout(dev_grid)
    p3_lay.addWidget(view.card_dev)

    # Informative hint when Clone is active
    view.card_clone_dev_hint = QFrame()
    view.card_clone_dev_hint.setStyleSheet(
        "background: #1e1b4b; border: 1.5px solid #6366f1; border-radius: 10px; padding: 14px;"
    )
    ccdh_layout = QVBoxLayout(view.card_clone_dev_hint)
    ccdh_layout.setSpacing(6)
    lbl_hint_title = QLabel("✨ Modo Clone Digital IA Ativo")
    lbl_hint_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #c084fc;")
    lbl_hint_desc = QLabel(
        "Como você escolheu apresentar a aula com o seu Clone Digital IA, a sua webcam física "
        "não será ligada durante a aula. A IA gerará a animação do seu rosto e a fala com sua voz clonada.\n"
        "Se ainda não gravou sua amostra de 15 segundos ou deseja trocar o avatar, use o botão abaixo:"
    )
    lbl_hint_desc.setStyleSheet("color: #cbd5e1; font-size: 12px; line-height: 1.4;")
    lbl_hint_desc.setWordWrap(True)
    ccdh_layout.addWidget(lbl_hint_title)
    ccdh_layout.addWidget(lbl_hint_desc)

    btn_calib_step3 = QPushButton("🎭 Abrir Estúdio para Calibrar / Gravar Clone com Câmera...")
    btn_calib_step3.setCursor(Qt.PointingHandCursor)
    btn_calib_step3.setStyleSheet(
        "background: #4338ca; color: #ffffff; font-weight: 700; font-size: 12px; padding: 8px 16px; border-radius: 6px; margin-top: 6px;"
    )
    btn_calib_step3.clicked.connect(view._open_clone_calibration)
    ccdh_layout.addWidget(btn_calib_step3)

    p3_lay.addWidget(view.card_clone_dev_hint)
    view.card_clone_dev_hint.hide()

    p3_lay.addStretch()

    s3_nav = QHBoxLayout()
    btn_prev_s3 = QPushButton("◀ Passo Anterior (Formato)")
    btn_prev_s3.setCursor(Qt.PointingHandCursor)
    btn_prev_s3.clicked.connect(lambda: view._switch_step(1))

    btn_next_s3 = QPushButton("Continuar para Roteiro (Teleprompter) ▶")
    btn_next_s3.setProperty("class", "primary")
    btn_next_s3.setCursor(Qt.PointingHandCursor)
    btn_next_s3.clicked.connect(lambda: view._switch_step(3))

    s3_nav.addWidget(btn_prev_s3)
    s3_nav.addStretch()
    s3_nav.addWidget(btn_next_s3)
    p3_lay.addLayout(s3_nav)

    # ====================================================
    # PAGE 4: Roteiro da Aula (Teleprompter ou Clone IA)
    # ====================================================
    page4 = QWidget()
    p4_lay = QVBoxLayout(page4)
    p4_lay.setContentsMargins(0, 8, 0, 0)
    p4_lay.setSpacing(12)

    card_tp = QFrame()
    card_tp.setProperty("class", "card")
    ct_layout = QVBoxLayout(card_tp)
    ct_layout.setContentsMargins(18, 16, 18, 16)
    ct_layout.setSpacing(10)

    view.ct_title = QLabel("4. Roteiro da Aula para o Teleprompter (Opcional)")
    view.ct_title.setProperty("class", "section-title")
    view.ct_sub = QLabel("Cole o roteiro abaixo. Ele rolará no topo da tela durante a gravação para você ler olhando para a câmera:")
    view.ct_sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
    ct_layout.addWidget(view.ct_title)
    ct_layout.addWidget(view.ct_sub)

    view.edit_script = QTextEdit()
    view.edit_script.setFixedHeight(140)
    view.edit_script.setPlaceholderText("Cole ou dite o texto da aula aqui...")
    ct_layout.addWidget(view.edit_script)

    row_script_tools = QHBoxLayout()
    btn_load_txt = QPushButton("Carregar arquivo de texto (.txt)...")
    btn_load_txt.setCursor(Qt.PointingHandCursor)
    btn_load_txt.clicked.connect(view._pick_txt_script)

    btn_voice_script = VoicePromptButton(target_input=view.edit_script)
    btn_voice_script.setToolTip("Ditar roteiro da aula pelo microfone")

    row_script_tools.addWidget(btn_load_txt)
    row_script_tools.addWidget(btn_voice_script)
    row_script_tools.addStretch()
    ct_layout.addLayout(row_script_tools)

    # ----------------------------------------------------
    # Audio Source for Clone Video (AI TTS vs Live Mic vs File)
    # ----------------------------------------------------
    card_audio_src = QFrame()
    card_audio_src.setStyleSheet(
        "background: #0f172a; border: 1.5px solid #334155; border-radius: 8px; margin-top: 8px;"
    )
    cas_layout = QVBoxLayout(card_audio_src)
    cas_layout.setContentsMargins(14, 12, 14, 12)
    cas_layout.setSpacing(10)

    lbl_as_title = QLabel("🎙️ Voz da Aula (Fonte de Áudio do Clone Digital):")
    lbl_as_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #38bdf8;")
    cas_layout.addWidget(lbl_as_title)

    view.audio_source_group = QButtonGroup(view)

    as_row = QHBoxLayout()
    as_row.setSpacing(16)

    view.radio_audio_tts = QRadioButton("🤖 Voz Sintetizada por IA (Edge-TTS)")
    view.radio_audio_tts.setChecked(True)
    view.radio_audio_tts.setStyleSheet("font-weight: 600; color: #f8fafc;")
    view.audio_source_group.addButton(view.radio_audio_tts, 1)

    view.radio_audio_record = QRadioButton("🎙️ Gravar Minha Própria Voz Agora")
    view.radio_audio_record.setStyleSheet("font-weight: 600; color: #34d399;")
    view.audio_source_group.addButton(view.radio_audio_record, 2)

    view.radio_audio_import = QRadioButton("📁 Importar Áudio Pronto (MP3 / WAV)")
    view.radio_audio_import.setStyleSheet("font-weight: 600; color: #c084fc;")
    view.audio_source_group.addButton(view.radio_audio_import, 3)

    as_row.addWidget(view.radio_audio_tts)
    as_row.addWidget(view.radio_audio_record)
    as_row.addWidget(view.radio_audio_import)
    as_row.addStretch()
    cas_layout.addLayout(as_row)

    # Panel 1: TTS hint
    view.panel_audio_tts = QWidget()
    pat_lay = QVBoxLayout(view.panel_audio_tts)
    pat_lay.setContentsMargins(0, 2, 0, 2)
    lbl_tts_info = QLabel("💡 A IA lerá o texto do roteiro acima com voz neural fluida em português brasileiro.")
    lbl_tts_info.setStyleSheet("color: #94a3b8; font-size: 11px;")
    pat_lay.addWidget(lbl_tts_info)
    cas_layout.addWidget(view.panel_audio_tts)

    # Panel 2: Live voice recording (Microphone)
    view.panel_audio_record = QWidget()
    par_lay = QHBoxLayout(view.panel_audio_record)
    par_lay.setContentsMargins(0, 4, 0, 4)
    par_lay.setSpacing(12)

    view.btn_record_voice = QPushButton("🔴 Iniciar Gravação da Minha Voz")
    view.btn_record_voice.setCursor(Qt.PointingHandCursor)
    view.btn_record_voice.setStyleSheet(
        "background: #dc2626; color: #ffffff; font-weight: 700; font-size: 12px; padding: 7px 16px; border-radius: 6px;"
    )
    view.btn_record_voice.clicked.connect(view._toggle_voice_recording)

    view.lbl_voice_timer = QLabel("00:00")
    view.lbl_voice_timer.setStyleSheet(
        "font-size: 14px; font-weight: 800; color: #38bdf8; background: #1e293b; padding: 4px 8px; border-radius: 6px;"
    )

    view.lbl_voice_status = QLabel("Leia o texto do roteiro acima em voz alta com seu microfone.")
    view.lbl_voice_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

    view.btn_play_voice = QPushButton("▶ Ouvir Gravação")
    view.btn_play_voice.setCursor(Qt.PointingHandCursor)
    view.btn_play_voice.setEnabled(False)
    view.btn_play_voice.setStyleSheet(
        "background: #1e293b; color: #38bdf8; font-weight: 600; font-size: 11px; padding: 6px 12px; border-radius: 6px;"
    )
    view.btn_play_voice.clicked.connect(view._play_preview_audio)

    par_lay.addWidget(view.btn_record_voice)
    par_lay.addWidget(view.lbl_voice_timer)
    par_lay.addWidget(view.lbl_voice_status, stretch=1)
    par_lay.addWidget(view.btn_play_voice)
    view.panel_audio_record.hide()
    cas_layout.addWidget(view.panel_audio_record)

    # Panel 3: Imported audio file
    view.panel_audio_import = QWidget()
    pai_lay = QHBoxLayout(view.panel_audio_import)
    pai_lay.setContentsMargins(0, 4, 0, 4)
    pai_lay.setSpacing(12)

    btn_pick_human_audio = QPushButton("📁 Selecionar Arquivo de Áudio...")
    btn_pick_human_audio.setCursor(Qt.PointingHandCursor)
    btn_pick_human_audio.setStyleSheet(
        "background: #6366f1; color: #ffffff; font-weight: 700; font-size: 12px; padding: 7px 16px; border-radius: 6px;"
    )
    btn_pick_human_audio.clicked.connect(view._pick_human_audio_file)

    view.lbl_import_audio_status = QLabel("Nenhum arquivo selecionado. Selecione um áudio em MP3 ou WAV gravado em outro dispositivo.")
    view.lbl_import_audio_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

    view.btn_play_imported = QPushButton("▶ Ouvir Áudio")
    view.btn_play_imported.setCursor(Qt.PointingHandCursor)
    view.btn_play_imported.setEnabled(False)
    view.btn_play_imported.setStyleSheet(
        "background: #1e293b; color: #38bdf8; font-weight: 600; font-size: 11px; padding: 6px 12px; border-radius: 6px;"
    )
    view.btn_play_imported.clicked.connect(view._play_preview_audio)

    pai_lay.addWidget(btn_pick_human_audio)
    pai_lay.addWidget(view.lbl_import_audio_status, stretch=1)
    pai_lay.addWidget(view.btn_play_imported)
    view.panel_audio_import.hide()
    cas_layout.addWidget(view.panel_audio_import)

    # Connect radio buttons to toggle panels
    view.radio_audio_tts.toggled.connect(view._on_audio_source_changed)
    view.radio_audio_record.toggled.connect(view._on_audio_source_changed)
    view.radio_audio_import.toggled.connect(view._on_audio_source_changed)

    ct_layout.addWidget(card_audio_src)
    p4_lay.addWidget(card_tp)
    p4_lay.addStretch()

    s4_nav = QHBoxLayout()
    btn_prev_s4 = QPushButton("◀ Passo Anterior (Dispositivos)")
    btn_prev_s4.setCursor(Qt.PointingHandCursor)
    btn_prev_s4.clicked.connect(lambda: view._switch_step(2))

    btn_next_s4 = QPushButton("Continuar para Fundo & Gravação ▶")
    btn_next_s4.setProperty("class", "primary")
    btn_next_s4.setCursor(Qt.PointingHandCursor)
    btn_next_s4.clicked.connect(lambda: view._switch_step(4))

    s4_nav.addWidget(btn_prev_s4)
    s4_nav.addStretch()
    s4_nav.addWidget(btn_next_s4)
    p4_lay.addLayout(s4_nav)

    # ====================================================
    # PAGE 5: Fundo Musical & Gravação
    # ====================================================
    page5 = QWidget()
    p5_lay = QVBoxLayout(page5)
    p5_lay.setContentsMargins(0, 8, 0, 0)
    p5_lay.setSpacing(12)

    card_extras = QFrame()
    card_extras.setProperty("class", "card")
    ce_layout = QVBoxLayout(card_extras)
    ce_layout.setContentsMargins(18, 16, 18, 16)
    ce_layout.setSpacing(12)

    ce_title = QLabel("5. Fundo Musical & Legendas com IA")
    ce_title.setProperty("class", "section-title")
    ce_layout.addWidget(ce_title)

    # BGM row
    bgm_row = QHBoxLayout()
    bgm_row.setSpacing(12)
    btn_pick_bgm = QPushButton("Música de Fundo (MP3/WAV)...")
    btn_pick_bgm.setCursor(Qt.PointingHandCursor)
    btn_pick_bgm.clicked.connect(view._pick_bgm)
    view.lbl_bgm_status = QLabel("Sem música de fundo (pode adicionar antes ou após gravar)")
    view.lbl_bgm_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
    bgm_row.addWidget(btn_pick_bgm)
    bgm_row.addWidget(view.lbl_bgm_status)
    bgm_row.addStretch()
    ce_layout.addLayout(bgm_row)

    # Subtitles row
    sub_row = QHBoxLayout()
    sub_row.setSpacing(14)
    view.chk_subtitles = QCheckBox("Gerar Legendas Automáticas com IA (Gemini)")
    view.chk_subtitles.setStyleSheet("font-weight: 600; color: #f8fafc;")

    lbl_lang = QLabel("Idioma da Legenda:")
    view.combo_sub_lang = QComboBox()
    for code, name in SUPPORTED_LANGUAGES.items():
        view.combo_sub_lang.addItem(name, code)

    sub_row.addWidget(view.chk_subtitles)
    sub_row.addWidget(lbl_lang)
    sub_row.addWidget(view.combo_sub_lang)
    sub_row.addStretch()
    ce_layout.addLayout(sub_row)

    p5_lay.addWidget(card_extras)
    p5_lay.addStretch()

    # Start Studio / Generate Buttons
    view.btn_enter_studio = QPushButton("🎬 Entrar no Estúdio de Gravação")
    view.btn_enter_studio.setProperty("class", "primary")
    view.btn_enter_studio.setFixedHeight(48)
    view.btn_enter_studio.setCursor(Qt.PointingHandCursor)
    view.btn_enter_studio.setStyleSheet("font-size: 15px; font-weight: 700;")
    view.btn_enter_studio.clicked.connect(view._enter_live_studio)
    p5_lay.addWidget(view.btn_enter_studio)

    view.btn_generate_clone_lesson = QPushButton("✨ Gerar Videoaula com Meu Clone IA (Automático)")
    view.btn_generate_clone_lesson.setFixedHeight(48)
    view.btn_generate_clone_lesson.setCursor(Qt.PointingHandCursor)
    view.btn_generate_clone_lesson.setStyleSheet(
        "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #ec4899); "
        "color: #ffffff; font-size: 15px; font-weight: 800; border-radius: 8px;"
    )
    view.btn_generate_clone_lesson.clicked.connect(view._start_clone_generation)
    view.btn_generate_clone_lesson.hide()
    p5_lay.addWidget(view.btn_generate_clone_lesson)

    s5_nav = QHBoxLayout()
    btn_prev_s5 = QPushButton("◀ Passo Anterior (Roteiro)")
    btn_prev_s5.setCursor(Qt.PointingHandCursor)
    btn_prev_s5.clicked.connect(lambda: view._switch_step(3))
    s5_nav.addWidget(btn_prev_s5)
    s5_nav.addStretch()
    p5_lay.addLayout(s5_nav)

    # Assemble step pages into step stack
    view.step_stack.addWidget(scroll_p1)
    view.step_stack.addWidget(page2)
    view.step_stack.addWidget(page3)
    view.step_stack.addWidget(page4)
    view.step_stack.addWidget(page5)
    layout.addWidget(view.step_stack, stretch=1)
    view._switch_step(0)
    view._update_presenter_cards_style()
    view._update_format_cards_style()

    return widget



def build_studio_view(view) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(12)

    # Top Bar (Back, Status, Record Timer)
    top_bar = QHBoxLayout()
    btn_leave = QPushButton("← Sair do Estúdio")
    btn_leave.setCursor(Qt.PointingHandCursor)
    btn_leave.clicked.connect(view._leave_studio)

    view.lbl_rec_indicator = QLabel("⚪ Não Gravando")
    view.lbl_rec_indicator.setStyleSheet("font-weight: 700; color: #94a3b8; font-size: 13px;")

    view.lbl_rec_timer = QLabel("00:00:00")
    view.lbl_rec_timer.setStyleSheet("font-size: 18px; font-weight: 800; color: #ffffff; padding: 2px 8px; background: #1a1e28; border-radius: 6px;")

    top_bar.addWidget(btn_leave)
    top_bar.addSpacing(16)
    top_bar.addWidget(view.lbl_rec_indicator)
    top_bar.addWidget(view.lbl_rec_timer)
    top_bar.addStretch()

    view.btn_studio_toggle_prompter = QPushButton("📝 Teleprompter Visível")
    view.btn_studio_toggle_prompter.setCursor(Qt.PointingHandCursor)
    view.btn_studio_toggle_prompter.clicked.connect(view._toggle_prompter_visibility)
    top_bar.addWidget(view.btn_studio_toggle_prompter)

    layout.addLayout(top_bar)

    # Teleprompter Widget (Top Center, eye level right below webcam)
    view.prompter = TeleprompterWidget(view)
    layout.addWidget(view.prompter, alignment=Qt.AlignHCenter)

    # Slide Area (Center Display)
    view.slide_display_frame = QFrame()
    view.slide_display_frame.setStyleSheet("background-color: #0b0d13; border: 1.5px solid #232938; border-radius: 10px;")
    sdf_layout = QVBoxLayout(view.slide_display_frame)
    sdf_layout.setContentsMargins(8, 8, 8, 8)
    sdf_layout.setAlignment(Qt.AlignCenter)

    view.lbl_live_slide = QLabel("Carregando slide...")
    view.lbl_live_slide.setAlignment(Qt.AlignCenter)
    view.lbl_live_slide.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    sdf_layout.addWidget(view.lbl_live_slide)

    layout.addWidget(view.slide_display_frame, stretch=1)

    # Slide Navigation Bar
    view.nav_slide_bar_widget = QWidget()
    nav_slide_bar = QHBoxLayout(view.nav_slide_bar_widget)
    nav_slide_bar.setContentsMargins(0, 0, 0, 0)
    nav_slide_bar.setSpacing(12)

    view.btn_prev_slide = QPushButton("◀ Slide Anterior (Seta Esquerda)")
    view.btn_prev_slide.setCursor(Qt.PointingHandCursor)
    view.btn_prev_slide.clicked.connect(view._go_prev_slide)

    view.lbl_slide_counter = QLabel("Slide 1 de 1")
    view.lbl_slide_counter.setStyleSheet("font-size: 14px; font-weight: 700; color: #38bdf8; min-width: 110px;")
    view.lbl_slide_counter.setAlignment(Qt.AlignCenter)

    view.btn_next_slide = QPushButton("Próximo Slide ▶ (Seta Direita / Espaço)")
    view.btn_next_slide.setProperty("class", "primary")
    view.btn_next_slide.setCursor(Qt.PointingHandCursor)
    view.btn_next_slide.clicked.connect(view._go_next_slide)

    nav_slide_bar.addStretch()
    nav_slide_bar.addWidget(view.btn_prev_slide)
    nav_slide_bar.addWidget(view.lbl_slide_counter)
    nav_slide_bar.addWidget(view.btn_next_slide)
    nav_slide_bar.addStretch()
    layout.addWidget(view.nav_slide_bar_widget)

    # Bottom Studio Controls
    controls_frame = QFrame()
    controls_frame.setProperty("class", "card")
    cf_layout = QHBoxLayout(controls_frame)
    cf_layout.setContentsMargins(16, 10, 16, 10)
    cf_layout.setSpacing(14)

    view.btn_rec_start = QPushButton("🔴 Iniciar Gravação")
    view.btn_rec_start.setStyleSheet("background: #dc2626; color: #ffffff; font-weight: 700; font-size: 14px; padding: 10px 22px; border-radius: 8px;")
    view.btn_rec_start.setCursor(Qt.PointingHandCursor)
    view.btn_rec_start.clicked.connect(view._start_recording)

    view.btn_rec_pause = QPushButton("⏸ Pausar")
    view.btn_rec_pause.setCursor(Qt.PointingHandCursor)
    view.btn_rec_pause.setEnabled(False)
    view.btn_rec_pause.clicked.connect(view._pause_recording)

    view.btn_rec_finish = QPushButton("⏹ Finalizar Aula & Gerar Vídeo")
    view.btn_rec_finish.setProperty("class", "primary")
    view.btn_rec_finish.setStyleSheet("font-size: 14px; font-weight: 700; padding: 10px 22px;")
    view.btn_rec_finish.setCursor(Qt.PointingHandCursor)
    view.btn_rec_finish.setEnabled(False)
    view.btn_rec_finish.clicked.connect(view._finish_recording)

    cf_layout.addWidget(view.btn_rec_start)
    cf_layout.addWidget(view.btn_rec_pause)
    cf_layout.addStretch()
    cf_layout.addWidget(view.btn_rec_finish)

    layout.addWidget(controls_frame)
    return widget

# ----------------------------------------------------
# SCREEN 2: RESULT / RENDER VIEW
# ----------------------------------------------------



def build_result_view(view) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(36, 32, 36, 32)
    layout.setSpacing(20)
    layout.setAlignment(Qt.AlignCenter)

    card = QFrame()
    card.setProperty("class", "card")
    c_layout = QVBoxLayout(card)
    c_layout.setContentsMargins(32, 32, 32, 32)
    c_layout.setSpacing(16)
    c_layout.setAlignment(Qt.AlignCenter)

    view.lbl_result_icon = QLabel("⏳")
    view.lbl_result_icon.setStyleSheet("font-size: 54px;")
    view.lbl_result_icon.setAlignment(Qt.AlignCenter)

    view.lbl_result_title = QLabel("Processando sua Videoaula...")
    view.lbl_result_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
    view.lbl_result_title.setAlignment(Qt.AlignCenter)

    view.lbl_result_status = QLabel("Aguarde a renderização dos slides e montagem do áudio...")
    view.lbl_result_status.setStyleSheet("color: #94a3b8; font-size: 13px;")
    view.lbl_result_status.setAlignment(Qt.AlignCenter)

    view.render_progress_bar = QProgressBar()
    view.render_progress_bar.setRange(0, 100)
    view.render_progress_bar.setValue(0)
    view.render_progress_bar.setFixedHeight(20)

    view.btn_cancel_render = QPushButton("⏹ Cancelar Renderização")
    view.btn_cancel_render.setCursor(Qt.PointingHandCursor)
    view.btn_cancel_render.clicked.connect(view._cancel_render)
    view.btn_cancel_render.hide()

    # Buttons (Hidden until completed)
    view.result_btn_row = QHBoxLayout()
    view.result_btn_row.setSpacing(14)
    view.result_btn_row.setAlignment(Qt.AlignCenter)

    view.btn_play_video = QPushButton("▶ Assistir Videoaula")
    view.btn_play_video.setProperty("class", "primary")
    view.btn_play_video.setCursor(Qt.PointingHandCursor)
    view.btn_play_video.clicked.connect(view._play_generated_video)

    view.btn_open_folder = QPushButton("📁 Abrir Pasta do Vídeo")
    view.btn_open_folder.setCursor(Qt.PointingHandCursor)
    view.btn_open_folder.clicked.connect(view._open_output_folder)

    view.btn_new_class = QPushButton("✨ Gravar Nova Aula")
    view.btn_new_class.setCursor(Qt.PointingHandCursor)
    view.btn_new_class.clicked.connect(view._reset_for_new_class)

    view.result_btn_row.addWidget(view.btn_play_video)
    view.result_btn_row.addWidget(view.btn_open_folder)
    view.result_btn_row.addWidget(view.btn_new_class)
    view.result_btn_container = QWidget()
    view.result_btn_container.setLayout(view.result_btn_row)
    view.result_btn_container.hide()

    c_layout.addWidget(view.lbl_result_icon)
    c_layout.addWidget(view.lbl_result_title)
    c_layout.addWidget(view.lbl_result_status)
    c_layout.addWidget(view.render_progress_bar)
    c_layout.addWidget(view.btn_cancel_render)
    c_layout.addWidget(view.result_btn_container)

    layout.addWidget(card)
    return widget

# ----------------------------------------------------
# EVENTS & HANDLERS
# ----------------------------------------------------

