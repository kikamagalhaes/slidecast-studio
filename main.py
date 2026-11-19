import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication

from app.core.logging_config import setup_logging
from app.ui.main_window import MainWindow
from app.ui.styles import theme_manager


def self_test(report_path=None) -> int:
    """Verify bundled dependencies, real PDF/MP4 rendering and both Qt themes."""
    import json
    import math
    import struct
    import subprocess
    import tempfile
    import wave
    from app.core.ffmpeg_utils import get_ffmpeg_paths

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    report = {"failures": [], "media_tools": {}, "renders": {}, "themes": []}
    failures = report["failures"]
    for mod in ("PySide6.QtWidgets", "pymupdf", "mutagen", "google.genai", "edge_tts", "replicate", "requests"):
        try:
            __import__(mod)
        except Exception as exc:
            failures.append(f"{mod}: {exc}")

    for name, executable in zip(("ffmpeg", "ffprobe"), get_ffmpeg_paths()):
        try:
            if not executable:
                raise RuntimeError("not found")
            if os.environ.get("SLIDECAST_REQUIRE_BUNDLED_MEDIA") == "1":
                bundle = Path(sys._MEIPASS).resolve()
                if not Path(executable).resolve().is_relative_to(bundle):
                    raise RuntimeError("tool outside bundle")
            result = subprocess.run([executable, "-version"], capture_output=True, text=True, check=True, timeout=30)
            report["media_tools"][name] = result.stdout.splitlines()[0]
        except Exception as exc:
            failures.append(f"{name}: {exc}")

    if not failures:
        try:
            import pymupdf
            from app.core.multitrack import MultimediaProject, inspect_video, probe_audio_track
            from app.core.multitrack_video_builder import generate_multimedia_video
            with tempfile.TemporaryDirectory(prefix="slidecast-selftest-") as tmp:
                root = Path(tmp)
                pdf = root / "aula com acentos.pdf"
                doc = pymupdf.open()
                for number in range(2):
                    page = doc.new_page(width=640, height=360)
                    page.insert_text((40, 80), f"SlideCast {number+1}", fontsize=28)
                doc.save(pdf); doc.close()
                audio = root / "narracao.wav"
                with wave.open(str(audio), "wb") as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
                    wav.writeframes(b"".join(struct.pack("<h", int(1600*math.sin(2*math.pi*220*n/8000))) for n in range(16000)))
                project = MultimediaProject()
                project.set_visual_source("pdf", str(pdf), slide_durations=[1, 1])
                for index in range(4):
                    project.add_track(probe_audio_track(str(audio), name=f"Faixa {index+1}", volume=.2, offset=index*.1))
                project.export_settings.update(resolution=[320, 180], fps=15)
                for kind in ("pdf", "mp4"):
                    output = str(root / f"saida-{kind}.mp4")
                    generate_multimedia_video(project, output, dpi=72)
                    info = inspect_video(output)
                    if not (1.8 <= info.duration <= 2.2 and info.has_audio and info.width == 320):
                        raise RuntimeError(f"Invalid {kind} output: {info}")
                    report["renders"][kind] = {"duration": info.duration, "width": info.width, "height": info.height, "audio": info.has_audio}
                    if kind == "pdf":
                        project.set_visual_source("video", output)
                project.save_to_file(str(root / "teste.slidecast"))
                restored = MultimediaProject.load_from_file(str(root / "teste.slidecast"))
                if len(restored.tracks) != 4:
                    raise RuntimeError("project did not preserve four tracks")
        except Exception as exc:
            failures.append(f"multimedia-pipeline: {exc!r}")

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt_app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.show()
        for theme in ("light", "dark"):
            window.theme_manager.set_theme(theme, persist=False)
            qt_app.processEvents()
            if window.grab().isNull():
                raise RuntimeError("Qt did not render the window")
            report["themes"].append(theme)
        window.close()
        qt_app.quit()
    except Exception as exc:
        failures.append(f"qt-window: {exc!r}")

    if report_path:
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    print("SELF-TEST FAILED" if failures else "SELF-TEST OK")
    return 1 if failures else 0


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
    app.setApplicationVersion("1.2.0")

    # Restore the operator theme before building any screens.
    theme_manager()

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
    if "--self-test" in sys.argv:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--self-test", action="store_true")
        parser.add_argument("--self-test-report")
        args = parser.parse_args()
        sys.exit(self_test(args.self_test_report))
    main()
