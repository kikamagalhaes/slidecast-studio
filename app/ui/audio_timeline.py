"""Precisely scaled audio blocks. No generated or decorative waveforms."""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget, QSizePolicy
from app.ui.styles import tokens, theme_manager
from app.core.ffmpeg_utils import format_duration


class AudioTimeline(QWidget):
    track_selected = Signal(str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.position = 0.0
        self.selected_id = None
        self.setMinimumWidth(400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("Linha do tempo de áudio. Edite o início de cada faixa nos controles ao lado.")
        self.setFocusPolicy(Qt.StrongFocus)
        theme_manager().changed.connect(self.update)
        self.refresh()

    def refresh(self):
        self.setFixedHeight(38 + max(1, len(self.project.tracks)) * 134)
        self.update()

    def paintEvent(self, event):
        c = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(c['surface']))
        total = max(1, self.project.calculate_total_duration())
        width = max(1, self.width()-32)
        p.setPen(QColor(c['muted']))
        ticks = max(2, min(12, width // 110))
        for i in range(ticks+1):
            x = 16 + i * width/ticks
            p.setPen(QColor(c['border']))
            p.drawLine(int(x), 30, int(x), self.height())
            p.setPen(QColor(c['muted']))
            p.drawText(QRectF(x-38, 4, 76, 24), Qt.AlignCenter, format_duration(total*i/ticks))
        end_x = 16+width
        p.setPen(QPen(QColor(c['border_strong']), 2, Qt.DashLine))
        p.drawLine(int(end_x), 30, int(end_x), self.height())
        for i, track in enumerate(self.project.tracks):
            y = 38+i*134
            p.fillRect(QRectF(16, y+8, width, 92), QColor(c['surface_alt']))
            x = 16+min(track.offset/total, 1)*width
            end = 16+min(track.effective_end()/total, 1)*width
            color = c['muted'] if track.mute or track.volume == 0 else c[f'track{i+1}']
            fill = QColor(color)
            fill.setAlpha(22)
            p.setBrush(fill)
            p.setPen(QPen(QColor(color if track.id == self.selected_id else c['border']), 2 if track.id == self.selected_id else 1))
            if end > x:
                rect = QRectF(x, y+14, max(2, end-x), 78)
                p.drawRoundedRect(rect, 7, 7)
                p.save()
                p.setClipRect(rect.adjusted(6, 2, -4, -2))
                p.setPen(QColor(c['text']))
                p.drawText(QRectF(x+10, y+24, max(200,end-x-20), 22), Qt.AlignLeft, f"{i+1}  {track.name}")
                p.setPen(QColor(c['secondary']))
                text = "Silenciada" if track.mute else f"Início {format_duration(track.offset)} · {track.volume*100:.0f}%"
                p.drawText(QRectF(x+10,y+55,max(200,end-x-20),22),Qt.AlignLeft,text)
                p.restore()
            if track.effective_end()>total:
                p.setPen(QColor(c['warning']))
                p.drawText(QRectF(16,y+76,width-6,22),Qt.AlignRight,"Corte no fim ›")
        if not self.project.tracks:
            p.setPen(QColor(c['muted']))
            p.drawText(self.rect().adjusted(20, 38, -20, 0), Qt.AlignCenter, "Adicione um áudio para ver sua posição no vídeo.")
        x = 16+min(max(self.position/total,0),1)*width
        p.setPen(QPen(QColor(c['danger']), 2))
        p.drawLine(int(x), 30, int(x), self.height())
        if self.hasFocus():
            p.setPen(QPen(QColor(c['focus']),2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(1,1,-1,-1))

    def mousePressEvent(self, event):
        index = int((event.position().y()-38)//134)
        if 0 <= index < len(self.project.tracks):
            self.selected_id = self.project.tracks[index].id
            self.track_selected.emit(self.selected_id)
            self.update()
        super().mousePressEvent(event)
