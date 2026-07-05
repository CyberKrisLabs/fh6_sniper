"""Row preview and calibration tool for FH6 auction list.

Step 1 — Verify the boxes look correct at your calibrated window size.
Step 2 — Resize the FH6 window, then nudge the boxes left/right with the
         arrow buttons (or keyboard arrows) until they align with the rows.
         Accept to save the corrected measurements.

Usage:
    python tools/preview_rows.py
"""

import json
import os
import signal
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import window_utils

# ---------------------------------------------------------------------------
# Formula constants (from docs/row_measurements.json)
# ---------------------------------------------------------------------------

# ROW_X_PCT: physical row left as a fraction of physical window width.
# Original measure_rows stored a mixed-DPI ratio (0.0047); the true value
# is ~4.1 %, derived from two calibration points at 150 % DPI scaling.
ROW_X_PCT = 0.041
ROW_Y_START_PCT = 0.1095
ROW_HEIGHT_PCT = 0.1163
ROW_WIDTH_PCT = 0.2999
ROW_GAP_PCT = 0.0049
ROW_STEP_PCT = ROW_HEIGHT_PCT + ROW_GAP_PCT
NUM_ROWS = 4

ROW_COLORS = [
    QColor(255, 60, 60, 230),
    QColor(60, 210, 60, 230),
    QColor(60, 150, 255, 230),
    QColor(255, 200, 40, 230),
]


def get_row_regions(win_x, win_y, win_w, win_h, x_correction: int = 0):
    # pygetwindow returns physical pixels; Qt draws in logical pixels.
    # Divide x and width by devicePixelRatio to convert. Y/H errors are
    # small (win_y ≈ 16 px) so they are left as-is to keep Y/height correct.
    dpr = QApplication.primaryScreen().devicePixelRatio()
    x = int(win_x / dpr + (win_w / dpr) * ROW_X_PCT) + x_correction
    w = int(win_w * ROW_WIDTH_PCT)
    h = int(win_h * ROW_HEIGHT_PCT)
    y0 = win_y + int(win_h * ROW_Y_START_PCT)
    step = int(win_h * ROW_STEP_PCT)
    return [(x, y0 + i * step, w, h) for i in range(NUM_ROWS)]


# ---------------------------------------------------------------------------
# Full-screen overlay
# ---------------------------------------------------------------------------


class RowOverlay(QWidget):
    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self._rows: list[tuple[int, int, int, int]] = []
        self._step = 1
        self.show()

    def set_rows(self, rows: list[tuple[int, int, int, int]], step: int) -> None:
        self._rows = rows
        self._step = step
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._rows:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for i, (rx, ry, rw, rh) in enumerate(self._rows):
            color = ROW_COLORS[i % len(ROW_COLORS)]

            pen = QPen(color)
            pen.setWidth(3)
            if self._step == 2:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rx, ry, rw, rh)

            # label
            label_color = QColor(color)
            label_color.setAlpha(255)
            painter.setPen(label_color)
            painter.drawText(rx + 6, ry + 20, f"Row {i + 1}")


# ---------------------------------------------------------------------------
# Control panel
# ---------------------------------------------------------------------------


