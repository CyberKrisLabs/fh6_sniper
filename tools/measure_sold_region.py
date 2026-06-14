"""Sold badge region tool for FH6 auction list.

Shows Row 1 on screen. Adjust the inner yellow box to cover the area where
the "Sold!" badge appears in a row card. Position is saved as percentages of
the row card dimensions — same region is reused for all rows.

Controls (focus the control panel first):
  Arrow keys          — move the badge box
  Shift + Arrow keys  — resize width/height
  Button groups       — same, in 1 px or 10 px steps

Usage:
    python tools/measure_sold_region.py
"""

import json
import os
import signal
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import window_utils

# ── Default badge box (fraction of row card) ─────────────────────────────────
# Starting guess: top-left ~15 % wide × 40 % tall of the card.
DEFAULT_X_PCT = 0.00
DEFAULT_Y_PCT = 0.00
DEFAULT_W_PCT = 0.15
DEFAULT_H_PCT = 0.40

ROW_COLOR = QColor(60, 210, 60, 200)    # green border = row 1
BADGE_COLOR = QColor(255, 200, 40, 230)  # yellow = raw calibration box
SCAN_COLOR = QColor(255, 140, 0, 230)    # orange = padded scan region the sniper uses


def load_saved_badge(win_w: int | None = None, win_h: int | None = None) -> dict | None:
    """Load previously saved badge percentages, picking the best profile for the given window."""
    return window_utils.load_badge_params(win_w, win_h)


# ── Overlay ──────────────────────────────────────────────────────────────────


class SoldRegionOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self._row: tuple[int, int, int, int] | None = None
        self._badge: tuple[int, int, int, int] | None = None
        self._scan: tuple[int, int, int, int] | None = None
        self.show()

    def set_regions(
        self,
        row: tuple[int, int, int, int] | None,
        badge: tuple[int, int, int, int] | None,
        scan: tuple[int, int, int, int] | None = None,
    ) -> None:
        self._row = row
        self._badge = badge
        self._scan = scan
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._row:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Row 1 — solid green
        pen = QPen(ROW_COLOR)
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rx, ry, rw, rh = self._row
        painter.drawRect(rx, ry, rw, rh)
        painter.drawText(rx + 6, ry + 20, "Row 1")

        if self._scan:
            sx, sy, sw, sh = self._scan
            pen3 = QPen(SCAN_COLOR)
            pen3.setWidth(2)
            pen3.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen3)
            fill3 = QColor(SCAN_COLOR)
            fill3.setAlpha(25)
            painter.setBrush(fill3)
            painter.drawRect(sx, sy, sw, sh)
            lc3 = QColor(SCAN_COLOR)
            lc3.setAlpha(255)
            painter.setPen(lc3)
            painter.drawText(sx + 4, sy + 16, "sniper scan region (+30%)")

        if self._badge:
            bx, by, bw, bh = self._badge
            pen2 = QPen(BADGE_COLOR)
            pen2.setWidth(2)
            pen2.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen2)
            fill = QColor(BADGE_COLOR)
            fill.setAlpha(35)
            painter.setBrush(fill)
            painter.drawRect(bx, by, bw, bh)
            lc = QColor(BADGE_COLOR)
            lc.setAlpha(255)
            painter.setPen(lc)
            painter.drawText(bx + 4, by + 32, 'calibration target')


# ── Control panel ─────────────────────────────────────────────────────────────


