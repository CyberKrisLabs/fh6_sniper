import json
import os
import subprocess
import sys
import threading
import time
import webbrowser

import pyautogui
from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import calibrator
import settings
import sniper
import theme
import vision_utils
import window_utils
from sniper import SOLD_THRESHOLD

try:
    import requests  # type: ignore

    HAVE_REQUESTS = True
except Exception:
    requests = None
    HAVE_REQUESTS = False

__version__ = "1.0.0"

_icon_file = window_utils.resource_path("assets/sniper.ico")

# Qt 6 manages DPI awareness internally on Windows and may warn if the process
# DPI context is already set. Avoid forcing DPI awareness here to prevent
# conflicts with Qt's default DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 behavior.


# ---------------------------------------------------------------------------
# Thread-safe bridge: background threads emit this signal to log to the UI
# ---------------------------------------------------------------------------


class _LogBridge(QObject):
    message = Signal(str)


# ---------------------------------------------------------------------------
# Always-on-top overlay for manual calibration countdown
# ---------------------------------------------------------------------------


class _CalibrationOverlay(QWidget):
    """Frameless always-on-top banner that shows calibration countdown.

    Implements the same .after() / .config() interface as a Tkinter widget so
    calibrator.calibrate() can call it without modification.  All signal
    emissions are thread-safe, so the background calibration thread can call
    these methods directly.
    """

    _text_signal = Signal(str)
    _close_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._text_signal.connect(self._on_set_text)
        self._close_signal.connect(self.close)
        self._custom_pos: QPoint | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel("")
        self._label.setStyleSheet(
            "background-color: rgba(0,0,0,215);"
            " color: #ffffff;"
            " font-size: 15pt; font-weight: bold;"
            " padding: 18px 28px;"
            " border-radius: 10px;"
            " border: 2px solid #f5a623;"
        )
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(640)
        layout.addWidget(self._label)

        self.adjustSize()
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, 60)
        self.show()

    def _on_set_text(self, text: str):
        self._label.setText(text)
        self.adjustSize()
        if self._custom_pos is not None:
            self.move(self._custom_pos)
        else:
            screen = QApplication.primaryScreen().geometry()
            self.move((screen.width() - self.width()) // 2, 60)

    # ── Tkinter-compatible interface (safe to call from background thread) ──

    def after(self, _delay: int, callback) -> None:
        # Call directly — config() emits _text_signal which is a queued connection
        # across threads, so Qt handles the thread-hop safely.
        callback()

    def config(self, text: str = "", bootstyle: str = "", **_kwargs) -> None:
        if text:
            self._text_signal.emit(str(text))

    def destroy_later(self) -> None:
        self._close_signal.emit()

    def reposition_for_ingame(self, extra_y: int = 0) -> None:
        """Move banner to the right side of the FH6 window.

        extra_y: logical-pixel offset below the window top — pass the in-game
        overlay's current height so the banner clears it.
        """
        win = window_utils.get_fh6_window()
        if not win:
            return
        self.adjustSize()
        dpr = QApplication.primaryScreen().devicePixelRatio()
        win_right = int((win.left + win.width) / dpr)
        win_top = int(win.top / dpr)
        x = win_right - self.width() - 12
        y = win_top + extra_y + 8
        self._custom_pos = QPoint(x, y)
        self.move(x, y)


class _QtCalibrationStatusProxy:
    """Qt-compatible proxy for calibrator status_label objects."""

    def __init__(self, label: QLabel):
        self._label = label

    def after(self, _delay: int, callback) -> None:
        QTimer.singleShot(0, callback)

    def config(self, text: str = "", bootstyle: str = "", **_kwargs) -> None:
        if text:
            color = "#ffffff"
            if bootstyle == "warning":
                color = "#ff9800"
            elif bootstyle == "danger":
                color = "#f44336"
            elif bootstyle == "info":
                color = "#2196f3"
            self._label.setText(text)
            self._label.setStyleSheet(f"font-size: 11pt; color: {color};")


_log_bridge = _LogBridge()


def _emit_log(msg: str) -> None:
    _log_bridge.message.emit(msg)


# ---------------------------------------------------------------------------
# Region overlays (PySide6) — replaces the old tkinter show_region_overlay
# ---------------------------------------------------------------------------


class _AuctionRegionOverlay(QWidget):
    """Frameless transparent always-on-top overlay showing the auction button region.

    Draws a red rectangle with a countdown so the user can verify the
    detection box is placed over the Auction Options button.
    """

    def __init__(self, region: tuple[int, int, int, int], duration_ms: int = 5000):
        super().__init__(
            None,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        rx, ry, rw, rh = region
        dpr = QApplication.primaryScreen().devicePixelRatio()
        # convert physical → logical for Qt geometry
        lx = int(rx / dpr)
        ly = int(ry / dpr)
        lw = int(rw / dpr)
        lh = int(rh / dpr)

        TEXT_H = 48
        MARGIN = 8
        _label_text = "Auction Options button should be inside the red box  (9s)"
        from PySide6.QtGui import QFontMetrics

        _fm = QFontMetrics(QApplication.font())
        _text_min_w = _fm.horizontalAdvance(_label_text) + MARGIN * 4
        ow = max(lw + MARGIN * 2, _text_min_w)
        # centre the region box if the widget had to widen for text
        box_x = (ow - lw) // 2
        self.setGeometry(
            lx - (ow - lw) // 2 - MARGIN, ly - TEXT_H - MARGIN, ow, lh + TEXT_H + MARGIN * 2
        )
        self._box = (box_x, TEXT_H + MARGIN, lw, lh)
        self._ow = ow
        self._th = TEXT_H
        self._seconds = max(1, duration_ms // 1000)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()
        QTimer.singleShot(duration_ms, self.close)
        self.show()

    def _tick(self):
        self._seconds = max(0, self._seconds - 1)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bx, by, bw, bh = self._box
        # detection box
        p.setPen(QPen(QColor(255, 60, 60), 3))
        p.setBrush(QColor(255, 60, 60, 25))
        p.drawRect(bx, by, bw, bh)
        # text background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 200))
        p.drawRoundedRect(4, 4, self._ow - 8, self._th - 8, 6, 6)
        # text
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            4,
            4,
            self._ow - 8,
            self._th - 8,
            Qt.AlignmentFlag.AlignCenter,
            f"Auction Options button should be inside the red box  ({self._seconds}s)",
        )


class _BadgeRegionOverlay(QWidget):
    """Full-screen transparent overlay that draws the sold-badge scan regions.

    Shows the badge detection box for each row so the user can confirm it is
    correctly aligned over the Sold! badge on visible car cards.
    Dismissed by clicking anywhere or after *duration_ms* milliseconds.
    """

    _COLOURS = [
        QColor(255, 220, 0),  # yellow
        QColor(80, 200, 255),  # cyan
        QColor(180, 255, 80),  # green
        QColor(255, 130, 50),  # orange
    ]

    def __init__(
        self,
        badge_rects: list[tuple[int, int, int, int]],
        row_rects: list[tuple[int, int, int, int]],
        duration_ms: int = 4000,
    ):
        """
        Args:
            badge_rects: badge scan areas in physical screen pixels.
            row_rects:   full row areas in physical screen pixels (drawn as outlines).
            duration_ms: auto-close delay.
        """
        super().__init__(
            None,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        dpr = QApplication.primaryScreen().devicePixelRatio()

        # convert physical → logical
        def _log(r):
            x, y, w, h = r
            return (int(x / dpr), int(y / dpr), int(w / dpr), int(h / dpr))

        self._badge_rects = [_log(r) for r in badge_rects]
        self._row_rects = [_log(r) for r in row_rects]
        self._seconds = max(1, duration_ms // 1000)

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()
        QTimer.singleShot(duration_ms, self.close)
        self.show()

    def _tick(self):
        self._seconds = max(0, self._seconds - 1)
        self.update()

    def mousePressEvent(self, _event):
        self.close()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        for i, (rx, ry, rw, rh) in enumerate(self._row_rects):
            col = self._COLOURS[i % len(self._COLOURS)]
            # row outline (faint)
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 80), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rx, ry, rw, rh)

        for i, (bx, by, bw, bh) in enumerate(self._badge_rects):
            col = self._COLOURS[i % len(self._COLOURS)]
            # badge box (solid)
            p.setPen(QPen(col, 3))
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 45))
            p.drawRect(bx, by, bw, bh)
            # label
            p.setPen(col)
            p.drawText(bx + 4, by - 4, f"Row {i + 1}")

        # instruction banner
        sw = self.width()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 195))
        p.drawRoundedRect(sw // 2 - 310, 20, 620, 42, 8, 8)
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            sw // 2 - 310,
            20,
            620,
            42,
            Qt.AlignmentFlag.AlignCenter,
            f"Sold badge scan regions (coloured boxes) — click to dismiss  ({self._seconds}s)",
        )


