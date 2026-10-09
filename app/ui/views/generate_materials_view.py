import os
import sys
import time
import subprocess
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QSpinBox,
    QProgressBar,
    QScrollArea,
    QFrame,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QSizePolicy,
    QStackedWidget,
)

from app.core.config_manager import get_gemini_api_key
from app.core.pdf_processor import inspect_pdf, render_thumbnail
from app.core.ebook_generator import generate_class_ebook
from app.core.image_generator import (
    generate_slide_image,
    create_pdf_from_images,
    enhance_slide_prompt_with_gemini,
)
from app.ui.voice_prompt_button import VoicePromptButton


class EbookGenerationWorker(QThread):
    progress_changed = Signal(float, str)
    finished_success = Signal(str)
    finished_error = Signal(str)

    def __init__(
        self,
        title: str,
        teacher: str,
        audio_path: str,
        slide_images: List[str],
        output_pdf: str,
    ):
        super().__init__()
        self.title = title
        self.teacher = teacher
        self.audio_path = audio_path
        self.slide_images = slide_images
        self.output_pdf = output_pdf

    def run(self):
        try:
            def callback(pct, msg):
                # Core reports 0.0-1.0; this view's bar uses 0-100.
                self.progress_changed.emit(pct * 100.0, msg)

            res = generate_class_ebook(
                title=self.title,
                teacher=self.teacher,
                audio_path=self.audio_path,
                slide_images=self.slide_images,
                output_pdf_path=self.output_pdf,
                progress_callback=callback,
            )
            self.finished_success.emit(res)
        except Exception as e:
            self.finished_error.emit(str(e))


