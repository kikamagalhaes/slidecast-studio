"""
Visual timeline widget for directed class composition.
Displays continuous recording duration, color-coded intervals for slides,
professor-focus regions, time ruler, and interactive playhead cursor.
"""
from typing import List, Optional
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPolygonF, QFont
from PySide6.QtWidgets import QWidget, QSizePolicy, QToolTip

from app.ui.styles import tokens, theme_manager
from app.core.dual_region_recorder import PresentationInterval, format_ms_to_time


class ClassTimelineWidget(QWidget):
    """
    Timeline visualizer for dual-region class direction.
    - Base track: Professor Focus (Layout 1: Centralized Professor on #10201E stage).
    - Intervals: Slide Display (Layout 2: ~80% Presentation + ~20% Professor).
    - Interactive ruler, playhead needle, click-to-seek, and hover tooltips.
    """
    time_selected = Signal(int)       # emits timestamp in milliseconds
    interval_clicked = Signal(int)    # emits index of clicked interval, or -1
    intervals_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.duration_ms: int = 0
        self.intervals: List[PresentationInterval] = []
        self.current_pos_ms: int = 0
        self.selected_index: int = -1

        self.setMinimumWidth(400)
        self.setMinimumHeight(84)
        self.setMaximumHeight(100)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("Linha do tempo de direção da aula")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        theme_manager().changed.connect(self.update)

    def set_duration_ms(self, duration_ms: int) -> None:
        """Sets the total session duration in milliseconds."""
        self.duration_ms = max(0, int(duration_ms))
        if self.current_pos_ms > self.duration_ms:
            self.current_pos_ms = self.duration_ms
        self.update()

    def set_intervals(self, intervals: List[PresentationInterval]) -> None:
        """Sets the list of presentation intervals."""
        self.intervals = list(intervals)
        self.update()
        self.intervals_changed.emit()

    def get_intervals(self) -> List[PresentationInterval]:
        """Returns the current list of intervals."""
        return list(self.intervals)

    def set_current_pos_ms(self, pos_ms: int) -> None:
        """Sets the playhead needle position in milliseconds."""
        self.current_pos_ms = max(0, min(self.duration_ms, int(pos_ms)))
        self.update()

    def get_layout_at_ms(self, pos_ms: int) -> str:
        """Returns 'slides' if inside any interval, else 'presenter_focus'."""
        for interval in self.intervals:
            if interval.start_ms <= pos_ms < interval.end_ms:
                return "slides"
        return "presenter_focus"

    def get_layout_label_at_ms(self, pos_ms: int) -> str:
        """Returns human-readable Portuguese layout label at given timestamp."""
        layout = self.get_layout_at_ms(pos_ms)
        if layout == "slides":
            return "Slides Grandes + Professor na Lateral (~80% / ~20%)"
        return "Professor em Destaque (Centralizado + Título da Aula)"

    def _x_to_ms(self, x: float) -> int:
        """Converts widget X coordinate to milliseconds."""
        left = 16.0
        width = max(1.0, float(self.width() - 32))
        ratio = max(0.0, min(1.0, (x - left) / width))
        return int(ratio * self.duration_ms)

    def _ms_to_x(self, ms: int) -> float:
        """Converts milliseconds to widget X coordinate."""
        if self.duration_ms <= 0:
            return 16.0
        left = 16.0
        width = max(1.0, float(self.width() - 32))
        ratio = max(0.0, min(1.0, float(ms) / float(self.duration_ms)))
        return left + (ratio * width)

    def paintEvent(self, event) -> None:
        c = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        track_left = 16.0
        track_w = max(1.0, float(w - 32))
        track_top = 28.0
        track_h = float(h - track_top - 16.0)

        # Background container
        p.fillRect(self.rect(), QColor(c.get("surface", "#18181b")))

        # 1. Time ruler (ticks & time strings)
        ruler_font = QFont()
        ruler_font.setPointSize(8)
        p.setFont(ruler_font)
        p.setPen(QColor(c.get("muted", "#71717a")))

        ticks = max(2, min(12, int(track_w // 100)))
        total_ms = max(1000, self.duration_ms)

        for i in range(ticks + 1):
            tick_x = track_left + (i * track_w / ticks)
            tick_ms = int(total_ms * (i / ticks))
            # Tick mark
            p.setPen(QColor(c.get("border", "#3f3f46")))
            p.drawLine(int(tick_x), 18, int(tick_x), 26)
            # Label
            p.setPen(QColor(c.get("muted", "#a1a1aa")))
            p.drawText(
                QRectF(tick_x - 35, 2, 70, 16),
                Qt.AlignCenter,
                format_ms_to_time(tick_ms),
            )

        # 2. Base track: Professor Focus (Default: #10201E stage)
        track_rect = QRectF(track_left, track_top, track_w, track_h)
        base_color = QColor(c.get("stage", "#10201E"))
        p.fillRect(track_rect, base_color)
        p.setPen(QPen(QColor(c.get("border", "#27272a")), 1))
        p.drawRoundedRect(track_rect, 4, 4)

        # Label in base track when empty or wide enough
        p.setPen(QColor(c.get("stage_text", "#a1a1aa")))
        track_label_font = QFont()
        track_label_font.setPointSize(8)
        track_label_font.setBold(True)
        p.setFont(track_label_font)

        # 3. Slide Intervals (Layout 2: dominant slides)
        # Use distinctive purple / indigo palette
        slide_fill = QColor("#6366f1")
        slide_border = QColor("#818cf8")
        slide_selected_border = QColor("#fbbf24")

        for idx, interval in enumerate(self.intervals):
            start_x = self._ms_to_x(interval.start_ms)
            end_x = self._ms_to_x(interval.end_ms)
            int_w = max(3.0, end_x - start_x)

            int_rect = QRectF(start_x, track_top + 2, int_w, track_h - 4)

            # Draw interval body
            p.fillRect(int_rect, slide_fill)

            # Draw border (highlighted if selected)
            if idx == self.selected_index:
                p.setPen(QPen(slide_selected_border, 2))
            else:
                p.setPen(QPen(slide_border, 1))
            p.drawRoundedRect(int_rect, 3, 3)

            # Label if width allows
            if int_w > 60:
                p.save()
                p.setClipRect(int_rect.adjusted(2, 2, -2, -2))
                p.setPen(QColor("#ffffff"))
                p.drawText(
                    QRectF(start_x + 4, track_top + 4, int_w - 8, track_h - 8),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    f"▶ SLIDES ({format_ms_to_time(interval.start_ms)})",
                )
                p.restore()

        # If no intervals exist, indicate 100% Professor Focus
        if not self.intervals:
            p.setPen(QColor(c.get("muted", "#94a3b8")))
            p.drawText(
                track_rect,
                Qt.AlignCenter,
                "👤 100% Professor em Destaque (Adicione intervalos abaixo para exibir slides)",
            )

        # 4. Playhead needle (current position cursor)
        play_x = self._ms_to_x(self.current_pos_ms)
        needle_color = QColor(c.get("focus", "#f59e0b"))

        # Inverted triangle at top
        p.setBrush(QBrush(needle_color))
        p.setPen(Qt.NoPen)
        tri = QPolygonF([
            QPointF(play_x - 5, 20),
            QPointF(play_x + 5, 20),
            QPointF(play_x, 28),
        ])
        p.drawPolygon(tri)

        # Vertical line through track
        p.setPen(QPen(needle_color, 2))
        p.drawLine(int(play_x), 28, int(play_x), int(track_top + track_h + 4))

        # Focus ring if focused
        if self.hasFocus():
            p.setPen(QPen(QColor(c.get("focus", "#f59e0b")), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            ms = self._x_to_ms(event.position().x())
            self.set_current_pos_ms(ms)
            self.time_selected.emit(ms)

            # Check if an interval was clicked
            clicked_idx = -1
            for idx, interval in enumerate(self.intervals):
                if interval.start_ms <= ms <= interval.end_ms:
                    clicked_idx = idx
                    break
            self.selected_index = clicked_idx
            self.interval_clicked.emit(clicked_idx)
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        ms = self._x_to_ms(event.position().x())
        if event.buttons() & Qt.LeftButton:
            self.set_current_pos_ms(ms)
            self.time_selected.emit(ms)
        else:
            # Hover tooltip
            layout_label = self.get_layout_label_at_ms(ms)
            time_str = format_ms_to_time(ms)
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"⏱ {time_str}\nLayout: {layout_label}",
                self,
            )
        super().mouseMoveEvent(event)
