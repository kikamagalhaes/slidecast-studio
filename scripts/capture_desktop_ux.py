"""Capture real Qt widgets; no camera/microphone recording or synthetic UI."""
import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QInputDialog
from app.ui.main_window import MainWindow
from app.ui.styles import LIGHT_THEME_QSS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--theme", default="light")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(LIGHT_THEME_QSS)
    window = MainWindow()
    if hasattr(window, "theme_manager"):
        window.theme_manager.set_theme(args.theme, persist=False)
    window.resize(1440, 960)
    window.show()
    for i, name in enumerate(("home", "editor", "aula", "reuniao", "podcast", "materiais")):
        window.stack.setCurrentIndex(i)
        app.processEvents()
        window.grab().save(str(out / f"{name}.png"))
    window.stack.setCurrentIndex(2)
    window.record_class_view.stack.setCurrentIndex(1)
    app.processEvents()
    window.grab().save(str(out / "estudio.png"))
    dialog = QInputDialog(window)
    dialog.setWindowTitle("Nome do projeto")
    dialog.setLabelText("Como você quer chamar esta aula?")
    dialog.setTextValue("Minha próxima aula")
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out / "dialogo.png"))
    dialog.close()
    window.close()
    print(f"Capturas Qt ({app.platformName()}) em {out}")


if __name__ == "__main__":
    main()
