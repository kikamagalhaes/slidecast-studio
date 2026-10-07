import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QThread
from PySide6.QtGui import QPixmap, QKeyEvent
from PySide6.QtMultimedia import (
    QMediaDevices,
    QAudioInput,
    QMediaCaptureSession,
    QMediaRecorder,
)
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
)

from app.core.ffmpeg_utils import format_duration
from app.core.subtitles_generator import SUPPORTED_LANGUAGES
from app.core.podcast_video_builder import build_podcast_video
from app.ui.teleprompter_widget import TeleprompterWidget
from app.ui.dialogs.generate_cover_dialog import GenerateCoverDialog


class PodcastVideoRenderWorker(QThread):
    progress_changed = Signal(float, str)
    render_finished = Signal(str)
    render_error = Signal(str)

    def __init__(
        self,
        cover_image: str,
        audio_path: str,
        output_path: str,
        bgm_path: Optional[str],
        waveform_color: str,
        enable_subtitles: bool,
        subtitles_language: str,
    ):
        super().__init__()
        self.cover_image = cover_image
        self.audio_path = audio_path
        self.output_path = output_path
        self.bgm_path = bgm_path
        self.waveform_color = waveform_color
        self.enable_subtitles = enable_subtitles
        self.subtitles_language = subtitles_language

    def run(self):
        try:
            def callback(pct, msg):
                self.progress_changed.emit(pct, msg)

            res = build_podcast_video(
                cover_image_path=self.cover_image,
                narration_audio_path=self.audio_path,
                output_video_path=self.output_path,
                bgm_path=self.bgm_path,
                waveform_color=self.waveform_color,
                enable_subtitles=self.enable_subtitles,
                subtitles_language=self.subtitles_language,
                progress_callback=callback,
            )
            self.render_finished.emit(res)
        except Exception as e:
            self.render_error.emit(str(e))