class SlideCardWidget(QFrame):
    enhance_requested = Signal(int)

    def __init__(self, slide_num: int, total: int, parent=None):
        super().__init__(parent)
        self.slide_num = slide_num
        self.setProperty("class", "card")
        self.setStyleSheet(
            "QFrame { background-color: #171b26; border: 1px solid #283042; border-radius: 10px; padding: 12px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Content area prompt text edit (instantiated first for target binding)
        self.text_prompt = QTextEdit()
        self.text_prompt.setPlaceholderText(
            f"Descreva detalhadamente o conteúdo visual do Slide {slide_num}...\n"
            f"Ex: Apresentação moderna 16:9 sobre o conceito principal, estética minimalista, "
            f"tipografia nítida, iluminação cinematográfica sutil, estilo NotebookLM / Apple Keynote."
        )
        self.text_prompt.setFixedHeight(95)
        self.text_prompt.setStyleSheet(
            "background-color: #0f121a; border: 1px solid #232938; border-radius: 6px; color: #f8fafc; font-size: 12px; padding: 8px;"
        )

        # Header of card
        header = QHBoxLayout()
        self.lbl_title = QLabel(f"Slide {slide_num} de {total}")
        self.lbl_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #38bdf8;")
        header.addWidget(self.lbl_title)

        header.addStretch()

        self.btn_mic = VoicePromptButton(target_input=self.text_prompt)
        header.addWidget(self.btn_mic)

        self.btn_enhance = QPushButton("✨ Aprimorar com IA")
        self.btn_enhance.setCursor(Qt.PointingHandCursor)
        self.btn_enhance.setToolTip("Usa o Gemini para expandir este prompt em uma descrição visual detalhada e profissional.")
        self.btn_enhance.setStyleSheet("font-size: 11px; padding: 4px 10px;")
        self.btn_enhance.clicked.connect(lambda: self.enhance_requested.emit(self.slide_num))
        header.addWidget(self.btn_enhance)

        layout.addLayout(header)

        # Content area: Prompt text edit + Preview thumbnail
        body_layout = QHBoxLayout()
        body_layout.setSpacing(12)
        body_layout.addWidget(self.text_prompt, stretch=3)

        # Thumbnail preview
        self.thumb_frame = QFrame()
        self.thumb_frame.setFixedSize(140, 95)
        self.thumb_frame.setStyleSheet(
            "background-color: #0b0d13; border: 1px dashed #333c52; border-radius: 6px;"
        )
        tf_layout = QVBoxLayout(self.thumb_frame)
        tf_layout.setContentsMargins(2, 2, 2, 2)
        tf_layout.setAlignment(Qt.AlignCenter)

        self.lbl_thumb = QLabel("Aguardando\ngeração")
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self.lbl_thumb.setStyleSheet("color: #64748b; font-size: 11px;")
        tf_layout.addWidget(self.lbl_thumb)

        body_layout.addWidget(self.thumb_frame, stretch=0)
        layout.addLayout(body_layout)

        # Status indicator
        self.lbl_status = QLabel("● Pronto para gerar")
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(self.lbl_status)

    def set_total_slides(self, total: int):
        self.lbl_title.setText(f"Slide {self.slide_num} de {total}")

    def get_prompt(self) -> str:
        return self.text_prompt.toPlainText().strip()

    def set_prompt(self, text: str):
        self.text_prompt.setPlainText(text)

    def set_status(self, status_text: str, color_hex: str = "#94a3b8"):
        self.lbl_status.setText(f"● {status_text}")
        self.lbl_status.setStyleSheet(f"color: {color_hex}; font-size: 11px; font-weight: 600;")

    def set_thumbnail(self, image_path: str):
        pix = QPixmap(image_path)
        if not pix.isNull():
            scaled = pix.scaled(
                self.thumb_frame.size() - Qt.QSize(4, 4),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.lbl_thumb.setPixmap(scaled)
            self.thumb_frame.setStyleSheet("background-color: #000000; border: 1px solid #10b981; border-radius: 6px;")


class BatchSlideGenerationWorker(QThread):
    progress_changed = Signal(int, int, str)     # current_index, total, message
    slide_completed = Signal(int, str)           # slide_index, image_path
    generation_finished = Signal(str, list)      # pdf_path, list_of_image_paths
    generation_error = Signal(str)

    def __init__(self, prompts: List[str], output_dir: str, pdf_filename: str):
        super().__init__()
        self.prompts = prompts
        self.output_dir = output_dir
        self.pdf_filename = pdf_filename
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        total = len(self.prompts)
        generated_images: List[str] = []

        try:
            for idx, prompt in enumerate(self.prompts):
                if self._is_cancelled:
                    self.generation_error.emit("A geração de slides foi cancelada pelo usuário.")
                    return

                slide_num = idx + 1
                self.progress_changed.emit(
                    slide_num,
                    total,
                    f"Gerando arte do Slide {slide_num} de {total} via IA...",
                )

                img_path = str(out_dir / f"slide_{slide_num:03d}.jpg")
                final_img = generate_slide_image(prompt, img_path, width=1280, height=720)
                generated_images.append(final_img)

                self.slide_completed.emit(idx, final_img)
                time.sleep(0.5)

            if self._is_cancelled:
                return

            self.progress_changed.emit(total, total, "Unindo todos os slides em um arquivo PDF de alta definição...")

            pdf_path = str(out_dir / self.pdf_filename)
            final_pdf = create_pdf_from_images(generated_images, pdf_path)

            self.generation_finished.emit(final_pdf, generated_images)

        except Exception as e:
            self.generation_error.emit(f"Erro durante a geração de materiais:\n{e}")


class GenerateMaterialsView(QWidget):
    back_to_home = Signal()
    send_to_create_video = Signal(str)
    send_to_record_class = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: Optional[BatchSlideGenerationWorker] = None
        self.ebook_worker: Optional[EbookGenerationWorker] = None
        self.slide_cards: List[SlideCardWidget] = []
        self.latest_generated_pdf: Optional[str] = None
        self.latest_generated_images: List[str] = []
        self.external_pdf_for_ebook: Optional[str] = None
        self.latest_ebook_pdf: Optional[str] = None

        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(28, 20, 28, 20)
        root_layout.setSpacing(16)

        # 1. Top Navigation Bar
        nav_bar = QHBoxLayout()
        btn_back = QPushButton("← Voltar ao Menu Inicial")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.clicked.connect(self.back_to_home.emit)

        title = QLabel("🪄 5. Gerar Materiais da Aula - Apresentações e Slides com IA")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #818cf8;")

        nav_bar.addWidget(btn_back)
        nav_bar.addWidget(title)
        nav_bar.addStretch()
        root_layout.addLayout(nav_bar)

        # Step Navigation Bar (Clickable screens without scrollbars)
        self.step_bar = QHBoxLayout()
        self.step_bar.setSpacing(8)
        self.step_buttons = []
        step_labels = [
            "1. ⚙️ Configurações da Apresentação",
            "2. 📝 Prompts dos Slides (Até 100)",
            "3. 🪄 Geração & Exportação",
        ]
        for idx, text in enumerate(step_labels):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self._switch_step(i))
            self.step_bar.addWidget(btn)
            self.step_buttons.append(btn)
        root_layout.addLayout(self.step_bar)

        self.step_stack = QStackedWidget()

        # Page 1: Configurações & E-book
        page1 = QWidget()
        p1_lay = QVBoxLayout(page1)
        p1_lay.setContentsMargins(0, 8, 0, 0)
        p1_lay.setSpacing(12)

        # Page 2: Prompts dos Slides (com ScrollArea apenas nesta tela para os até 100 slides)
        page2 = QWidget()
        p2_lay = QVBoxLayout(page2)
        p2_lay.setContentsMargins(0, 8, 0, 0)
        p2_lay.setSpacing(12)

        # Page 3: Visualização e Exportação
        page3 = QWidget()
        p3_lay = QVBoxLayout(page3)
        p3_lay.setContentsMargins(0, 8, 0, 0)
        p3_lay.setSpacing(12)

        # --- Section 1: Configurações Gerais da Apresentação ---
        cfg_frame = QFrame()
        cfg_frame.setProperty("class", "card")
        cfg_layout = QVBoxLayout(cfg_frame)
        cfg_layout.setContentsMargins(18, 16, 18, 16)
        cfg_layout.setSpacing(12)

        sec1_title = QLabel("1. Configurações da Apresentação")
        sec1_title.setProperty("class", "section-title")
        cfg_layout.addWidget(sec1_title)

        row_meta = QHBoxLayout()
        row_meta.setSpacing(14)

        box_topic = QVBoxLayout()
        lbl_topic = QLabel("Tema / Título da Apresentação:")
        topic_input_row = QHBoxLayout()
        self.edit_topic = QLineEdit()
        self.edit_topic.setPlaceholderText("Ex: Revolução da Inteligência Artificial nos Negócios")
        self.btn_topic_mic = VoicePromptButton(target_input=self.edit_topic)
        topic_input_row.addWidget(self.edit_topic)
        topic_input_row.addWidget(self.btn_topic_mic)
        box_topic.addWidget(lbl_topic)
        box_topic.addLayout(topic_input_row)

        box_count = QVBoxLayout()
        lbl_count = QLabel("Quantidade de Slides (1 a 100):")
        row_spin = QHBoxLayout()
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 100)
        self.spin_count.setValue(5)
        self.spin_count.setFixedHeight(34)
        self.spin_count.setFixedWidth(80)

        btn_apply_count = QPushButton("Aplicar Quantidade")
        btn_apply_count.setCursor(Qt.PointingHandCursor)
        btn_apply_count.clicked.connect(self._rebuild_slide_cards)

        row_spin.addWidget(self.spin_count)
        row_spin.addWidget(btn_apply_count)
        box_count.addWidget(lbl_count)
        box_count.addLayout(row_spin)

        row_meta.addLayout(box_topic, stretch=3)
        row_meta.addLayout(box_count, stretch=2)
        cfg_layout.addLayout(row_meta)

        # AI Assistant Auto-Fill Row
        btn_auto_suggest = QPushButton("✨ Sugerir Roteiro & Prompts com IA Gemini para todos os Slides")
        btn_auto_suggest.setCursor(Qt.PointingHandCursor)
        btn_auto_suggest.setStyleSheet(
            "background-color: #1e1b4b; border: 1px solid #4338ca; color: #c7d2fe; font-weight: 600; padding: 8px 14px; border-radius: 8px;"
        )
        btn_auto_suggest.clicked.connect(self._auto_suggest_all_prompts)
        cfg_layout.addWidget(btn_auto_suggest)

        p1_lay.addWidget(cfg_frame)

        # --- Section: Gerador Independente de E-book Didático a partir de PDF Existente ---
        ebook_frame = QFrame()
        ebook_frame.setProperty("class", "card")
        ef_layout = QVBoxLayout(ebook_frame)
        ef_layout.setContentsMargins(18, 16, 18, 16)
        ef_layout.setSpacing(12)

        sec3_title = QLabel("2. Gerar E-book Didático / Apostila da Aula a partir de PDF")
        sec3_title.setProperty("class", "section-title")
        ef_layout.addWidget(sec3_title)

        lbl_eb_desc = QLabel(
            "Transforme qualquer apresentação de slides existente em uma apostila didática completa em PDF (formato A4 para impressão e leitura), "
            "com todos os slides intercalados com explicações aprofundadas geradas por IA, destaques conceituais e questões de fixação."
        )
        lbl_eb_desc.setWordWrap(True)
        lbl_eb_desc.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        ef_layout.addWidget(lbl_eb_desc)

        eb_inputs = QHBoxLayout()
        eb_inputs.setSpacing(12)

        self.edit_standalone_teacher = QLineEdit()
        self.edit_standalone_teacher.setPlaceholderText("Nome do Professor(a)")

        btn_pick_eb_pdf = QPushButton("📁 Escolher PDF de Slides...")
        btn_pick_eb_pdf.setCursor(Qt.PointingHandCursor)
        btn_pick_eb_pdf.clicked.connect(self._pick_external_pdf_for_ebook)

        self.lbl_eb_pdf_status = QLabel("Nenhum PDF selecionado")
        self.lbl_eb_pdf_status.setStyleSheet("color: #94a3b8; font-size: 12px;")

        eb_inputs.addWidget(self.edit_standalone_teacher, stretch=1)
        eb_inputs.addWidget(btn_pick_eb_pdf)
        eb_inputs.addWidget(self.lbl_eb_pdf_status)
        eb_inputs.addStretch()
        ef_layout.addLayout(eb_inputs)

        btn_run_eb = QPushButton("📚 Gerar E-book Didático com Slides Intercalados")
        btn_run_eb.setCursor(Qt.PointingHandCursor)
        btn_run_eb.setStyleSheet("background-color: #6d28d9; color: white; font-weight: 700; padding: 10px 20px; border-radius: 6px;")
        btn_run_eb.clicked.connect(self._generate_standalone_ebook)
        ef_layout.addWidget(btn_run_eb, alignment=Qt.AlignLeft)

        p1_lay.addWidget(ebook_frame)
        p1_lay.addStretch()

        s1_nav = QHBoxLayout()
        s1_nav.addStretch()
        btn_next_s1 = QPushButton("Avançar para Prompts dos Slides (Até 100) ▶")
        btn_next_s1.setProperty("class", "primary")
        btn_next_s1.setCursor(Qt.PointingHandCursor)
        btn_next_s1.clicked.connect(lambda: self._switch_step(1))
        s1_nav.addWidget(btn_next_s1)
        p1_lay.addLayout(s1_nav)

        # --- Section 2: Prompts dos Slides (com ScrollArea apenas nesta tela para os até 100 slides) ---
        slides_sec_frame = QFrame()
        slides_sec_frame.setProperty("class", "card")
        self.ssf_layout = QVBoxLayout(slides_sec_frame)
        self.ssf_layout.setContentsMargins(18, 16, 18, 16)
        self.ssf_layout.setSpacing(12)

        sec2_header = QHBoxLayout()
        sec2_title = QLabel("2. Descreva os Prompts para Cada Slide (Até 100)")
        sec2_title.setProperty("class", "section-title")
        sec2_header.addWidget(sec2_title)
        sec2_header.addStretch()

        lbl_tip = QLabel("💡 Dica: Quanto mais descritivo o prompt, mais impressionante e profissional será a imagem.")
        lbl_tip.setStyleSheet("color: #94a3b8; font-size: 12px;")
        sec2_header.addWidget(lbl_tip)
        self.ssf_layout.addLayout(sec2_header)

        # Scroll area exclusivamente para a lista dos até 100 slides
        self.slides_prompts_scroll = QScrollArea()
        self.slides_prompts_scroll.setWidgetResizable(True)
        self.slides_prompts_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        cards_content = QWidget()
        self.cards_container = QVBoxLayout(cards_content)
        self.cards_container.setContentsMargins(0, 0, 0, 0)
        self.cards_container.setSpacing(12)
        self.slides_prompts_scroll.setWidget(cards_content)

        self.ssf_layout.addWidget(self.slides_prompts_scroll, stretch=1)
        p2_lay.addWidget(slides_sec_frame, stretch=1)

        s2_nav = QHBoxLayout()
        btn_prev_s2 = QPushButton("◀ Passo Anterior (Configurações)")
        btn_prev_s2.setCursor(Qt.PointingHandCursor)
        btn_prev_s2.clicked.connect(lambda: self._switch_step(0))

        self.btn_generate = QPushButton("🚀 Gerar Apresentação em Slides (PDF)")
        self.btn_generate.setProperty("class", "primary")
        self.btn_generate.setFixedHeight(44)
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.setStyleSheet("font-size: 14px; font-weight: 700; padding: 0 24px;")
        self.btn_generate.clicked.connect(self._start_generation)

        s2_nav.addWidget(btn_prev_s2)
        s2_nav.addStretch()
        s2_nav.addWidget(self.btn_generate)
        p2_lay.addLayout(s2_nav)

        # --- Section 3: Visualização e Exportação dos Materiais ---
        step3_frame = QFrame()
        step3_frame.setProperty("class", "card")
        s3f_layout = QVBoxLayout(step3_frame)
        s3f_layout.setContentsMargins(18, 16, 18, 16)
        s3f_layout.setSpacing(14)

        sec3_res_title = QLabel("3. Geração com IA & Exportação dos Materiais")
        sec3_res_title.setProperty("class", "section-title")
        s3f_layout.addWidget(sec3_res_title)

        # Progress display
        self.progress_container = QWidget()
        pc_layout = QVBoxLayout(self.progress_container)
        pc_layout.setContentsMargins(0, 0, 0, 0)
        pc_layout.setSpacing(8)

        self.lbl_progress = QLabel("Aguardando início da geração...")
        self.lbl_progress.setStyleSheet("font-size: 14px; color: #38bdf8; font-weight: 700;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(20)

        self.btn_cancel = QPushButton("Cancelar Geração")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.hide()
        self.btn_cancel.clicked.connect(self._cancel_generation)

        pc_layout.addWidget(self.lbl_progress)
        pc_layout.addWidget(self.progress_bar)
        pc_layout.addWidget(self.btn_cancel, alignment=Qt.AlignLeft)
        s3f_layout.addWidget(self.progress_container)

        # Success Action Buttons (initially hidden)
        self.success_container = QWidget()
        sc_layout = QHBoxLayout(self.success_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(10)

        self.btn_download_pdf = QPushButton("💾 Salvar Como...")
        self.btn_download_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_download_pdf.clicked.connect(self._save_pdf_as)

        self.btn_open_pdf = QPushButton("📄 Abrir PDF")
        self.btn_open_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_open_pdf.clicked.connect(self._open_generated_pdf)

        self.btn_send_create_video = QPushButton("🎬 Usar no 'Criar Vídeo'")
        self.btn_send_create_video.setCursor(Qt.PointingHandCursor)
        self.btn_send_create_video.setStyleSheet("background-color: #0369a1; color: white;")
        self.btn_send_create_video.clicked.connect(self._dispatch_to_create_video)

        self.btn_send_record_class = QPushButton("🎓 Usar no 'Gravar Aula'")
        self.btn_send_record_class.setCursor(Qt.PointingHandCursor)
        self.btn_send_record_class.setStyleSheet("background-color: #6d28d9; color: white;")
        self.btn_send_record_class.clicked.connect(self._dispatch_to_record_class)

        self.btn_create_ebook_from_slides = QPushButton("📚 Gerar E-book Didático a partir destes Slides")
        self.btn_create_ebook_from_slides.setCursor(Qt.PointingHandCursor)
        self.btn_create_ebook_from_slides.setStyleSheet("background-color: #7c3aed; color: white; font-weight: 700;")
        self.btn_create_ebook_from_slides.clicked.connect(self._create_ebook_from_current_slides)

        sc_layout.addWidget(self.btn_download_pdf)
        sc_layout.addWidget(self.btn_open_pdf)
        sc_layout.addWidget(self.btn_create_ebook_from_slides)
        sc_layout.addWidget(self.btn_send_create_video)
        sc_layout.addWidget(self.btn_send_record_class)
        self.success_container.hide()

        s3f_layout.addWidget(self.success_container)
        s3f_layout.addStretch()

        p3_lay.addWidget(step3_frame, stretch=1)

        s3_nav = QHBoxLayout()
        btn_prev_s3 = QPushButton("◀ Voltar aos Prompts dos Slides")
        btn_prev_s3.setCursor(Qt.PointingHandCursor)
        btn_prev_s3.clicked.connect(lambda: self._switch_step(1))
        s3_nav.addWidget(btn_prev_s3)
        s3_nav.addStretch()
        p3_lay.addLayout(s3_nav)

        # Assemble step pages into step stack
        self.step_stack.addWidget(page1)
        self.step_stack.addWidget(page2)
        self.step_stack.addWidget(page3)
        root_layout.addWidget(self.step_stack, stretch=1)
        self._switch_step(0)

        # Build initial cards
        self._rebuild_slide_cards()

    def _switch_step(self, idx: int):
        self.step_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.step_buttons):
            if i == idx:
                btn.setStyleSheet(
                    "background: #4f46e5; color: #ffffff; font-weight: 700; "
                    "border: 1.5px solid #818cf8; padding: 8px 14px; border-radius: 8px;"
                )
            else:
                btn.setStyleSheet(
                    "background: #1a1e28; color: #94a3b8; font-weight: 600; "
                    "border: 1px solid #2d3343; padding: 8px 14px; border-radius: 8px;"
                )

    def _rebuild_slide_cards(self):
        target_count = self.spin_count.value()

        # Preserve existing text
        old_texts = [card.get_prompt() for card in self.slide_cards]

        # Clear existing cards
        while self.cards_container.count():
            item = self.cards_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.slide_cards.clear()

        # Recreate cards
        for i in range(target_count):
            card = SlideCardWidget(slide_num=i + 1, total=target_count, parent=self)
            card.enhance_requested.connect(self._on_enhance_single_prompt)
            if i < len(old_texts) and old_texts[i]:
                card.set_prompt(old_texts[i])
            self.cards_container.addWidget(card)
            self.slide_cards.append(card)

    def _on_enhance_single_prompt(self, slide_num: int):
        idx = slide_num - 1
        if idx >= len(self.slide_cards):
            return

        card = self.slide_cards[idx]
        current_text = card.get_prompt()
        if not current_text:
            topic = self.edit_topic.text().strip() or "Apresentação Educacional"
            current_text = f"Slide sobre {topic}, aspecto número {slide_num}"

        card.set_status("Aprimorando prompt com Gemini...", "#38bdf8")
        total = len(self.slide_cards)
        topic = self.edit_topic.text().strip()

        enhanced = enhance_slide_prompt_with_gemini(
            user_prompt=current_text,
            slide_num=slide_num,
            total_slides=total,
            lesson_topic=topic,
        )
        card.set_prompt(enhanced)
        card.set_status("✓ Prompt aprimorado com sucesso!", "#10b981")

    def _auto_suggest_all_prompts(self):
        topic = self.edit_topic.text().strip()
        if not topic:
            QMessageBox.information(
                self,
                "Tema Necessário",
                "Por favor, digite o tema ou título da apresentação para que a IA possa sugerir os prompts dos slides.",
            )
            return

        api_key = get_gemini_api_key()
        if not api_key:
            QMessageBox.warning(
                self,
                "Chave Gemini Necessária",
                "Configure sua chave gratuita do Gemini no menu inicial para usar o assistente de roteiro.",
            )
            return

        total = len(self.slide_cards)

        prompt_request = (
            f"Você é um designer de apresentações renomado. Crie uma sequência de {total} slides "
            f"para uma apresentação sobre o tema: '{topic}'.\n"
            f"Para cada slide, forneça uma descrição visual detalhada em inglês (prompt para IA de imagens) "
            f"explicando a composição estética, elementos centrais, iluminação e estilo moderno widescreen 16:9.\n"
            f"Responda EXATAMENTE no formato JSON com uma lista de strings, exemplo:\n"
            f'["Slide 1 prompt...", "Slide 2 prompt...", ...]\n'
            f"Não inclua markdown adicional além do JSON puro."
        )

        try:
            from google import genai
            from app.core.gemini_client import GeminiError, generate_with_fallback

            client = genai.Client(api_key=api_key)

            import json

            try:
                resp = generate_with_fallback(client, contents=prompt_request)
                text = resp.text.strip()
                if text.startswith("```json"):
                    text = text[7:]
                if text.endswith("```"):
                    text = text[:-3]
                prompts_list = json.loads(text.strip())
            except (GeminiError, ValueError):
                prompts_list = []

            if isinstance(prompts_list, list) and len(prompts_list) > 0:
                for idx, p_text in enumerate(prompts_list):
                    if idx < len(self.slide_cards):
                        self.slide_cards[idx].set_prompt(str(p_text))
                        self.slide_cards[idx].set_status("✓ Sugestão gerada pela IA", "#10b981")
                QMessageBox.information(
                    self,
                    "Roteiro Gerado",
                    f"A IA gerou sugestões detalhadas para todos os {len(self.slide_cards)} slides!",
                )
                return

            QMessageBox.warning(self, "Aviso", "Não foi possível estruturar as sugestões automaticamente.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao consultar Gemini:\n{e}")

    def _start_generation(self):
        prompts = [card.get_prompt() for card in self.slide_cards]

        # Verify that prompts are not empty
        empty_indices = [i + 1 for i, p in enumerate(prompts) if not p]
        if empty_indices:
            topic = self.edit_topic.text().strip() or "Apresentação Educacional"
            # Auto-fill missing prompts with reasonable defaults
            for idx in empty_indices:
                auto_p = f"Modern widescreen 16:9 presentation slide about {topic}, section {idx}, minimal elegant design, dark aesthetics"
                self.slide_cards[idx - 1].set_prompt(auto_p)
            prompts = [card.get_prompt() for card in self.slide_cards]

        topic_slug = self.edit_topic.text().strip().lower().replace(" ", "_") or "apresentacao"
        clean_slug = "".join(c for c in topic_slug if c.isalnum() or c in ("-", "_"))[:30]
        timestamp = int(time.time())

        output_dir = str(Path.home() / "SlideCast_Materials" / f"{clean_slug}_{timestamp}")
        pdf_filename = f"{clean_slug}_apresentacao.pdf"

        # UI state - switch to Step 3 (Visualização & Progresso)
        self._switch_step(2)
        self.btn_generate.setEnabled(False)
        self.btn_cancel.show()
        self.progress_container.show()
        self.success_container.hide()
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("Iniciando geração inteligente dos slides...")

        for card in self.slide_cards:
            card.set_status("Na fila...", "#94a3b8")

        self.worker = BatchSlideGenerationWorker(prompts, output_dir, pdf_filename)
        self.worker.progress_changed.connect(self._on_worker_progress)
        self.worker.slide_completed.connect(self._on_slide_completed)
        self.worker.generation_finished.connect(self._on_generation_finished)
        self.worker.generation_error.connect(self._on_generation_error)
        self.worker.start()

    def _cancel_generation(self):
        if self.worker:
            self.worker.cancel()
            self.lbl_progress.setText("Cancelando...")
            self.btn_cancel.setEnabled(False)

    def _on_worker_progress(self, current: int, total: int, msg: str):
        pct = int((current / max(1, total)) * 100)
        self.progress_bar.setValue(pct)
        self.lbl_progress.setText(msg)

    def _on_slide_completed(self, idx: int, image_path: str):
        if idx < len(self.slide_cards):
            card = self.slide_cards[idx]
            card.set_thumbnail(image_path)
            card.set_status("✓ Arte Gerada em Alta Definição", "#10b981")

    def _on_generation_finished(self, pdf_path: str, images: list):
        self.latest_generated_pdf = pdf_path
        self.latest_generated_images = images
        self.btn_generate.setEnabled(True)
        self.btn_cancel.hide()
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(100)
        self.lbl_progress.setText(f"✓ Apresentação em PDF concluída! ({len(images)} slides)")
        self.lbl_progress.setStyleSheet("color: #10b981; font-weight: 700;")
        self.success_container.show()

        QMessageBox.information(
            self,
            "Sucesso!",
            f"Sua apresentação com {len(images)} slides foi gerada com sucesso e compilada em PDF!\n\nArquivo: {pdf_path}",
        )

    def _on_generation_error(self, err_msg: str):
        self.btn_generate.setEnabled(True)
        self.btn_cancel.hide()
        self.btn_cancel.setEnabled(True)
        self.lbl_progress.setText("Geração interrompida.")
        self.lbl_progress.setStyleSheet("color: #ef4444; font-weight: 700;")
        QMessageBox.critical(self, "Aviso de Geração", err_msg)

    def _save_pdf_as(self):
        if not self.latest_generated_pdf or not Path(self.latest_generated_pdf).exists():
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Apresentação PDF",
            str(Path.home() / Path(self.latest_generated_pdf).name),
            "Arquivos PDF (*.pdf)",
        )
        if dest:
            import shutil
            shutil.copy2(self.latest_generated_pdf, dest)
            QMessageBox.information(self, "Arquivo Salvo", f"O PDF foi salvo com sucesso em:\n{dest}")

    def _open_generated_pdf(self):
        if not self.latest_generated_pdf or not Path(self.latest_generated_pdf).exists():
            return
        try:
            if sys.platform == "win32":
                os.startfile(self.latest_generated_pdf)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.latest_generated_pdf])
            else:
                subprocess.Popen(["xdg-open", self.latest_generated_pdf])
        except Exception as e:
            QMessageBox.warning(self, "Aviso", f"Não foi possível abrir o PDF diretamente:\n{e}")

    def _dispatch_to_create_video(self):
        if self.latest_generated_pdf:
            self.send_to_create_video.emit(self.latest_generated_pdf)

    def _dispatch_to_record_class(self):
        if self.latest_generated_pdf:
            self.send_to_record_class.emit(self.latest_generated_pdf)

    def _create_ebook_from_current_slides(self):
        if not self.latest_generated_images:
            QMessageBox.warning(self, "Aviso", "Nenhum slide gerado disponível para criar o e-book.")
            return

        topic = self.edit_topic.text().strip() or "Apresentação da Aula"
        teacher, ok = QInputDialog.getText(
            self,
            "Nome do Professor",
            "Informe o nome do Professor(a) para a capa do E-book:",
            text="Prof. Kika Magalhães",
        )
        if not ok:
            return

        dest_dir = Path.home() / "SlideCast_Materials" / "ebooks"
        dest_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        clean_slug = "".join(c for c in topic.lower().replace(" ", "_") if c.isalnum() or c in "_-")[:25]
        out_ebook = str(dest_dir / f"ebook_{clean_slug}_{timestamp}.pdf")

        self.progress_container.show()
        self.progress_bar.setValue(10)
        self.lbl_progress.setText("Criando E-book didático em PDF com slides intercalados...")

        self.ebook_worker = EbookGenerationWorker(
            title=topic,
            teacher=teacher or "Professor Responsável",
            audio_path="",
            slide_images=self.latest_generated_images,
            output_pdf=out_ebook,
        )
        self.ebook_worker.progress_changed.connect(self._on_ebook_progress)
        self.ebook_worker.finished_success.connect(self._on_ebook_success)
        self.ebook_worker.finished_error.connect(self._on_ebook_error)
        self.ebook_worker.start()

    def _pick_external_pdf_for_ebook(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Apresentação de Slides (PDF)",
            "",
            "Arquivos PDF (*.pdf)",
        )
        if file_path:
            self.external_pdf_for_ebook = file_path
            self.lbl_eb_pdf_status.setText(f"✓ {Path(file_path).name}")
            self.lbl_eb_pdf_status.setStyleSheet("color: #10b981; font-weight: 600;")

    def _generate_standalone_ebook(self):
        if not self.external_pdf_for_ebook or not Path(self.external_pdf_for_ebook).exists():
            QMessageBox.warning(self, "PDF Necessário", "Por favor, selecione um arquivo PDF de slides para gerar o E-book.")
            return

        topic = self.edit_topic.text().strip() or Path(self.external_pdf_for_ebook).stem.replace("_", " ").title()
        teacher = self.edit_standalone_teacher.text().strip() or "Professor Responsável"

        # Extract thumbnails from PDF
        temp_dir = Path.home() / "SlideCast_Materials" / "temp_slides"
        temp_dir.mkdir(parents=True, exist_ok=True)
        info = inspect_pdf(self.external_pdf_for_ebook)
        slide_images = []
        for idx in range(info.page_count):
            img_bytes = render_thumbnail(self.external_pdf_for_ebook, idx, max_dimension=1280)
            img_p = str(temp_dir / f"slide_{idx:03d}.png")
            with open(img_p, "wb") as f:
                f.write(img_bytes)
            slide_images.append(img_p)

        dest_dir = Path.home() / "SlideCast_Materials" / "ebooks"
        dest_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        clean_slug = "".join(c for c in topic.lower().replace(" ", "_") if c.isalnum() or c in "_-")[:25]
        out_ebook = str(dest_dir / f"ebook_{clean_slug}_{timestamp}.pdf")

        self.progress_container.show()
        self.progress_bar.setValue(10)
        self.lbl_progress.setText("Criando E-book didático em PDF com slides intercalados...")

        self.ebook_worker = EbookGenerationWorker(
            title=topic,
            teacher=teacher,
            audio_path="",
            slide_images=slide_images,
            output_pdf=out_ebook,
        )
        self.ebook_worker.progress_changed.connect(self._on_ebook_progress)
        self.ebook_worker.finished_success.connect(self._on_ebook_success)
        self.ebook_worker.finished_error.connect(self._on_ebook_error)
        self.ebook_worker.start()

    def _on_ebook_progress(self, pct: float, msg: str):
        self.progress_bar.setValue(int(pct))
        self.lbl_progress.setText(msg)

    def _on_ebook_success(self, pdf_path: str):
        self.latest_ebook_pdf = pdf_path
        self.progress_bar.setValue(100)
        self.lbl_progress.setText("✓ E-book didático em PDF gerado com sucesso!")
        self.lbl_progress.setStyleSheet("color: #10b981; font-weight: 700;")

        msg = QMessageBox(self)
        msg.setWindowTitle("E-book Gerado com Sucesso!")
        msg.setText(f"A apostila didática com slides intercalados foi gerada em:\n{pdf_path}")
        msg.setIcon(QMessageBox.Information)

        btn_open = msg.addButton("📄 Abrir E-book", QMessageBox.ActionRole)
        btn_folder = msg.addButton("📁 Abrir Pasta", QMessageBox.ActionRole)
        btn_close = msg.addButton("Fechar", QMessageBox.RejectRole)
        msg.exec()

        if msg.clickedButton() == btn_open:
            if sys.platform == "win32":
                os.startfile(pdf_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", pdf_path])
            else:
                subprocess.Popen(["xdg-open", pdf_path])
        elif msg.clickedButton() == btn_folder:
            folder = str(Path(pdf_path).parent.resolve())
            if sys.platform == "win32":
                subprocess.Popen(["explorer", folder])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])

    def _on_ebook_error(self, err: str):
        self.lbl_progress.setText("Erro ao gerar e-book.")
        self.lbl_progress.setStyleSheet("color: #ef4444; font-weight: 700;")
        QMessageBox.critical(self, "Erro", f"Não foi possível gerar o e-book:\n{err}")
