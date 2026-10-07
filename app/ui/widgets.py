from pathlib import Path
from typing import List, Optional
from PySide6.QtCore import Qt, Signal, QByteArray
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QImage
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QDoubleSpinBox,
    QWidget,
    QSizePolicy,
)


class DropAreaWidget(QFrame):
    file_selected = Signal(str)
    file_removed = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        icon_text: str,
        file_filter: str,
        valid_extensions: List[str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.title_text = title
        self.subtitle_text = subtitle
        self.icon_text = icon_text
        self.file_filter = file_filter
        self.valid_extensions = [ext.lower() for ext in valid_extensions]
        self.current_file_path: Optional[str] = None

        self.setAcceptDrops(True)
        self.setProperty("class", "drop-zone")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._build_ui()

    def _build_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(10)
        self.layout.setAlignment(Qt.AlignCenter)

        # Empty view container
        self.empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(8)

        self.lbl_icon = QLabel(self.icon_text)
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        self.lbl_icon.setStyleSheet("font-size: 36px; margin-bottom: 4px;")

        self.lbl_title = QLabel(self.title_text)
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: 600; color: #f1f5f9;")

        self.lbl_sub = QLabel(self.subtitle_text)
        self.lbl_sub.setAlignment(Qt.AlignCenter)
        self.lbl_sub.setStyleSheet("font-size: 12px; color: #94a3b8;")

        self.btn_browse = QPushButton("Procurar Arquivo...")
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.setStyleSheet("margin-top: 6px;")
        self.btn_browse.clicked.connect(self._open_file_dialog)

        empty_layout.addWidget(self.lbl_icon)
        empty_layout.addWidget(self.lbl_title)
        empty_layout.addWidget(self.lbl_sub)
        empty_layout.addWidget(self.btn_browse, alignment=Qt.AlignCenter)

        # Loaded view container
        self.loaded_widget = QWidget()
        loaded_layout = QVBoxLayout(self.loaded_widget)
        loaded_layout.setAlignment(Qt.AlignCenter)
        loaded_layout.setSpacing(8)

        self.lbl_loaded_icon = QLabel(self.icon_text)
        self.lbl_loaded_icon.setAlignment(Qt.AlignCenter)
        self.lbl_loaded_icon.setStyleSheet("font-size: 32px;")

        self.lbl_filename = QLabel("")
        self.lbl_filename.setAlignment(Qt.AlignCenter)
        self.lbl_filename.setWordWrap(True)
        self.lbl_filename.setStyleSheet("font-size: 14px; font-weight: 600; color: #38bdf8;")

        self.lbl_info = QLabel("")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        self.lbl_info.setStyleSheet("font-size: 12px; color: #a7f3d0;")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.setAlignment(Qt.AlignCenter)

        self.btn_change = QPushButton("Trocar")
        self.btn_change.setCursor(Qt.PointingHandCursor)
        self.btn_change.clicked.connect(self._open_file_dialog)

        self.btn_remove = QPushButton("Remover")
        self.btn_remove.setProperty("class", "danger")
        self.btn_remove.setCursor(Qt.PointingHandCursor)
        self.btn_remove.clicked.connect(self.clear_file)

        btn_row.addWidget(self.btn_change)
        btn_row.addWidget(self.btn_remove)

        loaded_layout.addWidget(self.lbl_loaded_icon)
        loaded_layout.addWidget(self.lbl_filename)
        loaded_layout.addWidget(self.lbl_info)
        loaded_layout.addLayout(btn_row)

        self.layout.addWidget(self.empty_widget)
        self.layout.addWidget(self.loaded_widget)
        self.loaded_widget.hide()

    def _open_file_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Selecionar {self.title_text}",
            "",
            self.file_filter,
        )
        if file_path:
            self.set_file(file_path)

    def set_file(self, file_path: str, info_text: str = ""):
        self.current_file_path = file_path
        path = Path(file_path)
        self.lbl_filename.setText(path.name)
        self.lbl_info.setText(info_text)

        self.empty_widget.hide()
        self.loaded_widget.show()
        self.setProperty("class", "drop-zone-loaded")
        self.style().unpolish(self)
        self.style().polish(self)

        self.file_selected.emit(file_path)

    def update_info(self, info_text: str):
        self.lbl_info.setText(info_text)

    def clear_file(self):
        self.current_file_path = None
        self.lbl_filename.setText("")
        self.lbl_info.setText("")
        self.loaded_widget.hide()
        self.empty_widget.show()
        self.setProperty("class", "drop-zone")
        self.style().unpolish(self)
        self.style().polish(self)
        self.file_removed.emit()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) > 0:
                file_path = urls[0].toLocalFile()
                suffix = Path(file_path).suffix.lower()
                if suffix in self.valid_extensions:
                    event.acceptProposedAction()
                    self.setProperty("class", "drop-zone-active")
                    self.style().unpolish(self)
                    self.style().polish(self)
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        cls = "drop-zone-loaded" if self.current_file_path else "drop-zone"
        self.setProperty("class", cls)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        cls = "drop-zone-loaded" if self.current_file_path else "drop-zone"
        self.setProperty("class", cls)
        self.style().unpolish(self)
        self.style().polish(self)

        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            suffix = Path(file_path).suffix.lower()
            if suffix in self.valid_extensions:
                self.set_file(file_path)
                event.acceptProposedAction()


class SlideThumbWidget(QFrame):
    duration_changed = Signal(int, float)  # slide_index, new_duration

    def __init__(
        self,
        slide_index: int,
        thumbnail_bytes: bytes,
        duration: float,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.slide_index = slide_index
        self._duration = duration

        self.setProperty("class", "card")
        self.setStyleSheet("""
            QFrame.card {
                background-color: #171b26;
                border: 1px solid #2e3547;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        self.setFixedWidth(160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Header badge: Slide #
        self.lbl_title = QLabel(f"Slide {slide_index + 1}")
        self.lbl_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #93c5fd;")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_title)

        # Thumbnail image
        self.lbl_image = QLabel()
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setFixedHeight(95)
        self.lbl_image.setStyleSheet("background-color: #0b0d13; border-radius: 4px;")

        qimg = QImage.fromData(thumbnail_bytes)
        pix = QPixmap.fromImage(qimg)
        scaled_pix = pix.scaled(148, 95, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lbl_image.setPixmap(scaled_pix)
        layout.addWidget(self.lbl_image)

        # Duration control
        dur_row = QHBoxLayout()
        dur_row.setSpacing(4)
        lbl_sec = QLabel("Duração:")
        lbl_sec.setStyleSheet("font-size: 11px; color: #94a3b8;")

        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setRange(0.1, 7200.0)
        self.spin_duration.setSingleStep(0.5)
        self.spin_duration.setDecimals(1)
        self.spin_duration.setSuffix(" s")
        self.spin_duration.setValue(duration)
        self.spin_duration.setStyleSheet("font-size: 11px; font-weight: 600;")
        self.spin_duration.valueChanged.connect(self._on_value_changed)

        dur_row.addWidget(lbl_sec)
        dur_row.addWidget(self.spin_duration)
        layout.addLayout(dur_row)

    def _on_value_changed(self, val: float):
        self._duration = val
        self.duration_changed.emit(self.slide_index, val)

    def set_duration(self, val: float):
        self.spin_duration.blockSignals(True)
        self.spin_duration.setValue(val)
        self.spin_duration.blockSignals(False)
        self._duration = val
