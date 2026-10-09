"""Background render workers for the Record Class view.

Extracted from ``app.ui.views.record_class_view`` so the view file stays
focused on UI wiring. Import the workers from here going forward.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from app.core.avatar_video_generator import generate_avatar_speech, render_avatar_video
from app.core.class_video_builder import build_class_video
from app.core.ffmpeg_utils import (
    get_ffmpeg_paths,
    get_video_duration,
    run_process_cancellable,
)
from app.core.meeting_recorder import extract_audio_from_video
from app.core.pdf_processor import render_all_slides_to_dir
from app.core.slide_timing import calculate_slide_durations_from_script
from app.core.subtitles_generator import generate_subtitles_with_gemini

__all__ = [
    "CloneLessonRenderWorker",
    "ClassVideoRenderWorker",
    "TutorialPostProcessWorker",
]

logger = logging.getLogger(__name__)


class CloneLessonRenderWorker(QThread):
    progress_changed = Signal(float, str)
    render_finished = Signal(str)
    render_error = Signal(str)
    render_cancelled = Signal()

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
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            import tempfile
            temp_dir = Path(tempfile.mkdtemp(prefix="clone_lesson_"))

            self.progress_changed.emit(0.05, "Extraindo slides da apresentação em alta definição...")
            images = render_all_slides_to_dir(
                file_path=self.pdf_path,
                output_dir=temp_dir,
                target_dpi=150,
                cancel_check=lambda: self._cancelled,
            )
            slide_count = len(images)
            if slide_count == 0:
                raise RuntimeError("Nenhum slide encontrado no arquivo PDF fornecido.")

            if self._cancelled:
                self.render_cancelled.emit()
                return
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

            if self._cancelled:
                self.render_cancelled.emit()
                return
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
            durations = calculate_slide_durations_from_script(
                self.script_text, slide_count, total_dur
            )

            if self._cancelled:
                self.render_cancelled.emit()
                return
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
                    logger.warning("Aviso ao gerar legendas para clone: %s", e)
                    srt_path = None

            if self._cancelled:
                self.render_cancelled.emit()
                return
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
                cancel_check=lambda: self._cancelled,
            )

            self.progress_changed.emit(1.0, "Videoaula com Clone Digital concluída com sucesso!")
            self.render_finished.emit(out_video)

        except InterruptedError:
            self.render_cancelled.emit()
        except Exception as e:
            self.render_error.emit(str(e))


class ClassVideoRenderWorker(QThread):
    progress_changed = Signal(float, str)
    render_finished = Signal(str)
    render_error = Signal(str)
    render_cancelled = Signal()

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
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            import tempfile
            temp_dir = Path(tempfile.mkdtemp(prefix="class_render_"))

            self.progress_changed.emit(0.05, "Extraindo slides da apresentação...")
            images = render_all_slides_to_dir(
                file_path=self.pdf_path,
                output_dir=temp_dir,
                target_dpi=150,
                cancel_check=lambda: self._cancelled,
            )

            if self._cancelled:
                self.render_cancelled.emit()
                return
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
                    logger.warning("Falha ao gerar legendas (%s), continuando sem legendas...", e)
                    srt_path = None

            if self._cancelled:
                self.render_cancelled.emit()
                return
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
                cancel_check=lambda: self._cancelled,
            )

            self.progress_changed.emit(1.0, "Vídeo concluído!")
            self.render_finished.emit(out_video)

        except InterruptedError:
            self.render_cancelled.emit()
        except Exception as e:
            self.render_error.emit(str(e))


class TutorialPostProcessWorker(QThread):
    progress_changed = Signal(float, str)
    render_finished = Signal(str)
    render_error = Signal(str)
    render_cancelled = Signal()

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
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            import tempfile
            ffmpeg_exe, _ = get_ffmpeg_paths()
            current_video = self.raw_video_path

            if self._cancelled:
                self.render_cancelled.emit()
                return
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
                    logger.warning("Aviso: Falha nas legendas do tutorial: %s", e)
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

                completed = run_process_cancellable(cmd, cancel_check=lambda: self._cancelled)
                if completed.returncode != 0:
                    raise subprocess.CalledProcessError(completed.returncode, cmd)
                final_path = self.output_path
            else:
                final_path = current_video

            self.progress_changed.emit(1.0, "Tutorial concluído com sucesso!")
            self.render_finished.emit(final_path)

        except InterruptedError:
            self.render_cancelled.emit()
        except Exception as e:
            self.render_error.emit(str(e))

