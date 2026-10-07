import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.ui.main_window import MainWindow
from app.ui.styles import DARK_THEME_QSS


def main():
    # Fix potential font rendering / platform issues
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    # On Linux, pre-load local libxcb-cursor if present
    if sys.platform == "linux":
        try:
            import ctypes
            libs_dir = Path(__file__).resolve().parent / "libs"
            cursor_lib = libs_dir / "libxcb-cursor.so.0"
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
