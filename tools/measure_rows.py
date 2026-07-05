"""Row measurement tool for FH6 auction list.

Run this with the FH6 auction list visible on screen.
Hover over each prompted corner and press Space (or click Record) to capture it.
Results are saved to docs/row_measurements.json.

Usage:
    python tools/measure_rows.py
"""

import json
import os
import signal
import sys
from typing import Any

import pyautogui
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
# 8 points: top-left + bottom-right of each of the 4 rows
# ---------------------------------------------------------------------------

PROMPTS = [
    ("Row 1 — TOP-LEFT", "top-left corner of the row 1 card"),
    ("Row 1 — BOTTOM-RIGHT", "bottom-right corner of the row 1 card"),
    ("Row 2 — TOP-LEFT", "top-left corner of the row 2 card"),
    ("Row 2 — BOTTOM-RIGHT", "bottom-right corner of the row 2 card"),
    ("Row 3 — TOP-LEFT", "top-left corner of the row 3 card"),
    ("Row 3 — BOTTOM-RIGHT", "bottom-right corner of the row 3 card"),
    ("Row 4 — TOP-LEFT", "top-left corner of the row 4 card"),
    ("Row 4 — BOTTOM-RIGHT", "bottom-right corner of the row 4 card"),
]


# ---------------------------------------------------------------------------
# Full-screen transparent crosshair overlay
# ---------------------------------------------------------------------------


class CrosshairOverlay(QWidget):
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
        self._mx = 0
        self._my = 0
        self.show()

    def update_pos(self, x: int, y: int) -> None:
        self._mx = x
        self._my = y
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        pen = QPen(QColor(255, 60, 60, 200))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(self._mx, 0, self._mx, self.height())
        painter.drawLine(0, self._my, self.width(), self._my)

        painter.setBrush(QColor(255, 60, 60, 200))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self._mx - 5, self._my - 5, 10, 10)


# ---------------------------------------------------------------------------
# Main measurement panel
# ---------------------------------------------------------------------------


