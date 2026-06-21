import os

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import window_utils


class _CalibrationOverlay(QWidget):
    """Frameless always-on-top banner that shows calibration countdown.

    Implements the same .after() / .config() interface as a Tkinter widget so
    calibrator.calibrate() can call it without modification.  All signal
    emissions are thread-safe, so the background calibration thread can call
    these methods directly.
    """

    _text_signal = Signal(str)
    _close_signal = Signal()
    _img_signal = Signal(str)

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
        self._img_signal.connect(self._on_set_image)
        self._custom_pos: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container.setStyleSheet(
            "QWidget { background-color: rgba(0,0,0,215);"
            " border-radius: 10px;"
            " border: 2px solid #f5a623; }"
        )
        row = QHBoxLayout(container)
        row.setContentsMargins(18, 14, 28, 14)
        row.setSpacing(14)

        self._img_label = QLabel()
        self._img_label.setStyleSheet("border: none; background: transparent;")
        self._img_label.setVisible(False)
        row.addWidget(self._img_label)

        self._label = QLabel("")
        self._label.setStyleSheet(
            "border: none; background: transparent;"
            " color: #ffffff;"
            " font-size: 15pt; font-weight: bold;"
        )
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(580)
        row.addWidget(self._label, 1)

        outer.addWidget(container)

        self.adjustSize()
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, int(screen.height() * 0.15))
        self.show()

    def _on_set_text(self, text: str):
        self._label.setText(text)
        self.adjustSize()
        if self._custom_pos is not None:
            self.move(self._custom_pos)
        else:
            screen = QApplication.primaryScreen().geometry()
            self.move((screen.width() - self.width()) // 2, int(screen.height() * 0.15))

    def _on_set_image(self, path: str) -> None:
        if path and os.path.isfile(path):
            pix = QPixmap(path).scaledToHeight(48, Qt.TransformationMode.SmoothTransformation)
            self._img_label.setPixmap(pix)
            self._img_label.setVisible(True)
        else:
            self._img_label.clear()
            self._img_label.setVisible(False)
        self.adjustSize()

    def show_image(self, path: str) -> None:
        """Show a template thumbnail in the banner (thread-safe)."""
        self._img_signal.emit(path)

    # ── Tkinter-compatible interface (safe to call from background thread) ──

    def after(self, _delay: int, callback) -> None:
        callback()

    def config(self, text: str = "", bootstyle: str = "", **_kwargs) -> None:
        if text:
            self._text_signal.emit(str(text))

    def destroy_later(self) -> None:
        self._close_signal.emit()

    def reposition_for_ingame(self, extra_y: int = 0) -> None:
        """Move banner to the right side of the FH6 window."""
        win = window_utils.get_fh6_window()
        if not win:
            return
        self.adjustSize()
        dpr = QApplication.primaryScreen().devicePixelRatio()
        win_right = int((win.left + win.width) / dpr)
        win_top = int(win.top / dpr)
        x = win_right - self.width() - 12
        y = win_top + extra_y + int(QApplication.primaryScreen().geometry().height() * 0.15)
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
