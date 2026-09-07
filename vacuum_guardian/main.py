"""Vacuum Guardian entry point.

Composition root: loads the config, builds the MonitorEngine and the main
window, then hands control to the Qt loop. All dependency wiring happens
here - no internal module reaches around another.
"""

from __future__ import annotations

import faulthandler
import sys
from pathlib import Path

from loguru import logger

from app import __version__


def _enable_crash_dump(log_dir: Path) -> None:
    """Writes the native stack to logs/crash.log if the process dies outright.

    A crash in C (OpenCV, Qt, a video driver) kills the process without going
    through Python: the operator only sees "VacuumGuardian.exe has stopped
    working" and nothing is left in the log. With faulthandler enabled, a file
    records which call brought it down - the difference between diagnosing and
    guessing.

    The file is left OPEN for the whole run on purpose: at crash time there is
    no chance to open anything.
    """
    try:
        handle = (log_dir / "crash.log").open("a", encoding="utf-8")
        faulthandler.enable(file=handle, all_threads=True)
    except OSError as exc:  # no write permission: carry on without the dump
        logger.warning("Could not enable the crash dump: {}", exc)


def main() -> int:
    from app.config import ConfigService
    from app.logging import setup_logging
    from app.services.monitor import MonitorEngine
    from app.ui.main_window import MainWindow
    from app.utils import user_data_path
    from PySide2.QtCore import Qt
    from PySide2.QtWidgets import QApplication

    # Config and logs are writable: they live beside the .exe (or in the
    # project root in dev), never in PyInstaller's temporary folder.
    PROJECT_ROOT = user_data_path()
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    setup_logging(PROJECT_ROOT / "logs")
    _enable_crash_dump(PROJECT_ROOT / "logs")
    logger.info("Vacuum Guardian starting v{}", __version__)

    config_service = ConfigService(PROJECT_ROOT / "config.json")
    config = config_service.load()

    # High DPI: automatic on Qt6, but on Qt5 it must be enabled explicitly
    # BEFORE creating the QApplication. It keeps point-sized fonts at the same
    # physical size on Full HD and 4K, as documented in the alarm popup.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # fechar janela nao encerra (fica na bandeja)

    engine = MonitorEngine(config, PROJECT_ROOT)
    window = MainWindow(engine, config_service, PROJECT_ROOT)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
