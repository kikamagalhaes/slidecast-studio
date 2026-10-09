import logging
import time
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

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
    QScrollArea,
    QWidget,
)

from app.core.image_generator import (
    generate_slide_image,
    enhance_background_prompt_with_gemini,
)
from app.ui.voice_prompt_button import VoicePromptButton


# Preset styles specifically tailored for professional background backdrops
BACKGROUND_PRESETS: Dict[str, Dict[str, str]] = {
    "office": {
        "title": "🏢 Escritório Executivo",
        "prompt": (
            "Modern luxury executive office backdrop with large glass windows overlooking a city skyline at dusk, "
            "warm interior accent lamps, dark walnut shelves, sleek architecture, shallow depth of field, soft bokeh, "
            "empty room ready for presenter, 8k cinematic broadcast quality, no people"
        ),
    },
    "studio": {
        "title": "🎙️ Estúdio Acústico Minimalista",
        "prompt": (
            "Premium podcast and recording studio backdrop, dark vertical acoustic wood slat wall, "
            "subtle neon purple and ice blue LED edge lighting, minimalist floating shelf, soft studio depth of field, "
            "empty background for video recording, high-end broadcast aesthetic, no people"
        ),
    },
    "library": {
        "title": "📚 Biblioteca Clássica de Luxo",
        "prompt": (
            "Elegant dark mahogany library backdrop, rich bookshelves filled with vintage and modern books, "
            "warm ambient brass desk lamp lighting, soft blurred background with beautiful bokeh, "
            "intellectual academic prestige, empty scene for presenter, no people"
        ),
    },
    "clean": {
        "title": "🌿 Ambiente Clean & Luz Natural",
        "prompt": (
            "Contemporary bright Scandinavian loft interior backdrop, warm oak wooden textures, "
            "delicate green indoor plants (monstera, fiddle leaf fig), soft natural daylight through sheer curtains, "
            "airy minimalist aesthetic, shallow depth of field, empty room, no people"
        ),
    },
    "tech": {
        "title": "🔮 High-Tech Tecnológico Suave",
        "prompt": (
            "Sleek technological studio backdrop with dark brushed aluminum and tinted glass panels, "
            "subtle glowing cyan and deep violet geometric lighting, modern fintech keynote aesthetic, "
            "empty backdrop, cinematic lighting, no people"
        ),
    },
    "gradient": {
        "title": "🎨 Gradiente Studio 3D",
        "prompt": (
            "Luxurious abstract 3D studio backdrop with smooth dark midnight blue and royal violet gradients, "
            "sculptural flowing silk curves, soft volumetric studio spotlighting, ultra-clean high-end advertising aesthetic, "
            "empty background, no people"
        ),
    },
}


class BackgroundGenerationWorker(QThread):
    finished_success = Signal(str)
    finished_error = Signal(str)

    def __init__(self, prompt: str, aspect_ratio: str, output_path: str):
        super().__init__()
        self.prompt = prompt
        self.aspect_ratio = aspect_ratio
        self.output_path = output_path

    def run(self):
        try:
            if self.aspect_ratio == "9:16":
                width, height = 720, 1280
            elif self.aspect_ratio == "1:1":
                width, height = 1080, 1080
            else:
                width, height = 1280, 720

            img_path = generate_slide_image(
                prompt=self.prompt,
                output_path=self.output_path,
                width=width,
                height=height,
                timeout=18,
            )
            self.finished_success.emit(img_path)
        except Exception as e:
            self.finished_error.emit(str(e))


