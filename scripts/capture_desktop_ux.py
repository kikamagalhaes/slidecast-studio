"""Capture real Qt widgets; no camera/microphone recording or synthetic UI."""
import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QInputDialog, QFileDialog, QMenu
from PySide6.QtCore import QPoint
from app.ui.main_window import MainWindow
from app.ui.styles import LIGHT_THEME_QSS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--theme", default="light")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--matrix", action="store_true")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(LIGHT_THEME_QSS)
    window = MainWindow()
    if hasattr(window, "theme_manager"):
        window.theme_manager.set_theme(args.theme, persist=False)
    if args.sample:
        import math
        import struct
        import wave
        import pymupdf
        from app.core.multitrack import probe_audio_track
        samples = out / "amostras"
        samples.mkdir(exist_ok=True)
        pdf = samples / "A arte de ensinar.pdf"
        doc = pymupdf.open()
        for i, title in enumerate(("Ideias que ganham vida.", "Uma boa história aproxima.", "O conhecimento continua.")):
            page = doc.new_page(width=960, height=540)
            page.draw_rect(page.rect, color=None, fill=(.06,.18,.16))
            page.insert_text((64,78), "SLIDECAST  /  AULA DE DEMONSTRACAO", fontsize=14, color=(.78,.86,.76))
            page.insert_textbox(pymupdf.Rect(64,158,900,370), title, fontsize=58, fontname="tiro", color=(.96,.94,.88))
            page.draw_line((64,418),(896,418),color=(.58,.67,.53))
            page.insert_text((64,460), "Preparar. Compartilhar. Inspirar.", fontsize=20,color=(.83,.72,.44))
            page.insert_text((860,460), f"0{i+1}", fontsize=20,color=(.83,.72,.44))
        doc.save(pdf)
        doc.close()
        editor = window.create_video_view
        editor.project.title = "A arte de ensinar"
        editor.project.set_visual_source("pdf",str(pdf.resolve()),slide_durations=[10,10,10])
        for i, (name, duration, volume, offset) in enumerate((
                ("Narração",30,1,0), ("Música de fundo",40,.2,0),
                ("Sonoplastia",3,.65,10), ("Complemento",8,.8,19))):
            path = samples / f"{name}.wav"
            with wave.open(str(path),"wb") as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000)
                f.writeframes(b"".join(struct.pack("<h", int(1800*math.sin(2*math.pi*(220+i*110)*n/8000))) for n in range(8000*duration)))
            editor.project.add_track(probe_audio_track(str(path.resolve()),name=name,volume=volume,offset=offset))
        editor.refresh()
        # The sample really is saved using the engine serializer.
        editor.project_path = str(samples / "aula.slidecast")
        editor.save_dialog()
    window.resize(args.width, args.height)
    window.show()
    for i, name in enumerate(("home", "editor", "aula", "reuniao", "podcast", "materiais")):
        window.stack.setCurrentIndex(i)
        app.processEvents()
        window.grab().save(str(out / f"{name}.png"))
    if args.matrix:
        for index, name, view in ((2,"aula",window.record_class_view),(3,"reuniao",window.record_meet_view),(4,"podcast",window.record_podcast_view),(5,"materiais",window.generate_materials_view)):
            window.stack.setCurrentIndex(index)
            for step in range(view.step_stack.count()):
                view._switch_step(step)
                app.processEvents()
                window.grab().save(str(out / f"{name}-etapa-{step+1}.png"))
            view._switch_step(0)
    window.stack.setCurrentIndex(2)
    window.record_class_view.stack.setCurrentIndex(1)
    app.processEvents()
    if args.sample:
        from app.core.pdf_processor import inspect_pdf
        from app.core import studio as core
        view = window.record_class_view
        info = inspect_pdf(str(pdf.resolve()))
        for slot in (1, 2, 3):
            view.pdf_slots[slot] = {"info": info, "page": slot-1}
            view.studio = core.set_pdf(view.studio,slot,str(pdf.resolve()),info.page_count,f"Material {slot}")
        view.pdf_info = info
        view.prompter.set_script_text("Boas-vindas à nossa aula. Hoje vamos descobrir como transformar ideias em experiências de aprendizagem.\n\nFaça uma pausa e convide a turma a participar.")
        view._update_slide_display()
        app.processEvents()
    window.grab().save(str(out / "estudio.png"))
    dialog = QInputDialog(window)
    dialog.setWindowTitle("Nome do projeto")
    dialog.setLabelText("Como você quer chamar esta aula?")
    dialog.setTextValue("Minha próxima aula")
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out / "dialogo.png"))
    # Theme changes are made with a real open modal in this process.
    if hasattr(window, "theme_manager"):
        window.theme_manager.set_theme("light" if args.theme == "dark" else "dark", persist=False)
        app.processEvents()
        dialog.grab().save(str(out / "dialogo-tema-alternado.png"))
        window.theme_manager.set_theme(args.theme, persist=False)
    dialog.close()
    picker = QFileDialog(window, "Selecionar arquivos")
    picker.setOption(QFileDialog.DontUseNativeDialog, True)
    picker.setDirectory(str(out.resolve()))
    picker.show()
    app.processEvents()
    picker.grab().save(str(out / "seletor-arquivos.png"))
    picker.close()
    menu = QMenu(window)
    menu.addAction("Abrir projeto")
    menu.addAction("Salvar projeto")
    menu.addAction("Indisponível neste estado").setEnabled(False)
    menu.popup(QPoint(100,100))
    app.processEvents()
    menu.grab().save(str(out / "menu.png"))
    menu.close()
    if hasattr(window, "create_video_view") and hasattr(window.create_video_view, "dirty"):
        window.create_video_view.dirty = False
    window.close()
    print(f"Capturas Qt ({app.platformName()}) em {out}")


if __name__ == "__main__":
    main()
