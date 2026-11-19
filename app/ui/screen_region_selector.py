"""
Interactive screen region selection overlay for SlideCast Desktop.

Allows users to click and drag to delimit a rectangle on screen:
  - Cyan (#38bdf8) for Presentation Area
  - Amber (#f59e0b) for Presenter Area

Features:
  - Frameless semi-transparent overlay covering the virtual screen geometry.
  - Clean rectangular boundary with dimension badge and action buttons.
  - Corner and edge handles to fine-tune the selection.
  - Complete closure before recording starts, ensuring no selection artifacts
    are captured in the final video.
  - Programmatic API for automated headless testing.
"""
from typing import Optional, Tuple
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QCursor
from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)

from app.core.dual_region_recorder import ScreenRegion


class ScreenRegionSelector(QWidget):
    """
    Fullscreen transparent overlay that lets the user drag to select a region.
    """
    region_selected = Signal(int, int, int, int)  # x, y, width, height (screen/physical pixels)
    selection_cancelled = Signal()

    def __init__(
        self,
        target_name: str = "presentation",  # "presentation" or "presenter"
        initial_rect: Optional[QRect] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.target_name = target_name
        self.is_presentation = (target_name == "presentation")

        # Visual styling
        if self.is_presentation:
            self.accent_color = QColor("#38bdf8")  # Sky / Cyan
            self.target_label = "ÁREA DA APRESENTAÇÃO"
            self.instruction_text = (
                "Clique e arraste com o mouse para selecionar os SLIDES ou MATERIAL EXIBIDO.\n"
                "Pressione Enter para confirmar ou Esc para cancelar."
            )
        else:
            self.accent_color = QColor("#f59e0b")  # Amber / Warm Gold
            self.target_label = "ÁREA DO PROFESSOR"
            self.instruction_text = (
                "Clique e arraste com o mouse para selecionar o VÍDEO DO PROFESSOR (câmera / mosaico do Meet).\n"
                "Pressione Enter para confirmar ou Esc para cancelar."
            )

        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

        # Screen geometry covering virtual desktop
        screen = QApplication.primaryScreen()
        geo = screen.virtualGeometry() if screen else QRect(0, 0, 1920, 1080)
        self.setGeometry(geo)

        # State
        self.origin = QPoint()
        self.current = QPoint()
        self.selected_rect: Optional[QRect] = initial_rect
        self.is_drawing = False
        self.is_dragging = False
        self.drag_start = QPoint()
        self.active_handle: Optional[str] = None

        self._build_top_banner()

    def _build_top_banner(self):
        # Top banner showing instructions
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 20, 0, 0)
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.banner = QFrame(self)
        self.banner.setStyleSheet(
            "background-color: rgba(16, 32, 30, 0.92); "
            "border: 1.5px solid " + self.accent_color.name() + "; "
            "border-radius: 10px; padding: 10px 24px;"
        )
        b_lay = QVBoxLayout(self.banner)
        b_lay.setAlignment(Qt.AlignCenter)
        b_lay.setSpacing(6)

        lbl_badge = QLabel(f"📐 {self.target_label}", self.banner)
        lbl_badge.setStyleSheet(
            f"color: {self.accent_color.name()}; font-size: 15px; font-weight: 800; letter-spacing: 1px;"
        )
        lbl_badge.setAlignment(Qt.AlignCenter)

        lbl_inst = QLabel(self.instruction_text, self.banner)
        lbl_inst.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 500;")
        lbl_inst.setAlignment(Qt.AlignCenter)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignCenter)

        self.btn_confirm = QPushButton("✓ Confirmar Seleção (Enter)", self.banner)
        self.btn_confirm.setCursor(Qt.PointingHandCursor)
        self.btn_confirm.setStyleSheet(
            f"background-color: {self.accent_color.name()}; color: #10201e; "
            "font-weight: 800; font-size: 12px; padding: 6px 16px; border-radius: 6px;"
        )
        self.btn_confirm.clicked.connect(self.confirm_selection)
        self.btn_confirm.setEnabled(self.selected_rect is not None)

        self.btn_cancel = QPushButton("✕ Cancelar (Esc)", self.banner)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.15); color: #FFFFFF; "
            "font-weight: 600; font-size: 12px; padding: 6px 16px; border-radius: 6px;"
        )
        self.btn_cancel.clicked.connect(self.cancel_selection)

        btn_row.addWidget(self.btn_confirm)
        btn_row.addWidget(self.btn_cancel)

        b_lay.addWidget(lbl_badge)
        b_lay.addWidget(lbl_inst)
        b_lay.addLayout(btn_row)

        layout.addWidget(self.banner)

    # ----------------------------------------------------
    # MOUSE & DRAWING LOGIC
    # ----------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            # If click was inside banner, ignore selection change
            if self.banner.geometry().contains(pos):
                return super().mousePressEvent(event)

            # Check if clicked inside existing rect to drag it
            if self.selected_rect and self.selected_rect.contains(pos):
                self.is_dragging = True
                self.drag_start = pos
            else:
                # Start drawing new rectangle
                self.is_drawing = True
                self.origin = pos
                self.current = pos
                self.selected_rect = QRect(pos, pos)
            self.update()

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self.is_drawing:
            self.current = pos
            self.selected_rect = QRect(self.origin, self.current).normalized()
            self.update()
        elif self.is_dragging and self.selected_rect:
            dx = pos.x() - self.drag_start.x()
            dy = pos.y() - self.drag_start.y()
            self.selected_rect.translate(dx, dy)
            self.drag_start = pos
            self.update()
        else:
            # Update cursor if hovering over rect
            if self.selected_rect and self.selected_rect.contains(pos):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_drawing:
                self.is_drawing = False
                if self.selected_rect and (self.selected_rect.width() < 32 or self.selected_rect.height() < 32):
                    self.selected_rect = None
            if self.is_dragging:
                self.is_dragging = False

            if hasattr(self, "btn_confirm"):
                self.btn_confirm.setEnabled(self.selected_rect is not None)
            self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.confirm_selection()
        elif event.key() == Qt.Key_Escape:
            self.cancel_selection()
        else:
            super().keyPressEvent(event)

    # ----------------------------------------------------
    # PAINT EVENT
    # ----------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw semi-transparent dark background over the whole screen
        dim_color = QColor(0, 0, 0, 110)
        painter.fillRect(self.rect(), dim_color)

        if self.selected_rect and self.selected_rect.isValid():
            r = self.selected_rect

            # Clear hole for selection
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(r, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            # Draw outer highlight border
            pen = QPen(self.accent_color, 2.5, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r)

            # Draw corner handles
            handle_size = 10
            painter.setBrush(QBrush(self.accent_color))
            painter.setPen(QPen(Qt.black, 1))
            corners = [
                QPoint(r.left(), r.top()),
                QPoint(r.right(), r.top()),
                QPoint(r.left(), r.bottom()),
                QPoint(r.right(), r.bottom()),
            ]
            for pt in corners:
                painter.drawRect(
                    pt.x() - handle_size // 2,
                    pt.y() - handle_size // 2,
                    handle_size,
                    handle_size,
                )

            # Draw dimension badge above or below rect
            w = r.width()
            h = r.height()
            w_even = w if w % 2 == 0 else w - 1
            h_even = h if h % 2 == 0 else h - 1
            dim_str = f" {self.target_label}: {w_even} × {h_even} px "

            font = QFont("sans-serif", 10, QFont.Bold)
            painter.setFont(font)
            badge_rect = QRect(r.left(), max(10, r.top() - 26), 260, 22)
            painter.fillRect(badge_rect, QColor("#10201e"))
            painter.setPen(QPen(self.accent_color, 1))
            painter.drawRect(badge_rect)
            painter.setPen(QPen(Qt.white))
            painter.drawText(badge_rect, Qt.AlignCenter, dim_str)

    # ----------------------------------------------------
    # PUBLIC ACTIONS & PROGRAMMATIC TESTING API
    # ----------------------------------------------------
    def set_selection_rect(self, x: int, y: int, w: int, h: int):
        """Sets the selection rectangle programmatically (useful for testing)."""
        self.selected_rect = QRect(x, y, w, h)
        if hasattr(self, "btn_confirm"):
            self.btn_confirm.setEnabled(True)
        self.update()

    def get_selection_tuple(self) -> Optional[Tuple[int, int, int, int]]:
        """Returns normalized (x, y, w, h) in physical screen coordinates, or None."""
        if not self.selected_rect or not self.selected_rect.isValid():
            return None
        r = self.selected_rect.normalized()
        w = max(32, r.width())
        h = max(32, r.height())
        w_even = w if w % 2 == 0 else w - 1
        h_even = h if h % 2 == 0 else h - 1
        return (r.x(), r.y(), w_even, h_even)

    def to_screen_region(self) -> Optional[ScreenRegion]:
        t = self.get_selection_tuple()
        if not t:
            return None
        x, y, w, h = t
        return ScreenRegion(
            name=self.target_name,
            label=self.target_label,
            x=x,
            y=y,
            width=w,
            height=h,
        )

    def confirm_selection(self):
        t = self.get_selection_tuple()
        if t:
            self.region_selected.emit(*t)
        self.close()

    def cancel_selection(self):
        self.selection_cancelled.emit()
        self.close()
