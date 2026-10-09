import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.core.logging_config import setup_logging
from app.ui.main_window import MainWindow
from app.ui.styles import DARK_THEME_QSS


def main():
    setup_logging()

    # Fix potential font rendering / platform issues
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    # On Linux, pre-load local libxcb-cursor if present
    if sys.platform == "linux":
        try:
            import ctypes

            if getattr(sys, "frozen", False):
                base_dir = Path(sys._MEIPASS)  # PyInstaller bundle dir
            else:
                base_dir = Path(__file__).resolve().parent
            cursor_lib = base_dir / "libs" / "libxcb-cursor.so.0"
            if cursor_lib.exists():
                ctypes.CDLL(str(cursor_lib))
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("SlideCast Studio")
    app.setOrganizationName("SlideCast")
    app.setApplicationVersion("1.0.0")

    # Apply Dark Theme QSS
    app.setStyleSheet(DARK_THEME_QSS)

    window = MainWindow()
    window.show()

    # Packaging smoke test: quit shortly after startup when requested.
    smoke_ms = os.environ.get("SLIDECAST_SMOKE_QUIT")
    if smoke_ms:
        try:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(max(500, int(smoke_ms)), app.quit)
        except ValueError:
            pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