class RecordPodcastView(QWidget):
    back_to_home = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cover_image_path: Optional[str] = None
        self.bgm_path: Optional[str] = None
        self.output_video_path: Optional[str] = None

        # State
        self.is_recording = False
        self.record_start_time = 0.0
        self.temp_audio_file = str(Path.home() / "SlideCast_Materials" / "podcast_temp_rec.m4a")

        # Media capture session
        self.capture_session = QMediaCaptureSession(self)
        self.audio_input = QAudioInput(self)
        self.capture_session.setAudioInput(self.audio_input)
        self.recorder = QMediaRecorder(self)
        self.capture_session.setRecorder(self.recorder)

        # Timer
        self.record_timer = QTimer(self)
        self.record_timer.setInterval(200)
        self.record_timer.timeout.connect(self._update_record_timer)

        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)

        self.setup_view = self._build_setup_view()
        self.studio_view = self._build_studio_view()
        self.result_view = self._build_result_view()

        self.stack.addWidget(self.setup_view)   # Index 0
        self.stack.addWidget(self.studio_view)  # Index 1
        self.stack.addWidget(self.result_view)  # Index 2

        self.stack.setCurrentIndex(0)

    # ----------------------------------------------------
    # SCREEN 0: SETUP
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

        title = QLabel("🎙️ 4. Gravar Podcast - Áudio ao Vivo com Ondas Sonoras e Teleprompter")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f59e0b;")

        nav.addWidget(btn_back)
        nav.addWidget(title)
        nav.addStretch()
        layout.addLayout(nav)

        # Step Navigation Bar (Clickable screens without scrollbars)
        self.step_bar = QHBoxLayout()
        self.step_bar.setSpacing(8)
        self.step_buttons = []
        step_labels = [
            "1. 🖼️ Capa & Microfone",
            "2. 📝 Pauta & Teleprompter",
            "3. 🎵 Áudio & Gravação",
        ]
        for idx, text in enumerate(step_labels):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self._switch_step(i))
            self.step_bar.addWidget(btn)
            self.step_buttons.append(btn)
        layout.addLayout(self.step_bar)

        self.step_stack = QStackedWidget()

        # Page 1: Capa e Microfone
        page1 = QWidget()
        p1_lay = QVBoxLayout(page1)
        p1_lay.setContentsMargins(0, 8, 0, 0)
        p1_lay.setSpacing(12)

        # Page 2: Pauta e Teleprompter
        page2 = QWidget()
        p2_lay = QVBoxLayout(page2)
        p2_lay.setContentsMargins(0, 8, 0, 0)
        p2_lay.setSpacing(12)

        # Page 3: Fundo Musical e Gravação
        page3 = QWidget()
        p3_lay = QVBoxLayout(page3)
        p3_lay.setContentsMargins(0, 8, 0, 0)
        p3_lay.setSpacing(12)

        # Section 1: Informações do Episódio
        card_info = QFrame()
        card_info.setProperty("class", "card")
        ci_layout = QVBoxLayout(card_info)
        ci_layout.setContentsMargins(18, 16, 18, 16)
        ci_layout.setSpacing(12)

        ci_title = QLabel("1. Informações do Episódio")
        ci_title.setProperty("class", "section-title")
        ci_layout.addWidget(ci_title)

        grid_info = QHBoxLayout()
        grid_info.setSpacing(16)

        box_t = QVBoxLayout()
        lbl_t = QLabel("Título do Episódio:")
        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("Ex: Café com Tecnologia #12 - O Futuro da IA")
        box_t.addWidget(lbl_t)
        box_t.addWidget(self.edit_title)

        box_p = QVBoxLayout()
        lbl_p = QLabel("Nome do Host / Apresentador(a):")
        self.edit_host = QLineEdit()
        self.edit_host.setPlaceholderText("Ex: Kika Magalhães")
        box_p.addWidget(lbl_p)
        box_p.addWidget(self.edit_host)

        grid_info.addLayout(box_t, stretch=2)
        grid_info.addLayout(box_p, stretch=1)
        ci_layout.addLayout(grid_info)
        p1_lay.addWidget(card_info)

        # Section 2: Capa do Podcast
        card_cover = QFrame()
        card_cover.setProperty("class", "card")
        cc_layout = QVBoxLayout(card_cover)
        cc_layout.setContentsMargins(18, 16, 18, 16)
        cc_layout.setSpacing(12)

        cc_title = QLabel("2. Imagem da Capa do Podcast")
        cc_title.setProperty("class", "section-title")
        cc_layout.addWidget(cc_title)

        row_cover = QHBoxLayout()
        row_cover.setSpacing(12)

        btn_pick_cover = QPushButton("📁 Escolher Capa do Computador...")
        btn_pick_cover.setCursor(Qt.PointingHandCursor)
        btn_pick_cover.clicked.connect(self._pick_cover_image)

        btn_ai_cover = QPushButton("🎨 Gerar Capa com IA...")
        btn_ai_cover.setCursor(Qt.PointingHandCursor)
        btn_ai_cover.setStyleSheet("background-color: #7c2d12; color: #fdba74; font-weight: 600;")
        btn_ai_cover.clicked.connect(self._open_ai_cover_generator)

        self.lbl_cover_status = QLabel("Nenhuma imagem selecionada (Necessária para o vídeo)")
        self.lbl_cover_status.setStyleSheet("color: #94a3b8; font-size: 12px;")

        row_cover.addWidget(btn_pick_cover)
        row_cover.addWidget(btn_ai_cover)
        row_cover.addWidget(self.lbl_cover_status)
        row_cover.addStretch()
        cc_layout.addLayout(row_cover)
        p1_lay.addWidget(card_cover)

        # Section 5 (placed in Step 1): Microfone
        card_mic = QFrame()
        card_mic.setProperty("class", "card")
        cm_layout = QVBoxLayout(card_mic)
        cm_layout.setContentsMargins(18, 16, 18, 16)
        cm_layout.setSpacing(12)

        cm_title = QLabel("3. Microfone de Gravação")
        cm_title.setProperty("class", "section-title")
        cm_layout.addWidget(cm_title)

        row_mic = QHBoxLayout()
        lbl_mic = QLabel("Dispositivo:")
        self.combo_mics = QComboBox()
        audio_devs = QMediaDevices.audioInputs()
        if audio_devs:
            for d in audio_devs:
                self.combo_mics.addItem(d.description(), d)
        else:
            self.combo_mics.addItem("Microfone Padrão do Sistema", None)
        row_mic.addWidget(lbl_mic)
        row_mic.addWidget(self.combo_mics)
        row_mic.addStretch()
        cm_layout.addLayout(row_mic)
        p1_lay.addWidget(card_mic)
        p1_lay.addStretch()

        s1_nav = QHBoxLayout()
        s1_nav.addStretch()
        btn_next_s1 = QPushButton("Continuar para Pauta (Teleprompter) ▶")
        btn_next_s1.setProperty("class", "primary")
        btn_next_s1.setCursor(Qt.PointingHandCursor)
        btn_next_s1.clicked.connect(lambda: self._switch_step(1))
        s1_nav.addWidget(btn_next_s1)
        p1_lay.addLayout(s1_nav)

        # Section 3: Roteiro / Pauta para o Teleprompter (Step 2)
        card_script = QFrame()
        card_script.setProperty("class", "card")
        cs_layout = QVBoxLayout(card_script)
        cs_layout.setContentsMargins(18, 16, 18, 16)
        cs_layout.setSpacing(12)

        cs_title = QLabel("2. Roteiro / Pauta (Teleprompter)")
        cs_title.setProperty("class", "section-title")
        cs_layout.addWidget(cs_title)

        self.edit_script = QTextEdit()
        self.edit_script.setPlaceholderText(
            "Cole aqui a pauta, notas ou roteiro completo da gravação...\n"
            "O texto rolará suavemente no teleprompter no topo da tela durante a sua fala."
        )
        self.edit_script.setFixedHeight(140)
        cs_layout.addWidget(self.edit_script)

        btn_load_script = QPushButton("Carregar Arquivo de Roteiro (.txt, .md)...")
        btn_load_script.setCursor(Qt.PointingHandCursor)
        btn_load_script.clicked.connect(self._pick_txt_script)
        cs_layout.addWidget(btn_load_script, alignment=Qt.AlignLeft)
        p2_lay.addWidget(card_script)
        p2_lay.addStretch()

        s2_nav = QHBoxLayout()
        btn_prev_s2 = QPushButton("◀ Passo Anterior")
        btn_prev_s2.setCursor(Qt.PointingHandCursor)
        btn_prev_s2.clicked.connect(lambda: self._switch_step(0))
        btn_next_s2 = QPushButton("Continuar para Áudio & Gravação ▶")
        btn_next_s2.setProperty("class", "primary")
        btn_next_s2.setCursor(Qt.PointingHandCursor)
        btn_next_s2.clicked.connect(lambda: self._switch_step(2))
        s2_nav.addWidget(btn_prev_s2)
        s2_nav.addStretch()
        s2_nav.addWidget(btn_next_s2)
        p2_lay.addLayout(s2_nav)

        # Section 4: Fundo Musical, Legendas & Visualizador (Step 3)
        card_extra = QFrame()
        card_extra.setProperty("class", "card")
        ce_layout = QVBoxLayout(card_extra)
        ce_layout.setContentsMargins(18, 16, 18, 16)
        ce_layout.setSpacing(12)

        ce_title = QLabel("3. Estilo das Ondas Sonoras, Fundo Musical & Legendas")
        ce_title.setProperty("class", "section-title")
        ce_layout.addWidget(ce_title)

        row_wave = QHBoxLayout()
        lbl_wave = QLabel("Cor das Ondas Sonoras Animadas:")
        self.combo_wave_color = QComboBox()
        self.combo_wave_color.addItem("Azul Ciano Neon", "0x38bdf8")
        self.combo_wave_color.addItem("Violeta Digital", "0xa78bfa")
        self.combo_wave_color.addItem("Ouro Radiante", "0xf59e0b")
        self.combo_wave_color.addItem("Verde Esmeralda", "0x34d399")
        self.combo_wave_color.addItem("Branco Puro", "0xffffff")
        row_wave.addWidget(lbl_wave)
        row_wave.addWidget(self.combo_wave_color)
        row_wave.addStretch()
        ce_layout.addLayout(row_wave)

        # BGM
        row_bgm = QHBoxLayout()
        btn_pick_bgm = QPushButton("Música de Fundo (MP3/WAV)...")
        btn_pick_bgm.setCursor(Qt.PointingHandCursor)
        btn_pick_bgm.clicked.connect(self._pick_bgm)
        self.lbl_bgm_status = QLabel("Sem música de fundo (opcional)")
        self.lbl_bgm_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
        row_bgm.addWidget(btn_pick_bgm)
        row_bgm.addWidget(self.lbl_bgm_status)
        row_bgm.addStretch()
        ce_layout.addLayout(row_bgm)

        # Subtitles
        row_sub = QHBoxLayout()
        self.chk_subtitles = QCheckBox("Gerar Legendas Automáticas com IA (Gemini)")
        self.chk_subtitles.setStyleSheet("font-weight: 600; color: #f8fafc;")

        lbl_lang = QLabel("Idioma da Legenda:")
        self.combo_sub_lang = QComboBox()
        for code, name in SUPPORTED_LANGUAGES.items():
            self.combo_sub_lang.addItem(name, code)

        row_sub.addWidget(self.chk_subtitles)
        row_sub.addWidget(lbl_lang)
        row_sub.addWidget(self.combo_sub_lang)
        row_sub.addStretch()
        ce_layout.addLayout(row_sub)

        p3_lay.addWidget(card_extra)
        p3_lay.addStretch()

        # Enter Studio Button
        btn_enter_studio = QPushButton("🎙️ Entrar no Estúdio do Podcast")
        btn_enter_studio.setProperty("class", "primary")
        btn_enter_studio.setFixedHeight(48)
        btn_enter_studio.setCursor(Qt.PointingHandCursor)
        btn_enter_studio.setStyleSheet("font-size: 15px; font-weight: 700;")
        btn_enter_studio.clicked.connect(self._enter_live_studio)
        p3_lay.addWidget(btn_enter_studio)

        s3_nav = QHBoxLayout()
        btn_prev_s3 = QPushButton("◀ Passo Anterior")
        btn_prev_s3.setCursor(Qt.PointingHandCursor)
        btn_prev_s3.clicked.connect(lambda: self._switch_step(1))
        s3_nav.addWidget(btn_prev_s3)
        s3_nav.addStretch()
        p3_lay.addLayout(s3_nav)

        # Assemble step pages
        self.step_stack.addWidget(page1)
        self.step_stack.addWidget(page2)
        self.step_stack.addWidget(page3)
        layout.addWidget(self.step_stack, stretch=1)
        self._switch_step(0)

        return widget

    def _switch_step(self, idx: int):
        self.step_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.step_buttons):
            if i == idx:
                btn.setStyleSheet(
                    "background: #f59e0b; color: #000000; font-weight: 700; "
                    "border: 1.5px solid #fbbf24; padding: 8px 14px; border-radius: 8px;"
                )
            else:
                btn.setStyleSheet(
                    "background: #1a1e28; color: #94a3b8; font-weight: 600; "
                    "border: 1px solid #2d3343; padding: 8px 14px; border-radius: 8px;"
                )

    # ----------------------------------------------------
    # SCREEN 1: LIVE STUDIO
    # ----------------------------------------------------
    def _build_studio_view(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        # Top Bar
        top_bar = QHBoxLayout()
        btn_leave = QPushButton("← Sair do Estúdio")
        btn_leave.setCursor(Qt.PointingHandCursor)
        btn_leave.clicked.connect(self._leave_studio)

        self.lbl_rec_indicator = QLabel("● PRONTO PARA GRAVAR")
        self.lbl_rec_indicator.setStyleSheet("font-weight: 700; color: #94a3b8; font-size: 13px;")

        self.lbl_rec_timer = QLabel("00:00")
        self.lbl_rec_timer.setStyleSheet(
            "font-size: 18px; font-weight: 800; color: #f59e0b; "
            "background-color: #12151f; padding: 4px 12px; border-radius: 6px;"
        )

        top_bar.addWidget(btn_leave)
        top_bar.addSpacing(16)
        top_bar.addWidget(self.lbl_rec_indicator)
        top_bar.addWidget(self.lbl_rec_timer)
        top_bar.addStretch()

        self.btn_toggle_prompter = QPushButton("📝 Teleprompter Visível")
        self.btn_toggle_prompter.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_prompter.clicked.connect(self._toggle_prompter)
        top_bar.addWidget(self.btn_toggle_prompter)

        layout.addLayout(top_bar)

        # Teleprompter Widget (Top Center, eye level)
        self.prompter = TeleprompterWidget(self)
        layout.addWidget(self.prompter, alignment=Qt.AlignHCenter)

        # Center Display: Cover Image + Audio Visualizer
        self.cover_display_frame = QFrame()
        self.cover_display_frame.setStyleSheet(
            "background-color: #0b0d13; border: 1.5px solid #232938; border-radius: 10px;"
        )
        cdf_layout = QVBoxLayout(self.cover_display_frame)
        cdf_layout.setContentsMargins(12, 12, 12, 12)
        cdf_layout.setAlignment(Qt.AlignCenter)

        self.lbl_live_cover = QLabel("Capa do Podcast")
        self.lbl_live_cover.setAlignment(Qt.AlignCenter)
        self.lbl_live_cover.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cdf_layout.addWidget(self.lbl_live_cover)

        self.lbl_live_waveform_hint = QLabel("〜 〜 〜 Ondas Sonoras Dinâmicas Ativas 〜 〜 〜")
        self.lbl_live_waveform_hint.setAlignment(Qt.AlignCenter)
        self.lbl_live_waveform_hint.setStyleSheet(
            "color: #f59e0b; font-size: 14px; font-weight: 700; letter-spacing: 2px;"
        )
        cdf_layout.addWidget(self.lbl_live_waveform_hint)

        layout.addWidget(self.cover_display_frame, stretch=1)

        # Bottom Controls
        controls = QFrame()
        controls.setProperty("class", "card")
        c_layout = QHBoxLayout(controls)
        c_layout.setContentsMargins(16, 10, 16, 10)
        c_layout.setSpacing(14)

        self.btn_rec_start = QPushButton("🔴 Iniciar Gravação do Podcast")
        self.btn_rec_start.setStyleSheet(
            "background: #dc2626; color: #ffffff; font-weight: 700; font-size: 14px; padding: 10px 22px; border-radius: 8px;"
        )
        self.btn_rec_start.setCursor(Qt.PointingHandCursor)
        self.btn_rec_start.clicked.connect(self._start_recording)

        self.btn_rec_pause = QPushButton("⏸ Pausar")
        self.btn_rec_pause.setCursor(Qt.PointingHandCursor)
        self.btn_rec_pause.setEnabled(False)
        self.btn_rec_pause.clicked.connect(self._pause_recording)

        self.btn_rec_finish = QPushButton("⏹ Finalizar Podcast & Gerar Vídeo")
        self.btn_rec_finish.setProperty("class", "primary")
        self.btn_rec_finish.setStyleSheet("font-size: 14px; font-weight: 700; padding: 10px 22px;")
        self.btn_rec_finish.setCursor(Qt.PointingHandCursor)
        self.btn_rec_finish.setEnabled(False)
        self.btn_rec_finish.clicked.connect(self._finish_recording)

        c_layout.addWidget(self.btn_rec_start)
        c_layout.addWidget(self.btn_rec_pause)
        c_layout.addStretch()
        c_layout.addWidget(self.btn_rec_finish)

        layout.addWidget(controls)
        return widget

    # ----------------------------------------------------
    # SCREEN 2: RESULT
    # ----------------------------------------------------
    def _build_result_view(self) -> QWidget:
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

        self.lbl_result_icon = QLabel("⏳")
        self.lbl_result_icon.setStyleSheet("font-size: 54px;")
        self.lbl_result_icon.setAlignment(Qt.AlignCenter)

        self.lbl_result_title = QLabel("Processando seu Podcast em Vídeo...")
        self.lbl_result_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        self.lbl_result_title.setAlignment(Qt.AlignCenter)

        self.lbl_result_status = QLabel("Aguarde a renderização das ondas sonoras e sincronização...")
        self.lbl_result_status.setStyleSheet("color: #94a3b8; font-size: 13px;")
        self.lbl_result_status.setAlignment(Qt.AlignCenter)

        self.render_progress_bar = QProgressBar()
        self.render_progress_bar.setRange(0, 100)
        self.render_progress_bar.setValue(0)
        self.render_progress_bar.setFixedHeight(20)

        # Buttons
        self.result_btn_container = QWidget()
        bc_layout = QHBoxLayout(self.result_btn_container)
        bc_layout.setSpacing(14)
        bc_layout.setAlignment(Qt.AlignCenter)

        self.btn_play_video = QPushButton("▶ Assistir Vídeo do Podcast")
        self.btn_play_video.setProperty("class", "primary")
        self.btn_play_video.setCursor(Qt.PointingHandCursor)
        self.btn_play_video.clicked.connect(self._open_result_file)

        self.btn_open_folder = QPushButton("📁 Abrir Pasta")
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.clicked.connect(self._open_result_folder)

        self.btn_new_recording = QPushButton("← Gravar Outro Episódio")
        self.btn_new_recording.setCursor(Qt.PointingHandCursor)
        self.btn_new_recording.clicked.connect(lambda: self.stack.setCurrentIndex(0))

        bc_layout.addWidget(self.btn_play_video)
        bc_layout.addWidget(self.btn_open_folder)
        bc_layout.addWidget(self.btn_new_recording)
        self.result_btn_container.hide()

        c_layout.addWidget(self.lbl_result_icon)
        c_layout.addWidget(self.lbl_result_title)
        c_layout.addWidget(self.lbl_result_status)
        c_layout.addWidget(self.render_progress_bar)
        c_layout.addWidget(self.result_btn_container)

        layout.addWidget(card)
        return widget

    # ----------------------------------------------------
    # HANDLERS
    # ----------------------------------------------------
    def _pick_cover_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Imagem da Capa do Podcast",
            "",
            "Imagens (*.png *.jpg *.jpeg *.webp)",
        )
        if file_path:
            self._set_cover(file_path)

    def _open_ai_cover_generator(self):
        topic = self.edit_title.text().strip() or "Podcast Moderno"
        dlg = GenerateCoverDialog(self, default_topic=topic, default_aspect="1:1")
        if dlg.exec():
            if dlg.generated_cover_path:
                self._set_cover(dlg.generated_cover_path)

    def _set_cover(self, file_path: str):
        self.cover_image_path = file_path
        self.lbl_cover_status.setText(f"✓ {Path(file_path).name}")
        self.lbl_cover_status.setStyleSheet("color: #10b981; font-weight: 600;")

    def _pick_txt_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Roteiro / Pauta",
            "",
            "Arquivos de Texto (*.txt *.md)",
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.edit_script.setPlainText(f.read())
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
        if not self.cover_image_path or not Path(self.cover_image_path).exists():
            QMessageBox.warning(
                self,
                "Capa Necessária",
                "Por favor, selecione ou gere uma imagem de capa para o podcast antes de entrar no estúdio.",
            )
            return

        # Prepare teleprompter text
        script = self.edit_script.toPlainText().strip()
        if script:
            self.prompter.set_script_text(script)
            self.prompter.show()
        else:
            self.prompter.hide()

        # Update cover preview
        pix = QPixmap(self.cover_image_path)
        if not pix.isNull():
            scaled = pix.scaled(
                self.cover_display_frame.size() - Qt.QSize(30, 80),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.lbl_live_cover.setPixmap(scaled)

        # Set audio device
        selected_dev = self.combo_mics.currentData()
        if selected_dev:
            self.audio_input.setDevice(selected_dev)

        self.stack.setCurrentIndex(1)

    def _leave_studio(self):
        if self.is_recording:
            reply = QMessageBox.question(
                self,
                "Gravação em Andamento",
                "O podcast está sendo gravado. Deseja cancelar e voltar à configuração?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._stop_recording_discard()

        self.stack.setCurrentIndex(0)

    def _toggle_prompter(self):
        if self.prompter.isVisible():
            self.prompter.hide()
            self.btn_toggle_prompter.setText("📝 Teleprompter Oculto")
        else:
            self.prompter.show()
            self.btn_toggle_prompter.setText("📝 Teleprompter Visível")

    def _start_recording(self):
        try:
            temp_dir = Path.home() / "SlideCast_Materials"
            temp_dir.mkdir(parents=True, exist_ok=True)
            self.temp_audio_file = str(temp_dir / f"podcast_rec_{int(time.time())}.m4a")

            self.recorder.setOutputLocation(QUrl.fromLocalFile(self.temp_audio_file))
            self.recorder.record()

            self.is_recording = True
            self.record_start_time = time.time()
            self.record_timer.start()

            self.lbl_rec_indicator.setText("🔴 GRAVANDO PODCAST AO VIVO")
            self.lbl_rec_indicator.setStyleSheet("font-weight: 700; color: #ef4444; font-size: 13px;")

            self.btn_rec_start.setEnabled(False)
            self.btn_rec_pause.setEnabled(True)
            self.btn_rec_finish.setEnabled(True)

            if self.prompter.isVisible():
                self.prompter.start_scrolling()

        except Exception as e:
            QMessageBox.critical(self, "Erro ao Gravar", f"Não foi possível iniciar a gravação de áudio:\n{e}")

    def _pause_recording(self):
        if not self.is_recording:
            return
        if self.recorder.recorderState() == QMediaRecorder.RecordingState:
            self.recorder.pause()
            self.record_timer.stop()
            self.lbl_rec_indicator.setText("⏸ GRAVAÇÃO PAUSADA")
            self.lbl_rec_indicator.setStyleSheet("font-weight: 700; color: #eab308; font-size: 13px;")
            self.btn_rec_pause.setText("▶ Continuar")
            self.prompter.pause_scrolling()
        else:
            self.recorder.record()
            self.record_timer.start()
            self.lbl_rec_indicator.setText("🔴 GRAVANDO PODCAST AO VIVO")
            self.lbl_rec_indicator.setStyleSheet("font-weight: 700; color: #ef4444; font-size: 13px;")
            self.btn_rec_pause.setText("⏸ Pausar")
            self.prompter.start_scrolling()

    def _stop_recording_discard(self):
        self.is_recording = False
        self.record_timer.stop()
        self.recorder.stop()
        if Path(self.temp_audio_file).exists():
            try:
                Path(self.temp_audio_file).unlink()
            except Exception:
                pass

    def _finish_recording(self):
        self.is_recording = False
        self.record_timer.stop()
        self.recorder.stop()
        self.prompter.pause_scrolling()

        # Switch to result view
        self.stack.setCurrentIndex(2)
        self.lbl_result_icon.setText("⏳")
        self.lbl_result_title.setText("Renderizando seu Podcast em Vídeo...")
        self.lbl_result_status.setText("Sincronizando áudio, visualizador de ondas e legendas...")
        self.render_progress_bar.setValue(5)
        self.result_btn_container.hide()

        timestamp = int(time.time())
        title_slug = self.edit_title.text().strip().lower().replace(" ", "_") or "podcast"
        clean_slug = "".join(c for c in title_slug if c.isalnum() or c in ("-", "_"))[:30]

        out_dir = Path.home() / "SlideCast_Materials" / "podcasts"
        out_dir.mkdir(parents=True, exist_ok=True)
        self.output_video_path = str(out_dir / f"{clean_slug}_{timestamp}.mp4")

        # Start Render Worker
        self.worker = PodcastVideoRenderWorker(
            cover_image=self.cover_image_path,
            audio_path=self.temp_audio_file,
            output_path=self.output_video_path,
            bgm_path=self.bgm_path,
            waveform_color=self.combo_wave_color.currentData() or "0x38bdf8",
            enable_subtitles=self.chk_subtitles.isChecked(),
            subtitles_language=self.combo_sub_lang.currentData() or "pt",
        )
        self.worker.progress_changed.connect(self._on_render_progress)
        self.worker.render_finished.connect(self._on_render_finished)
        self.worker.render_error.connect(self._on_render_error)
        self.worker.start()

    def _on_render_progress(self, pct: float, msg: str):
        self.render_progress_bar.setValue(int(pct))
        self.lbl_result_status.setText(msg)

    def _on_render_finished(self, out_path: str):
        self.output_video_path = out_path
        self.render_progress_bar.setValue(100)
        self.lbl_result_icon.setText("🎉")
        self.lbl_result_title.setText("Vídeo do Podcast Concluído!")
        self.lbl_result_status.setText(f"O vídeo com ondas sonoras animadas está pronto:\n{out_path}")
        self.result_btn_container.show()

    def _on_render_error(self, err: str):
        self.lbl_result_icon.setText("❌")
        self.lbl_result_title.setText("Erro na Renderização")
        self.lbl_result_status.setText(f"Falha ao gerar o vídeo do podcast:\n{err}")
        self.result_btn_container.show()
        QMessageBox.critical(self, "Erro", f"Não foi possível renderizar o podcast:\n{err}")

    def _update_record_timer(self):
        elapsed = time.time() - self.record_start_time
        self.lbl_rec_timer.setText(format_duration(elapsed))

    def _open_result_file(self):
        if self.output_video_path and Path(self.output_video_path).exists():
            try:
                if sys.platform == "win32":
                    os.startfile(self.output_video_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", self.output_video_path])
                else:
                    subprocess.Popen(["xdg-open", self.output_video_path])
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o vídeo:\n{e}")

    def _open_result_folder(self):
        if self.output_video_path and Path(self.output_video_path).exists():
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
