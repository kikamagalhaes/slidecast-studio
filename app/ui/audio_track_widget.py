"""Controls edit the engine AudioTrack directly; colors never carry meaning alone."""
from pathlib import Path
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDoubleSpinBox, QCheckBox, QPushButton
from app.ui.styles import apply_style
from app.core.ffmpeg_utils import format_duration


class AudioTrackItemWidget(QFrame):
    track_changed = Signal(str)
    remove_requested = Signal(str)
    replace_requested = Signal(str)
    selected = Signal(str)

    def __init__(self, track, index=0, parent=None):
        super().__init__(parent)
        self.track, self.index = track, index
        self.setProperty("class", "track")
        self.setFixedHeight(104)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        top = QHBoxLayout()
        badge = QLabel(f"Faixa {index + 1}")
        apply_style(badge, f"color: @track{index + 1}@; font-weight: 700;")
        top.addWidget(badge)
        self.edit_name = QLineEdit(track.name)
        self.edit_name.setAccessibleName(f"Nome da faixa {index + 1}")
        self.edit_name.setMinimumWidth(80)
        self.edit_name.textEdited.connect(self._name_changed)
        top.addWidget(self.edit_name, 1)
        self.btn_replace = QPushButton("Trocar")
        self.btn_replace.setAccessibleName(f"Substituir arquivo da faixa {index + 1}")
        self.btn_replace.clicked.connect(lambda: self.replace_requested.emit(track.id))
        top.addWidget(self.btn_replace)
        self.btn_remove = QPushButton("Remover")
        self.btn_remove.setAccessibleName(f"Remover faixa {index + 1}")
        self.btn_remove.clicked.connect(lambda: self.remove_requested.emit(track.id))
        top.addWidget(self.btn_remove)
        layout.addLayout(top)
        row = QHBoxLayout()
        self.spin_volume = QDoubleSpinBox()
        self.spin_volume.setRange(0, 200)
        self.spin_volume.setDecimals(0)
        self.spin_volume.setSuffix(" %")
        self.spin_volume.setSingleStep(5)
        self.spin_volume.setValue(track.volume * 100)
        self.spin_volume.setAccessibleName(f"Volume da faixa {index + 1}, em porcentagem")
        self.spin_volume.valueChanged.connect(self._volume_changed)
        row.addWidget(QLabel("Volume"))
        row.addWidget(self.spin_volume)
        self.chk_mute = QCheckBox("Silenciar")
        self.chk_mute.setChecked(track.mute)
        self.chk_mute.toggled.connect(self._mute_changed)
        row.addWidget(self.chk_mute)
        row.addWidget(QLabel("Início"))
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(0, 864000)
        self.spin_offset.setDecimals(2)
        self.spin_offset.setSuffix(" s")
        self.spin_offset.setSingleStep(.5)
        self.spin_offset.setValue(track.offset)
        self.spin_offset.setAccessibleName(f"Início da faixa {index + 1}, em segundos")
        self.spin_offset.valueChanged.connect(self._offset_changed)
        row.addWidget(self.spin_offset)
        layout.addLayout(row)
        self.file_label = QLabel()
        self.file_label.setProperty("class", "muted")
        self.file_label.setMinimumWidth(0)
        layout.addWidget(self.file_label)
        self.update_status(0)

    def update_status(self, total):
        t = self.track
        if not Path(t.file_path).is_file():
            message = "Arquivo ausente. Use Trocar para localizar."
            color = "danger"
        elif t.mute or t.volume == 0:
            message, color = "Silenciada", "muted"
        elif total and t.offset >= total:
            message, color = "Começa após o fim do vídeo", "warning"
        elif total and t.effective_end() > total + .05:
            message, color = "Será cortada no final do vídeo", "warning"
        elif total and t.effective_end() < total - .05:
            message, color = "Termina antes do vídeo", "muted"
        else:
            message, color = "Áudio validado", "success"
        text = f"{Path(t.file_path).name} · {format_duration(t.duration)} · {message}"
        self.file_label.setToolTip(f"{t.file_path}\n{text}")
        # An elided label cannot force the editor past the notebook width.
        self.file_label.setText(self.file_label.fontMetrics().elidedText(text, Qt.ElideMiddle, max(300, self.width()-24)))
        apply_style(self.file_label, f"font-size: 11px; color: @{color}@;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "file_label"):
            self.update_status(getattr(self, "total", 0))

    def _name_changed(self, value):
        self.track.name = value.strip() or f"Faixa {self.index + 1}"
        self.track_changed.emit(self.track.id)

    def _volume_changed(self, value):
        self.track.volume = value / 100
        self.track_changed.emit(self.track.id)

    def _mute_changed(self, value):
        self.track.mute = value
        self.track_changed.emit(self.track.id)

    def _offset_changed(self, value):
        self.track.offset = value
        self.track_changed.emit(self.track.id)