class ControlPanel(QWidget):
    def __init__(self, overlay: SoldRegionOverlay) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("Sold Badge Region")
        self._overlay = overlay
        self._bdx = 0  # badge offset from row left (logical px)
        self._bdy = 0  # badge offset from row top  (logical px)
        self._bw = 0  # badge width  (logical px)
        self._bh = 0  # badge height (logical px)
        self._row: tuple[int, int, int, int] | None = None
        self._init = False  # deferred init after first window read

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        self.win_label = QLabel("FH6: detecting…")
        self.win_label.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        root.addWidget(self.win_label)

        self.row_label = QLabel("Row 1: —")
        self.row_label.setStyleSheet("font-family: Consolas; font-size: 9pt; color: #6d6;")
        root.addWidget(self.row_label)

        self.badge_label = QLabel("Badge: —")
        self.badge_label.setStyleSheet("font-family: Consolas; font-size: 9pt; color: #fc8;")
        self.badge_label.setWordWrap(True)
        root.addWidget(self.badge_label)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #555;")
        root.addWidget(sep)

        root.addWidget(
            self._nudge_group(
                "X position  (← →  or  Shift+← → arrows)",
                [("◀◀ 10", -10), ("◀ 1", -1), ("1 ▶", 1), ("10 ▶▶", 10)],
                lambda d: self._adj(dx=d),
            )
        )
        root.addWidget(
            self._nudge_group(
                "Y position  (↑ ↓  arrows)",
                [("▲▲ 10", -10), ("▲ 1", -1), ("1 ▼", 1), ("10 ▼▼", 10)],
                lambda d: self._adj(dy=d),
            )
        )
        root.addWidget(
            self._nudge_group(
                "Width  (Shift+← →  arrows)",
                [("◀◀ 10", -10), ("◀ 1", -1), ("1 ▶", 1), ("10 ▶▶", 10)],
                lambda d: self._adj(dw=d),
            )
        )
        root.addWidget(
            self._nudge_group(
                "Height  (Shift+↑ ↓  arrows)",
                [("▲▲ 10", -10), ("▲ 1", -1), ("1 ▼", 1), ("10 ▼▼", 10)],
                lambda d: self._adj(dh=d),
            )
        )

        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: #555;")
        root.addWidget(sep2)

        hint = QLabel(
            'Move the yellow box over the "Sold!" badge area in a row.\n'
            "Position is saved as % of card — same for all 4 rows."
        )
        hint.setStyleSheet("font-style: italic; color: #aaa; font-size: 9pt;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        save_btn = QPushButton("Save  ✓")
        save_btn.setFixedHeight(34)
        save_btn.setStyleSheet("font-weight: bold;")
        save_btn.clicked.connect(self._save)
        root.addWidget(save_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 9pt; color: #8f8;")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.setFixedWidth(420)

    def _nudge_group(self, title: str, steps: list, fn) -> QGroupBox:
        box = QGroupBox(title)
        row = QHBoxLayout(box)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        for label, delta in steps:
            btn = QPushButton(label)
            btn.setFixedWidth(68)
            btn.clicked.connect(lambda _, d=delta: fn(d))
            row.addWidget(btn)
        row.addStretch()
        return box

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._adj(dw=-1) if shift else self._adj(dx=-1)
        elif key == Qt.Key.Key_Right:
            self._adj(dw=1) if shift else self._adj(dx=1)
        elif key == Qt.Key.Key_Up:
            self._adj(dh=-1) if shift else self._adj(dy=-1)
        elif key == Qt.Key.Key_Down:
            self._adj(dh=1) if shift else self._adj(dy=1)

    # ── Adjustment ───────────────────────────────────────────────────────────

    def _adj(self, dx: int = 0, dy: int = 0, dw: int = 0, dh: int = 0) -> None:
        self._bdx += dx
        self._bdy += dy
        self._bw = max(10, self._bw + dw)
        self._bh = max(10, self._bh + dh)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        win = window_utils.get_fh6_window()
        if not win:
            self.win_label.setText("FH6: NOT FOUND — open the game")
            self._overlay.set_regions(None, None)
            return

        dpr = QApplication.primaryScreen().devicePixelRatio()
        lw, lh = int(win.width / dpr), int(win.height / dpr)
        self.win_label.setText(
            f"FH6:  {win.width}×{win.height} phys  ({lw}×{lh} logical)  DPR={dpr:.2f}"
        )

        phys_rows = window_utils.get_row_regions(win)
        rx_p, ry_p, rw_p, rh_p = phys_rows[0]
        row = (int(rx_p / dpr), int(ry_p / dpr), int(rw_p / dpr), int(rh_p / dpr))
        source = "tuned" if window_utils.get_tuned_row_regions(win) else "formula"
        self._row = row
        rx, ry, rw, rh = row

        # First run: restore saved calibration or fall back to defaults
        if not self._init:
            saved = load_saved_badge(win.width, win.height)
            if saved:
                self._bdx = int(rw * saved["badge_x_pct"])
                self._bdy = int(rh * saved["badge_y_pct"])
                self._bw = max(10, int(rw * saved["badge_w_pct"]))
                self._bh = max(10, int(rh * saved["badge_h_pct"]))
            else:
                self._bdx = int(rw * DEFAULT_X_PCT)
                self._bdy = int(rh * DEFAULT_Y_PCT)
                self._bw = max(10, int(rw * DEFAULT_W_PCT))
                self._bh = max(10, int(rh * DEFAULT_H_PCT))
            self._init = True

        badge = (rx + self._bdx, ry + self._bdy, self._bw, self._bh)

        # Compute the padded scan region that the sniper will actually use
        pad_x = max(1, int(self._bw * 0.15))
        pad_y = max(1, int(self._bh * 0.15))
        sx = max(rx, rx + self._bdx - pad_x)
        sy = max(ry, ry + self._bdy - pad_y)
        sw = min(rx + rw - sx, self._bw + 2 * pad_x)
        sh = min(ry + rh - sy, self._bh + 2 * pad_y)
        scan = (sx, sy, sw, sh)

        self._overlay.set_regions(row, badge, scan)

        self.row_label.setText(f"Row 1 [{source}]:  ({rx},{ry})  {rw}×{rh} px")

        xp = self._bdx / rw if rw else 0
        yp = self._bdy / rh if rh else 0
        wp = self._bw / rw if rw else 0
        hp = self._bh / rh if rh else 0
        self.badge_label.setText(
            f"Offset:  dx={self._bdx}px  dy={self._bdy}px\n"
            f"Size:    {self._bw}×{self._bh}px\n"
            f"As % of row:  x={xp * 100:.1f}%  y={yp * 100:.1f}%  "
            f"w={wp * 100:.1f}%  h={hp * 100:.1f}%"
        )

    # ── Save ─────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self._row:
            self.status_label.setText("ERROR: FH6 window not found.")
            return
        win = window_utils.get_fh6_window()
        rx, ry, rw, rh = self._row
        result = {
            "badge_x_pct": round(self._bdx / rw, 4) if rw else 0,
            "badge_y_pct": round(self._bdy / rh, 4) if rh else 0,
            "badge_w_pct": round(self._bw / rw, 4) if rw else 0,
            "badge_h_pct": round(self._bh / rh, 4) if rh else 0,
            "badge_dx_px": self._bdx,
            "badge_dy_px": self._bdy,
            "badge_w_px": self._bw,
            "badge_h_px": self._bh,
            "row_ref_px": [rw, rh],
            "note": (
                "Percentages are relative to the row card (width, height). "
                "Apply to any row: badge_x = row_x + row_w * badge_x_pct, etc."
            ),
        }
        ww = win.width if win else rw
        wh = win.height if win else rh
        dpr = float(QApplication.primaryScreen().devicePixelRatio())
        window_utils.save_badge_params(result, ww, wh, dpr)

        self.status_label.setText(
            f"Saved → docs/sold_badge_region.json\n"
            f"x={result['badge_x_pct'] * 100:.1f}%  y={result['badge_y_pct'] * 100:.1f}%  "
            f"w={result['badge_w_pct'] * 100:.1f}%  h={result['badge_h_pct'] * 100:.1f}%"
        )
        print(json.dumps(result, indent=2))

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._overlay.close()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        "QWidget { background: #2b2b2b; color: #e0e0e0; font-size: 10pt; }"
        "QGroupBox { border: 1px solid #555; border-radius: 4px;"
        " margin-top: 8px; padding-top: 4px; font-size: 9pt; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 6px; }"
        "QPushButton { background: #4a4a4a; border: 1px solid #666;"
        " border-radius: 4px; padding: 4px 6px; }"
        "QPushButton:hover { background: #5a5a5a; }"
    )
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    overlay = SoldRegionOverlay()
    panel = ControlPanel(overlay)
    panel.show()
    app.exec()


if __name__ == "__main__":
    main()
