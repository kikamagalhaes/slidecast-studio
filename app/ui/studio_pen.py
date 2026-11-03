"""Pen overlay for the desktop live studio (permanent + temporary ink).

Draws on top of the slide/whiteboard preview. Temporary strokes expire
after the configured TTL (3/5/8s) so they appear in the exported frame
only while visible; the source PDF is never modified.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget

from app.core import studio as studio_core


class StudioPenOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.state: dict = studio_core.new_studio_state()
        self.mode = "off"  # off | temp | perm | highlight
        self.board_mode = False
        self._current: list | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def set_enabled(self, mode: str, board: bool = False) -> None:
        self.mode = mode
        self.board_mode = board
        active = mode != "off" or board
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not active)

    def _norm(self, pos) -> list[float]:
        w, h = max(1, self.width()), max(1, self.height())
        return [pos.x() / w, pos.y() / h]

    def mousePressEvent(self, event):  # noqa: N802 (Qt naming)
        if self.mode == "off" and not self.board_mode:
            return
        self._current = [self._norm(event.position())]
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._current is None:
            return
        self._current.append(self._norm(event.position()))
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._current is None or len(self._current) < 2:
            self._current = None
            return
        kind = "perm" if self.board_mode else self.mode
        if self.board_mode:
            self.state["whiteboard"]["strokes"].append(
                {"points": self._current, "color": "#1d4ed8", "width": 4})
        else:
            studio_core.add_stroke(
                self.state, self._current, kind=kind,
                color="#facc15" if kind == "highlight" else "#e11d48",
                width=16 if kind == "highlight" else 4)
        self._current = None
        self.update()
        event.accept()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        now = time.time()
        strokes = list(studio_core.visible_strokes(self.state, now=now))
        if self.board_mode:
            strokes = [{"kind": "perm", "color": s.get("color", "#1d4ed8"),
                        "width": s.get("width", 4), "points": s["points"]}
                       for s in self.state["whiteboard"]["strokes"]]
        if self._current:
            strokes = strokes + [{"kind": "perm", "color": "#e11d48",
                                  "width": 4, "points": self._current}]
        w, h = self.width(), self.height()
        for s in strokes:
            color = QColor(s.get("color", "#e11d48"))
            if s.get("kind") == "highlight":
                color.setAlpha(90)
            painter.setPen(QPen(color, int(s.get("width", 4)),
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            pts = [QPointF(x * w, y * h) for x, y in s.get("points", [])]
            for a, b in zip(pts, pts[1:]):
                painter.drawLine(a, b)
        painter.end()
