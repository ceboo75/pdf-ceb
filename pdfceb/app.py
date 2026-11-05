"""Point d'entrée de PDF Ceb."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _arg_value(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return None


def make_app(argv=None):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QGuiApplication
    from PySide6.QtWidgets import QApplication

    from .ui import icons
    from .ui.style import build_qss

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("PDF Ceb")
    app.setOrganizationName("PDF Ceb")
    app.setStyle("Fusion")
    font = QFont("Segoe UI" if sys.platform.startswith("win") else app.font().family())
    font.setPointSizeF(9.5)
    app.setFont(font)
    app.setStyleSheet(build_qss())
    app.setWindowIcon(icons.app_icon())
    return app


def main():
    if "--selftest" in sys.argv:
        from .selftest import main as selftest_main
        sys.exit(selftest_main(_arg_value("--selftest")))
    if "--selftest-ui" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from .uitest import main as ui_main
        sys.exit(ui_main(_arg_value("--selftest-ui")))

    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PDFCeb.App.1")
        except Exception:
            pass
    app = make_app()
    from .ui.main_window import MainWindow
    from .ui.widgets import error_box

    win = MainWindow()

    def excepthook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb)
        try:
            error_box(win, exc, "Erreur inattendue")
        except Exception:
            pass

    sys.excepthook = excepthook
    win.show()
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    if files:
        win.open_files_from_args(files)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
