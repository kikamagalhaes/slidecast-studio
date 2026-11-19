from app.ui.styles import apply_style
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QWidget,
    QSizePolicy,
)


class TeleprompterTextEdit(QTextEdit):
    """Subclass of QTextEdit that emits clicked signal on mouse release without selection."""
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and not self.textCursor().hasSelection():
            self.clicked.emit()


class TeleprompterWidget(QFrame):
    toggled_play = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_playing = False
        self.scroll_speed = 1.0  # speed multiplier
        self.font_size = 18

        self.setObjectName("teleprompterFrame")
        self.setFixedWidth(560)
        self.setFixedHeight(288)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._apply_frame_style(active=False)

        self.timer = QTimer(self)
        self.timer.setInterval(40)  # ~25 fps smooth scroll
        self.timer.timeout.connect(self._auto_scroll_tick)

        self._build_ui()

    def _apply_frame_style(self, active: bool = False):
        border_color = "@primary@" if active else "@border@"
        apply_style(self, f"""
            QFrame#teleprompterFrame {{
                background-color: @surface_alt@;
                border: 1px solid {border_color};
                border-radius: 12px;
            }}
        """)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. Text View Area (No top gray bar at all - reading text starts directly at top)
        self.text_edit = TeleprompterTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.viewport().setAutoFillBackground(False)
        apply_style(self.text_edit.viewport(), "background-color: transparent;")
        self.text_edit.setCursor(Qt.PointingHandCursor)
        self.text_edit.setToolTip("Clique no texto ou pressione Espaço para Iniciar / Pausar a rolagem")
        self.text_edit.clicked.connect(self.toggle_play)

        self.text_edit.setFixedHeight(194)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setPlaceholderText(
            "O roteiro da aula rolará aqui suavemente.\n\n"
            "Posicione o olhar diretamente para a lente da webcam no alto.\n"
            "Pressione Espaço ou clique aqui para iniciar."
        )
        self._update_font_style()
        layout.addWidget(self.text_edit)

        # 2. Sleek Minimalist Bottom Controls (Dark theme matching modules)
        bottom_bar = QFrame()
        apply_style(bottom_bar, """
            QFrame {
                background-color: @surface_alt@;
                border-top: 1px solid @border@;
                border-radius: 8px;
                padding: 2px 4px;
            }
            QPushButton {
                background-color: @surface_alt@;
                color: @text@;
                border: 1px solid @border@;
                border-radius: 5px;
                padding: 7px 9px;
                min-height: 26px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: @surface_alt@;
                border-color: @focus@;
                color: @text@;
            }
            QPushButton:pressed {
                background-color: @surface_alt@;
            }
        """)
        b_layout = QHBoxLayout(bottom_bar)
        b_layout.setContentsMargins(6, 2, 6, 2)
        b_layout.setSpacing(6)

        # Play / Pause button
        self.btn_play = QPushButton("▶ Iniciar (Espaço)")
        self.btn_play.setCursor(Qt.PointingHandCursor)
        apply_style(self.btn_play, "background-color: @primary@; color: @on_primary@; border: 1px solid @focus@; "
            "padding: 3px 10px; font-weight: 700;")
        self.btn_play.clicked.connect(self.toggle_play)
        b_layout.addWidget(self.btn_play)

        # Slower
        btn_slower = QPushButton("🐢")
        btn_slower.setToolTip("Diminuir velocidade da rolagem")
        btn_slower.setCursor(Qt.PointingHandCursor)
        btn_slower.setFixedWidth(42)
        btn_slower.clicked.connect(self.slow_down)
        b_layout.addWidget(btn_slower)

        # Speed Label
        self.lbl_speed = QLabel("1.0x")
        apply_style(self.lbl_speed, "font-size: 11px; font-weight: 700; color: @primary@; min-width: 30px;")
        self.lbl_speed.setAlignment(Qt.AlignCenter)
        b_layout.addWidget(self.lbl_speed)

        # Faster
        btn_faster = QPushButton("🐇")
        btn_faster.setToolTip("Aumentar velocidade da rolagem")
        btn_faster.setCursor(Qt.PointingHandCursor)
        btn_faster.setFixedWidth(42)
        btn_faster.clicked.connect(self.speed_up)
        b_layout.addWidget(btn_faster)

        b_layout.addStretch()

        # Font -
        btn_font_dec = QPushButton("A-")
        btn_font_dec.setToolTip("Diminuir tamanho da fonte")
        btn_font_dec.setCursor(Qt.PointingHandCursor)
        btn_font_dec.setFixedWidth(42)
        btn_font_dec.clicked.connect(self.decrease_font)
        b_layout.addWidget(btn_font_dec)

        # Font +
        btn_font_inc = QPushButton("A+")
        btn_font_inc.setToolTip("Aumentar tamanho da fonte")
        btn_font_inc.setCursor(Qt.PointingHandCursor)
        btn_font_inc.setFixedWidth(42)
        btn_font_inc.clicked.connect(self.increase_font)
        b_layout.addWidget(btn_font_inc)

        # Reset to Top
        btn_reset = QPushButton("⏮ Topo")
        btn_reset.setToolTip("Voltar ao início do texto")
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.clicked.connect(self.reset_to_top)
        b_layout.addWidget(btn_reset)

        layout.addWidget(bottom_bar)

    def set_script_text(self, text: str):
        self.text_edit.setPlainText(text)
        self.reset_to_top()

    def toggle_play(self):
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def play(self):
        self.is_playing = True
        self.btn_play.setText("⏸ Pausar")
        apply_style(self.btn_play, "background-color: @warning@; color: @on_primary@; border: 1px solid @focus@; "
            "padding: 3px 10px; font-weight: 700;")
        self._apply_frame_style(active=True)
        self.timer.start()
        self.toggled_play.emit(True)

    def pause(self):
        self.is_playing = False
        self.btn_play.setText("▶ Retomar")
        apply_style(self.btn_play, "background-color: @primary@; color: @on_primary@; border: 1px solid @focus@; "
            "padding: 3px 10px; font-weight: 700;")
        self._apply_frame_style(active=False)
        self.timer.stop()
        self.toggled_play.emit(False)

    def speed_up(self):
        self.scroll_speed = min(5.0, round(self.scroll_speed + 0.25, 2))
        self.lbl_speed.setText(f"{self.scroll_speed:.1f}x")

    def slow_down(self):
        self.scroll_speed = max(0.25, round(self.scroll_speed - 0.25, 2))
        self.lbl_speed.setText(f"{self.scroll_speed:.1f}x")

    def increase_font(self):
        self.font_size = min(36, self.font_size + 2)
        self._update_font_style()

    def decrease_font(self):
        self.font_size = max(12, self.font_size - 2)
        self._update_font_style()

    def _update_font_style(self):
        apply_style(self.text_edit, f"""
            QTextEdit {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
                color: @text@;
                font-size: {self.font_size}px;
                line-height: 1.6;
                padding: 8px 12px;
                selection-background-color: @primary@;
            }}
        """)

    def reset_to_top(self):
        self.text_edit.verticalScrollBar().setValue(0)

    def _auto_scroll_tick(self):
        bar = self.text_edit.verticalScrollBar()
        step = int(self.scroll_speed * 2)
        if step < 1:
            step = 1
        bar.setValue(bar.value() + step)
        if bar.value() >= bar.maximum():
            self.pause()