class MeasureTool(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("FH6 Row Measurement Tool")
        self._points: list[tuple[int, int]] = []
        self._step = 0
        self._win = None

        self._build_ui()
        self._overlay = CrosshairOverlay()

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        self._refresh_window_info()
        self._update_prompt()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        self.win_label = QLabel("FH6 window: detecting…")
        self.win_label.setStyleSheet("font-size: 9pt; color: #aaa;")
        root.addWidget(self.win_label)

        self.mouse_label = QLabel("Mouse: —")
        self.mouse_label.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        root.addWidget(self.mouse_label)

        self.rel_label = QLabel("Relative to window: —")
        self.rel_label.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        root.addWidget(self.rel_label)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #555;")
        root.addWidget(sep)

        self.prompt_label = QLabel("")
        self.prompt_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.prompt_label.setWordWrap(True)
        root.addWidget(self.prompt_label)

        self.sub_prompt = QLabel("")
        self.sub_prompt.setStyleSheet("font-style: italic; color: #bbb; font-size: 9pt;")
        self.sub_prompt.setWordWrap(True)
        root.addWidget(self.sub_prompt)

        self.progress_label = QLabel(f"Points recorded: 0 / {len(PROMPTS)}")
        self.progress_label.setStyleSheet("font-size: 9pt;")
        root.addWidget(self.progress_label)

        btn_row = QHBoxLayout()
        self.record_btn = QPushButton("Record  [Space]")
        self.record_btn.setFixedHeight(36)
        self.record_btn.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.record_btn.clicked.connect(self._record)
        btn_row.addWidget(self.record_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self.reset_btn)
        root.addLayout(btn_row)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 9pt; color: #8f8;"
        )
        root.addWidget(self.result_label)

        self.setFixedWidth(460)

    # ── Keyboard shortcut ──────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._record()

    # ── Poll loop ──────────────────────────────────────────────────────────

    def _poll(self) -> None:
        mx, my = pyautogui.position()
        self.mouse_label.setText(f"Mouse:    x={mx}  y={my}")

        win = window_utils.get_fh6_window()
        self._win = win
        if win:
            self.win_label.setText(f"FH6:  x={win.left}  y={win.top}  {win.width}×{win.height}")
            rx = mx - win.left
            ry = my - win.top
            rx_pct = rx / win.width * 100 if win.width else 0
            ry_pct = ry / win.height * 100 if win.height else 0
            self.rel_label.setText(f"Relative: x={rx}  y={ry}   ({rx_pct:.1f}%  {ry_pct:.1f}%)")
        else:
            self.win_label.setText("FH6 window: NOT FOUND — open FH6 first")
            self.rel_label.setText("Relative: —")

        self._overlay.update_pos(mx, my)

    def _refresh_window_info(self) -> None:
        self._win = window_utils.get_fh6_window()

    # ── Record / calculate ─────────────────────────────────────────────────

    def _record(self) -> None:
        if self._step >= len(PROMPTS):
            return
        mx, my = pyautogui.position()
        self._points.append((mx, my))
        self._step += 1
        self.progress_label.setText(f"Points recorded: {self._step} / {len(PROMPTS)}")

        if self._step < len(PROMPTS):
            self._update_prompt()
        else:
            self.prompt_label.setText("✅ All points recorded — calculating…")
            self.sub_prompt.setText("")
            self.record_btn.setEnabled(False)
            self._calculate()

    def _update_prompt(self) -> None:
        title, detail = PROMPTS[self._step]
        self.prompt_label.setText(f"Step {self._step + 1}/{len(PROMPTS)}: {title}")
        self.sub_prompt.setText(f"Hover over the {detail}, then press Space.")

    def _calculate(self) -> None:
        win = self._win
        if not win:
            self.result_label.setText("ERROR: FH6 window not found — reset and try again.")
            return

        wx, wy, ww, wh = win.left, win.top, win.width, win.height

        # Unpack 8 points: (tl, br) per row
        pairs = [(self._points[i * 2], self._points[i * 2 + 1]) for i in range(4)]

        result: dict[str, Any] = {
            "window": {"x": wx, "y": wy, "width": ww, "height": wh},
            "rows": [],
            "gaps": [],
        }

        lines = [f"Window: {ww}×{wh} at ({wx},{wy})\n"]
        prev_bottom = None

        for i, (tl, br) in enumerate(pairs):
            ax, ay = tl
            aw = br[0] - tl[0]
            ah = br[1] - tl[1]
            rx = ax - wx
            ry = ay - wy
            x_pct = round(rx / ww, 4)
            y_pct = round(ry / wh, 4)
            w_pct = round(aw / ww, 4)
            h_pct = round(ah / wh, 4)

            result["rows"].append(
                {
                    "abs": [ax, ay, aw, ah],
                    "rel": [rx, ry, aw, ah],
                    "pct": [x_pct, y_pct, w_pct, h_pct],
                }
            )
            lines.append(
                f"Row {i + 1}: rel=({rx},{ry})  {aw}×{ah}px  "
                f"pct=({x_pct * 100:.1f}%,{y_pct * 100:.1f}%)  "
                f"{w_pct * 100:.1f}%w × {h_pct * 100:.1f}%h"
            )

            # Gap between this row and the previous one
            if prev_bottom is not None:
                gap_px = ay - prev_bottom
                gap_pct = round(gap_px / wh, 4)
                result["gaps"].append({"px": gap_px, "pct": gap_pct})
                lines.append(f"  ↕ gap above row {i + 1}: {gap_px}px  ({gap_pct * 100:.2f}%h)")

            prev_bottom = ay + ah

        # Derived formula constants (averages across all 4 rows)
        rows = result["rows"]
        avg_x_pct = round(sum(r["pct"][0] for r in rows) / 4, 4)
        avg_y_start_pct = rows[0]["pct"][1]
        avg_h_pct = round(sum(r["pct"][3] for r in rows) / 4, 4)
        avg_w_pct = round(sum(r["pct"][2] for r in rows) / 4, 4)
        avg_gap_pct = (
            round(sum(g["pct"] for g in result["gaps"]) / len(result["gaps"]), 4)
            if result["gaps"]
            else 0
        )

        result["formula"] = {
            "ROW_X_PCT": avg_x_pct,
            "ROW_Y_START_PCT": avg_y_start_pct,
            "ROW_HEIGHT_PCT": avg_h_pct,
            "ROW_WIDTH_PCT": avg_w_pct,
            "ROW_GAP_PCT": avg_gap_pct,
        }

        lines.append("\nDerived formula constants:")
        lines.append(f"  ROW_X_PCT       = {avg_x_pct}  ({avg_x_pct * 100:.2f}%)")
        lines.append(f"  ROW_Y_START_PCT = {avg_y_start_pct}  ({avg_y_start_pct * 100:.2f}%)")
        lines.append(f"  ROW_HEIGHT_PCT  = {avg_h_pct}  ({avg_h_pct * 100:.2f}%)")
        lines.append(f"  ROW_WIDTH_PCT   = {avg_w_pct}  ({avg_w_pct * 100:.2f}%)")
        lines.append(f"  ROW_GAP_PCT     = {avg_gap_pct}  ({avg_gap_pct * 100:.2f}%)")

        out_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "docs",
            "row_measurements.json",
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)

        lines.append("\nSaved → docs/row_measurements.json")
        self.result_label.setText("\n".join(lines))
        print("\n".join(lines))

    def _reset(self) -> None:
        self._points = []
        self._step = 0
        self.record_btn.setEnabled(True)
        self.progress_label.setText(f"Points recorded: 0 / {len(PROMPTS)}")
        self.result_label.setText("")
        self._update_prompt()

    # ── Cleanup ────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._overlay.close()
        super().closeEvent(event)


# ---------------------------------------------------------------------------


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        "QWidget { background: #2b2b2b; color: #e0e0e0; }"
        "QPushButton { background: #4a4a4a; border: 1px solid #666;"
        " border-radius: 4px; padding: 4px 10px; }"
        "QPushButton:hover { background: #5a5a5a; }"
        "QPushButton:disabled { color: #555; }"
    )
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    tool = MeasureTool()
    tool.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
