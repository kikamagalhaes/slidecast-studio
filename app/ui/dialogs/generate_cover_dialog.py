import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QComboBox,
    QProgressBar,
    QMessageBox,
    QFrame,
)

from app.core.image_generator import generate_slide_image, enhance_slide_prompt_with_gemini
from app.ui.voice_prompt_button import VoicePromptButton


class CoverGenerationWorker(QThread):
    finished_success = Signal(str)
    finished_error = Signal(str)

    def __init__(self, prompt: str, aspect_ratio: str, output_path: str):
        super().__init__()
        self.prompt = prompt
        self.aspect_ratio = aspect_ratio
        self.output_path = output_path

    def run(self):
        try:
            if self.aspect_ratio == "1:1":
                width, height = 1080, 1080
            else:
                width, height = 1280, 720

            img_path = generate_slide_image(
                self.prompt,
                self.output_path,
                width=width,
                height=height,
                timeout=16,
            )
            self.finished_success.emit(img_path)
        except Exception as e:
            self.finished_error.emit(str(e))


class GenerateCoverDialog(QDialog):
    """
    Dialog allowing the user to generate custom high-resolution covers
    using AI (Flux/Gemini/DALL-E) from a detailed prompt.
    """

    def __init__(self, parent=None, default_topic: str = "", default_aspect: str = "16:9"):
        super().__init__(parent)
        self.setWindowTitle("Gerar Capa com IA")
        self.resize(600, 560)
        self.setMinimumSize(520, 500)

        self.generated_cover_path: Optional[str] = None
        self.worker: Optional[CoverGenerationWorker] = None
        self.default_topic = default_topic
        self.default_aspect = default_aspect

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header
        lbl_title = QLabel("🎨 Criador de Capa Inteligente")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #38bdf8;")
        lbl_desc = QLabel(
            "Descreva como deseja a arte da capa e a IA criará uma imagem de altíssima qualidade."
        )
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_desc)

        # Prompt input frame
        prompt_frame = QFrame()
        prompt_frame.setProperty("class", "card")
        pf_layout = QVBoxLayout(prompt_frame)
        pf_layout.setContentsMargins(14, 14, 14, 14)
        pf_layout.setSpacing(10)

        self.edit_prompt = QTextEdit()
        self.edit_prompt.setPlaceholderText(
            "Ex: Capa profissional e elegante para podcast/aula sobre Tecnologia e Inovação. "
            "Fundo escuro em tons de azul escuro e roxo neon, iluminação de estúdio suave, "
            "composição moderna e limpa, visual cinematográfico de alto padrão."
        )
        if self.default_topic:
            self.edit_prompt.setPlainText(
                f"Capa profissional moderna para '{self.default_topic}', iluminação suave de estúdio, estética minimalista e elegante."
            )
        self.edit_prompt.setFixedHeight(95)

        header_p = QHBoxLayout()
        lbl_p = QLabel("Descrição da Capa (Prompt):")
        lbl_p.setStyleSheet("font-weight: 600; color: #f8fafc;")
        header_p.addWidget(lbl_p)
        header_p.addStretch()

        self.btn_mic = VoicePromptButton(target_input=self.edit_prompt)
        header_p.addWidget(self.btn_mic)

        btn_enhance = QPushButton("✨ Aprimorar com Gemini")
        btn_enhance.setCursor(Qt.PointingHandCursor)
        btn_enhance.setStyleSheet("font-size: 11px; padding: 4px 10px;")
        btn_enhance.clicked.connect(self._enhance_prompt)
        header_p.addWidget(btn_enhance)
        pf_layout.addLayout(header_p)

        pf_layout.addWidget(self.edit_prompt)

        # Ratio selector
        row_ratio = QHBoxLayout()
        lbl_ratio = QLabel("Proporção da Capa:")
        self.combo_ratio = QComboBox()
        self.combo_ratio.addItem("16:9 Widescreen (1280x720) - YouTube / Aulas / Vídeos", "16:9")
        self.combo_ratio.addItem("1:1 Quadrado (1080x1080) - Podcasts / Spotify / Instagram", "1:1")
        if self.default_aspect == "1:1":
            self.combo_ratio.setCurrentIndex(1)
        row_ratio.addWidget(lbl_ratio)
        row_ratio.addWidget(self.combo_ratio)
        row_ratio.addStretch()
        pf_layout.addLayout(row_ratio)

        layout.addWidget(prompt_frame)

        # Preview Frame
        self.preview_frame = QFrame()
        self.preview_frame.setStyleSheet(
            "background-color: #0b0d13; border: 1.5px dashed #283042; border-radius: 8px;"
        )
        self.preview_frame.setFixedHeight(180)
        pv_layout = QVBoxLayout(self.preview_frame)
        pv_layout.setContentsMargins(6, 6, 6, 6)
        pv_layout.setAlignment(Qt.AlignCenter)

        self.lbl_preview = QLabel("Pré-visualização da Capa aparecerá aqui")
        self.lbl_preview.setStyleSheet("color: #64748b; font-size: 12px;")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        pv_layout.addWidget(self.lbl_preview)
        layout.addWidget(self.preview_frame)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Action buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(12)

        self.btn_generate = QPushButton("🎨 Gerar Imagem com IA")
        self.btn_generate.setProperty("class", "primary")
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.setFixedHeight(38)
        self.btn_generate.clicked.connect(self._start_generation)

        self.btn_use_cover = QPushButton("✓ Usar esta Imagem como Capa")
        self.btn_use_cover.setCursor(Qt.PointingHandCursor)
        self.btn_use_cover.setFixedHeight(38)
        self.btn_use_cover.setStyleSheet("background-color: #10b981; color: white; font-weight: 700;")
        self.btn_use_cover.setEnabled(False)
        self.btn_use_cover.clicked.connect(self.accept)

        btn_cancel = QPushButton("Fechar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(38)
        btn_cancel.clicked.connect(self.reject)

        btn_bar.addWidget(self.btn_generate)
        btn_bar.addWidget(self.btn_use_cover)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_cancel)
        layout.addLayout(btn_bar)

    def _enhance_prompt(self):
        text = self.edit_prompt.toPlainText().strip()
        if not text:
            text = self.default_topic or "Capa Profissional Moderna"
        enhanced = enhance_slide_prompt_with_gemini(text, 1, 1, self.default_topic)
        self.edit_prompt.setPlainText(enhanced)

    def _start_generation(self):
        prompt = self.edit_prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Aviso", "Por favor, digite uma descrição para a capa.")
            return

        aspect = self.combo_ratio.currentData()
        timestamp = int(time.time())
        dest_dir = Path.home() / "SlideCast_Materials" / "covers"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = str(dest_dir / f"capa_{timestamp}.jpg")

        self.btn_generate.setEnabled(False)
        self.progress_bar.show()
        self.lbl_preview.setText("Gerando arte em altíssima resolução via IA...")

        self.worker = CoverGenerationWorker(prompt, aspect, dest_file)
        self.worker.finished_success.connect(self._on_success)
        self.worker.finished_error.connect(self._on_error)
        self.worker.start()

    def _on_success(self, img_path: str):
        self.generated_cover_path = img_path
        self.progress_bar.hide()
        self.btn_generate.setEnabled(True)
        self.btn_use_cover.setEnabled(True)

        try:
            pix = QPixmap(img_path)
            if not pix.isNull():
                target_size = self.preview_frame.size() - QSize(16, 16)
                if target_size.width() < 50 or target_size.height() < 50:
                    target_size = QSize(400, 220)
                scaled = pix.scaled(
                    target_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.lbl_preview.setText("")
                self.lbl_preview.setPixmap(scaled)
                self.preview_frame.setStyleSheet(
                    "background-color: #000000; border: 2px solid #10b981; border-radius: 8px;"
                )
            else:
                self.lbl_preview.setText(f"✓ Imagem gerada: {Path(img_path).name}")
        except Exception as e:
            print("Aviso ao exibir preview:", e)
            self.lbl_preview.setText(f"✓ Imagem gerada com sucesso!")

    def _on_error(self, err: str):
        self.progress_bar.hide()
        self.btn_generate.setEnabled(True)
        self.lbl_preview.setText("Falha ao gerar imagem.")
        QMessageBox.critical(self, "Erro na Geração", f"Não foi possível gerar a capa:\n{err}")

    def get_generated_image_path(self) -> Optional[str]:
        return self.generated_cover_path
