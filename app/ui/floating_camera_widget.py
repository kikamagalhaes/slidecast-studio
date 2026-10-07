from typing import Optional
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
)
from PySide6.QtMultimedia import (
    QCamera,
    QCameraDevice,
    QMediaCaptureSession,
    QMediaDevices,
)
from PySide6.QtMultimediaWidgets import QVideoWidget


class FloatingCameraWidget(QWidget):
    """
    Always-on-top, draggable floating camera bubble for teachers during live classes / Meet.
    Appears over any presentation, meeting, or app and is captured seamlessly in the recording.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(320, 210)
        self._drag_pos = QPoint()
        self.current_size_idx = 1  # 0: Small (240x160), 1: Med (320x210), 2: Large (420x280)
        self.sizes = [(240, 160), (320, 210), (420, 280)]

        # Camera & capture session
        self.camera: Optional[QCamera] = None
        self.capture_session = QMediaCaptureSession(self)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        # Outer rounded frame
        self.frame = QFrame()
        self.frame.setStyleSheet("""
            QFrame {
                background-color: #0b0f19;
                border: 2px solid #818cf8;
                border-radius: 12px;
            }
        """)
        f_layout = QVBoxLayout(self.frame)
        f_layout.setContentsMargins(4, 4, 4, 4)
        f_layout.setSpacing(4)

        # Top handle bar
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(6, 2, 6, 2)
        top_bar.setSpacing(6)

        lbl_drag = QLabel("📷 Minha Câmera")
        lbl_drag.setStyleSheet("font-size: 11px; font-weight: 700; color: #c7d2fe; border: none; background: transparent;")
        lbl_drag.setToolTip("Clique e arraste para posicionar a câmera onde quiser na tela")

        self.btn_resize = QPushButton("Tamanho")
        self.btn_resize.setCursor(Qt.PointingHandCursor)
        self.btn_resize.setToolTip("Alternar tamanho: Pequeno / Médio / Grande")
        self.btn_resize.setStyleSheet("""
            QPushButton {
                background: #1e1b4b;
                color: #a5b4fc;
                border: 1px solid #4338ca;
                border-radius: 4px;
                padding: 1px 6px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #312e81;
            }
        """)
        self.btn_resize.clicked.connect(self._cycle_size)

        btn_close = QPushButton("✕")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setToolTip("Ocultar câmera flutuante")
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #94a3b8;
                border: none;
                font-size: 12px;
                font-weight: 700;
                padding: 1px 4px;
            }
            QPushButton:hover {
                color: #ef4444;
            }
        """)
        btn_close.clicked.connect(self.hide)

        top_bar.addWidget(lbl_drag)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_resize)
        top_bar.addWidget(btn_close)
        f_layout.addLayout(top_bar)

        # Video Output Widget
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("border-radius: 8px; background-color: #000000; border: none;")
        self.capture_session.setVideoOutput(self.video_widget)
        f_layout.addWidget(self.video_widget)

        root.addWidget(self.frame)

    def start_camera(self, camera_device: Optional[QCameraDevice] = None):
        try:
            if self.camera:
                self.camera.stop()
                self.camera.deleteLater()
                self.camera = None

            if camera_device:
                self.camera = QCamera(camera_device, self)
            else:
                default_cam = QMediaDevices.defaultVideoInput()
                self.camera = QCamera(default_cam, self) if default_cam else QCamera(self)

            self.capture_session.setCamera(self.camera)
            self.camera.start()
        except Exception as e:
            print(f"Aviso ao iniciar câmera flutuante: {e}")

    def stop_camera(self):
        if self.camera:
            try:
                self.camera.stop()
            except Exception:
                pass

    def _cycle_size(self):
        self.current_size_idx = (self.current_size_idx + 1) % len(self.sizes)
        w, h = self.sizes[self.current_size_idx]
        self.resize(w, h)

    # Drag window handlers
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