class _IngameOverlay(QWidget):
    """Frameless in-game header overlay shown on top of the FH6 window."""

    _calib_img_signal = Signal(str)  # path → show image; "" → hide

    def __init__(self, sniper_tab: "SniperTab") -> None:
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
        # Short grace period to allow the user to switch to FH6 after
        # clicking the overlay toggle in the app; prevents immediate auto-hide.
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

        # Single message row: show timer/metrics on the left and a single
        # message area on the right. Keep the message area transparent so the
        # overlay background shows through (no separate solid box).
        # Timer and metrics sit on the same top row as the buttons
        self._timer_label = QLabel("⏱  00:00")
        self._timer_label.setStyleSheet("font-size: 12pt; font-weight: bold; color: #ffffff;")
        top_row.addWidget(self._timer_label)

        # `Attempts` label removed; refresh count is shown instead.

        self._buyout_label = QLabel("Buyout: 0 success | 0 failed")
        self._buyout_label.setStyleSheet("font-size: 11pt; color: #ffffff;")
        top_row.addWidget(self._buyout_label)

        self._refresh_label = QLabel("Refreshed: 0/0")
        self._refresh_label.setStyleSheet("font-size: 11pt; color: #ffffff;")
        top_row.addWidget(self._refresh_label)

        # Single message row: template image (during calibration) + log text
        msg_row = QHBoxLayout()
        msg_row.setSpacing(8)

        self._calib_img_label = QLabel()
        self._calib_img_label.setVisible(False)
        self._calib_img_label.setStyleSheet("background: transparent;")
        msg_row.addWidget(self._calib_img_label)

        self._message_label = QLabel("")
        self._message_label.setStyleSheet(
            "font-size: 10pt; color: #ffffff; background-color: rgba(0,0,0,0.65); "
            "padding: 6px; border-radius: 6px;"
        )
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignCenter)
        msg_row.addWidget(self._message_label, stretch=1)
        self._layout.addLayout(msg_row)

        self._calib_img_signal.connect(self._on_calib_img)
        self._calib_status_proxy = _QtCalibrationStatusProxy(self._message_label)
        self._update_controls()

    def _on_calib_img(self, path: str) -> None:
        if path and os.path.isfile(path):
            pix = QPixmap(path).scaledToHeight(34, Qt.TransformationMode.SmoothTransformation)
            self._calib_img_label.setPixmap(pix)
            self._calib_img_label.setVisible(True)
        else:
            self._calib_img_label.clear()
            self._calib_img_label.setVisible(False)

    def show_calib_image(self, path: str) -> None:
        """Show a template image in the log row (thread-safe)."""
        self._calib_img_signal.emit(path)

    def hide_calib_image(self) -> None:
        """Hide the template image from the log row (thread-safe)."""
        self._calib_img_signal.emit("")

    def _launch_row_tuner_from_overlay(self) -> None:
        calib_tab = self._sniper_tab._calib_tab
        if calib_tab is not None:
            calib_tab._launch_row_tuner()

    def _refresh(self) -> None:
        geometry = self._fh6_geometry()
        if geometry is None:
            self.close()
            return

        # If FH6 isn't the active window, hide the overlay so it doesn't
        # remain visible when the user tabs out.
        try:
            active = window_utils.gw.getActiveWindow()
            win = window_utils.get_fh6_window()
            # Only close if we've passed the initial grace period. This
            # lets the user click the game to bring it into focus after
            # toggling the overlay from the app.
            not_focused = (
                not active
                or not win
                or getattr(active, "title", None) != getattr(win, "title", None)
            )
            # keep overlay visible for a short period after user interaction
            recent_interact = (time.time() - getattr(self, "_last_interaction_time", 0)) < 1.2
            grace_passed = time.time() > getattr(self, "_focus_grace_until", 0)
            if not_focused and grace_passed and not recent_interact:
                self.close()
                return
        except Exception:
            # If active-window detection fails, fall back to showing overlay.
            pass

        self.setGeometry(*geometry)
        self._update_timer_label()
        self._update_controls()

    def _on_overlay_interact(self):
        """Record the last time the overlay was used so the watcher won't auto-hide it."""
        try:
            self._last_interaction_time = time.time()
            # also extend focus grace so quick clicks don't cause immediate hide
            self._focus_grace_until = time.time() + 1.0
        except Exception:
            pass

    def _fh6_geometry(self) -> tuple[int, int, int, int] | None:
        win = window_utils.get_fh6_window()
        if not win:
            return None
        # Put the header at the very top of the game window (use logical
        # coordinates provided by pygetwindow.Window attributes). Keep sizing
        # tightly to the button content so the header is compact.
        top = win.top + 4

        self.adjustSize()
        content_w = self.sizeHint().width()
        content_h = self.sizeHint().height()

        width = content_w
        height = max(28, content_h)

        # Compute FH6 window center in Qt logical coords accounting for display DPR.
        try:
            phys = window_utils.get_window_region(win)
            if phys:
                phys_left, phys_top, phys_w, phys_h = phys
                dpr = window_utils._get_display_dpr()
                # convert physical -> logical for Qt coordinates
                win_left_log = int(phys_left / dpr)
                win_w_log = int(phys_w / dpr)
                win_center_x = win_left_log + win_w_log // 2
            else:
                win_center_x = win.left + win.width // 2
        except Exception:
            win_center_x = win.left + win.width // 2
        left = win_center_x - width // 2

        # Ensure overlay fits on the screen.
        screen = QApplication.screenAt(QPoint(win.left, win.top)) or QApplication.primaryScreen()
        screen_geom = screen.geometry()
        screen_left = screen_geom.left()
        screen_right = screen_left + screen_geom.width()
        # Ensure overlay fits on the screen horizontally
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
        # The overlay uses a single message label now; update it if present.
        try:
            self._message_label.setText(msg)
        except Exception:
            try:
                # fall back to legacy attribute if present
                self._log_label.setText(msg)
            except Exception:
                pass

    def _apply_stats(
        self, attempts: int, successes: int, failures: int, refreshes: int, scans_done: int
    ) -> None:
        total = settings.get_scans()
        # Attempts removed from overlay; keep buyout + refresh info
        self._buyout_label.setText(f"Buyout: {successes} success | {failures} failed")
        self._refresh_label.setText(f"Refreshed: {refreshes}/{total}")

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
            # Only clear the toggle if the user explicitly hid the overlay.
            if getattr(self, "_user_closed", False):
                self._sniper_tab.ingame_overlay_btn.setChecked(False)
                self._sniper_tab.ingame_overlay_btn.setText("Show In-game Overlay")
        if getattr(self, "_log_bridge_connected", False):
            try:
                _log_bridge.message.disconnect(self._on_log_message)
            except Exception:
                pass
            self._log_bridge_connected = False
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Sniper tab
# ---------------------------------------------------------------------------


