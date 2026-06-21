from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

import window_utils
from ui.tabs.calibration import CalibrationTab
from ui.tabs.guides import GuidesTab
from ui.tabs.info import InfoTab
from ui.tabs.settings import SettingsTab
from ui.tabs.sniper import SniperTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FH6 Sniper")
        self.resize(930, 740)
        self.setMaximumHeight(740)

        try:
            icon_path = window_utils.resource_path("assets/sniper.ico")
            self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass

        sniper_tab = SniperTab()
        self._sniper_tab = sniper_tab
        calib_tab = CalibrationTab(sniper_tab)
        sniper_tab._calib_tab = calib_tab
        settings_tab = SettingsTab(sniper_tab)
        guides_tab = GuidesTab()
        info_tab = InfoTab()

        central = QWidget()
        h_layout = QHBoxLayout(central)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(0)

        nav = QListWidget()
        nav.setFixedWidth(130)
        nav.addItems(["Sniper", "Calibration", "Settings", "Guide", "Info"])
        nav.setStyleSheet(
            "QListWidget {"
            "    background-color: #1a1a2e;"
            "    border: none;"
            "    border-right: 1px solid #333355;"
            "    font-size: 11pt;"
            "    outline: none;"
            "}"
            "QListWidget::item {"
            "    padding: 14px 12px;"
            "    color: #aaaacc;"
            "}"
            "QListWidget::item:selected {"
            "    background-color: #2a2a45;"
            "    color: #ffffff;"
            "    border-left: 3px solid #f5a623;"
            "    padding-left: 9px;"
            "}"
            "QListWidget::item:hover:!selected {"
            "    background-color: #22223a;"
            "    color: #ddddee;"
            "}"
        )

        stack = QStackedWidget()
        stack.addWidget(sniper_tab)
        stack.addWidget(calib_tab)
        stack.addWidget(settings_tab)
        stack.addWidget(guides_tab)
        stack.addWidget(info_tab)

        nav.currentRowChanged.connect(stack.setCurrentIndex)
        nav.setCurrentRow(0)

        h_layout.addWidget(nav)
        h_layout.addWidget(stack)

        self.setCentralWidget(central)

        sniper_tab._navigate_to_calibration = lambda: nav.setCurrentRow(1)

    def closeEvent(self, event) -> None:
        self._sniper_tab._stop_event.set()

        for w in QApplication.topLevelWidgets():
            if w is not self:
                try:
                    w.close()
                except Exception:
                    pass

        event.accept()