class ControlPanel(QWidget):
    def __init__(self, overlay: RowOverlay):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("Row Calibration")
        self._overlay = overlay
        self._step = 1
        self._x_correction = 0
        self._step1_win: dict[str, int] | None = None  # window info captured at step 1 accept

        self._build_ui()
        self._enter_step1()

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # Window info
        self.win_label = QLabel("FH6: detecting…")
        self.win_label.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        root.addWidget(self.win_label)

        # Step description
        self.step_label = QLabel("")
        self.step_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.step_label.setWordWrap(True)
        root.addWidget(self.step_label)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet("font-style: italic; color: #aaa; font-size: 9pt;")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #555;")
        root.addWidget(sep)

        # Row positions
        self.row_labels: list[QLabel] = []
        for i in range(NUM_ROWS):
            color = ROW_COLORS[i]
            hex_c = f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
            lbl = QLabel(f"Row {i + 1}: —")
            lbl.setStyleSheet(f"font-family: Consolas, monospace; font-size: 9pt; color: {hex_c};")
            root.addWidget(lbl)
            self.row_labels.append(lbl)

        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: #555;")
        root.addWidget(sep2)

        # X correction display (step 2 only)
        self.correction_label = QLabel("")
        self.correction_label.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        root.addWidget(self.correction_label)

        # Nudge buttons (step 2 only)
        self.nudge_widget = QWidget()
        nudge_row = QHBoxLayout(self.nudge_widget)
        nudge_row.setContentsMargins(0, 0, 0, 0)
        nudge_row.setSpacing(4)

        for label, delta in [("◀◀ 10", -10), ("◀ 1", -1), ("1 ▶", 1), ("10 ▶▶", 10)]:
            btn = QPushButton(label)
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda _, d=delta: self._nudge(d))
            nudge_row.addWidget(btn)

        nudge_row.addStretch()
        root.addWidget(self.nudge_widget)

        # Action buttons
        btn_row = QHBoxLayout()
        self.accept_btn = QPushButton("Accept Step 1")
        self.accept_btn.setFixedHeight(34)
        self.accept_btn.setStyleSheet("font-weight: bold;")
        self.accept_btn.clicked.connect(self._accept)
        btn_row.addWidget(self.accept_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self.reset_btn)
        root.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 9pt; color: #8f8;")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.setFixedWidth(420)

    # ── Step management ────────────────────────────────────────────────────

    def _enter_step1(self) -> None:
        self._step = 1
        self._x_correction = 0
        self.step_label.setText("Step 1 — Verify at calibrated window size")
        self.hint_label.setText(
            "Solid borders should line up with the 4 auction rows.\n"
            "When they look correct, click Accept Step 1."
        )
        self.accept_btn.setText("Accept Step 1  ✓")
        self.nudge_widget.setVisible(False)
        self.correction_label.setText("")
        self.status_label.setText("")

    def _enter_step2(self) -> None:
        self._step = 2
        self._x_correction = 0
        self.step_label.setText("Step 2 — Resize window and adjust X position")
        self.hint_label.setText(
            "Resize the FH6 window. Use the arrow buttons (or ← → keys) to\n"
            "nudge all boxes left/right until they align with the rows.\n"
            "Then click Save & Accept."
        )
        self.accept_btn.setText("Save & Accept  ✓")
        self.nudge_widget.setVisible(True)
        self.status_label.setText("")

    # ── Nudge ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        if self._step == 2:
            if event.key() == Qt.Key.Key_Left:
                self._nudge(-1)
            elif event.key() == Qt.Key.Key_Right:
                self._nudge(1)

    def _nudge(self, delta: int) -> None:
        if self._step == 2:
            self._x_correction += delta

    # ── Accept / reset ─────────────────────────────────────────────────────

    def _accept(self) -> None:
        win = window_utils.get_fh6_window()
        if not win:
            self.status_label.setText("ERROR: FH6 window not found.")
            return

        if self._step == 1:
            self._step1_win = {
                "width": win.width,
                "height": win.height,
                "x": win.left,
                "y": win.top,
            }
            self._enter_step2()
        else:
            self._save(win)

    def _reset(self) -> None:
        self._enter_step1()
        self.status_label.setText("")

    # ── Save ───────────────────────────────────────────────────────────────

    def _save(self, win) -> None:
        ww, wh = win.width, win.height
        rows = get_row_regions(win.left, win.top, ww, wh, self._x_correction)

        # Effective X relative to window at this size
        rel_x = rows[0][0] - win.left
        x_pct_new = round(rel_x / ww, 4)

        result = {
            "step1_window": self._step1_win,
            "step2_window": {"width": ww, "height": wh, "x": win.left, "y": win.top},
            "x_correction_px": self._x_correction,
            "effective_rel_x_px": rel_x,
            "effective_x_pct": x_pct_new,
            "note": (
                f"At step1 ROW_X_PCT was {ROW_X_PCT}. "
                f"At step2 window ({ww}x{wh}), corrected rel_x={rel_x}px ({x_pct_new * 100:.2f}%). "
                f"Update ROW_X_PCT to {x_pct_new} if this window size is your new reference."
            ),
        }

        out_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "docs",
            "row_x_calibration.json",
        )
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)

        self.status_label.setText(
            f"Saved → docs/row_x_calibration.json\n"
            f"Effective X: {rel_x}px ({x_pct_new * 100:.2f}%) at {ww}×{wh}"
        )
        print(json.dumps(result, indent=2))

    # ── Refresh loop ───────────────────────────────────────────────────────

    def _refresh(self) -> None:
        win = window_utils.get_fh6_window()
        if not win:
            self.win_label.setText("FH6: NOT FOUND — open the game")
            self._overlay.set_rows([], self._step)
            return

        ww, wh = win.width, win.height
        dpr = QApplication.primaryScreen().devicePixelRatio()
        lw, lh = int(ww / dpr), int(wh / dpr)
        self.win_label.setText(f"FH6:  {ww}×{wh} phys  ({lw}×{lh} logical)  DPR={dpr:.2f}")

        rows = get_row_regions(win.left, win.top, ww, wh, self._x_correction)
        self._overlay.set_rows(rows, self._step)

        win_x_log = win.left / dpr
        win_y_log = win.top / dpr
        for i, (rx, ry, rw, rh) in enumerate(rows):
            rel_x = rx - win_x_log
            rel_y = ry - win_y_log
            self.row_labels[i].setText(f"Row {i + 1}:  rel=({rel_x:.0f}, {rel_y:.0f})  {rw}×{rh}px")

        if self._step == 2:
            win_x_log = win.left / dpr
            win_w_log = ww / dpr
            rel_x0 = rows[0][0] - win_x_log
            formula_x = int(win_w_log * ROW_X_PCT)
            inside = win_x_log <= rows[0][0] <= win_x_log + win_w_log
            warning = "" if inside else "  ⚠ OUTSIDE WINDOW"
            self.correction_label.setText(
                f"X correction: {self._x_correction:+d}px   "
                f"formula X: {formula_x}px → effective: {rel_x0:.0f}px  "
                f"({rel_x0 / win_w_log * 100:.2f}%){warning}"
            )

    # ── Cleanup ────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._overlay.close()
        super().closeEvent(event)


# ---------------------------------------------------------------------------


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        "QWidget { background: #2b2b2b; color: #e0e0e0; font-size: 10pt; }"
        "QPushButton { background: #4a4a4a; border: 1px solid #666;"
        " border-radius: 4px; padding: 4px 10px; }"
        "QPushButton:hover { background: #5a5a5a; }"
    )

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    overlay = RowOverlay()
    panel = ControlPanel(overlay)
    panel.show()

    app.exec()


if __name__ == "__main__":
    main()
