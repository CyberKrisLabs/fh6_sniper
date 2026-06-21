from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import calibrator  # noqa: F401 — tests patch app.calibrator.CONFIG_FILE
import vision_utils
import window_utils
from ui.log_bridge import _emit_log  # noqa: F401
from ui.main_window import MainWindow

# backward-compat re-exports (used by test_tab_*.py fixtures)
from ui.tabs.calibration import CalibrationTab  # noqa: F401
from ui.tabs.info import (
    InfoTab,  # noqa: F401
    __version__,  # noqa: F401
)
from ui.tabs.settings import SettingsTab  # noqa: F401
from ui.tabs.sniper import SniperTab  # noqa: F401
from ui.theme import STYLESHEET


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    app.aboutToQuit.connect(vision_utils.release_dxcam)

    try:
        app.setWindowIcon(QIcon(str(window_utils.resource_path("assets/sniper.ico"))))
    except Exception:
        pass

    win = MainWindow()
    win.show()
    exit_code = app.exec()
    os._exit(exit_code)


if __name__ == "__main__":
    main()