class SniperTab(QWidget):
    stats_updated = Signal(int, int, int, int, int)
    _sniper_done = Signal()
    _calib_mode_signal = Signal(bool)  # True = re-enable buttons after calibration

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sniper_running = False
        self._stop_event = threading.Event()
        self._first_start = True
        self._calib_done_this_session = False
        self._elapsed = 0
        self._ingame_overlay = None
        self._calibration_in_progress = False
        self._calib_tab = None  # set by main window after CalibrationTab is constructed
        self._navigate_to_calibration = None
        self._active_cal_overlay: _CalibrationOverlay | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_timer)

        self.stats_updated.connect(self._apply_stats)
        self._sniper_done.connect(self._on_sniper_done)
        self._calib_mode_signal.connect(self._set_calibration_mode)
        _log_bridge.message.connect(self._append_log)

        self._build_ui()
        self._refresh_stats_display(0, 0, 0, 0)

        # Watcher to reopen/close the in-game overlay based on FH6 focus.
        self._overlay_watcher = QTimer(self)
        self._overlay_watcher.setInterval(1000)  # check once per second
        self._overlay_watcher.timeout.connect(self._overlay_watcher_tick)
        self._overlay_watcher.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Controls row ──────────────────────────────────────────────────
        ctrl = QHBoxLayout()

        btn_col = QVBoxLayout()
        self.start_btn = QPushButton("Start Sniper")
        self.start_btn.setFixedWidth(120)
        self.start_btn.setProperty("class", "primary-btn")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop Sniper")
        self.stop_btn.setFixedWidth(120)
        self.stop_btn.setProperty("class", "danger-btn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.ingame_overlay_btn = QPushButton("Show In-game Overlay")
        self.ingame_overlay_btn.setCheckable(True)
        self.ingame_overlay_btn.setFixedWidth(160)
        self.ingame_overlay_btn.clicked.connect(self._toggle_ingame_overlay)
        btn_col.addWidget(self.start_btn)
        btn_col.addWidget(self.stop_btn)
        btn_col.addWidget(self.ingame_overlay_btn)
        ctrl.addLayout(btn_col)

        ctrl.addStretch()
        title = QLabel("Sniper Controls")
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        ctrl.addWidget(title)
        ctrl.addStretch()

        self.timer_label = QLabel("⏱  00:00")
        self.timer_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        ctrl.addWidget(self.timer_label)

        root.addLayout(ctrl)

        # ── Stats row ─────────────────────────────────────────────────────
        stats_row = QHBoxLayout()
        self.stats_label = QLabel("Buy attempts: 0 | Success: 0 | Fail: 0 | Refreshes: 0")
        self.stats_label.setStyleSheet("font-size: 11pt;")
        self.scans_label = QLabel(f"Scans left: {settings.get_scans()}")
        self.scans_label.setStyleSheet("font-size: 11pt;")
        stats_row.addWidget(self.stats_label)
        stats_row.addStretch()
        stats_row.addWidget(self.scans_label)
        root.addLayout(stats_row)

        # ── Log area ──────────────────────────────────────────────────────
        log_box = QGroupBox("Status Log")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        log_layout.addWidget(self.log_view)
        root.addWidget(log_box)

        self._append_log("Ready...")

    # ── Slots ──────────────────────────────────────────────────────────────

    def _append_log(self, msg: str):
        color_map = {
            "✅": "#4caf50",
            "❌": "#f44336",
            "⚠️": "#ff9800",
            "🛑": "#f44336",
            "🚀": "#2196f3",
            "🔒": "#9e9e9e",
            "🔍": "#2196f3",
        }
        color = "#ffffff"
        for emoji, c in color_map.items():
            if msg.startswith(emoji):
                color = c
                break
        self.log_view.append(f'<span style="color:{color};">{msg}</span>')
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        lines = self.log_view.document().blockCount()
        if lines > 10000:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(
                cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, lines - 10000
            )
            cursor.removeSelectedText()

    def _set_calibration_mode(self, enabled: bool) -> None:
        self._calibration_in_progress = not enabled
        self.start_btn.setEnabled(enabled and not self._sniper_running)
        self.stop_btn.setEnabled(enabled and self._sniper_running)
        self.ingame_overlay_btn.setEnabled(enabled)
        if self._ingame_overlay is not None:
            self._ingame_overlay._auto_cal_btn.setEnabled(enabled)
            self._ingame_overlay._manual_auction_btn.setEnabled(enabled)
            self._ingame_overlay._manual_badge_btn.setEnabled(enabled)
            self._ingame_overlay._start_btn.setEnabled(enabled and not self._sniper_running)
            self._ingame_overlay._stop_btn.setEnabled(enabled and self._sniper_running)

    def _apply_stats(self, attempts, successes, failures, refreshes, scans_done):
        self.stats_label.setText(
            f"Buy attempts: {attempts} | Success: {successes}"
            f" | Fail: {failures} | Refreshes: {refreshes}"
        )
        remaining = max(settings.get_scans() - scans_done, 0)
        self.scans_label.setText(f"Scans left: {remaining}")

    def _refresh_stats_display(self, attempts, successes, failures, refreshes):
        self.stats_label.setText(
            f"Buy attempts: {attempts} | Success: {successes}"
            f" | Fail: {failures} | Refreshes: {refreshes}"
        )
        self.scans_label.setText(f"Scans left: {settings.get_scans()}")

    # --- Overlay-triggered calibration wrappers ---------------------------------
    def run_auto_from_overlay(self) -> None:
        """Run auto calibration from the in-game overlay (background thread)."""
        self._set_calibration_mode(False)

        def _work():
            try:
                status_proxy = (
                    self._ingame_overlay._calib_status_proxy if self._ingame_overlay else None
                )

                # Capture prints and forward trimmed messages to UI/log while
                # leaving the calibrator logic unchanged.
                import builtins

                real_print = builtins.print

                def _trim_path_tokens(msg: str) -> str:
                    try:
                        tokens = msg.split()
                        new = []
                        for t in tokens:
                            if "/" in t or "\\\\" in t or t.startswith("assets/"):
                                try:
                                    bn = os.path.basename(t)
                                    new.append(bn if bn else t)
                                except Exception:
                                    new.append(t)
                            else:
                                new.append(t)
                        return " ".join(new)
                    except Exception:
                        return msg

                def capture_print(*args, **kwargs):
                    try:
                        msg = " ".join(str(a) for a in args)
                        short = _trim_path_tokens(msg)
                        _emit_log(short)
                        if status_proxy:
                            try:
                                status_proxy.config(text=short)
                            except Exception:
                                pass
                    except Exception:
                        pass

                builtins.print = capture_print
                try:
                    result = calibrator.auto_calibrate(status_label=status_proxy)
                finally:
                    builtins.print = real_print
                if result and result is not False:
                    self.mark_calibration_done()
                    _emit_log("✅ Auto calibration complete (overlay)")
                else:
                    _emit_log("❌ Auto calibration failed (overlay)")
            except Exception as e:
                _emit_log(f"❌ Auto calibration error (overlay): {e}")
            finally:
                self._set_calibration_mode(True)

        threading.Thread(target=_work, daemon=True).start()

    def run_manual_auction_from_overlay(self) -> None:
        """Manual calibration — auction button only (overlay trigger)."""
        _root = os.path.dirname(os.path.abspath(__file__))
        tpl = os.path.join(_root, "assets", "auction_options_template_med.png")
        if self._ingame_overlay:
            self._ingame_overlay.show_calib_image(tpl)
        self._set_calibration_mode(False)
        self._active_cal_overlay = _CalibrationOverlay()
        extra_y = self._ingame_overlay.height() if self._ingame_overlay else 0
        self._active_cal_overlay.reposition_for_ingame(extra_y=extra_y)
        cal_overlay = self._active_cal_overlay  # local alias for closure

        def _work():
            import builtins
            import traceback

            real_print = builtins.print

            def capture_print(*args, **kwargs):
                try:
                    _emit_log(" ".join(str(a) for a in args))
                except Exception:
                    pass

            region = None
            try:
                builtins.print = capture_print
                region = calibrator.calibrate(status_label=cal_overlay, error_label=cal_overlay)
            except Exception:
                _emit_log(f"❌ Auction calibration error:\n{traceback.format_exc()}")
            finally:
                builtins.print = real_print
                cal_overlay.destroy_later()
                if self._ingame_overlay:
                    self._ingame_overlay.hide_calib_image()

            if region:
                cfg_path = window_utils.get_config_file()
                try:
                    with open(cfg_path) as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                cfg["AUCTION_OPTIONS_REGION"] = list(region)
                try:
                    with open(cfg_path, "w") as f:
                        json.dump(cfg, f, indent=2)
                    self.mark_calibration_done()
                    _emit_log("✅ Auction button region saved")
                except Exception:
                    _emit_log(f"❌ Could not save calibration:\n{traceback.format_exc()}")
            else:
                _emit_log("❌ Auction button calibration failed")

            self._calib_mode_signal.emit(True)

        threading.Thread(target=_work, daemon=True).start()

    def run_manual_badge_from_overlay(self) -> None:
        """Manual calibration — sold badge only (overlay trigger)."""
        if self._calib_tab is None:
            _emit_log("❌ Calibration tab not ready")
            return
        _root = os.path.dirname(os.path.abspath(__file__))
        tpl = os.path.join(_root, "assets", "sold_badge_template_med.png")
        if self._ingame_overlay:
            self._ingame_overlay.show_calib_image(tpl)
        self._set_calibration_mode(False)
        self._active_cal_overlay = _CalibrationOverlay()
        extra_y = self._ingame_overlay.height() if self._ingame_overlay else 0
        self._active_cal_overlay.reposition_for_ingame(extra_y=extra_y)
        cal_overlay = self._active_cal_overlay  # local alias for closure

        def _work():
            try:
                self._calib_tab._show_sold_badge_step(cal_overlay)
            finally:
                cal_overlay.destroy_later()
                if self._ingame_overlay:
                    self._ingame_overlay.hide_calib_image()
                self._calib_mode_signal.emit(True)

        threading.Thread(target=_work, daemon=True).start()

    def _tick_timer(self):
        self._elapsed += 1
        h, rem = divmod(self._elapsed, 3600)
        m, s = divmod(rem, 60)
        if h:
            self.timer_label.setText(f"⏱  {h}:{m:02d}:{s:02d}")
        else:
            self.timer_label.setText(f"⏱  {m:02d}:{s:02d}")

    # ── Start / stop ───────────────────────────────────────────────────────

    def mark_calibration_done(self):
        self._calib_done_this_session = True

    def _start(self):
        if self._sniper_running:
            _emit_log("⚠️ Sniper already running!")
            return

        if (
            self._first_start
            and not settings.get_skip_recalibration_reminder()
            and not self._calib_done_this_session
        ):
            self._first_start = False
            if not self._show_recal_reminder():
                return

        if (
            not calibrator.has_manual_region()
            and not calibrator.has_auto_region()
            and not settings.get_skip_calibration_warning()
        ):
            if not self._show_calib_warning():
                return

        self._sniper_running = True
        self._stop_event.clear()
        self._elapsed = 0
        self._refresh_stats_display(0, 0, 0, 0)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        region = calibrator.load_region()
        scans = settings.get_scans()
        timings = settings.load_timings()
        buyout_target = settings.get_buyout_target()

        QTimer.singleShot(5000, self._begin_timer)
        threading.Thread(
            target=self._run_sniper,
            args=(region, scans, timings, buyout_target),
            daemon=True,
        ).start()

    def _begin_timer(self):
        if self._sniper_running:
            self._elapsed = 0
            self._timer.start()

    def _stop(self):
        if self._sniper_running and not self._stop_event.is_set():
            self._stop_event.set()
            _emit_log("🛑 Stop requested...")
            self.stop_btn.setEnabled(False)

    def _toggle_ingame_overlay(self, checked: bool) -> None:
        if checked:
            self._show_ingame_overlay()
        else:
            self._hide_ingame_overlay()

    def _show_ingame_overlay(self) -> None:
        win = window_utils.get_fh6_window()
        if not win:
            _emit_log("⚠ FH6 window not found — open the game first")
            self.ingame_overlay_btn.setChecked(False)
            return

        # Show immediately even if FH6 isn't focused.
        if self._ingame_overlay is None:
            self._ingame_overlay = _IngameOverlay(self)
        self.ingame_overlay_btn.setText("Hide In-game Overlay")
        self.ingame_overlay_btn.setChecked(True)

    def _hide_ingame_overlay(self) -> None:
        if self._ingame_overlay is not None:
            self._ingame_overlay.close()
            self._ingame_overlay = None
        self.ingame_overlay_btn.setText("Show In-game Overlay")
        self.ingame_overlay_btn.setChecked(False)

    def _overlay_watcher_tick(self) -> None:
        # If the user has the overlay toggle enabled, ensure the overlay is
        # shown when FH6 is focused and hidden otherwise. Do not change the
        # toggle button state here; user controls that.
        try:
            want = getattr(self, "ingame_overlay_btn", None) and self.ingame_overlay_btn.isChecked()
            win = window_utils.get_fh6_window()
            active = window_utils.gw.getActiveWindow()
            focused = bool(
                win and active and getattr(active, "title", None) == getattr(win, "title", None)
            )
            if want and focused and self._ingame_overlay is None:
                self._ingame_overlay = _IngameOverlay(self)
            if (not focused or not win) and self._ingame_overlay is not None:
                # If the user interacted with the overlay very recently, don't
                # auto-close it (clicks move focus away briefly). This mirrors
                # the per-overlay grace logic.
                should_close = True
                try:
                    last = getattr(self._ingame_overlay, "_last_interaction_time", 0)
                    if time.time() - last < 1.5:
                        should_close = False
                except Exception:
                    pass
                if should_close:
                    # Close overlay but leave the toggle button checked so the
                    # watcher can reopen it when focus returns.
                    # Mark user_closed False so closeEvent doesn't uncheck button.
                    try:
                        self._ingame_overlay._user_closed = False
                    except Exception:
                        pass
                    self._ingame_overlay.close()
                    self._ingame_overlay = None
        except Exception:
            # Keep silent on watcher errors.
            pass

    def _run_sniper(self, region, scans, timings, buyout_target):
        def status_cb(attempts, successes, failures, refreshes, scans_done):
            self.stats_updated.emit(attempts, successes, failures, refreshes, scans_done)

        try:
            sniper.sniper_loop(
                _emit_log,
                region,
                scans,
                timings,
                self._stop_event,
                status_cb,
                buyout_target,
            )
        except Exception as e:
            _emit_log(f"❌ Error: {e}")
        finally:
            # Route cleanup to the main thread via signal — Qt timers and widgets
            # must not be touched from a background thread.
            self._sniper_done.emit()

    def _on_sniper_done(self):
        self._sniper_running = False
        self._timer.stop()
        self._stop_event.clear()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ── Dialogs ────────────────────────────────────────────────────────────

    def _show_recal_reminder(self) -> bool:
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Recalibration Recommended")
        dlg.setText("Recalibration Recommended")
        dlg.setInformativeText(
            "If you have closed and reopened Forza Horizon 6 or started a new gaming session, "
            "the window position or size may have changed.\n\n"
            "For optimal detection, run calibration again before starting."
        )
        skip_cb = QCheckBox("Don't show this reminder again")
        dlg.setCheckBox(skip_cb)
        calibrate_btn = dlg.addButton("Calibrate Now", QMessageBox.ButtonRole.AcceptRole)
        continue_btn = dlg.addButton("Continue Anyway", QMessageBox.ButtonRole.RejectRole)
        # Track whether the user explicitly clicked a button — Qt activates the
        # RejectRole button internally when the X / Escape is used, so
        # clickedButton() alone cannot distinguish a real click from X-to-close.
        _explicit: list[object] = []
        calibrate_btn.clicked.connect(lambda: _explicit.append(calibrate_btn))
        continue_btn.clicked.connect(lambda: _explicit.append(continue_btn))
        dlg.exec()
        if skip_cb.isChecked():
            settings.set_skip_recalibration_reminder(True)
        explicitly_clicked = _explicit[0] if _explicit else None
        if explicitly_clicked is calibrate_btn:
            if callable(self._navigate_to_calibration):
                self._navigate_to_calibration()
            return False
        return explicitly_clicked is continue_btn

    def _show_calib_warning(self) -> bool:
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Calibration Required")
        dlg.setText("No Calibration Detected")
        dlg.setInformativeText(
            "For faster and more accurate scans, run Auto or Manual Calibration before starting."
        )
        skip_cb = QCheckBox("Don't show this warning again")
        dlg.setCheckBox(skip_cb)
        go_btn = dlg.addButton("Cancel & Calibrate", QMessageBox.ButtonRole.AcceptRole)
        dlg.addButton("Continue Without Calibration", QMessageBox.ButtonRole.RejectRole)
        dlg.setMinimumWidth(560)
        dlg.exec()
        if skip_cb.isChecked():
            settings.set_skip_calibration_warning(True)
        if dlg.clickedButton() is go_btn:
            if callable(self._navigate_to_calibration):
                self._navigate_to_calibration()
            return False
        return True


# ---------------------------------------------------------------------------
# Calibration helpers
# ---------------------------------------------------------------------------


_BADGE_MARGIN = 20  # extra pixels added on each side after hover calibration


def _save_badge_from_clicks(badge_x: int, badge_y: int, badge_w: int, badge_h: int) -> bool:
    """Convert hover-captured coords to row-relative badge params and save.

    A margin of _BADGE_MARGIN pixels is added on every side before saving so that
    the scan area covers the full badge even when the sold badge text is angled.
    """
    try:
        # Expand by margin before computing percentages
        badge_x -= _BADGE_MARGIN
        badge_y -= _BADGE_MARGIN
        badge_w += _BADGE_MARGIN * 2
        badge_h += _BADGE_MARGIN * 2

        win = window_utils.get_fh6_window()
        if win is None:
            return False
        row_regions = window_utils.get_tuned_row_regions(win)
        if not row_regions:
            return False
        badge_cy = badge_y + badge_h // 2
        rx, ry, rw, rh = min(row_regions, key=lambda r: abs((r[1] + r[3] // 2) - badge_cy))
        params = {
            "badge_x_pct": (badge_x - rx) / rw,
            "badge_y_pct": (badge_y - ry) / rh,
            "badge_w_pct": badge_w / rw,
            "badge_h_pct": badge_h / rh,
            "badge_dx_px": badge_x - rx,
            "badge_dy_px": badge_y - ry,
            "badge_w_px": badge_w,
            "badge_h_px": badge_h,
            "row_ref_px": [rw, rh],
            "calibration_score": 1.0,
            "note": "Manually calibrated via hover capture (20 px margin applied).",
        }
        dpr = window_utils._get_display_dpr()
        window_utils.save_badge_params(params, win.width, win.height, dpr)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Calibration tab
# ---------------------------------------------------------------------------


class CalibrationTab(QWidget):
    _status_changed = Signal(str, bool)
    _auction_done = Signal(object, str)  # (region_list_or_None, result_text)
    _badge_done = Signal(str)  # result_text

    def __init__(self, sniper_tab: SniperTab, parent=None):
        super().__init__(parent)
        self._sniper_tab = sniper_tab
        self._active_cal_overlay: _CalibrationOverlay | None = None
        self._status_changed.connect(self._set_status)
        self._auction_done.connect(self._on_auction_done)
        self._badge_done.connect(self._on_badge_done)
        self._build_ui()
        self._refresh_status()

    def _on_auction_done(self, region, result_text: str) -> None:
        self.result_label.setText(result_text)
        self._refresh_status()
        self._set_calibration_buttons(True)

    def _on_badge_done(self, result_text: str) -> None:
        self.result_label.setText(result_text)
        self._refresh_status()
        self._set_calibration_buttons(True)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        _root_dir = os.path.dirname(os.path.abspath(__file__))

        _step_style = (
            "QGroupBox { font-weight:bold; font-size:11pt;"
            " border:1px solid #555; border-radius:6px;"
            " margin-top:14px; padding-top:6px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; }"
        )

        # ── STEP 1: Row Calibration ───────────────────────────────────────
        step1 = QGroupBox("Step 1 — Row Calibration")
        step1.setStyleSheet(_step_style)
        s1_lay = QVBoxLayout(step1)
        s1_lay.setSpacing(8)

        s1_desc = QLabel(
            "Align the scan regions to your auction listing rows. "
            "At different resolutions or display scales the rows may need adjustment. "
            "Open the Row Tuner to drag and resize each row interactively."
        )
        s1_desc.setWordWrap(True)
        s1_desc.setStyleSheet("font-style:italic; color:#ccc;")
        s1_lay.addWidget(s1_desc)

        s1_btn_row = QHBoxLayout()
        s1_btn_row.setSpacing(12)
        self.tune_rows_btn = QPushButton("Open Row Tuner")
        self.tune_rows_btn.setProperty("class", "accent-btn")
        self.tune_rows_btn.setFixedWidth(160)
        self.tune_rows_btn.clicked.connect(self._launch_row_tuner)
        s1_btn_row.addWidget(self.tune_rows_btn)

        self.row_status_label = QLabel("Using formula defaults — open Row Tuner to calibrate")
        self.row_status_label.setStyleSheet("font-style:italic; color:#aaa;")
        s1_btn_row.addWidget(self.row_status_label)
        s1_btn_row.addStretch()
        s1_lay.addLayout(s1_btn_row)

        root.addWidget(step1)

        # ── STEP 2: Detection Calibration ─────────────────────────────────
        step2 = QGroupBox("Step 2 — Detection Calibration")
        step2.setStyleSheet(_step_style)
        s2_lay = QVBoxLayout(step2)
        s2_lay.setSpacing(8)

        s2_desc = QLabel(
            "Calibrate the auction button and sold badge detection for your screen. "
            "Auto is recommended. Manual lets you point to the regions with your mouse."
        )
        s2_desc.setWordWrap(True)
        s2_desc.setStyleSheet("font-style:italic; color:#ccc;")
        s2_lay.addWidget(s2_desc)

        self.sub_tabs = QTabWidget()

        # Auto tab
        auto_page = QWidget()
        auto_layout = QVBoxLayout(auto_page)
        auto_layout.setContentsMargins(10, 10, 10, 10)
        auto_layout.setSpacing(8)

        self.auto_blocked_notice = QLabel(
            "Manual calibration is active. Remove it first to use Auto Calibration."
        )
        self.auto_blocked_notice.setWordWrap(True)
        self.auto_blocked_notice.setStyleSheet(
            "background:#2a1800; color:#ffcc44; padding:8px;"
            " border-radius:4px; border:1px solid #554400;"
        )
        self.auto_blocked_notice.setVisible(False)
        auto_layout.addWidget(self.auto_blocked_notice)

        auto_explain = QLabel(
            "Automatically detects the Auction Options button and best-fit sold badge template.\n"
            "Open the auction house and wait until at least one row shows a car with the "
            'yellow "Sold!" badge visible, then run calibration.'
        )
        auto_explain.setWordWrap(True)
        auto_explain.setStyleSheet("font-style:italic;")
        auto_layout.addWidget(auto_explain)

        self.auto_run_btn = QPushButton("Run Auto Calibration")
        self.auto_run_btn.setProperty("class", "accent-btn")
        self.auto_run_btn.clicked.connect(self._run_auto)
        auto_layout.addWidget(self.auto_run_btn)

        self.auto_remove_btn = QPushButton("Remove Auto Calibration")
        self.auto_remove_btn.setEnabled(False)
        self.auto_remove_btn.clicked.connect(self._remove_auto)
        auto_layout.addWidget(self.auto_remove_btn)

        auto_layout.addStretch()
        self.sub_tabs.addTab(auto_page, "Auto Calibration")

        # Manual tab
        manual_page = QWidget()
        manual_layout = QVBoxLayout(manual_page)
        manual_layout.setContentsMargins(10, 10, 10, 10)
        manual_layout.setSpacing(6)

        self.manual_blocked_notice = QLabel(
            "Auto calibration is active. Remove it first to use Manual Calibration."
        )
        self.manual_blocked_notice.setWordWrap(True)
        self.manual_blocked_notice.setStyleSheet(
            "background:#2a1800; color:#ffcc44; padding:8px;"
            " border-radius:4px; border:1px solid #554400;"
        )
        self.manual_blocked_notice.setVisible(False)
        manual_layout.addWidget(self.manual_blocked_notice)

        manual_explain = QLabel(
            "Point to the auction button and sold badge with your mouse.\n"
            "Use this if Auto Calibration doesn't detect correctly for your setup."
        )
        manual_explain.setWordWrap(True)
        manual_explain.setStyleSheet("font-style:italic;")
        manual_layout.addWidget(manual_explain)

        auction_row = QHBoxLayout()
        auction_row.setSpacing(8)
        _auction_tpl = os.path.join(_root_dir, "assets", "auction_options_template_med.png")
        if os.path.isfile(_auction_tpl):
            _pix = QPixmap(_auction_tpl).scaledToHeight(
                44, Qt.TransformationMode.SmoothTransformation
            )
            _img = QLabel()
            _img.setPixmap(_pix)
            auction_row.addWidget(_img)
        self.manual_auction_btn = QPushButton("Manual Calibrate Auction Button")
        self.manual_auction_btn.setProperty("class", "accent-btn")
        self.manual_auction_btn.clicked.connect(self._run_manual_auction)
        auction_row.addWidget(self.manual_auction_btn)
        auction_row.addStretch()
        manual_layout.addLayout(auction_row)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        _badge_tpl = os.path.join(_root_dir, "assets", "sold_badge_template_med.png")
        if os.path.isfile(_badge_tpl):
            _pix = QPixmap(_badge_tpl).scaledToHeight(
                44, Qt.TransformationMode.SmoothTransformation
            )
            _img = QLabel()
            _img.setPixmap(_pix)
            badge_row.addWidget(_img)
        self.manual_badge_btn = QPushButton("Manual Calibrate Sold Badge")
        self.manual_badge_btn.setProperty("class", "accent-btn")
        self.manual_badge_btn.clicked.connect(self._run_manual_badge)
        badge_row.addWidget(self.manual_badge_btn)
        badge_row.addStretch()
        manual_layout.addLayout(badge_row)

        self.manual_remove_btn = QPushButton("Remove Manual Calibration")
        self.manual_remove_btn.setEnabled(False)
        self.manual_remove_btn.clicked.connect(self._remove_manual)
        manual_layout.addWidget(self.manual_remove_btn)

        manual_layout.addStretch()
        self.sub_tabs.addTab(manual_page, "Manual Calibration")

        s2_lay.addWidget(self.sub_tabs)
        root.addWidget(step2)

        # ── Shared status box ─────────────────────────────────────────────
        status_box = QGroupBox("Calibration Status")
        status_layout = QVBoxLayout(status_box)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11pt;")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 11pt; color: #2196f3;")
        self.progress_label.setWordWrap(True)
        status_layout.addWidget(self.progress_label)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-style: italic; font-size: 11pt;")
        status_layout.addWidget(self.result_label)
        root.addWidget(status_box)

        # ── Test / overlay buttons ────────────────────────────────────────
        test_row = QHBoxLayout()

        self.test_btn = QPushButton("Test Auction Button Region")
        self.test_btn.setEnabled(False)
        self.test_btn.clicked.connect(self._test_region)
        test_row.addWidget(self.test_btn)

        self.test_badge_btn = QPushButton("Test Badge Region")
        self.test_badge_btn.setEnabled(False)
        self.test_badge_btn.clicked.connect(self._test_badge_region)
        test_row.addWidget(self.test_badge_btn)

        self.overlay_btn = QPushButton("Show Auction Region Overlay")
        self.overlay_btn.setEnabled(False)
        self.overlay_btn.clicked.connect(self._show_overlay)
        test_row.addWidget(self.overlay_btn)

        self.badge_overlay_btn = QPushButton("Show Badge Region Overlay")
        self.badge_overlay_btn.setToolTip(
            "Flashes the sold-badge detection boxes on screen for 4 s.\n"
            "Open the auction house with sold cars visible before clicking."
        )
        self.badge_overlay_btn.clicked.connect(self._show_badge_overlay)
        test_row.addWidget(self.badge_overlay_btn)

        root.addLayout(test_row)

    def _launch_row_tuner(self) -> None:
        from row_tuner import ControlPanel, TuneOverlay

        if getattr(self, "_row_tuner_panel", None) and self._row_tuner_panel.isVisible():
            self._row_tuner_panel.raise_()
            self._row_tuner_panel.activateWindow()
            return

        overlay = TuneOverlay()
        panel = ControlPanel(overlay)
        panel.closed.connect(self._refresh_status)
        panel.show()
        self._row_tuner_panel = panel

    # ── Slots ──────────────────────────────────────────────────────────────

    def _set_status(self, text: str, ok: bool):
        color = "#4caf50" if ok else "#f44336"
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"font-size: 11pt; color: {color};")

    def _refresh_status(self):
        has_manual = calibrator.has_manual_region()
        has_auto = calibrator.has_auto_region()
        has_badge = calibrator.has_sold_badge_auto_cal()

        lines = [
            f"Manual calibration (auction button): {'SET' if has_manual else 'NOT SET'}",
            f"Auto calibration (auction button):   {'SET' if has_auto else 'NOT SET'}",
            f"Auto sold badge template:            "
            f"{'SET' if has_badge else 'NOT SET (uses runtime selection)'}",
        ]
        ok = has_manual or has_auto
        self._status_changed.emit("\n".join(lines), ok)

        # Row tuner status
        row_path = window_utils.get_user_data_file("row_regions_tuned.json")
        if os.path.isfile(row_path):
            try:
                with open(row_path) as f:
                    data = json.load(f)
                n = len(data.get("profiles", [data] if "rows" in data else []))
                self.row_status_label.setText(f"✓ {n} profile(s) saved")
                self.row_status_label.setStyleSheet("color:#4caf50; font-style:italic;")
            except Exception:
                self.row_status_label.setText("✓ Tuned file exists")
                self.row_status_label.setStyleSheet("color:#4caf50; font-style:italic;")
        else:
            self.row_status_label.setText("Using formula defaults — open Row Tuner to calibrate")
            self.row_status_label.setStyleSheet("color:#aaa; font-style:italic;")

        # Tab mutual exclusion — show notice banners; tabs stay clickable so
        # the user can reach the Remove button inside the blocked tab.
        self.auto_blocked_notice.setVisible(has_manual)
        self.manual_blocked_notice.setVisible(has_auto)

        self._set_calibration_buttons(not self._sniper_tab._calibration_in_progress)

    def _set_calibration_buttons(self, enabled: bool) -> None:
        has_manual = calibrator.has_manual_region()
        has_auto = calibrator.has_auto_region()
        self.auto_run_btn.setEnabled(enabled and not has_manual)
        self.auto_remove_btn.setEnabled(enabled and has_auto)
        self.manual_auction_btn.setEnabled(enabled and not has_auto)
        self.manual_badge_btn.setEnabled(enabled and not has_auto)
        self.manual_remove_btn.setEnabled(enabled and has_manual)
        self.test_btn.setEnabled(enabled and (has_manual or has_auto))
        has_cal = has_manual or has_auto
        has_badge = window_utils.load_badge_params() is not None
        self.test_badge_btn.setEnabled(enabled and has_badge and has_cal)
        self.overlay_btn.setEnabled(enabled and has_cal)
        self.badge_overlay_btn.setEnabled(enabled and has_cal)
        self._sniper_tab._set_calibration_mode(enabled)

    def _run_auto(self):
        self.result_label.setText("Running auto calibration…")
        self.progress_label.setText("")
        self._set_calibration_buttons(False)

        def _work():
            status_proxy = _QtCalibrationStatusProxy(self.progress_label)

            import builtins

            real_print = builtins.print

            def _trim_path_tokens(msg: str) -> str:
                try:
                    tokens = msg.split()
                    new = []
                    for t in tokens:
                        if "/" in t or "\\\\" in t or t.startswith("assets/"):
                            try:
                                bn = os.path.basename(t)
                                new.append(bn if bn else t)
                            except Exception:
                                new.append(t)
                        else:
                            new.append(t)
                    return " ".join(new)
                except Exception:
                    return msg

            def capture_print(*args, **kwargs):
                try:
                    msg = " ".join(str(a) for a in args)
                    short = _trim_path_tokens(msg)
                    _emit_log(short)
                    try:
                        status_proxy.config(text=short)
                    except Exception:
                        pass
                except Exception:
                    pass

            builtins.print = capture_print
            try:
                result = calibrator.auto_calibrate(status_label=status_proxy)
            finally:
                builtins.print = real_print
            # auto_calibrate returns (True, verified) on success or False on failure
            if result and result is not False:
                success, verified = result if isinstance(result, tuple) else (result, None)
            else:
                success, verified = False, None

            if success:
                self._sniper_tab.mark_calibration_done()
                badge_tpl = calibrator.load_sold_badge_template() or "default"
                badge_name = os.path.basename(badge_tpl)
                if verified:
                    _emit_log("✅ Auto calibration complete and verified")
                    self.result_label.setText(
                        f"✅ Calibration saved and verified — button re-detected in saved region.\n"
                        f"   Sold badge template: {badge_name}"
                    )
                else:
                    _emit_log("⚠️ Auto calibration saved but verification failed")
                    self.result_label.setText(
                        "⚠️ Calibration saved but the button was NOT re-detected"
                        " in the saved region.\n"
                        "   The auction screen may have changed — try recalibrating with it "
                        "clearly visible.\n"
                        f"   Sold badge template: {badge_name}"
                    )
                    self.result_label.setStyleSheet(
                        "font-style: italic; font-size: 11pt; color: #ff9800;"
                    )
            else:
                _emit_log("❌ Auto calibration failed")
                self.result_label.setText(
                    "❌ Auto calibration failed — make sure the FH6 auction screen is visible"
                    " and try again."
                )
            self._refresh_status()
            self._set_calibration_buttons(True)

        threading.Thread(target=_work, daemon=True).start()

    def _run_manual_auction(self):
        """Manual calibration — auction button only (hover-based)."""
        self.result_label.setText(
            "Auction button — follow the countdown, then hover over the Buy Options button"
        )
        self.progress_label.setText("")
        self._set_calibration_buttons(False)
        self._active_cal_overlay = _CalibrationOverlay()
        ingame = self._sniper_tab._ingame_overlay
        extra_y = ingame.height() if (ingame and ingame.isVisible()) else 0
        self._active_cal_overlay.reposition_for_ingame(extra_y=extra_y)
        overlay = self._active_cal_overlay  # local alias for closure

        def _work():
            status_proxy = _QtCalibrationStatusProxy(self.progress_label)

            import builtins

            real_print = builtins.print

            def _trim_path_tokens(msg: str) -> str:
                try:
                    tokens = msg.split()
                    new = []
                    for t in tokens:
                        if "/" in t or "\\\\" in t or t.startswith("assets/"):
                            try:
                                bn = os.path.basename(t)
                                new.append(bn if bn else t)
                            except Exception:
                                new.append(t)
                        else:
                            new.append(t)
                    return " ".join(new)
                except Exception:
                    return msg

            def capture_print(*args, **kwargs):
                try:
                    msg = " ".join(str(a) for a in args)
                    short = _trim_path_tokens(msg)
                    _emit_log(short)
                    try:
                        status_proxy.config(text=short)
                    except Exception:
                        pass
                except Exception:
                    pass

            region = None
            builtins.print = capture_print
            try:
                region = calibrator.calibrate(status_label=overlay, error_label=overlay)
            except Exception as e:
                _emit_log(f"❌ Auction calibration error: {e}")
            finally:
                builtins.print = real_print
                overlay.destroy_later()

            if not region:
                self._auction_done.emit(None, "❌ Auction button calibration failed — try again")
                return

            cfg_path = window_utils.get_config_file()
            try:
                with open(cfg_path) as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
            cfg["AUCTION_OPTIONS_REGION"] = list(region)
            with open(cfg_path, "w") as f:
                json.dump(cfg, f, indent=2)
            self._sniper_tab.mark_calibration_done()
            _emit_log("✅ Auction button region saved")
            self._auction_done.emit(list(region), "✅ Auction button calibrated")

        threading.Thread(target=_work, daemon=True).start()

    def _run_manual_badge(self):
        """Manual calibration — sold badge only (hover-based)."""
        self.result_label.setText(
            "Sold badge — open auction with a sold car visible,\n"
            "then hover the top-left corner of the badge, then the bottom-right corner"
        )
        self.progress_label.setText("")
        self._set_calibration_buttons(False)
        self._active_cal_overlay = _CalibrationOverlay()
        ingame = self._sniper_tab._ingame_overlay
        extra_y = ingame.height() if (ingame and ingame.isVisible()) else 0
        self._active_cal_overlay.reposition_for_ingame(extra_y=extra_y)
        overlay = self._active_cal_overlay  # local alias for closure

        def _work():
            result_text = "❌ Badge calibration error"
            try:
                result_text = self._show_sold_badge_step(overlay)
            except Exception as e:
                _emit_log(f"❌ Badge calibration error: {e}")
                result_text = f"❌ Badge calibration error: {e}"
            finally:
                overlay.destroy_later()
            self._badge_done.emit(result_text)

        threading.Thread(target=_work, daemon=True).start()

    def _show_sold_badge_step(self, overlay: "_CalibrationOverlay | None" = None) -> str:
        """Sold badge hover calibration — same countdown pattern as the auction button.

        Returns a result string suitable for display in result_label. The caller is
        responsible for showing it (via signal or direct call on main thread).
        overlay: pre-created on the main thread by the caller. When None, one is
        created here via a QTimer + threading.Event round-trip.
        The caller owns destroy_later() when overlay is passed in; this method
        destroys it when it creates its own.
        """
        _close_overlay = overlay is None
        if _close_overlay:
            import threading as _threading

            ready = _threading.Event()
            holder: list = []

            def _make() -> None:
                holder.append(_CalibrationOverlay())
                ready.set()

            QTimer.singleShot(0, _make)
            ready.wait(timeout=5)
            if not holder:
                _emit_log("❌ Badge calibration: could not create countdown banner")
                return "⚠️ Badge calibration failed — try again"
            overlay = holder[0]

        try:
            for i in range(5, 0, -1):
                overlay.config(text=f"Move mouse to TOP-LEFT corner of sold badge ({i})")
                time.sleep(1)
            pt1 = pyautogui.position()
            _emit_log(f"📌 Top-left: {pt1.x}, {pt1.y}")

            for i in range(5, 0, -1):
                overlay.config(text=f"Move mouse to BOTTOM-RIGHT corner of sold badge ({i})")
                time.sleep(1)
            pt2 = pyautogui.position()
            _emit_log(f"📌 Bottom-right: {pt2.x}, {pt2.y}")
        finally:
            if _close_overlay:
                overlay.destroy_later()

        w = pt2.x - pt1.x
        h = pt2.y - pt1.y
        if w <= 0 or h <= 0:
            _emit_log("❌ Badge calibration failed — hover TOP-LEFT first, then BOTTOM-RIGHT")
            return "⚠️ Badge calibration failed — hover TOP-LEFT first, then BOTTOM-RIGHT"

        ok = _save_badge_from_clicks(pt1.x, pt1.y, w, h)
        if ok:
            _emit_log("✅ Sold badge region saved")
            return "✅ Sold badge calibrated"
        else:
            _emit_log("❌ Could not save badge region — is FH6 running?")
            return "⚠️ Badge region failed — make sure FH6 is open and try again"

    @staticmethod
    def _launch_badge_tool(parent_dialog=None):
        root = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(root, "tools", "measure_sold_region.py")
        if os.path.isfile(script):
            subprocess.Popen([sys.executable, script])
        else:
            QMessageBox.warning(parent_dialog, "Not Found", f"Script not found:\n{script}")

    def _remove_auto(self):
        calibrator.reset_auto_region()
        _emit_log("🔄 Auto calibration removed (auction + sold badge)")
        self.result_label.setText("")
        self._refresh_status()

    def _remove_manual(self):
        calibrator.reset_region()
        _emit_log("🔄 Manual region removed")
        self.result_label.setText("")
        self._refresh_status()

    def _test_region(self):
        if calibrator.has_manual_region():
            region = calibrator.load_region()
            label = "manual"
        elif calibrator.has_auto_region():
            region = calibrator.load_auto_region()
            label = "auto"
        else:
            region = None
            label = ""
        if region is None:
            self.result_label.setText("No calibration region set")
            return
        self.result_label.setText("Testing region…")

        def _work():
            found = sniper.car_available(region)
            if found:
                self.result_label.setText(f"✅ Auction button detected in {label} region")
            else:
                self.result_label.setText(
                    f"❌ Auction button NOT detected — check {label} region alignment"
                )

        threading.Thread(target=_work, daemon=True).start()

    def _test_badge_region(self):
        self.result_label.setText("Testing badge region…")

        def _work():
            try:
                win = window_utils.get_fh6_window()
                if not win:
                    self.result_label.setText("⚠ FH6 window not found — open the game first")
                    return
                bp = window_utils.load_badge_params(win.width, win.height)
                if not bp:
                    self.result_label.setText("⚠ Badge region not calibrated")
                    return
                sold_template = calibrator.load_sold_badge_template() or window_utils.resource_path(
                    "assets/sold_badge_template.png"
                )
                row_rects = window_utils.get_row_regions(win)
                if not row_rects:
                    self.result_label.setText("⚠ Row regions not configured")
                    return
                full_img = vision_utils.grab_full_screen()
                scores = []
                for rx, ry, rw, rh in row_rects:
                    row_img = (
                        full_img.crop((rx, ry, rx + rw, ry + rh)) if full_img is not None else None
                    )
                    score = vision_utils.sold_badge_score(
                        (rx, ry, rw, rh), bp, sold_template, row_img=row_img
                    )
                    scores.append(score)
                detected = any(s >= SOLD_THRESHOLD for s in scores)
                score_str = ", ".join(f"{s:.2f}" for s in scores)
                if detected:
                    self.result_label.setText(f"✅ Sold badge detected (scores: {score_str})")
                else:
                    self.result_label.setText(
                        f"❌ No sold badge detected (scores: {score_str}) — open AH with sold cars visible"
                    )
            except Exception as e:
                self.result_label.setText(f"⚠ Badge test error: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def _show_overlay(self):
        region = None
        if calibrator.has_manual_region():
            region = calibrator.load_region()
        elif calibrator.has_auto_region():
            region = calibrator.load_auto_region()
        if region:
            self._auction_overlay = _AuctionRegionOverlay(region, duration_ms=5000)

    def _show_badge_overlay(self):
        """Compute badge scan rects from saved params + current window, then flash them."""
        try:
            win = window_utils.get_fh6_window()
            if not win:
                self.result_label.setText("⚠ FH6 window not found — open the game first")
                return

            bp = window_utils.load_badge_params(win.width, win.height)
            if not bp:
                self.result_label.setText(
                    "⚠ docs/sold_badge_region.json missing — run measure_sold_region.py first"
                )
                return

            row_rects_phys = window_utils.get_row_regions(win)

            badge_rects_phys = [vision_utils.badge_scan_region(row, bp) for row in row_rects_phys]

            self._badge_overlay = _BadgeRegionOverlay(
                badge_rects_phys, row_rects_phys, duration_ms=4000
            )

        except Exception as e:
            self.result_label.setText(f"⚠ Badge overlay error: {e}")


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------

PRESETS = {
    "Fast": {"buy_attempt_interval": 0.3, "post_buy_wait": 4.0, "reset_interval": 0.7},
    "Mid": {"buy_attempt_interval": 0.5, "post_buy_wait": 5.0, "reset_interval": 0.8},
    "Slow": {"buy_attempt_interval": 0.7, "post_buy_wait": 6.0, "reset_interval": 1.1},
}


class SettingsTab(QWidget):
    def __init__(self, sniper_tab: SniperTab, parent=None):
        super().__init__(parent)
        self._sniper_tab = sniper_tab
        self._applying_preset = False
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        root.addWidget(QLabel("<b style='font-size:14pt;'>Settings</b>"))

        explain = QLabel(
            "Choose a timing preset based on your PC and connection speed, or set custom values.\n"
            "Start with Mid — it gives reliable detection for most setups. "
            "Fast timing can cause available cars to be missed at high speed; "
            "only use it on a high-end PC with a fast connection."
        )
        explain.setWordWrap(True)
        explain.setStyleSheet("font-style: italic;")
        root.addWidget(explain)

        # ── Preset selector ───────────────────────────────────────────────
        preset_row = QHBoxLayout()
        preset_row.addStretch()
        preset_row.addWidget(QLabel("<b>Timing Preset:</b>"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Custom", "Fast", "Mid", "Slow"])
        self.preset_combo.setFixedWidth(120)
        self.preset_combo.currentTextChanged.connect(self._on_preset_change)
        preset_row.addWidget(self.preset_combo)
        preset_row.addStretch()
        root.addLayout(preset_row)

        # ── Numeric fields ────────────────────────────────────────────────
        form = QGroupBox("Timing Values")
        form_layout = QVBoxLayout(form)

        self.scans_spin = self._make_int_row(
            form_layout,
            "Number of Scans",
            1,
            100000,
            "How many auction listings to scan before stopping.",
        )
        self.buyout_target_combo = self._make_combo_row(
            form_layout,
            "Buyout Target",
            ["Infinite"] + [str(i) for i in range(1, 101)],
            "Stop the sniper after this many successful buyouts. Infinite means no buy target.",
        )
        self.buy_interval_spin = self._make_float_row(
            form_layout,
            "Buy Interval (s)",
            0.1,
            20.0,
            "Delay between keypresses during buy navigation.",
        )
        self.post_buy_spin = self._make_float_row(
            form_layout,
            "Post Buy Wait (s)",
            0.1,
            20.0,
            "Wait time after a buy attempt for the game to respond.",
        )
        self.reset_interval_spin = self._make_float_row(
            form_layout,
            "Reset Interval (s)",
            0.1,
            20.0,
            "Delay between keypresses during auction list reset.",
        )

        for spin in (self.buy_interval_spin, self.post_buy_spin, self.reset_interval_spin):
            spin.valueChanged.connect(self._on_value_changed)

        root.addWidget(form)

        # ── Save button + feedback ────────────────────────────────────────
        save_row = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setFixedWidth(140)
        self.save_btn.clicked.connect(self._save)
        save_row.addStretch()
        save_row.addWidget(self.save_btn)
        save_row.addStretch()
        root.addLayout(save_row)

        self.feedback_label = QLabel("")
        self.feedback_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.feedback_label)

        root.addStretch()

    @staticmethod
    def _make_float_row(parent_layout, label: str, mn: float, mx: float, tip: str):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(180)
        lbl.setToolTip(tip)
        spin = QDoubleSpinBox()
        spin.setRange(mn, mx)
        spin.setSingleStep(0.001)
        spin.setDecimals(3)
        spin.setFixedWidth(100)
        row.addStretch()
        row.addWidget(lbl)
        row.addWidget(spin)
        row.addStretch()
        parent_layout.addLayout(row)
        return spin

    @staticmethod
    def _make_int_row(parent_layout, label: str, mn: int, mx: int, tip: str):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(180)
        lbl.setToolTip(tip)
        spin = QSpinBox()
        spin.setRange(mn, mx)
        spin.setFixedWidth(100)
        row.addStretch()
        row.addWidget(lbl)
        row.addWidget(spin)
        row.addStretch()
        parent_layout.addLayout(row)
        return spin

    @staticmethod
    def _make_combo_row(parent_layout, label: str, items: list[str], tip: str):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(180)
        lbl.setToolTip(tip)
        combo = QComboBox()
        combo.addItems(items)
        combo.setFixedWidth(120)
        row.addStretch()
        row.addWidget(lbl)
        row.addWidget(combo)
        row.addStretch()
        parent_layout.addLayout(row)
        return combo

    # ── Logic ──────────────────────────────────────────────────────────────

    def _load_values(self):
        timings = settings.load_timings()
        self.scans_spin.setValue(settings.get_scans())
        buyout_val = settings.get_buyout_target()
        self.buyout_target_combo.setCurrentText(
            "Infinite" if buyout_val is None else str(buyout_val)
        )
        self.buy_interval_spin.setValue(timings.get("buy_attempt_interval", 0.6))
        self.post_buy_spin.setValue(timings.get("post_buy_wait", 5.0))
        self.reset_interval_spin.setValue(timings.get("reset_interval", 0.9))
        self._detect_preset()

    def _detect_preset(self):
        current = {
            "buy_attempt_interval": self.buy_interval_spin.value(),
            "post_buy_wait": self.post_buy_spin.value(),
            "reset_interval": self.reset_interval_spin.value(),
        }
        for name, vals in PRESETS.items():
            if all(abs(current[k] - vals[k]) < 0.01 for k in vals):
                self._applying_preset = True
                self.preset_combo.setCurrentText(name)
                self._applying_preset = False
                return
        self._applying_preset = True
        self.preset_combo.setCurrentText("Custom")
        self._applying_preset = False

    def _on_preset_change(self, name: str):
        if self._applying_preset or name not in PRESETS:
            return
        vals = PRESETS[name]
        self.buy_interval_spin.setValue(vals["buy_attempt_interval"])
        self.post_buy_spin.setValue(vals["post_buy_wait"])
        self.reset_interval_spin.setValue(vals["reset_interval"])
        self._save(message=f"✅ {name} preset applied and saved")

    def _on_value_changed(self):
        if not self._applying_preset:
            self._detect_preset()

    def _save(self, message=None):
        timings = {
            "buy_attempt_interval": self.buy_interval_spin.value(),
            "post_buy_wait": self.post_buy_spin.value(),
            "reset_interval": self.reset_interval_spin.value(),
        }
        combo_text = self.buyout_target_combo.currentText()
        buyout_target = None if combo_text == "Infinite" else int(combo_text)
        is_valid, error_msg, corrected = settings.save_timings_ui(
            timings,
            self.scans_spin.value(),
            buyout_target,
        )
        self.scans_spin.setValue(corrected["scans"])
        self.buy_interval_spin.setValue(corrected["timings"]["buy_attempt_interval"])
        self.post_buy_spin.setValue(corrected["timings"]["post_buy_wait"])
        self.reset_interval_spin.setValue(corrected["timings"]["reset_interval"])
        self._sniper_tab.scans_label.setText(f"Scans left: {corrected['scans']}")
        if message:
            self.feedback_label.setText(message)
            self.feedback_label.setStyleSheet("color: #4caf50;")
        elif is_valid:
            self.feedback_label.setText("✅ Settings saved")
            self.feedback_label.setStyleSheet("color: #4caf50;")
        else:
            self.feedback_label.setText(f"⚠️ {error_msg} (auto-corrected and saved)")
            self.feedback_label.setStyleSheet("color: #ff9800;")


# ---------------------------------------------------------------------------
# Info tab
# ---------------------------------------------------------------------------


class InfoTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        root.addWidget(QLabel("<b style='font-size:14pt;'>FH6 Sniper</b>"))
        root.addWidget(QLabel(f"Version {__version__}"))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        # GitHub link
        gh_row = QHBoxLayout()
        gh_row.addWidget(QLabel("View the project on GitHub"))
        gh_btn = QPushButton("Open")
        gh_btn.setFixedWidth(80)
        gh_btn.clicked.connect(
            lambda: webbrowser.open("https://github.com/CyberKrisLabs/fh6_sniper")
        )
        gh_row.addWidget(gh_btn)
        gh_row.addStretch()
        root.addLayout(gh_row)

        # PayPal
        pp_row = QHBoxLayout()
        pp_row.addWidget(QLabel("Support the project via PayPal"))
        pp_btn = QPushButton("Donate")
        pp_btn.setFixedWidth(80)
        pp_btn.clicked.connect(
            lambda: webbrowser.open("https://www.paypal.com/ncp/payment/W2FY4KHD58UEG")
        )
        pp_row.addWidget(pp_btn)
        pp_row.addStretch()
        root.addLayout(pp_row)

        # Update check
        upd_row = QHBoxLayout()
        self.update_btn = QPushButton("Check for Updates")
        self.update_btn.setFixedWidth(160)
        self.update_btn.clicked.connect(self._check_updates)
        upd_row.addWidget(self.update_btn)
        upd_row.addStretch()
        root.addLayout(upd_row)

        self.update_label = QLabel("")
        root.addWidget(self.update_label)

        root.addStretch()
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _check_updates(self):
        self.update_btn.setEnabled(False)
        self.update_label.setText("Checking…")

        def _work():
            if not HAVE_REQUESTS:
                self.update_label.setText("⚠️ 'requests' not installed — cannot check for updates")
                self.update_btn.setEnabled(True)
                return
            try:
                resp = requests.get(
                    "https://api.github.com/repos/CyberKrisLabs/fh6_sniper/releases/latest",
                    timeout=4,
                )
                if resp.ok:
                    tag = resp.json().get("tag_name", "")
                    latest = tag.lstrip("vV")
                    try:
                        newer = tuple(int(x) for x in latest.split(".")) > tuple(
                            int(x) for x in __version__.split(".")
                        )
                    except Exception:
                        newer = latest != __version__
                    if newer:
                        self.update_label.setText(f"🔄 Update available: {tag}")
                    else:
                        self.update_label.setText("✅ You are up to date")
                else:
                    self.update_label.setText("⚠️ Update check failed")
            except Exception:
                self.update_label.setText("⚠️ Update check failed (network error)")
            self.update_btn.setEnabled(True)

        threading.Thread(target=_work, daemon=True).start()


# ---------------------------------------------------------------------------
# Guide tab
# ---------------------------------------------------------------------------


class GuidesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(20, 16, 20, 24)
        root.setSpacing(6)

        def _section(title: str) -> None:
            if root.count():
                root.addSpacing(10)
            lbl = QLabel(f"<b style='font-size:13pt;'>{title}</b>")
            root.addWidget(lbl)
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("QFrame { color: #555; }")
            root.addWidget(sep)

        def _para(text: str, color: str = "#ccc") -> None:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"font-size:10pt; color:{color}; padding-top:4px;")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            root.addWidget(lbl)

        def _subhead(text: str) -> None:
            lbl = QLabel(f"<b style='font-size:10pt; color:#aaddff;'>{text}</b>")
            lbl.setStyleSheet("padding-top:8px;")
            root.addWidget(lbl)

        # ── Requirements ─────────────────────────────────────────────
        _section("Requirements")
        _para(
            "• Windows 10 or 11\n"
            "• Forza Horizon 6 installed and running\n"
            '• The game must be set to English — the sniper reads the "Sold!" badge text '
            "using OCR, other languages will not be detected\n"
            "• Windowed or borderless windowed mode is recommended for calibration"
        )

        # ── Quick Start ───────────────────────────────────────────────
        _section("Quick Start")
        _para(
            "1.  Launch FH6 and navigate to the Auction House.\n"
            "2.  In this app, open the Calibration tab.\n"
            "3.  Before running calibration, check that the row regions line up with the "
            "auction cards on screen. Open the Row Tuner (Step 1) and adjust the rows — "
            "they are likely out of alignment on first use or after a resolution change.\n"
            "4.  Run Auto Calibration (Step 2) — make sure at least one row shows a car "
            'with the yellow "Sold!" badge before clicking Run.\n'
            "5.  Go to Settings and pick Mid as your starting timing preset.\n"
            "6.  Return to the Sniper tab and hit Start."
        )

        # ── Calibration ───────────────────────────────────────────────
        _section("Calibration")

        _subhead("Row Calibration")
        _para(
            "The sniper watches 4 row regions for sold badges and available cars. "
            "At different resolutions or display-scaling levels the formula estimate may not "
            "line up perfectly with the actual cards.\n\n"
            "Open the Row Tuner, select a row with the numbered buttons (or keys 1–4), "
            "then use the right panel to move the row up/down/left/right and the left panel "
            "to resize it until the coloured overlay box sits on the auction card. "
            "Use Copy to all rows once the first row is correct, then fine-tune the rest. "
            "Hit Save — profiles are stored per resolution so rows stay correct after "
            "resolution changes."
        )

        _subhead("Auto Calibration (recommended)")
        _para(
            "Automatically finds the Auction Options button and picks the best sold-badge "
            "template for your screen.\n\n"
            "How to use:\n"
            "  1. Open the Auction House in FH6.\n"
            '  2. Wait until at least one row shows a car with the yellow "Sold!" badge.\n'
            "  3. Click Run Auto Calibration.\n\n"
            "If it fails, make sure the game is fully visible (not covered by other windows) "
            "and retry. Windowed mode works best."
        )

        _subhead("Manual Calibration")
        _para(
            "Use this if Auto Calibration cannot find the button, or if you have an unusual "
            "window layout.\n\n"
            "Both the auction button and sold badge use the same method: hover your mouse "
            "over the top-left corner when prompted, wait for the countdown, then move to "
            "the bottom-right corner and wait again. Just follow the on-screen countdown "
            "and hold still at each corner.\n\n"
            "Tip: the in-game overlay (toggle in the Sniper tab) has Calib Auction and "
            "Calib Badge buttons so you can calibrate without alt-tabbing."
        )

        # ── Settings ──────────────────────────────────────────────────
        _section("Settings")

        _subhead("Timing Presets")
        _para(
            "Timing controls how fast keystrokes are sent during buy attempts and auction resets.\n\n"
            "Mid  —  recommended starting point. Reliable detection for most setups.\n"
            "Fast  —  aggressive timing; may cause available cars to be missed at high speed. "
            "Only try this once Mid is working well and you want more speed.\n"
            "Slow  —  for slower PCs or laggy connections.\n\n"
            "If available cars are being missed, switch to Mid or Slow and re-run calibration."
        )

        _subhead("Number of Scans")
        _para(
            "How many auction listings the sniper will scan before stopping automatically. "
            "Set this high (or leave at the default) for a long session, or low for a quick "
            "targeted run."
        )

        _subhead("Buyout Target")
        _para(
            "How many successful car purchases to make before the sniper stops automatically. "
            "Set to Infinite to keep running until you stop it manually or the Number of Scans "
            "is reached, or pick a specific number if you only want to buy a fixed amount of cars."
        )

        # ── Buyout Attempt Detection ──────────────────────────────────
        _section("Buyout Attempt Detection")
        _para(
            "After each buyout attempt the sniper waits and tries to detect whether the "
            "purchase succeeded or failed. This detection step has a short built-in delay "
            "to account for slower internet connections and laggy servers — the game needs "
            "a moment to confirm the transaction before the result can be read.\n\n"
            "If you are on a slower connection and buyouts are being logged as failed even "
            "when they succeed, try increasing the Post Buy Wait value in Settings."
        )

        # ── In-game Overlay ───────────────────────────────────────────
        _section("In-game Overlay")
        _para(
            "Toggle the overlay from the Sniper tab. It floats above the FH6 window and lets "
            "you start/stop the sniper, trigger calibration, and open the Row Tuner "
            "without alt-tabbing.\n\n"
            "The overlay auto-hides when FH6 loses focus and reappears when it's active again. "
            "Click Hide or uncheck the toggle to close it permanently."
        )

        # ── Tips ──────────────────────────────────────────────────────
        _section("Tips & Troubleshooting")
        _para(
            "• Recalibrate after resizing, moving, or switching FH6 between windowed and "
            "fullscreen — the button position changes.\n"
            "• Only one calibration type (Auto or Manual) can be active at a time. "
            "Remove the current one before switching.\n"
            "• If the sniper stops detecting after a game update, re-run Auto Calibration.\n"
            "• Config is saved at  %APPDATA%\\FH6Sniper\\config.json\n"
            "• Logs are shown in the Status Log panel on the Sniper tab."
        )

        root.addStretch()
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FH6 Sniper")
        self.resize(930, 740)
        self.setMaximumHeight(740)

        try:
            self.setWindowIcon(QIcon(_icon_file))
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
        # Stop sniper loop so its daemon thread exits cleanly.
        self._sniper_tab._stop_event.set()

        # Close every other top-level window (overlays, dialogs).
        # Without this, Qt's quitOnLastWindowClosed keeps app.exec() alive
        # even after the main window is gone, so the process never exits.
        for w in QApplication.topLevelWidgets():
            if w is not self:
                try:
                    w.close()
                except Exception:
                    pass

        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    app.aboutToQuit.connect(vision_utils.release_dxcam)

    win = MainWindow()
    win.show()
    exit_code = app.exec()
    # os._exit bypasses Python's module-teardown phase, which can hang when C-extension
    # globals (dxcam, cv2, numpy) are destroyed in an undefined order at interpreter shutdown.
    os._exit(exit_code)


if __name__ == "__main__":
    main()
