"""Audio Track Widget for SlideCast Multimedia Video Creator.

Renders an individual audio track row with:
- Track label & custom display name
- Probed file info and duration badge
- Gain / Volume control (0% - 200%)
- Mute toggle
- Start offset on timeline (seconds)
- Remove track button
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QDoubleSpinBox,
    QSlider,
    QCheckBox,
    QPushButton,
    QWidget,
)

from app.core.multitrack import AudioTrack
from app.core.ffmpeg_utils import format_duration


class AudioTrackItemWidget(QFrame):
    """Widget representing one audio track in the multitrack editor."""
    track_changed = Signal(str)      # track_id
    remove_requested = Signal(str)   # track_id

    def __init__(self, track: AudioTrack, index: int = 0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.track = track
        self.index = index
        self.setProperty("class", "card")
        self.setStyleSheet(
            "QFrame { background-color: #1e2430; border: 1px solid #334155; border-radius: 8px; padding: 6px; } "
            "QLabel { color: #f8fafc; font-size: 12px; } "
            "QLineEdit { background: #0f172a; color: #f8fafc; border: 1px solid #475569; border-radius: 4px; padding: 4px 8px; font-size: 12px; } "
            "QDoubleSpinBox { background: #0f172a; color: #f8fafc; border: 1px solid #475569; border-radius: 4px; padding: 2px 4px; font-size: 12px; } "
            "QCheckBox { color: #cbd5e1; font-size: 12px; }"
        )
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 6, 8, 6)
        main_layout.setSpacing(6)

        # Top row: Index badge, Name input, File name, Duration, Remove button
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        lbl_idx = QLabel(f"#{self.index + 1}")
        lbl_idx.setStyleSheet("font-weight: 700; color: #38bdf8; min-width: 24px;")
        top_row.addWidget(lbl_idx)

        self.edit_name = QLineEdit(self.track.name)
        self.edit_name.setPlaceholderText("Nome da faixa...")
        self.edit_name.setMaximumWidth(160)
        self.edit_name.textChanged.connect(self._on_name_changed)
        top_row.addWidget(self.edit_name)

        p = Path(self.track.file_path)
        lbl_file = QLabel(p.name)
        lbl_file.setStyleSheet("color: #94a3b8; font-style: italic;")
        lbl_file.setToolTip(str(p))
        top_row.addWidget(lbl_file, stretch=1)

        dur_text = format_duration(self.track.duration)
        if self.track.sample_rate:
            dur_text += f" • {self.track.sample_rate // 1000}kHz"
        self.lbl_dur = QLabel(dur_text)
        self.lbl_dur.setStyleSheet("background: #0f172a; color: #34d399; font-weight: 600; padding: 2px 6px; border-radius: 4px;")
        top_row.addWidget(self.lbl_dur)

        self.btn_remove = QPushButton("✕")
        self.btn_remove.setCursor(Qt.PointingHandCursor)
        self.btn_remove.setToolTip("Remover faixa")
        self.btn_remove.setStyleSheet(
            "QPushButton { background: #450a0a; color: #f87171; border: 1px solid #991b1b; "
            "border-radius: 4px; font-weight: 700; padding: 2px 8px; font-size: 11px; } "
            "QPushButton:hover { background: #7f1d1d; }"
        )
        self.btn_remove.clicked.connect(lambda: self.remove_requested.emit(self.track.id))
        top_row.addWidget(self.btn_remove)

        main_layout.addLayout(top_row)

        # Bottom row: Volume / Gain, Mute, Start Offset
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(14)

        # Volume control
        vol_box = QHBoxLayout()
        vol_box.setSpacing(6)
        lbl_vol = QLabel("Volume:")
        lbl_vol.setStyleSheet("color: #94a3b8;")
        self.spin_volume = QDoubleSpinBox()
        self.spin_volume.setRange(0.0, 200.0)
        self.spin_volume.setSingleStep(5.0)
        self.spin_volume.setSuffix("%")
        self.spin_volume.setValue(round(self.track.volume * 100, 1))
        self.spin_volume.valueChanged.connect(self._on_volume_changed)
        vol_box.addWidget(lbl_vol)
        vol_box.addWidget(self.spin_volume)
        ctrl_row.addLayout(vol_box)

        # Mute checkbox
        self.chk_mute = QCheckBox("Mutar")
        self.chk_mute.setChecked(self.track.mute)
        self.chk_mute.toggled.connect(self._on_mute_toggled)
        ctrl_row.addWidget(self.chk_mute)

        # Offset control
        offset_box = QHBoxLayout()
        offset_box.setSpacing(6)
        lbl_offset = QLabel("Início (offset):")
        lbl_offset.setStyleSheet("color: #94a3b8;")
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(0.0, 7200.0)
        self.spin_offset.setSingleStep(0.5)
        self.spin_offset.setSuffix("s")
        self.spin_offset.setValue(round(self.track.offset, 2))
        self.spin_offset.valueChanged.connect(self._on_offset_changed)
        offset_box.addWidget(lbl_offset)
        offset_box.addWidget(self.spin_offset)
        ctrl_row.addLayout(offset_box)

        ctrl_row.addStretch()
        main_layout.addLayout(ctrl_row)

    def _on_name_changed(self, text: str):
        self.track.name = text.strip() or "Faixa de Áudio"
        self.track_changed.emit(self.track.id)

    def _on_volume_changed(self, val: float):
        self.track.volume = max(0.0, min(2.0, val / 100.0))
        self.track_changed.emit(self.track.id)

    def _on_mute_toggled(self, checked: bool):
        self.track.mute = checked
        self.track_changed.emit(self.track.id)

    def _on_offset_changed(self, val: float):
        self.track.offset = max(0.0, float(val))
        self.track_changed.emit(self.track.id)

    def update_index(self, new_index: int):
        self.index = new_index
        # Refresh label if needed
