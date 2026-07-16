from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import calibrator
import settings
import window_utils
from ui.log_bridge import _log_bridge
from ui.overlays.calibration import _QtCalibrationStatusProxy

if TYPE_CHECKING:
    from ui.tabs.sniper import SniperTab


class _IngameOverlay(QWidget):
    """Frameless in-game header overlay shown on top of the FH6 window."""

    def __init__(self, sniper_tab: SniperTab) -> None:
        super().__init__(
            None,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._sniper_tab = sniper_tab

        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        self._sniper_tab.stats_updated.connect(self._apply_stats)
        _log_bridge.message.connect(self._on_log_message)
        self._log_bridge_connected = True
        self._refresh()
        self._focus_grace_until = time.time() + 2.0
        self._user_closed = False
        self._last_interaction_time = 0.0
        self.show()

    def _build_ui(self) -> None:
        self.setObjectName("ingameOverlay")
        self.setStyleSheet(
            "#ingameOverlay { background-color: rgba(0, 0, 0, 180); border-radius: 14px; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(10)

        self._title_label = QLabel("FH6 Sniper")
        self._title_label.setStyleSheet(
            "font-size:12pt; font-weight:bold; color: #ffffff; margin-right:12px;"
        )

        top_row = QHBoxLayout()
        top_row.addWidget(self._title_label)
        top_row.addStretch()

        self._start_btn = QPushButton("Start")
        self._start_btn.setFixedWidth(110)
        self._start_btn.setProperty("class", "primary-btn")
        self._start_btn.clicked.connect(self._sniper_tab._start)
        self._start_btn.pressed.connect(self._on_overlay_interact)
        top_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFixedWidth(110)
        self._stop_btn.setProperty("class", "danger-btn")
        self._stop_btn.clicked.connect(self._sniper_tab._stop)
        self._stop_btn.pressed.connect(self._on_overlay_interact)
        top_row.addWidget(self._stop_btn)

        self._row_tuner_btn = QPushButton("Row Tuner")
        self._row_tuner_btn.setFixedWidth(100)
        self._row_tuner_btn.setProperty("class", "accent-btn")
        self._row_tuner_btn.clicked.connect(self._launch_row_tuner_from_overlay)
        self._row_tuner_btn.pressed.connect(self._on_overlay_interact)
        top_row.addWidget(self._row_tuner_btn)

        self._auto_cal_btn = QPushButton("Auto Calibrate")
        self._auto_cal_btn.setFixedWidth(140)
        self._auto_cal_btn.setProperty("class", "accent-btn")
        self._auto_cal_btn.clicked.connect(self._sniper_tab.run_auto_from_overlay)
        self._auto_cal_btn.pressed.connect(self._on_overlay_interact)
        top_row.addWidget(self._auto_cal_btn)

        self._manual_auction_btn = QPushButton("Calib Auction")
        self._manual_auction_btn.setFixedWidth(108)
        self._manual_auction_btn.setProperty("class", "accent-btn")
        self._manual_auction_btn.clicked.connect(self._sniper_tab.run_manual_auction_from_overlay)
        self._manual_auction_btn.pressed.connect(self._on_overlay_interact)
        top_row.addWidget(self._manual_auction_btn)

        self._manual_badge_btn = QPushButton("Calib Badge")
        self._manual_badge_btn.setFixedWidth(100)
        self._manual_badge_btn.setProperty("class", "accent-btn")
        self._manual_badge_btn.clicked.connect(self._sniper_tab.run_manual_badge_from_overlay)
        self._manual_badge_btn.pressed.connect(self._on_overlay_interact)
        top_row.addWidget(self._manual_badge_btn)

        self._hide_btn = QPushButton("Hide")
        self._hide_btn.setFixedWidth(90)

        def _on_hide():
            self._user_closed = True
            self.close()

        self._hide_btn.clicked.connect(_on_hide)
        self._hide_btn.pressed.connect(self._on_overlay_interact)
        top_row.addWidget(self._hide_btn)

        self._layout.addLayout(top_row)

        self._timer_label = QLabel("⏱  00:00")
        self._timer_label.setStyleSheet("font-size: 12pt; font-weight: bold; color: #ffffff;")
        top_row.addWidget(self._timer_label)

        self._buyout_label = QLabel("Buyout: 0 success | 0 failed")
        self._buyout_label.setStyleSheet("font-size: 11pt; color: #ffffff;")
        top_row.addWidget(self._buyout_label)

        self._refresh_label = QLabel("Refreshed: 0/0")
        self._refresh_label.setStyleSheet("font-size: 11pt; color: #ffffff;")
        top_row.addWidget(self._refresh_label)

        msg_row = QHBoxLayout()
        msg_row.setSpacing(8)

        self._message_label = QLabel("")
        self._message_label.setStyleSheet(
            "font-size: 10pt; color: #ffffff; background-color: rgba(0,0,0,0.65); "
            "padding: 6px; border-radius: 6px;"
        )
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_row.addWidget(self._message_label, stretch=1)
        self._layout.addLayout(msg_row)

        self._calib_status_proxy = _QtCalibrationStatusProxy(self._message_label)
        self._update_controls()

    def _launch_row_tuner_from_overlay(self) -> None:
        calib_tab = self._sniper_tab._calib_tab
        if calib_tab is not None:
            calib_tab._launch_row_tuner()

    def _refresh(self) -> None:
        geometry = self._fh6_geometry()
        if geometry is None:
            self.close()
            return

        try:
            active = window_utils.gw.getActiveWindow()
            win = window_utils.get_fh6_window()
            not_focused = (
                not active
                or not win
                or getattr(active, "title", None) != getattr(win, "title", None)
            )
            recent_interact = (time.time() - getattr(self, "_last_interaction_time", 0)) < 1.2
            grace_passed = time.time() > getattr(self, "_focus_grace_until", 0)
            if not_focused and grace_passed and not recent_interact:
                self.close()
                return
        except Exception:
            pass

        self.setGeometry(*geometry)
        self._update_timer_label()
        self._update_controls()

    def _on_overlay_interact(self):
        try:
            self._last_interaction_time = time.time()
            self._focus_grace_until = time.time() + 1.0
        except Exception:
            pass

    def _fh6_geometry(self) -> tuple[int, int, int, int] | None:
        win = window_utils.get_fh6_window()
        if not win:
            return None
        top = win.top + 4

        self.adjustSize()
        content_w = self.sizeHint().width()
        content_h = self.sizeHint().height()

        width = content_w
        height = max(28, content_h)

        try:
            phys = window_utils.get_window_region(win)
            if phys:
                phys_left, phys_top, phys_w, phys_h = phys
                dpr = window_utils._get_display_dpr()
                win_left_log = int(phys_left / dpr)
                win_w_log = int(phys_w / dpr)
                win_center_x = win_left_log + win_w_log // 2
            else:
                win_center_x = win.left + win.width // 2
        except Exception:
            win_center_x = win.left + win.width // 2
        left = win_center_x - width // 2

        screen = QApplication.screenAt(QPoint(win.left, win.top)) or QApplication.primaryScreen()
        screen_geom = screen.geometry()
        screen_left = screen_geom.left()
        screen_right = screen_left + screen_geom.width()
        if left < screen_left:
            left = screen_left
        if left + width > screen_right:
            left = screen_right - width

        return (left, top, width, height)

    def _update_timer_label(self) -> None:
        elapsed = getattr(self._sniper_tab, "_elapsed", 0)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        if h:
            self._timer_label.setText(f"⏱  {h}:{m:02d}:{s:02d}")
        else:
            self._timer_label.setText(f"⏱  {m:02d}:{s:02d}")

    def _on_log_message(self, msg: str) -> None:
        try:
            self._message_label.setText(msg)
        except Exception:
            pass

    def _apply_stats(
        self, attempts: int, successes: int, failures: int, refreshes: int, scans_done: int
    ) -> None:
        total = settings.get_scans()
        self._buyout_label.setText(f"Buyout: {successes} success | {failures} failed")
        total_str = "∞" if total == 0 else str(total)
        self._refresh_label.setText(f"Refreshed: {refreshes}/{total_str}")

    def _update_controls(self) -> None:
        running = getattr(self._sniper_tab, "_sniper_running", False)
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        cal_busy = getattr(self._sniper_tab, "_calibration_in_progress", False)
        avail = not cal_busy
        has_manual = calibrator.has_manual_region()
        has_auto = calibrator.has_auto_region()
        self._auto_cal_btn.setEnabled(avail and not has_manual)
        self._manual_auction_btn.setEnabled(avail and not has_auto)
        self._manual_badge_btn.setEnabled(avail and not has_auto)

    def closeEvent(self, event) -> None:
        if getattr(self._sniper_tab, "_ingame_overlay", None) is self:
            self._sniper_tab._ingame_overlay = None
            if getattr(self, "_user_closed", False):
                # Hide clicked on the overlay itself — persist the setting off
                # and untick the Settings tab box.
                self._sniper_tab.overlay_hidden_by_user()
        if getattr(self, "_log_bridge_connected", False):
            try:
                _log_bridge.message.disconnect(self._on_log_message)
            except Exception:
                pass
            self._log_bridge_connected = False
        super().closeEvent(event)
