import time
import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, QThread
from PySide6.QtWidgets import QPushButton, QTextEdit, QLineEdit, QWidget, QMessageBox
from PySide6.QtMultimedia import (
    QMediaCaptureSession,
    QAudioInput,
    QMediaRecorder,
    QMediaDevices,
)

from app.core.voice_dictation import transcribe_voice_prompt


class VoiceTranscriptionWorker(QThread):
    transcription_done = Signal(str)
    transcription_failed = Signal(str)

    def __init__(self, audio_path: str, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path

    def run(self):
        try:
            text = transcribe_voice_prompt(self.audio_path)
            self.transcription_done.emit(text)
        except Exception as e:
            self.transcription_failed.emit(str(e))


class VoicePromptButton(QPushButton):
    """
    Interactive microphone button that records spoken audio from the user,
    transcribes it with Gemini Flash, and inserts it into a QTextEdit or QLineEdit prompt.
    """
    transcription_completed = Signal(str)

    def __init__(self, target_input: Optional[QWidget] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.target_input = target_input
        self.is_recording = False
        self.temp_audio_path: Optional[str] = None
        self.worker: Optional[VoiceTranscriptionWorker] = None

        # Media Capture Session
        self.capture_session = QMediaCaptureSession(self)
        self.audio_input = QAudioInput(self)
        self.capture_session.setAudioInput(self.audio_input)
        self.recorder = QMediaRecorder(self)
        self.capture_session.setRecorder(self.recorder)

        # Set default mic if available
        default_mic = QMediaDevices.defaultAudioInput()
        if default_mic:
            self.audio_input.setDevice(default_mic)

        self._apply_idle_style()
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Clique para falar seu prompt pelo microfone ao invés de digitar")
        self.clicked.connect(self._toggle_recording)

    def _apply_idle_style(self):
        self.setText("🎙️ Falar Prompt")
        self.setStyleSheet("""
            QPushButton {
                background-color: #1e1b4b;
                border: 1px solid #4338ca;
                color: #c7d2fe;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #312e81;
                color: #ffffff;
            }
        """)

    def _apply_recording_style(self):
        self.setText("🔴 Gravando... (Clique p/ Parar)")
        self.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                border: 1px solid #ef4444;
                color: #ffffff;
                font-weight: 700;
                font-size: 11px;
                padding: 4px 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """)

    def _apply_processing_style(self):
        self.setText("⏳ Transcrevendo IA...")
        self.setStyleSheet("""
            QPushButton {
                background-color: #2e1065;
                border: 1px solid #7c3aed;
                color: #e9d5ff;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 10px;
                border-radius: 6px;
            }
        """)

    def _toggle_recording(self):
        if not self.is_recording:
            # Start Recording
            timestamp = int(time.time() * 1000)
            self.temp_audio_path = str(Path(tempfile.gettempdir()) / f"voice_prompt_{timestamp}.m4a")
            self.recorder.setOutputLocation(QUrl.fromLocalFile(self.temp_audio_path))
            try:
                self.recorder.record()
                self.is_recording = True
                self._apply_recording_style()
            except Exception as e:
                QMessageBox.warning(self, "Erro no Microfone", f"Não foi possível iniciar a gravação do microfone:\n{e}")
        else:
            # Stop Recording & Transcribe
            self.is_recording = False
            try:
                self.recorder.stop()
            except Exception:
                pass

            self._apply_processing_style()
            self.setEnabled(False)

            # Wait 200ms for file buffer flush then launch worker
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, self._start_transcription)

    def _start_transcription(self):
        if not self.temp_audio_path or not Path(self.temp_audio_path).exists() or Path(self.temp_audio_path).stat().st_size < 500:
            self._apply_idle_style()
            self.setEnabled(True)
            QMessageBox.information(self, "Áudio Curto", "Nenhum áudio suficiente foi detectado. Fale com clareza no microfone.")
            return

        self.worker = VoiceTranscriptionWorker(self.temp_audio_path, self)
        self.worker.transcription_done.connect(self._on_transcription_success)
        self.worker.transcription_failed.connect(self._on_transcription_error)
        self.worker.start()

    def _on_transcription_success(self, text: str):
        self.setEnabled(True)
        self._apply_idle_style()

        if self.target_input and text.strip():
            if isinstance(self.target_input, QTextEdit):
                existing = self.target_input.toPlainText().strip()
                if existing:
                    self.target_input.setPlainText(f"{existing}\n{text.strip()}")
                else:
                    self.target_input.setPlainText(text.strip())
            elif isinstance(self.target_input, QLineEdit):
                existing = self.target_input.text().strip()
                if existing:
                    self.target_input.setText(f"{existing} {text.strip()}")
                else:
                    self.target_input.setText(text.strip())

        self.transcription_completed.emit(text)

        # Cleanup temp audio
        if self.temp_audio_path and Path(self.temp_audio_path).exists():
            try:
                Path(self.temp_audio_path).unlink()
            except Exception:
                pass

    def _on_transcription_error(self, err: str):
        self.setEnabled(True)
        self._apply_idle_style()
        QMessageBox.warning(
            self,
            "Transcrição de Voz",
            f"Não foi possível converter a fala em texto:\n{err}\n\n"
            "Verifique se sua chave da API do Gemini está configurada corretamente."
        )
