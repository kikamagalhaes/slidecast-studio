import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication

from app.core.logging_config import setup_logging
from app.ui.main_window import MainWindow
from app.ui.styles import DARK_THEME_QSS


def self_test() -> int:
    """Headless end-to-end check of the (frozen) bundle: deps, ffmpeg, core.

    Used by packaging CI on every OS and by support to diagnose installs.
    Returns process exit code (0 = OK). Prints SELF-TEST OK on success.
    """
    import math
    import struct
    import subprocess
    import tempfile
    import wave

    # Windowed frozen apps (Windows) have no stdout: keep prints from crashing.
    if sys.stdout is None:  # pragma: no cover - frozen Windows only
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:  # pragma: no cover - frozen Windows only
        sys.stderr = open(os.devnull, "w")

    failures = []

    for mod in (
        "PySide6.QtWidgets",
        "pymupdf",
        "mutagen",
        "google.genai",
        "edge_tts",
        "replicate",
        "requests",
    ):
        try:
            __import__(mod)
            print(f"import ok: {mod}")
        except Exception as exc:
            failures.append(mod)
            print(f"import FAIL: {mod}: {exc}")

    from app.core.ffmpeg_utils import get_ffmpeg_paths

    ffmpeg_path, _ = get_ffmpeg_paths()
    print(f"ffmpeg: {ffmpeg_path or 'NOT FOUND'}")
    if not ffmpeg_path:
        failures.append("ffmpeg")
    else:
        try:
            out = subprocess.run(
                [ffmpeg_path, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )
            print("ffmpeg runs:", out.stdout.splitlines()[0][:80] if out.stdout else "?")
            if out.returncode != 0:
                failures.append("ffmpeg-run")
        except Exception as exc:
            failures.append("ffmpeg-run")
            print(f"ffmpeg run FAIL: {exc}")

    try:
        import pymupdf

        from app.core.audio_processor import get_audio_info
        from app.core.pdf_processor import inspect_pdf

        with tempfile.TemporaryDirectory(prefix="slidecast-selftest-") as tmp:
            pdf_path = os.path.join(tmp, "t.pdf")
            doc = pymupdf.open()
            doc.new_page(width=595, height=842)
            doc.save(pdf_path)
            doc.close()
            wav_path = os.path.join(tmp, "t.wav")
            rate = 22050
            with wave.open(wav_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                for i in range(rate):
                    wav.writeframes(
                        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate)))
                    )
            pdf_info = inspect_pdf(pdf_path)
            audio_info = get_audio_info(wav_path)
            print(f"core ok: pages={pdf_info.page_count} duration={audio_info.duration:.1f}s")
    except Exception as exc:
        failures.append("core-pipeline")
        print(f"core pipeline FAIL: {exc!r}")

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from app.ui.main_window import MainWindow

        qt_app = QApplication([])
        window = MainWindow()
        print(f"qt ok: {window.windowTitle() or 'MainWindow'} built")
        qt_app.quit()
    except Exception as exc:
        failures.append("qt-window")
        print(f"qt window FAIL: {exc!r}")

    if failures:
        print(f"SELF-TEST FAILED: {', '.join(failures)}")
        return 1
    print("SELF-TEST OK")
    return 0


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
    if "--self-test" in sys.argv:
        sys.argv = [a for a in sys.argv if a != "--self-test"]
        sys.exit(self_test())
    main()