class GenerateBackgroundDialog(QDialog):
    """
    Dialog allowing the user to generate high-resolution custom background scenes
    using AI (Flux/Gemini) tailored for video recording (Clone and Natural).
    """

    def __init__(self, parent=None, default_aspect: str = "16:9", initial_prompt: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Criar Cenário / Fundo com IA")
        self.resize(680, 620)
        self.setMinimumSize(580, 540)

        self.default_aspect = default_aspect
        self.initial_prompt = initial_prompt
        self.generated_background_path: Optional[str] = None
        self.worker: Optional[BackgroundGenerationWorker] = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        # Header
        lbl_title = QLabel("✨ Criador de Cenário / Fundo com IA")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #38bdf8;")
        lbl_desc = QLabel(
            "Gere cenários profissionais (estúdios, escritórios, bibliotecas) para servir de fundo "
            "ao seu vídeo, tanto para gravação com Câmera Real quanto para o Clone Digital."
        )
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_desc)

        # Presets Bar
        lbl_presets = QLabel("Estilos Recomendados (Clique para aplicar):")
        lbl_presets.setStyleSheet("font-weight: 700; color: #cbd5e1; font-size: 12px; margin-top: 4px;")
        layout.addWidget(lbl_presets)

        preset_scroll = QScrollArea()
        preset_scroll.setWidgetResizable(True)
        preset_scroll.setFixedHeight(48)
        preset_scroll.setFrameShape(QFrame.NoFrame)
        preset_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        preset_container = QWidget()
        preset_container.setStyleSheet("background: transparent;")
        preset_lay = QHBoxLayout(preset_container)
        preset_lay.setContentsMargins(0, 0, 0, 0)
        preset_lay.setSpacing(8)

        for key, p_data in BACKGROUND_PRESETS.items():
            btn_p = QPushButton(p_data["title"])
            btn_p.setCursor(Qt.PointingHandCursor)
            btn_p.setStyleSheet(
                "background: #1e293b; color: #f1f5f9; font-size: 11px; font-weight: 600; "
                "padding: 6px 12px; border-radius: 6px; border: 1px solid #334155;"
            )
            prompt_val = p_data["prompt"]
            btn_p.clicked.connect(lambda _, p=prompt_val: self._apply_preset(p))
            preset_lay.addWidget(btn_p)

        preset_lay.addStretch()
        preset_scroll.setWidget(preset_container)
        layout.addWidget(preset_scroll)

        # Prompt input frame
        prompt_frame = QFrame()
        prompt_frame.setProperty("class", "card")
        pf_layout = QVBoxLayout(prompt_frame)
        pf_layout.setContentsMargins(14, 12, 14, 12)
        pf_layout.setSpacing(8)

        header_p = QHBoxLayout()
        lbl_p = QLabel("Descrição do Cenário de Fundo (Prompt):")
        lbl_p.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 12px;")
        header_p.addWidget(lbl_p)
        header_p.addStretch()

        self.btn_mic = VoicePromptButton(target_input=None)
        self.btn_mic.setToolTip("Ditar ideia do cenário pelo microfone")
        header_p.addWidget(self.btn_mic)

        btn_enhance = QPushButton("✨ Aprimorar Cenário com Gemini")
        btn_enhance.setCursor(Qt.PointingHandCursor)
        btn_enhance.setStyleSheet(
            "background: #312e81; color: #c7d2fe; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 6px;"
        )
        btn_enhance.clicked.connect(self._enhance_prompt)
        header_p.addWidget(btn_enhance)
        pf_layout.addLayout(header_p)

        self.edit_prompt = QTextEdit()
        default_txt = self.initial_prompt or BACKGROUND_PRESETS["studio"]["prompt"]
        self.edit_prompt.setPlainText(default_txt)
        self.edit_prompt.setFixedHeight(85)
        self.edit_prompt.setPlaceholderText(
            "Descreva como deseja o cenário de fundo. Ex: Estúdio moderno em tons de azul escuro e madeira, iluminação suave..."
        )
        pf_layout.addWidget(self.edit_prompt)
        self.btn_mic.target_input = self.edit_prompt

        # Ratio selector
        row_ratio = QHBoxLayout()
        lbl_ratio = QLabel("Proporção do Cenário:")
        lbl_ratio.setStyleSheet("font-weight: 600; color: #cbd5e1; font-size: 12px;")
        self.combo_ratio = QComboBox()
        self.combo_ratio.addItem("16:9 Widescreen (1280x720 / 1920x1080) - YouTube e Aulas Horizontais", "16:9")
        self.combo_ratio.addItem("9:16 Vertical (720x1280 / 1080x1920) - YouTube Shorts e Instagram Reels", "9:16")
        self.combo_ratio.addItem("1:1 Quadrado (1080x1080) - Formato Padrão Redes", "1:1")
        if self.default_aspect == "9:16":
            self.combo_ratio.setCurrentIndex(1)
        elif self.default_aspect == "1:1":
            self.combo_ratio.setCurrentIndex(2)
        else:
            self.combo_ratio.setCurrentIndex(0)

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

        self.lbl_preview = QLabel("A pré-visualização do cenário aparecerá aqui após a geração")
        self.lbl_preview.setStyleSheet("color: #64748b; font-size: 12px;")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        pv_layout.addWidget(self.lbl_preview)
        layout.addWidget(self.preview_frame)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Action buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(12)

        self.btn_generate = QPushButton("🎨 Gerar Cenário com IA")
        self.btn_generate.setProperty("class", "primary")
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.setFixedHeight(38)
        self.btn_generate.clicked.connect(self._start_generation)

        self.btn_use_bg = QPushButton("✓ Usar como Cenário de Fundo")
        self.btn_use_bg.setCursor(Qt.PointingHandCursor)
        self.btn_use_bg.setFixedHeight(38)
        self.btn_use_bg.setStyleSheet(
            "background-color: #10b981; color: white; font-weight: 700; padding: 0 16px; border-radius: 6px;"
        )
        self.btn_use_bg.setEnabled(False)
        self.btn_use_bg.clicked.connect(self.accept)

        btn_cancel = QPushButton("Fechar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(38)
        btn_cancel.clicked.connect(self.reject)

        btn_bar.addWidget(self.btn_generate)
        btn_bar.addWidget(self.btn_use_bg)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_cancel)
        layout.addLayout(btn_bar)

    def _apply_preset(self, prompt: str):
        self.edit_prompt.setPlainText(prompt)

    def _enhance_prompt(self):
        text = self.edit_prompt.toPlainText().strip()
        aspect = self.combo_ratio.currentData() or "16:9"
        if not text:
            text = "Modern professional recording studio background"
        enhanced = enhance_background_prompt_with_gemini(text, format_ratio=aspect)
        self.edit_prompt.setPlainText(enhanced)

    def _start_generation(self):
        prompt = self.edit_prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Aviso", "Por favor, digite ou selecione uma descrição para o cenário.")
            return

        aspect = self.combo_ratio.currentData() or "16:9"
        timestamp = int(time.time())
        dest_dir = Path.home() / "SlideCast_Materials" / "backgrounds"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = str(dest_dir / f"fundo_{timestamp}_{aspect.replace(':', 'x')}.jpg")

        self.btn_generate.setEnabled(False)
        self.progress_bar.show()
        self.lbl_preview.setText("Gerando cenário de estúdio realista via IA...")

        self.worker = BackgroundGenerationWorker(prompt, aspect, dest_file)
        self.worker.finished_success.connect(self._on_success)
        self.worker.finished_error.connect(self._on_error)
        self.worker.start()

    def _on_success(self, img_path: str):
        self.generated_background_path = img_path
        self.progress_bar.hide()
        self.btn_generate.setEnabled(True)
        self.btn_use_bg.setEnabled(True)

        try:
            pix = QPixmap(img_path)
            if not pix.isNull():
                target_size = self.preview_frame.size() - QSize(16, 16)
                if target_size.width() < 50 or target_size.height() < 50:
                    target_size = QSize(400, 160)
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
                self.lbl_preview.setText(f"✓ Cenário gerado: {Path(img_path).name}")
        except Exception as e:
            logger.warning("Aviso exibindo preview do fundo: %s", e)
            self.lbl_preview.setText("✓ Cenário gerado com sucesso!")

    def _on_error(self, err: str):
        self.progress_bar.hide()
        self.btn_generate.setEnabled(True)
        self.lbl_preview.setText("Falha ao gerar cenário.")
        QMessageBox.critical(self, "Erro na Geração", f"Não foi possível gerar o cenário de fundo:\n{err}")

    def get_generated_image_path(self) -> Optional[str]:
        return self.generated_background_path
