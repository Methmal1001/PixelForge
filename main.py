"""PixelForge AI Studio — application entry point.

Run with:  python main.py
"""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from app_info import APP_NAME, APP_VERSION, ORGANIZATION


def _set_windows_app_id() -> None:
    """Give the app its own taskbar identity on Windows (instead of python.exe)."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{ORGANIZATION}.AIStudio.{APP_VERSION}")
        except (AttributeError, OSError):
            pass


def main() -> int:
    _set_windows_app_id()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION)

    from ui.main_window import MainWindow
    from ui.preferences import load_theme_mode
    from ui.sidebar import logo_pixmap
    from ui.styles import apply_theme

    apply_theme(app, load_theme_mode())
    from ui.widgets import WheelGuard

    wheel_guard = WheelGuard(app)  # dropdowns/sliders change only on click, never on scroll
    app.installEventFilter(wheel_guard)
    app.setWindowIcon(QIcon(logo_pixmap()))

    # Let Ctrl+C in the terminal close the app: Qt's event loop otherwise never
    # hands control back to Python, so the signal would be ignored.
    signal.signal(signal.SIGINT, lambda *_: app.closeAllWindows())
    heartbeat = QTimer()
    heartbeat.start(250)
    heartbeat.timeout.connect(lambda: None)
    window = MainWindow()
    window.show()
    print(f"{APP_NAME} v{APP_VERSION} started — the app runs in its own window.", flush=True)
    print("Close the window to exit (or press Ctrl+C here).", flush=True)
    exit_code = app.exec()
    print(f"{APP_NAME} closed.", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
