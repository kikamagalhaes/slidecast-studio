import os
import sys
import time
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QThread
from PySide6.QtGui import QPixmap, QImage, QKeyEvent
from PySide6.QtMultimedia import (
    QMediaDevices,
    QAudioInput,
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

from app.core.ffmpeg_utils import format_duration, get_ffmpeg_paths, get_video_duration
from app.core.config_manager import get_gemini_api_key
from app.core.pdf_processor import inspect_pdf, render_thumbnail, render_all_slides_to_dir, PresentationInfo
from app.core.subtitles_generator import generate_subtitles_with_gemini, SUPPORTED_LANGUAGES
from app.core.class_video_builder import build_class_video
from app.core.meeting_recorder import ScreenRecordingProcess, extract_audio_from_video
from app.core.clone_manager import get_active_clone, list_clones
from app.core.avatar_video_generator import generate_avatar_speech, render_avatar_video
from app.ui.teleprompter_widget import TeleprompterWidget
from app.ui.dialogs.generate_cover_dialog import GenerateCoverDialog
from app.ui.dialogs.avatar_calibration_dialog import AvatarCalibrationDialog
from app.ui.dialogs.clone_engine_selection_dialog import CloneEngineSelectionDialog
from app.ui.voice_prompt_button import VoicePromptButton


class CloneLessonRenderWorker(QThread):
    progress_changed = Signal(float, str)
    render_finished = Signal(str)
    render_error = Signal(str)

    def __init__(
        self,
        pdf_path: str,
        script_text: str,
        output_path: str,
        clone_data: dict,
        class_title: str = "",
        teacher_name: str = "",
        cover_image: Optional[str] = None,
        bgm_path: Optional[str] = None,
        enable_subtitles: bool = True,
        subtitle_lang: str = "pt",
        engine_mode: str = "cloud_replicate",
        custom_audio_path: Optional[str] = None,
        video_format: str = "youtube",
        vertical_layout: str = "presenter",
        intro_mode: str = "auto",
        intro_video_path: Optional[str] = None,
        outro_mode: str = "auto",
        outro_video_path: Optional[str] = None,
        custom_bg_path: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.script_text = script_text
        self.output_path = output_path
        self.clone_data = clone_data
        self.class_title = class_title
        self.teacher_name = teacher_name
        self.cover_image = cover_image
        self.bgm_path = bgm_path
        self.enable_subtitles = enable_subtitles
        self.subtitle_lang = subtitle_lang
        self.engine_mode = engine_mode
        self.custom_audio_path = custom_audio_path
        self.video_format = video_format
        self.vertical_layout = vertical_layout
        self.intro_mode = intro_mode
        self.intro_video_path = intro_video_path
        self.outro_mode = outro_mode
        self.outro_video_path = outro_video_path
        self.custom_bg_path = custom_bg_path

    def run(self):
        try:
            import tempfile
            temp_dir = Path(tempfile.mkdtemp(prefix="clone_lesson_"))

            self.progress_changed.emit(0.05, "Extraindo slides da apresentação em alta definição...")
            images = render_all_slides_to_dir(
                file_path=self.pdf_path,
                output_dir=temp_dir,
                target_dpi=150,
            )
            slide_count = len(images)
            if slide_count == 0:
                raise RuntimeError("Nenhum slide encontrado no arquivo PDF fornecido.")

            if self.custom_audio_path and Path(self.custom_audio_path).exists():
                self.progress_changed.emit(0.20, "Carregando gravação de voz humana natural para a aula...")
                audio_path = str(Path(self.custom_audio_path).resolve())
            else:
                self.progress_changed.emit(0.20, "Sintetizando narração com a voz do clone digital (IA)...")
                audio_path = str(temp_dir / "narration.mp3")
                preferred_voice = self.clone_data.get("preferred_voice", "pt-BR-FranciscaNeural")

                def speech_cb(frac: float, msg: str):
                    self.progress_changed.emit(0.20 + (0.25 * frac), msg)

                generate_avatar_speech(
                    text=self.script_text,
                    output_audio_path=audio_path,
                    clone_data=self.clone_data,
                    preferred_voice=preferred_voice,
                    progress_callback=speech_cb,
                )

            self.progress_changed.emit(0.50, "Animando e renderizando vídeo do avatar sincronizado com a fala...")
            avatar_vid = str(temp_dir / "avatar.mp4")

            def avatar_cb(frac: float, msg: str):
                self.progress_changed.emit(0.50 + (0.15 * frac), msg)

            render_avatar_video(
                clone_data=self.clone_data,
                audio_path=audio_path,
                output_video_path=avatar_vid,
                progress_callback=avatar_cb,
                engine_mode=self.engine_mode,
            )

            # Calculate durations per slide dynamically based on script content
            total_dur = get_video_duration(audio_path)
            if total_dur <= 0:
                total_dur = 5.0 * slide_count
            durations = self._calculate_slide_durations(self.script_text, slide_count, total_dur)

            # Subtitles if requested
            srt_path = None
            if self.enable_subtitles:
                self.progress_changed.emit(0.70, "Gerando legendas inteligentes com o Gemini...")
                srt_path = str(temp_dir / "subtitles.srt")
                try:
                    generate_subtitles_with_gemini(
                        audio_path=audio_path,
                        output_srt_path=srt_path,
                        target_language=self.subtitle_lang,
                        progress_callback=lambda msg: self.progress_changed.emit(0.75, msg),
                    )
                except Exception as e:
                    print("Aviso ao gerar legendas para clone:", e)
                    srt_path = None

            self.progress_changed.emit(0.80, "Compondo videoaula nos padrões de proporção selecionados...")

            def build_cb(frac: float, msg: str):
                total_f = 0.80 + (0.19 * frac)
                self.progress_changed.emit(min(0.99, total_f), msg)

            out_video = build_class_video(
                slide_images=images,
                durations=durations,
                narration_audio_path=audio_path,
                output_path=self.output_path,
                class_title=self.class_title,
                teacher_name=self.teacher_name,
                cover_image_path=self.cover_image,
                bgm_path=self.bgm_path,
                subtitles_srt_path=srt_path,
                avatar_video_path=avatar_vid,
                custom_bg_path=self.custom_bg_path,
                video_format=self.video_format,
                vertical_layout=self.vertical_layout,
                intro_mode=self.intro_mode,
                intro_video_path=self.intro_video_path,
                outro_mode=self.outro_mode,
                outro_video_path=self.outro_video_path,
                intro_duration=3.5,
                outro_duration=3.5,
                fps=30,
                progress_callback=build_cb,
            )

            self.progress_changed.emit(1.0, "Videoaula com Clone Digital concluída com sucesso!")
            self.render_finished.emit(out_video)

        except Exception as e:
            self.render_error.emit(str(e))

    @staticmethod
    def _calculate_slide_durations(script_text: str, slide_count: int, total_duration: float) -> List[float]:
        if slide_count <= 1:
            return [max(1.5, total_duration)]

        # 1. Check for explicit [Slide X] or Slide X: markers
        import re
        slide_pattern = re.compile(r'\[?\bSlide\s*(\d+)[\:\-\]]?', re.IGNORECASE)
        splits = slide_pattern.split(script_text)
        if len(splits) > 2:
            slide_texts = {}
            for i in range(1, len(splits), 2):
                try:
                    num = int(splits[i])
                    txt = splits[i+1].strip() if i+1 < len(splits) else ""
                    slide_texts[num] = txt
                except (ValueError, IndexError):
                    pass
            if len(slide_texts) >= 2:
                word_counts = []
                for s in range(1, slide_count + 1):
                    txt = slide_texts.get(s, "")
                    wc = max(1, len(txt.split()))
                    word_counts.append(wc)
                total_words = sum(word_counts)
                durations = [(wc / total_words) * total_duration for wc in word_counts]
                durations = [max(1.5, d) for d in durations]
                factor = total_duration / sum(durations)
                durations = [round(d * factor, 3) for d in durations]
                diff = total_duration - sum(durations)
                durations[-1] += diff
                return durations

        # 2. Check if paragraphs match slide_count
        paras = [p.strip() for p in script_text.split("\n\n") if p.strip()]
        if len(paras) == slide_count and slide_count > 1:
            word_counts = [max(1, len(p.split())) for p in paras]
            total_words = sum(word_counts)
            durations = [(wc / total_words) * total_duration for wc in word_counts]
            durations = [max(1.5, d) for d in durations]
            factor = total_duration / sum(durations)
            durations = [round(d * factor, 3) for d in durations]
            diff = total_duration - sum(durations)
            durations[-1] += diff
            return durations

        # 3. Default: equal distribution
        per_slide = max(1.5, total_duration / slide_count)
        durations = [per_slide] * slide_count
        diff = total_duration - sum(durations)
        durations[-1] += diff
        return durations


class ClassVideoRenderWorker(QThread):
    progress_changed = Signal(float, str)
    render_finished = Signal(str)
    render_error = Signal(str)

    def __init__(
        self,
        pdf_path: str,
        durations: List[float],
        audio_path: str,
        output_path: str,
        class_title: str = "",
        teacher_name: str = "",
        cover_image: Optional[str] = None,
        bgm_path: Optional[str] = None,
        enable_subtitles: bool = True,
        subtitle_lang: str = "pt",
        video_format: str = "youtube",
        vertical_layout: str = "presenter",
        intro_mode: str = "auto",
        intro_video_path: Optional[str] = None,
        outro_mode: str = "auto",
        outro_video_path: Optional[str] = None,
        avatar_video_path: Optional[str] = None,
        custom_bg_path: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.durations = durations
        self.audio_path = audio_path
        self.output_path = output_path
        self.class_title = class_title
        self.teacher_name = teacher_name
        self.cover_image = cover_image
        self.bgm_path = bgm_path
        self.enable_subtitles = enable_subtitles
        self.subtitle_lang = subtitle_lang
        self.video_format = video_format
        self.vertical_layout = vertical_layout
        self.intro_mode = intro_mode
        self.intro_video_path = intro_video_path
        self.outro_mode = outro_mode
        self.outro_video_path = outro_video_path
        self.avatar_video_path = avatar_video_path
        self.custom_bg_path = custom_bg_path

    def run(self):
        try:
            import tempfile
            temp_dir = Path(tempfile.mkdtemp(prefix="class_render_"))

            self.progress_changed.emit(0.05, "Extraindo slides da apresentação...")
            images = render_all_slides_to_dir(
                file_path=self.pdf_path,
                output_dir=temp_dir,
                target_dpi=150,
            )

            # Subtitles generation if enabled
            srt_path = None
            if self.enable_subtitles:
                self.progress_changed.emit(0.20, "Gerando legendas inteligentes com a IA do Gemini...")
                srt_path = str(temp_dir / "subtitles.srt")
                try:
                    generate_subtitles_with_gemini(
                        audio_path=self.audio_path,
                        output_srt_path=srt_path,
                        target_language=self.subtitle_lang,
                        progress_callback=lambda msg: self.progress_changed.emit(0.25, msg),
                    )
                except Exception as e:
                    print(f"Aviso: Falha ao gerar legendas ({e}), continuando sem legendas...")
                    srt_path = None

            self.progress_changed.emit(0.40, "Iniciando renderização do vídeo final...")

            def progress_cb(frac: float, msg: str):
                total_frac = 0.40 + (0.58 * frac)
                self.progress_changed.emit(min(0.99, total_frac), msg)

            out_video = build_class_video(
                slide_images=images,
                durations=self.durations,
                narration_audio_path=self.audio_path,
                output_path=self.output_path,
                class_title=self.class_title,
                teacher_name=self.teacher_name,
                cover_image_path=self.cover_image,
                bgm_path=self.bgm_path,
                subtitles_srt_path=srt_path,
                avatar_video_path=self.avatar_video_path,
                custom_bg_path=self.custom_bg_path,
                video_format=self.video_format,
                vertical_layout=self.vertical_layout,
                intro_mode=self.intro_mode,
                intro_video_path=self.intro_video_path,
                outro_mode=self.outro_mode,
                outro_video_path=self.outro_video_path,
                intro_duration=3.5,
                outro_duration=3.5,
                fps=30,
                progress_callback=progress_cb,
            )

            self.progress_changed.emit(1.0, "Vídeo concluído!")
            self.render_finished.emit(out_video)

        except Exception as e:
            self.render_error.emit(str(e))


class TutorialPostProcessWorker(QThread):
    progress_changed = Signal(float, str)
    render_finished = Signal(str)
    render_error = Signal(str)

    def __init__(
        self,
        raw_video_path: str,
        output_path: str,
        bgm_path: Optional[str] = None,
        enable_subtitles: bool = False,
        subtitle_lang: str = "pt",
        parent=None,
    ):
        super().__init__(parent)
        self.raw_video_path = raw_video_path
        self.output_path = output_path
        self.bgm_path = bgm_path
        self.enable_subtitles = enable_subtitles
        self.subtitle_lang = subtitle_lang

    def run(self):
        try:
            import tempfile
            ffmpeg_exe, _ = get_ffmpeg_paths()
            current_video = self.raw_video_path

            # Subtitles generation if enabled
            srt_path = None
            if self.enable_subtitles:
                self.progress_changed.emit(0.2, "Extraindo áudio para gerar legendas com IA...")
                temp_audio = str(Path(tempfile.gettempdir()) / f"tut_audio_{int(time.time())}.aac")
                extract_audio_from_video(current_video, temp_audio)

                self.progress_changed.emit(0.4, "Gerando legendas inteligentes com o Gemini...")
                srt_path = str(Path(tempfile.gettempdir()) / f"tut_subs_{int(time.time())}.srt")
                try:
                    generate_subtitles_with_gemini(
                        audio_path=temp_audio,
                        output_srt_path=srt_path,
                        target_language=self.subtitle_lang,
                        progress_callback=lambda msg: self.progress_changed.emit(0.5, msg),
                    )
                except Exception as e:
                    print("Aviso: Falha nas legendas do tutorial:", e)
                    srt_path = None

            # If subtitles or bgm needed, run ffmpeg filter
            if srt_path or self.bgm_path:
                self.progress_changed.emit(0.7, "Aplicando legendas e trilha de fundo ao tutorial...")
                escaped_srt = str(Path(srt_path).resolve()).replace("\\", "/").replace(":", "\\:") if srt_path else None
                cmd = [ffmpeg_exe, "-y", "-i", current_video]

                if self.bgm_path:
                    cmd.extend(["-stream_loop", "-1", "-i", self.bgm_path])

                filter_parts = []
                if escaped_srt:
                    filter_parts.append(
                        f"subtitles='{escaped_srt}':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Shadow=0,MarginV=25'"
                    )

                if self.bgm_path:
                    cmd.extend([
                        "-filter_complex",
                        (f"[0:v]{filter_parts[0]}[v];" if filter_parts else "") +
                        "[1:a]volume=0.14[bgm];[0:a][bgm]amix=inputs=2:duration=first[a]",
                        "-map", "[v]" if filter_parts else "0:v",
                        "-map", "[a]",
                        "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
                        self.output_path,
                    ])
                elif filter_parts:
                    cmd.extend([
                        "-vf", filter_parts[0],
                        "-c:v", "libx264", "-c:a", "copy",
                        self.output_path,
                    ])
                else:
                    cmd.extend(["-c", "copy", self.output_path])

                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                final_path = self.output_path
            else:
                final_path = current_video

            self.progress_changed.emit(1.0, "Tutorial concluído com sucesso!")
            self.render_finished.emit(final_path)

        except Exception as e:
            self.render_error.emit(str(e))


class RecordClassView(QWidget):
    back_to_home = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_info: Optional[PresentationInfo] = None
        self.cover_image_path: Optional[str] = None
        self.bgm_path: Optional[str] = None
        self.output_video_path: Optional[str] = None

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
        self.preview_audio_output: Optional[QAudioInput] = None

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

        self.setup_view = self._build_setup_view()
        self.studio_view = self._build_studio_view()
        self.result_view = self._build_result_view()

        self.stack.addWidget(self.setup_view)   # Index 0: Configuração
        self.stack.addWidget(self.studio_view)  # Index 1: Estúdio ao Vivo
        self.stack.addWidget(self.result_view)  # Index 2: Vídeo Concluído

        self.stack.setCurrentIndex(0)

    # ----------------------------------------------------
    # SCREEN 0: SETUP / CONFIGURAÇÃO PRÉ-AULA
    # ----------------------------------------------------
    def _build_setup_view(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(14)

        # Nav bar
        nav = QHBoxLayout()
        btn_back = QPushButton("← Voltar ao Menu")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.clicked.connect(self.back_to_home.emit)

        title = QLabel("🎓 Gravar Aula - Configuração Inicial")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #a78bfa;")
        nav.addWidget(btn_back)
        nav.addWidget(title)
        nav.addStretch()
        layout.addLayout(nav)

        # Step Navigation Bar (Clickable screens without scrollbars)
        self.step_bar = QHBoxLayout()
        self.step_bar.setSpacing(6)
        self.step_buttons = []
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
            btn.clicked.connect(lambda _, i=idx: self._switch_step(i))
            self.step_bar.addWidget(btn)
            self.step_buttons.append(btn)
        layout.addLayout(self.step_bar)

        self.step_stack = QStackedWidget()

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
        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("Ex: Aula 01 - Introdução aos Conceitos...")
        box_title.addWidget(lbl_t)
        box_title.addWidget(self.edit_title)

        box_prof = QVBoxLayout()
        lbl_p = QLabel("Nome do Professor(a):")
        self.edit_teacher = QLineEdit()
        self.edit_teacher.setPlaceholderText("Ex: Prof. Kika Magalhães")
        box_prof.addWidget(lbl_p)
        box_prof.addWidget(self.edit_teacher)

        grid_info.addLayout(box_title, stretch=2)
        grid_info.addLayout(box_prof, stretch=1)
        ci_layout.addLayout(grid_info)

        # Cover Image Row
        cover_row = QHBoxLayout()
        cover_row.setSpacing(12)

        self.lbl_cover_status = QLabel("Nenhuma imagem de capa selecionada (Opcional)")
        self.lbl_cover_status.setStyleSheet("color: #94a3b8; font-size: 12px;")

        btn_pick_cover = QPushButton("Escolher Capa (16:9 / 1280x720)...")
        btn_pick_cover.setCursor(Qt.PointingHandCursor)
        btn_pick_cover.clicked.connect(self._pick_cover_image)

        btn_gen_cover = QPushButton("✨ Gerar Capa com IA...")
        btn_gen_cover.setCursor(Qt.PointingHandCursor)
        btn_gen_cover.setStyleSheet("background: #4338ca; color: #ffffff; font-weight: 600; padding: 5px 12px; border-radius: 6px;")
        btn_gen_cover.clicked.connect(self._generate_cover_ai)

        lbl_yt_hint = QLabel("💡 A capa será usada na miniatura e na vinheta de abertura automática!")
        lbl_yt_hint.setStyleSheet("color: #38bdf8; font-size: 11px;")

        cover_row.addWidget(btn_pick_cover)
        cover_row.addWidget(btn_gen_cover)
        cover_row.addWidget(self.lbl_cover_status)
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
        self.card_fmt_yt = QFrame()
        self.card_fmt_yt.setCursor(Qt.PointingHandCursor)
        cf_yt_lay = QVBoxLayout(self.card_fmt_yt)
        cf_yt_lay.setContentsMargins(14, 12, 14, 12)
        cf_yt_lay.setSpacing(6)

        self.radio_fmt_yt = QRadioButton("📺 YouTube Widescreen (16:9)")
        self.radio_fmt_yt.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
        self.radio_fmt_yt.setChecked(True)

        lbl_yt_res = QLabel("1920x1080 Full HD Horizontal")
        lbl_yt_res.setStyleSheet("color: #cbd5e1; font-size: 11px; font-weight: 600; margin-left: 22px;")

        lbl_yt_desc = QLabel("Padrão para computadores, TVs e canais do YouTube. Slides em tela cheia com avatar PIP no canto inferior direito.")
        lbl_yt_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        lbl_yt_desc.setWordWrap(True)

        cf_yt_lay.addWidget(self.radio_fmt_yt)
        cf_yt_lay.addWidget(lbl_yt_res)
        cf_yt_lay.addWidget(lbl_yt_desc)
        cf_yt_lay.addStretch()

        # YouTube Shorts Card
        self.card_fmt_shorts = QFrame()
        self.card_fmt_shorts.setCursor(Qt.PointingHandCursor)
        cf_sh_lay = QVBoxLayout(self.card_fmt_shorts)
        cf_sh_lay.setContentsMargins(14, 12, 14, 12)
        cf_sh_lay.setSpacing(6)

        self.radio_fmt_shorts = QRadioButton("🔴 YouTube Shorts (9:16)")
        self.radio_fmt_shorts.setStyleSheet("font-weight: 700; color: #f87171; font-size: 13px;")

        lbl_sh_res = QLabel("1080x1920 Vertical Dinâmico")
        lbl_sh_res.setStyleSheet("color: #cbd5e1; font-size: 11px; font-weight: 600; margin-left: 22px;")

        lbl_sh_desc = QLabel("Vídeo vertical para Shorts. Fundo dinâmico desfocado, slide no topo, avatar central e legendas acima da barra de ações.")
        lbl_sh_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        lbl_sh_desc.setWordWrap(True)

        cf_sh_lay.addWidget(self.radio_fmt_shorts)
        cf_sh_lay.addWidget(lbl_sh_res)
        cf_sh_lay.addWidget(lbl_sh_desc)
        cf_sh_lay.addStretch()

        # Instagram Reels Card
        self.card_fmt_reels = QFrame()
        self.card_fmt_reels.setCursor(Qt.PointingHandCursor)
        cf_re_lay = QVBoxLayout(self.card_fmt_reels)
        cf_re_lay.setContentsMargins(14, 12, 14, 12)
        cf_re_lay.setSpacing(6)

        self.radio_fmt_reels = QRadioButton("🟣 Instagram Reels (9:16)")
        self.radio_fmt_reels.setStyleSheet("font-weight: 700; color: #c084fc; font-size: 13px;")

        lbl_re_res = QLabel("1080x1920 com Safe Zone 4:5")
        lbl_re_res.setStyleSheet("color: #cbd5e1; font-size: 11px; font-weight: 600; margin-left: 22px;")

        lbl_re_desc = QLabel("Vídeo vertical com slide e avatar concentrados no centro (área 1080x1350) para nunca cortar na grade ou no feed do Instagram.")
        lbl_re_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        lbl_re_desc.setWordWrap(True)

        cf_re_lay.addWidget(self.radio_fmt_reels)
        cf_re_lay.addWidget(lbl_re_res)
        cf_re_lay.addWidget(lbl_re_desc)
        cf_re_lay.addStretch()

        fmt_cards_layout.addWidget(self.card_fmt_yt, stretch=1)
        fmt_cards_layout.addWidget(self.card_fmt_shorts, stretch=1)
        fmt_cards_layout.addWidget(self.card_fmt_reels, stretch=1)
        cfp_layout.addLayout(fmt_cards_layout)

        self.format_pub_group = QButtonGroup(self)
        self.format_pub_group.addButton(self.radio_fmt_yt)
        self.format_pub_group.addButton(self.radio_fmt_shorts)
        self.format_pub_group.addButton(self.radio_fmt_reels)

        self.card_fmt_yt.mousePressEvent = lambda e: self.radio_fmt_yt.setChecked(True)
        self.card_fmt_shorts.mousePressEvent = lambda e: self.radio_fmt_shorts.setChecked(True)
        self.card_fmt_reels.mousePressEvent = lambda e: self.radio_fmt_reels.setChecked(True)

        self.radio_fmt_yt.toggled.connect(self._on_video_format_changed)
        self.radio_fmt_shorts.toggled.connect(self._on_video_format_changed)
        self.radio_fmt_reels.toggled.connect(self._on_video_format_changed)

        # Vertical Layout Style Panel (Shorts & Reels)
        self.box_vert_layout = QFrame()
        self.box_vert_layout.setStyleSheet(
            "background: #0b0f19; border: 1.5px solid #3b82f6; border-radius: 8px; margin-top: 10px;"
        )
        bvl_lay = QVBoxLayout(self.box_vert_layout)
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
        self.radio_vlayout_presenter = QRadioButton("👤 Foco no Apresentador & Legendas (Sem Slides)")
        self.radio_vlayout_presenter.setStyleSheet("font-weight: 700; color: #ffffff; font-size: 12px;")
        self.radio_vlayout_presenter.setChecked(True)
        lbl_vlp_desc = QLabel("Destaque total para o clone ou sua imagem na tela vertical com fundo cinematográfico e legendas dinâmicas. Ideal para vídeos curtos e reels virais.")
        lbl_vlp_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        lbl_vlp_desc.setWordWrap(True)
        box_opt_pres.addWidget(self.radio_vlayout_presenter)
        box_opt_pres.addWidget(lbl_vlp_desc)

        # Option B: Split with Slides (Com slides)
        box_opt_split = QVBoxLayout()
        box_opt_split.setSpacing(3)
        self.radio_vlayout_split = QRadioButton("📊 Dividido com Slides (Slide no Topo + Apresentador)")
        self.radio_vlayout_split.setStyleSheet("font-weight: 700; color: #ffffff; font-size: 12px;")
        lbl_vls_desc = QLabel("Exibe o slide na metade superior e o apresentador embaixo. Ideal quando o conteúdo visual e tópicos do slide forem indispensáveis.")
        lbl_vls_desc.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        lbl_vls_desc.setWordWrap(True)
        box_opt_split.addWidget(self.radio_vlayout_split)
        box_opt_split.addWidget(lbl_vls_desc)

        v_opts_row.addLayout(box_opt_pres, stretch=1)
        v_opts_row.addLayout(box_opt_split, stretch=1)
        bvl_lay.addLayout(v_opts_row)

        self.vlayout_group = QButtonGroup(self)
        self.vlayout_group.addButton(self.radio_vlayout_presenter)
        self.vlayout_group.addButton(self.radio_vlayout_split)

        self.radio_vlayout_presenter.toggled.connect(self._on_vertical_layout_changed)
        self.radio_vlayout_split.toggled.connect(self._on_vertical_layout_changed)

        cfp_layout.addWidget(self.box_vert_layout)
        self.box_vert_layout.hide()  # hidden initially because default is youtube 16:9

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

        self.radio_intro_auto = QRadioButton("✨ Cartela Automática da Aula")
        self.radio_intro_auto.setStyleSheet("font-weight: 600; color: #f8fafc;")
        self.radio_intro_auto.setChecked(True)
        lbl_intro_auto_d = QLabel("Gera vinheta moderna de 3.5s com capa, título e professor.")
        lbl_intro_auto_d.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        bi_lay.addWidget(self.radio_intro_auto)
        bi_lay.addWidget(lbl_intro_auto_d)

        self.radio_intro_custom = QRadioButton("📁 Arquivo de Vídeo MP4 / MOV...")
        self.radio_intro_custom.setStyleSheet("font-weight: 600; color: #f8fafc;")
        bi_lay.addWidget(self.radio_intro_custom)

        row_intro_pick = QHBoxLayout()
        row_intro_pick.setContentsMargins(22, 0, 0, 0)
        row_intro_pick.setSpacing(8)
        btn_pick_intro = QPushButton("Escolher Vídeo...")
        btn_pick_intro.setCursor(Qt.PointingHandCursor)
        btn_pick_intro.setStyleSheet("background: #1e293b; color: #38bdf8; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
        btn_pick_intro.clicked.connect(self._pick_custom_intro)
        self.lbl_intro_file = QLabel("Nenhum arquivo selecionado")
        self.lbl_intro_file.setStyleSheet("color: #94a3b8; font-size: 11px;")
        row_intro_pick.addWidget(btn_pick_intro)
        row_intro_pick.addWidget(self.lbl_intro_file, stretch=1)
        bi_lay.addLayout(row_intro_pick)

        self.radio_intro_none = QRadioButton("🚫 Sem Vinheta de Abertura")
        self.radio_intro_none.setStyleSheet("font-weight: 600; color: #f8fafc;")
        lbl_intro_none_d = QLabel("Inicia a aula direto no primeiro slide sem introdução.")
        lbl_intro_none_d.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        bi_lay.addWidget(self.radio_intro_none)
        bi_lay.addWidget(lbl_intro_none_d)
        bi_lay.addStretch()

        self.group_intro = QButtonGroup(self)
        self.group_intro.addButton(self.radio_intro_auto)
        self.group_intro.addButton(self.radio_intro_custom)
        self.group_intro.addButton(self.radio_intro_none)
        self.radio_intro_auto.toggled.connect(self._on_intro_mode_changed)
        self.radio_intro_custom.toggled.connect(self._on_intro_mode_changed)
        self.radio_intro_none.toggled.connect(self._on_intro_mode_changed)

        # Right Column: Encerramento (Outro)
        box_outro = QFrame()
        box_outro.setStyleSheet("background: #0f172a; border: 1.5px solid #334155; border-radius: 10px;")
        bo_lay = QVBoxLayout(box_outro)
        bo_lay.setContentsMargins(14, 12, 14, 12)
        bo_lay.setSpacing(8)

        lbl_bo_title = QLabel("🏁 Vinheta de Encerramento (Final)")
        lbl_bo_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #c084fc;")
        bo_lay.addWidget(lbl_bo_title)

        self.radio_outro_auto = QRadioButton("✨ Cartela Final Automática")
        self.radio_outro_auto.setStyleSheet("font-weight: 600; color: #f8fafc;")
        self.radio_outro_auto.setChecked(True)
        lbl_outro_auto_d = QLabel("Gera tela final de 3.5s com 'Obrigado por assistir!' e chamada para inscrição.")
        lbl_outro_auto_d.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        bo_lay.addWidget(self.radio_outro_auto)
        bo_lay.addWidget(lbl_outro_auto_d)

        self.radio_outro_custom = QRadioButton("📁 Arquivo de Vídeo MP4 / MOV...")
        self.radio_outro_custom.setStyleSheet("font-weight: 600; color: #f8fafc;")
        bo_lay.addWidget(self.radio_outro_custom)

        row_outro_pick = QHBoxLayout()
        row_outro_pick.setContentsMargins(22, 0, 0, 0)
        row_outro_pick.setSpacing(8)
        btn_pick_outro = QPushButton("Escolher Vídeo...")
        btn_pick_outro.setCursor(Qt.PointingHandCursor)
        btn_pick_outro.setStyleSheet("background: #1e293b; color: #c084fc; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
        btn_pick_outro.clicked.connect(self._pick_custom_outro)
        self.lbl_outro_file = QLabel("Nenhum arquivo selecionado")
        self.lbl_outro_file.setStyleSheet("color: #94a3b8; font-size: 11px;")
        row_outro_pick.addWidget(btn_pick_outro)
        row_outro_pick.addWidget(self.lbl_outro_file, stretch=1)
        bo_lay.addLayout(row_outro_pick)

        self.radio_outro_none = QRadioButton("🚫 Sem Vinheta de Encerramento")
        self.radio_outro_none.setStyleSheet("font-weight: 600; color: #f8fafc;")
        lbl_outro_none_d = QLabel("Finaliza o vídeo assim que o conteúdo principal terminar.")
        lbl_outro_none_d.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 22px;")
        bo_lay.addWidget(self.radio_outro_none)
        bo_lay.addWidget(lbl_outro_none_d)
        bo_lay.addStretch()

        self.group_outro = QButtonGroup(self)
        self.group_outro.addButton(self.radio_outro_auto)
        self.group_outro.addButton(self.radio_outro_custom)
        self.group_outro.addButton(self.radio_outro_none)
        self.radio_outro_auto.toggled.connect(self._on_outro_mode_changed)
        self.radio_outro_custom.toggled.connect(self._on_outro_mode_changed)
        self.radio_outro_none.toggled.connect(self._on_outro_mode_changed)

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
        btn_next_s1.clicked.connect(lambda: self._switch_step(1))
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
        self.radio_slides = QRadioButton("📊 Apresentação de Slides (PDF)")
        self.radio_slides.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 13px;")
        self.radio_slides.setCursor(Qt.PointingHandCursor)
        self.radio_slides.setChecked(True)
        self.radio_slides.toggled.connect(self._on_format_changed)

        self.radio_screen = QRadioButton("🖥️ Gravação da Tela do Computador (Tutorial de Aplicativo)")
        self.radio_screen.setStyleSheet("font-weight: 700; color: #a78bfa; font-size: 13px;")
        self.radio_screen.setCursor(Qt.PointingHandCursor)

        self.format_group = QButtonGroup(self)
        self.format_group.addButton(self.radio_slides)
        self.format_group.addButton(self.radio_screen)

        format_row.addWidget(self.radio_slides)
        format_row.addWidget(self.radio_screen)
        format_row.addStretch()
        cf_layout.addLayout(format_row)

        self.lbl_format_desc = QLabel(
            "Apresente seus slides em PDF com narração sincronizada."
        )
        self.lbl_format_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        cf_layout.addWidget(self.lbl_format_desc)

        # Slides Picker (visible when in slides mode)
        self.card_slides = QFrame()
        self.card_slides.setStyleSheet("background: #0f172a; border-radius: 8px; border: 1px dashed #334155;")
        cs_layout = QHBoxLayout(self.card_slides)
        cs_layout.setContentsMargins(12, 8, 12, 8)
        cs_layout.setSpacing(12)

        btn_pick_pdf = QPushButton("📁 Selecionar Arquivo PDF da Aula...")
        btn_pick_pdf.setProperty("class", "primary")
        btn_pick_pdf.setCursor(Qt.PointingHandCursor)
        btn_pick_pdf.clicked.connect(self._pick_pdf)

        self.lbl_pdf_status = QLabel("Nenhum arquivo PDF carregado.")
        self.lbl_pdf_status.setStyleSheet("color: #94a3b8; font-weight: 500;")

        cs_layout.addWidget(btn_pick_pdf)
        cs_layout.addWidget(self.lbl_pdf_status)
        cs_layout.addStretch()
        cf_layout.addWidget(self.card_slides)

        # Resolution selector for screen tutorial mode
        self.box_screen_res = QWidget()
        bs_layout = QHBoxLayout(self.box_screen_res)
        bs_layout.setContentsMargins(0, 0, 0, 0)
        lbl_sres = QLabel("Resolução da Captura da Tela:")
        self.combo_screen_res = QComboBox()
        self.combo_screen_res.addItem("Tela Inteira (1920x1080 Full HD)", "1920x1080")
        self.combo_screen_res.addItem("Resolução HD (1280x720)", "1280x720")
        bs_layout.addWidget(lbl_sres)
        bs_layout.addWidget(self.combo_screen_res)
        bs_layout.addStretch()
        cf_layout.addWidget(self.box_screen_res)
        self.box_screen_res.hide()

        p2_lay.addWidget(card_format)

        # Card 2: Apresentador da Aula (Câmera Real vs Clone IA)
        self.box_presenter_mode = QFrame()
        self.box_presenter_mode.setObjectName("boxPresenterMode")
        self.box_presenter_mode.setStyleSheet("""
            QFrame#boxPresenterMode {
                background-color: #161922;
                border: 1.5px solid #2d3748;
                border-radius: 12px;
            }
        """)
        bpm_layout = QVBoxLayout(self.box_presenter_mode)
        bpm_layout.setContentsMargins(18, 14, 18, 14)
        bpm_layout.setSpacing(10)

        lbl_pm_title = QLabel("2. Como você deseja apresentar esta aula?")
        lbl_pm_title.setProperty("class", "section-title")
        bpm_layout.addWidget(lbl_pm_title)

        # Option A: Câmera Real / Ao Vivo Selection Card
        self.card_pres_live = QFrame()
        self.card_pres_live.setObjectName("cardPresLive")
        self.card_pres_live.setCursor(Qt.PointingHandCursor)
        cpl_layout = QVBoxLayout(self.card_pres_live)
        cpl_layout.setContentsMargins(14, 10, 14, 10)
        cpl_layout.setSpacing(3)

        self.radio_pres_live = QRadioButton("📹 Gravar com Câmera Real / Ao Vivo")
        self.radio_pres_live.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
        self.radio_pres_live.setCursor(Qt.PointingHandCursor)
        self.radio_pres_live.setChecked(True)
        self.radio_pres_live.toggled.connect(self._on_presenter_mode_changed)

        desc_pres_live = QLabel("Grave suas aulas com imagem real pela webcam (Picture-in-Picture) e microfone em tempo real.")
        desc_pres_live.setStyleSheet("font-size: 11px; color: #94a3b8; margin-left: 24px;")
        desc_pres_live.setWordWrap(True)

        cpl_layout.addWidget(self.radio_pres_live)
        cpl_layout.addWidget(desc_pres_live)
        self.card_pres_live.mousePressEvent = lambda e: self.radio_pres_live.setChecked(True)
        bpm_layout.addWidget(self.card_pres_live)

        # Option B: Clone Digital (Avatar IA) Selection Card
        self.card_pres_clone = QFrame()
        self.card_pres_clone.setObjectName("cardPresClone")
        self.card_pres_clone.setCursor(Qt.PointingHandCursor)
        cpc_layout = QVBoxLayout(self.card_pres_clone)
        cpc_layout.setContentsMargins(14, 10, 14, 10)
        cpc_layout.setSpacing(3)

        self.radio_pres_clone = QRadioButton("✨ Apresentar com Meu Clone Digital (Avatar IA - Sem precisar se filmar)")
        self.radio_pres_clone.setStyleSheet("font-size: 13px; font-weight: 700; color: #c084fc;")
        self.radio_pres_clone.setCursor(Qt.PointingHandCursor)

        desc_pres_clone = QLabel("A IA fala com a sua voz e anima seu rosto perfeitamente sincronizado aos slides. Não precisa se filmar!")
        desc_pres_clone.setStyleSheet("font-size: 11px; color: #cbd5e1; margin-left: 24px;")
        desc_pres_clone.setWordWrap(True)

        cpc_layout.addWidget(self.radio_pres_clone)
        cpc_layout.addWidget(desc_pres_clone)
        self.card_pres_clone.mousePressEvent = lambda e: self.radio_pres_clone.setChecked(True)
        bpm_layout.addWidget(self.card_pres_clone)

        self.presenter_group = QButtonGroup(self)
        self.presenter_group.addButton(self.radio_pres_live)
        self.presenter_group.addButton(self.radio_pres_clone)

        # Clone Digital Status & Controls Card inside presenter box
        self.card_clone_status = QFrame()
        self.card_clone_status.setStyleSheet(
            "background: #1e1b4b; border: 1.5px solid #6366f1; border-radius: 8px; padding: 8px;"
        )
        ccs_layout = QHBoxLayout(self.card_clone_status)
        ccs_layout.setContentsMargins(12, 8, 12, 8)
        ccs_layout.setSpacing(12)

        self.lbl_clone_face = QLabel("🎭")
        self.lbl_clone_face.setStyleSheet("font-size: 30px; background: #0f172a; border-radius: 24px; border: 1px solid #4338ca;")
        self.lbl_clone_face.setFixedSize(48, 48)
        self.lbl_clone_face.setAlignment(Qt.AlignCenter)

        clone_info_v = QVBoxLayout()
        clone_info_v.setSpacing(2)
        self.lbl_clone_name = QLabel("Meu Clone Digital")
        self.lbl_clone_name.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
        self.lbl_clone_engine = QLabel("Motor: Local Gratuito (Neural Edge-TTS)")
        self.lbl_clone_engine.setStyleSheet("font-size: 11px; color: #a5b4fc;")
        clone_info_v.addWidget(self.lbl_clone_name)
        clone_info_v.addWidget(self.lbl_clone_engine)

        self.btn_open_calibration = QPushButton("🎭 Calibrar / Gerenciar Clone...")
        self.btn_open_calibration.setCursor(Qt.PointingHandCursor)
        self.btn_open_calibration.setStyleSheet(
            "background: #4338ca; color: #ffffff; font-weight: 700; font-size: 12px; padding: 8px 16px; border-radius: 6px;"
        )
        self.btn_open_calibration.clicked.connect(self._open_clone_calibration)

        ccs_layout.addWidget(self.lbl_clone_face)
        ccs_layout.addLayout(clone_info_v)
        ccs_layout.addStretch()
        ccs_layout.addWidget(self.btn_open_calibration)

        bpm_layout.addWidget(self.card_clone_status)
        self.card_clone_status.hide()

        p2_lay.addWidget(self.box_presenter_mode)
        p2_lay.addStretch()

        s2_nav = QHBoxLayout()
        btn_prev_s2 = QPushButton("◀ Voltar para Informações")
        btn_prev_s2.setCursor(Qt.PointingHandCursor)
        btn_prev_s2.clicked.connect(lambda: self._switch_step(0))

        btn_next_s2 = QPushButton("Continuar para Câmera & Microfone ▶")
        btn_next_s2.setProperty("class", "primary")
        btn_next_s2.setCursor(Qt.PointingHandCursor)
        btn_next_s2.clicked.connect(lambda: self._switch_step(2))

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

        self.card_dev = QFrame()
        self.card_dev.setProperty("class", "card")
        cd_layout = QVBoxLayout(self.card_dev)
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
        self.combo_mics = QComboBox()
        audio_devs = QMediaDevices.audioInputs()
        if audio_devs:
            for d in audio_devs:
                self.combo_mics.addItem(d.description(), d)
        else:
            self.combo_mics.addItem("Microfone Padrão do Sistema", None)
        mic_box.addWidget(lbl_mic)
        mic_box.addWidget(self.combo_mics)

        # Cam
        cam_box = QVBoxLayout()
        self.chk_enable_camera = QCheckBox("Habilitar Câmera / Webcam")
        self.chk_enable_camera.setStyleSheet("font-weight: 600; color: #f8fafc;")
        self.chk_enable_camera.setChecked(False)
        self.chk_enable_camera.setToolTip("Desmarque para gravar a aula mostrando apenas os slides em tela cheia com a narração.")

        cam_hdr = QHBoxLayout()
        lbl_cam = QLabel("Dispositivo de Câmera:")
        btn_refresh_cams = QPushButton("🔄 Atualizar")
        btn_refresh_cams.setCursor(Qt.PointingHandCursor)
        btn_refresh_cams.setToolTip("Atualizar lista de câmeras conectadas")
        btn_refresh_cams.setStyleSheet("background: #1e293b; color: #38bdf8; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px;")
        btn_refresh_cams.clicked.connect(self._refresh_audio_and_video_devices)
        cam_hdr.addWidget(lbl_cam)
        cam_hdr.addStretch()
        cam_hdr.addWidget(btn_refresh_cams)

        self.combo_cams = QComboBox()
        self.combo_cams.setEnabled(False)

        def _on_cam_toggled(checked: bool):
            self.combo_cams.setEnabled(checked)
            if checked:
                self._refresh_audio_and_video_devices()

        self.chk_enable_camera.toggled.connect(_on_cam_toggled)

        cam_box.addWidget(self.chk_enable_camera)
        cam_box.addLayout(cam_hdr)
        cam_box.addWidget(self.combo_cams)

        dev_grid.addLayout(mic_box, stretch=1)
        dev_grid.addLayout(cam_box, stretch=1)
        cd_layout.addLayout(dev_grid)
        p3_lay.addWidget(self.card_dev)

        # Informative hint when Clone is active
        self.card_clone_dev_hint = QFrame()
        self.card_clone_dev_hint.setStyleSheet(
            "background: #1e1b4b; border: 1.5px solid #6366f1; border-radius: 10px; padding: 14px;"
        )
        ccdh_layout = QVBoxLayout(self.card_clone_dev_hint)
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
        btn_calib_step3.clicked.connect(self._open_clone_calibration)
        ccdh_layout.addWidget(btn_calib_step3)

        p3_lay.addWidget(self.card_clone_dev_hint)
        self.card_clone_dev_hint.hide()

        p3_lay.addStretch()

        s3_nav = QHBoxLayout()
        btn_prev_s3 = QPushButton("◀ Passo Anterior (Formato)")
        btn_prev_s3.setCursor(Qt.PointingHandCursor)
        btn_prev_s3.clicked.connect(lambda: self._switch_step(1))

        btn_next_s3 = QPushButton("Continuar para Roteiro (Teleprompter) ▶")
        btn_next_s3.setProperty("class", "primary")
        btn_next_s3.setCursor(Qt.PointingHandCursor)
        btn_next_s3.clicked.connect(lambda: self._switch_step(3))

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

        self.ct_title = QLabel("4. Roteiro da Aula para o Teleprompter (Opcional)")
        self.ct_title.setProperty("class", "section-title")
        self.ct_sub = QLabel("Cole o roteiro abaixo. Ele rolará no topo da tela durante a gravação para você ler olhando para a câmera:")
        self.ct_sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
        ct_layout.addWidget(self.ct_title)
        ct_layout.addWidget(self.ct_sub)

        self.edit_script = QTextEdit()
        self.edit_script.setFixedHeight(140)
        self.edit_script.setPlaceholderText("Cole ou dite o texto da aula aqui...")
        ct_layout.addWidget(self.edit_script)

        row_script_tools = QHBoxLayout()
        btn_load_txt = QPushButton("Carregar arquivo de texto (.txt)...")
        btn_load_txt.setCursor(Qt.PointingHandCursor)
        btn_load_txt.clicked.connect(self._pick_txt_script)

        btn_voice_script = VoicePromptButton(target_input=self.edit_script)
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

        self.audio_source_group = QButtonGroup(self)

        as_row = QHBoxLayout()
        as_row.setSpacing(16)

        self.radio_audio_tts = QRadioButton("🤖 Voz Sintetizada por IA (Edge-TTS)")
        self.radio_audio_tts.setChecked(True)
        self.radio_audio_tts.setStyleSheet("font-weight: 600; color: #f8fafc;")
        self.audio_source_group.addButton(self.radio_audio_tts, 1)

        self.radio_audio_record = QRadioButton("🎙️ Gravar Minha Própria Voz Agora")
        self.radio_audio_record.setStyleSheet("font-weight: 600; color: #34d399;")
        self.audio_source_group.addButton(self.radio_audio_record, 2)

        self.radio_audio_import = QRadioButton("📁 Importar Áudio Pronto (MP3 / WAV)")
        self.radio_audio_import.setStyleSheet("font-weight: 600; color: #c084fc;")
        self.audio_source_group.addButton(self.radio_audio_import, 3)

        as_row.addWidget(self.radio_audio_tts)
        as_row.addWidget(self.radio_audio_record)
        as_row.addWidget(self.radio_audio_import)
        as_row.addStretch()
        cas_layout.addLayout(as_row)

        # Panel 1: TTS hint
        self.panel_audio_tts = QWidget()
        pat_lay = QVBoxLayout(self.panel_audio_tts)
        pat_lay.setContentsMargins(0, 2, 0, 2)
        lbl_tts_info = QLabel("💡 A IA lerá o texto do roteiro acima com voz neural fluida em português brasileiro.")
        lbl_tts_info.setStyleSheet("color: #94a3b8; font-size: 11px;")
        pat_lay.addWidget(lbl_tts_info)
        cas_layout.addWidget(self.panel_audio_tts)

        # Panel 2: Live voice recording (Microphone)
        self.panel_audio_record = QWidget()
        par_lay = QHBoxLayout(self.panel_audio_record)
        par_lay.setContentsMargins(0, 4, 0, 4)
        par_lay.setSpacing(12)

        self.btn_record_voice = QPushButton("🔴 Iniciar Gravação da Minha Voz")
        self.btn_record_voice.setCursor(Qt.PointingHandCursor)
        self.btn_record_voice.setStyleSheet(
            "background: #dc2626; color: #ffffff; font-weight: 700; font-size: 12px; padding: 7px 16px; border-radius: 6px;"
        )
        self.btn_record_voice.clicked.connect(self._toggle_voice_recording)

        self.lbl_voice_timer = QLabel("00:00")
        self.lbl_voice_timer.setStyleSheet(
            "font-size: 14px; font-weight: 800; color: #38bdf8; background: #1e293b; padding: 4px 8px; border-radius: 6px;"
        )

        self.lbl_voice_status = QLabel("Leia o texto do roteiro acima em voz alta com seu microfone.")
        self.lbl_voice_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

        self.btn_play_voice = QPushButton("▶ Ouvir Gravação")
        self.btn_play_voice.setCursor(Qt.PointingHandCursor)
        self.btn_play_voice.setEnabled(False)
        self.btn_play_voice.setStyleSheet(
            "background: #1e293b; color: #38bdf8; font-weight: 600; font-size: 11px; padding: 6px 12px; border-radius: 6px;"
        )
        self.btn_play_voice.clicked.connect(self._play_preview_audio)

        par_lay.addWidget(self.btn_record_voice)
        par_lay.addWidget(self.lbl_voice_timer)
        par_lay.addWidget(self.lbl_voice_status, stretch=1)
        par_lay.addWidget(self.btn_play_voice)
        self.panel_audio_record.hide()
        cas_layout.addWidget(self.panel_audio_record)

        # Panel 3: Imported audio file
        self.panel_audio_import = QWidget()
        pai_lay = QHBoxLayout(self.panel_audio_import)
        pai_lay.setContentsMargins(0, 4, 0, 4)
        pai_lay.setSpacing(12)

        btn_pick_human_audio = QPushButton("📁 Selecionar Arquivo de Áudio...")
        btn_pick_human_audio.setCursor(Qt.PointingHandCursor)
        btn_pick_human_audio.setStyleSheet(
            "background: #6366f1; color: #ffffff; font-weight: 700; font-size: 12px; padding: 7px 16px; border-radius: 6px;"
        )
        btn_pick_human_audio.clicked.connect(self._pick_human_audio_file)

        self.lbl_import_audio_status = QLabel("Nenhum arquivo selecionado. Selecione um áudio em MP3 ou WAV gravado em outro dispositivo.")
        self.lbl_import_audio_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

        self.btn_play_imported = QPushButton("▶ Ouvir Áudio")
        self.btn_play_imported.setCursor(Qt.PointingHandCursor)
        self.btn_play_imported.setEnabled(False)
        self.btn_play_imported.setStyleSheet(
            "background: #1e293b; color: #38bdf8; font-weight: 600; font-size: 11px; padding: 6px 12px; border-radius: 6px;"
        )
        self.btn_play_imported.clicked.connect(self._play_preview_audio)

        pai_lay.addWidget(btn_pick_human_audio)
        pai_lay.addWidget(self.lbl_import_audio_status, stretch=1)
        pai_lay.addWidget(self.btn_play_imported)
        self.panel_audio_import.hide()
        cas_layout.addWidget(self.panel_audio_import)

        # Connect radio buttons to toggle panels
        self.radio_audio_tts.toggled.connect(self._on_audio_source_changed)
        self.radio_audio_record.toggled.connect(self._on_audio_source_changed)
        self.radio_audio_import.toggled.connect(self._on_audio_source_changed)

        ct_layout.addWidget(card_audio_src)
        p4_lay.addWidget(card_tp)
        p4_lay.addStretch()

        s4_nav = QHBoxLayout()
        btn_prev_s4 = QPushButton("◀ Passo Anterior (Dispositivos)")
        btn_prev_s4.setCursor(Qt.PointingHandCursor)
        btn_prev_s4.clicked.connect(lambda: self._switch_step(2))

        btn_next_s4 = QPushButton("Continuar para Fundo & Gravação ▶")
        btn_next_s4.setProperty("class", "primary")
        btn_next_s4.setCursor(Qt.PointingHandCursor)
        btn_next_s4.clicked.connect(lambda: self._switch_step(4))

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
        btn_pick_bgm.clicked.connect(self._pick_bgm)
        self.lbl_bgm_status = QLabel("Sem música de fundo (pode adicionar antes ou após gravar)")
        self.lbl_bgm_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
        bgm_row.addWidget(btn_pick_bgm)
        bgm_row.addWidget(self.lbl_bgm_status)
        bgm_row.addStretch()
        ce_layout.addLayout(bgm_row)

        # Subtitles row
        sub_row = QHBoxLayout()
        sub_row.setSpacing(14)
        self.chk_subtitles = QCheckBox("Gerar Legendas Automáticas com IA (Gemini)")
        self.chk_subtitles.setStyleSheet("font-weight: 600; color: #f8fafc;")

        lbl_lang = QLabel("Idioma da Legenda:")
        self.combo_sub_lang = QComboBox()
        for code, name in SUPPORTED_LANGUAGES.items():
            self.combo_sub_lang.addItem(name, code)

        sub_row.addWidget(self.chk_subtitles)
        sub_row.addWidget(lbl_lang)
        sub_row.addWidget(self.combo_sub_lang)
        sub_row.addStretch()
        ce_layout.addLayout(sub_row)

        p5_lay.addWidget(card_extras)
        p5_lay.addStretch()

        # Start Studio / Generate Buttons
        self.btn_enter_studio = QPushButton("🎬 Entrar no Estúdio de Gravação")
        self.btn_enter_studio.setProperty("class", "primary")
        self.btn_enter_studio.setFixedHeight(48)
        self.btn_enter_studio.setCursor(Qt.PointingHandCursor)
        self.btn_enter_studio.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.btn_enter_studio.clicked.connect(self._enter_live_studio)
        p5_lay.addWidget(self.btn_enter_studio)

        self.btn_generate_clone_lesson = QPushButton("✨ Gerar Videoaula com Meu Clone IA (Automático)")
        self.btn_generate_clone_lesson.setFixedHeight(48)
        self.btn_generate_clone_lesson.setCursor(Qt.PointingHandCursor)
        self.btn_generate_clone_lesson.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #ec4899); "
            "color: #ffffff; font-size: 15px; font-weight: 800; border-radius: 8px;"
        )
        self.btn_generate_clone_lesson.clicked.connect(self._start_clone_generation)
        self.btn_generate_clone_lesson.hide()
        p5_lay.addWidget(self.btn_generate_clone_lesson)

        s5_nav = QHBoxLayout()
        btn_prev_s5 = QPushButton("◀ Passo Anterior (Roteiro)")
        btn_prev_s5.setCursor(Qt.PointingHandCursor)
        btn_prev_s5.clicked.connect(lambda: self._switch_step(3))
        s5_nav.addWidget(btn_prev_s5)
        s5_nav.addStretch()
        p5_lay.addLayout(s5_nav)

        # Assemble step pages into step stack
        self.step_stack.addWidget(scroll_p1)
        self.step_stack.addWidget(page2)
        self.step_stack.addWidget(page3)
        self.step_stack.addWidget(page4)
        self.step_stack.addWidget(page5)
        layout.addWidget(self.step_stack, stretch=1)
        self._switch_step(0)
        self._update_presenter_cards_style()
        self._update_format_cards_style()

        return widget

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
    # SCREEN 1: LIVE STUDIO / ESTÚDIO AO VIVO
    # ----------------------------------------------------
    def _build_studio_view(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        # Top Bar (Back, Status, Record Timer)
        top_bar = QHBoxLayout()
        btn_leave = QPushButton("← Sair do Estúdio")
        btn_leave.setCursor(Qt.PointingHandCursor)
        btn_leave.clicked.connect(self._leave_studio)

        self.lbl_rec_indicator = QLabel("⚪ Não Gravando")
        self.lbl_rec_indicator.setStyleSheet("font-weight: 700; color: #94a3b8; font-size: 13px;")

        self.lbl_rec_timer = QLabel("00:00:00")
        self.lbl_rec_timer.setStyleSheet("font-size: 18px; font-weight: 800; color: #ffffff; padding: 2px 8px; background: #1a1e28; border-radius: 6px;")

        top_bar.addWidget(btn_leave)
        top_bar.addSpacing(16)
        top_bar.addWidget(self.lbl_rec_indicator)
        top_bar.addWidget(self.lbl_rec_timer)
        top_bar.addStretch()

        self.btn_studio_toggle_prompter = QPushButton("📝 Teleprompter Visível")
        self.btn_studio_toggle_prompter.setCursor(Qt.PointingHandCursor)
        self.btn_studio_toggle_prompter.clicked.connect(self._toggle_prompter_visibility)
        top_bar.addWidget(self.btn_studio_toggle_prompter)

        layout.addLayout(top_bar)

        # Teleprompter Widget (Top Center, eye level right below webcam)
        self.prompter = TeleprompterWidget(self)
        layout.addWidget(self.prompter, alignment=Qt.AlignHCenter)

        # Slide Area (Center Display)
        self.slide_display_frame = QFrame()
        self.slide_display_frame.setStyleSheet("background-color: #0b0d13; border: 1.5px solid #232938; border-radius: 10px;")
        sdf_layout = QVBoxLayout(self.slide_display_frame)
        sdf_layout.setContentsMargins(8, 8, 8, 8)
        sdf_layout.setAlignment(Qt.AlignCenter)

        self.lbl_live_slide = QLabel("Carregando slide...")
        self.lbl_live_slide.setAlignment(Qt.AlignCenter)
        self.lbl_live_slide.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sdf_layout.addWidget(self.lbl_live_slide)

        layout.addWidget(self.slide_display_frame, stretch=1)

        # Slide Navigation Bar
        self.nav_slide_bar_widget = QWidget()
        nav_slide_bar = QHBoxLayout(self.nav_slide_bar_widget)
        nav_slide_bar.setContentsMargins(0, 0, 0, 0)
        nav_slide_bar.setSpacing(12)

        self.btn_prev_slide = QPushButton("◀ Slide Anterior (Seta Esquerda)")
        self.btn_prev_slide.setCursor(Qt.PointingHandCursor)
        self.btn_prev_slide.clicked.connect(self._go_prev_slide)

        self.lbl_slide_counter = QLabel("Slide 1 de 1")
        self.lbl_slide_counter.setStyleSheet("font-size: 14px; font-weight: 700; color: #38bdf8; min-width: 110px;")
        self.lbl_slide_counter.setAlignment(Qt.AlignCenter)

        self.btn_next_slide = QPushButton("Próximo Slide ▶ (Seta Direita / Espaço)")
        self.btn_next_slide.setProperty("class", "primary")
        self.btn_next_slide.setCursor(Qt.PointingHandCursor)
        self.btn_next_slide.clicked.connect(self._go_next_slide)

        nav_slide_bar.addStretch()
        nav_slide_bar.addWidget(self.btn_prev_slide)
        nav_slide_bar.addWidget(self.lbl_slide_counter)
        nav_slide_bar.addWidget(self.btn_next_slide)
        nav_slide_bar.addStretch()
        layout.addWidget(self.nav_slide_bar_widget)

        # Bottom Studio Controls
        controls_frame = QFrame()
        controls_frame.setProperty("class", "card")
        cf_layout = QHBoxLayout(controls_frame)
        cf_layout.setContentsMargins(16, 10, 16, 10)
        cf_layout.setSpacing(14)

        self.btn_rec_start = QPushButton("🔴 Iniciar Gravação")
        self.btn_rec_start.setStyleSheet("background: #dc2626; color: #ffffff; font-weight: 700; font-size: 14px; padding: 10px 22px; border-radius: 8px;")
        self.btn_rec_start.setCursor(Qt.PointingHandCursor)
        self.btn_rec_start.clicked.connect(self._start_recording)

        self.btn_rec_pause = QPushButton("⏸ Pausar")
        self.btn_rec_pause.setCursor(Qt.PointingHandCursor)
        self.btn_rec_pause.setEnabled(False)
        self.btn_rec_pause.clicked.connect(self._pause_recording)

        self.btn_rec_finish = QPushButton("⏹ Finalizar Aula & Gerar Vídeo")
        self.btn_rec_finish.setProperty("class", "primary")
        self.btn_rec_finish.setStyleSheet("font-size: 14px; font-weight: 700; padding: 10px 22px;")
        self.btn_rec_finish.setCursor(Qt.PointingHandCursor)
        self.btn_rec_finish.setEnabled(False)
        self.btn_rec_finish.clicked.connect(self._finish_recording)

        cf_layout.addWidget(self.btn_rec_start)
        cf_layout.addWidget(self.btn_rec_pause)
        cf_layout.addStretch()
        cf_layout.addWidget(self.btn_rec_finish)

        layout.addWidget(controls_frame)
        return widget

    # ----------------------------------------------------
    # SCREEN 2: RESULT / RENDER VIEW
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

        self.lbl_result_title = QLabel("Processando sua Videoaula...")
        self.lbl_result_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        self.lbl_result_title.setAlignment(Qt.AlignCenter)

        self.lbl_result_status = QLabel("Aguarde a renderização dos slides e montagem do áudio...")
        self.lbl_result_status.setStyleSheet("color: #94a3b8; font-size: 13px;")
        self.lbl_result_status.setAlignment(Qt.AlignCenter)

        self.render_progress_bar = QProgressBar()
        self.render_progress_bar.setRange(0, 100)
        self.render_progress_bar.setValue(0)
        self.render_progress_bar.setFixedHeight(20)

        # Buttons (Hidden until completed)
        self.result_btn_row = QHBoxLayout()
        self.result_btn_row.setSpacing(14)
        self.result_btn_row.setAlignment(Qt.AlignCenter)

        self.btn_play_video = QPushButton("▶ Assistir Videoaula")
        self.btn_play_video.setProperty("class", "primary")
        self.btn_play_video.setCursor(Qt.PointingHandCursor)
        self.btn_play_video.clicked.connect(self._play_generated_video)

        self.btn_open_folder = QPushButton("📁 Abrir Pasta do Vídeo")
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.clicked.connect(self._open_output_folder)

        self.btn_new_class = QPushButton("✨ Gravar Nova Aula")
        self.btn_new_class.setCursor(Qt.PointingHandCursor)
        self.btn_new_class.clicked.connect(self._reset_for_new_class)

        self.result_btn_row.addWidget(self.btn_play_video)
        self.result_btn_row.addWidget(self.btn_open_folder)
        self.result_btn_row.addWidget(self.btn_new_class)
        self.result_btn_container = QWidget()
        self.result_btn_container.setLayout(self.result_btn_row)
        self.result_btn_container.hide()

        c_layout.addWidget(self.lbl_result_icon)
        c_layout.addWidget(self.lbl_result_title)
        c_layout.addWidget(self.lbl_result_status)
        c_layout.addWidget(self.render_progress_bar)
        c_layout.addWidget(self.result_btn_container)

        layout.addWidget(card)
        return widget

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
            print("Erro ao renderizar slide ao vivo:", e)

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
        self.worker.start()

    def _on_render_progress(self, frac: float, msg: str):
        val = int(frac * 100)
        self.render_progress_bar.setValue(val)
        self.lbl_result_status.setText(msg)

    def _on_render_finished(self, video_path: str):
        self.output_video_path = video_path
        self.render_progress_bar.setValue(100)
        self.lbl_result_icon.setText("🎉")
        if self.visual_mode == "screen":
            self.lbl_result_title.setText("Tutorial Gravado com Sucesso!")
        else:
            self.lbl_result_title.setText("Videoaula Gerada com Sucesso!")
        self.lbl_result_status.setText(f"Arquivo salvo em:\n{video_path}")
        self.result_btn_container.show()

    def _on_render_error(self, err: str):
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
