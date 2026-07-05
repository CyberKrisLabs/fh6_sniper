"""Detection test tool for FH6 auction rows.

Captures all 4 row regions and runs the same detection logic the sniper uses:
  1. row_has_car()  — brightness threshold to tell empty slot from car card
  2. detect_sold()  — template match for the "Sold!" badge

Shows a thumbnail and result for each row so you can verify detection works
and tune the threshold / confidence before running the sniper for real.

Usage:
    python tools/test_detection.py
"""

import csv
import json
import os
import sys
import time

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vision_utils
import window_utils
from window_utils import (
    ROW_HEIGHT_PCT,
    ROW_STEP_PCT,
    ROW_WIDTH_PCT,
    ROW_X_PCT,
    ROW_Y_START_PCT,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOLD_TEMPLATE = os.path.join(ROOT, "assets", "sold_badge_template.png")
BADGE_JSON = os.path.join(ROOT, "docs", "sold_badge_region.json")
TUNED_JSON = os.path.join(ROOT, "docs", "row_regions_tuned.json")
CAPTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
NUM_ROWS = 4


def _load_badge_params(win_w: int | None = None, win_h: int | None = None) -> dict | None:
    return window_utils.load_badge_params(win_w, win_h)


def _get_row_regions(win) -> tuple[list[tuple[int, int, int, int]], str]:
    """Return row regions in physical screen pixels for pyautogui.

    In a PySide6 process the DPI-aware context makes pygetwindow return physical
    coords.  The overlay tools (tune_rows, preview_rows) work in Qt LOGICAL
    pixels and Qt maps logical → physical internally.  pyautogui does NOT do
    that mapping — it takes physical coords directly.  So we compute the same
    Qt logical rect as the overlay, then multiply by DPR to get physical.
    """
    dpr = QApplication.primaryScreen().devicePixelRatio()
    wx, wy, ww, wh = win.left, win.top, win.width, win.height  # physical from pygetwindow

    def to_phys(x, y, w, h):
        """Qt logical → physical screen pixels."""
        return (int(x * dpr), int(y * dpr), int(w * dpr), int(h * dpr))

    # Try tuned file first
    try:
        with open(TUNED_JSON) as f:
            data = json.load(f)
        rows_pct = data.get("rows", [])
        if rows_pct:
            result = []
            for r in rows_pct[:NUM_ROWS]:
                # Reconstruct Qt logical rect (same formula as tune_rows._base_rows)
                x = int(wx / dpr + (ww / dpr) * r["x_pct"])
                y = wy + int(wh * r["y_pct"])
                w = int(ww * r["w_pct"])
                h = int(wh * r["h_pct"])
                result.append(to_phys(x, y, w, h))
            return result, "tuned"
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Formula fallback — same as _base_rows in tune_rows.py, converted to physical
    x = int(wx / dpr + (ww / dpr) * ROW_X_PCT)
    w = int(ww * ROW_WIDTH_PCT)
    h = int(wh * ROW_HEIGHT_PCT)
    y0 = wy + int(wh * ROW_Y_START_PCT)
    step = int(wh * ROW_STEP_PCT)
    base = [(x, y0 + i * step, w, h) for i in range(NUM_ROWS)]
    return [to_phys(*r) for r in base], "formula"


def _to_pixmap(pil_img, max_h: int = 55) -> QPixmap:
    arr = np.ascontiguousarray(np.array(pil_img))
    h, w = arr.shape[:2]
    qimg = QImage(arr.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg).scaledToHeight(max_h, Qt.TransformationMode.SmoothTransformation)


# ── Per-row result widget ─────────────────────────────────────────────────────


class RowResult(QWidget):
    def __init__(self, idx: int) -> None:
        super().__init__()
        self._idx = idx
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(10)

        lbl = QLabel(f"<b>Row {idx + 1}</b>")
        lbl.setFixedWidth(46)
        layout.addWidget(lbl)

        self.thumb = QLabel()
        self.thumb.setFixedSize(220, 55)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background:#1a1a1a; border:1px solid #444;")
        self.thumb.setText("—")
        layout.addWidget(self.thumb)

        info = QVBoxLayout()
        info.setSpacing(1)
        self.bright_lbl = QLabel("Brightness: —")
        self.car_lbl = QLabel("—")
        self.sold_lbl = QLabel("—")
        for lbl in (self.bright_lbl, self.car_lbl, self.sold_lbl):
            lbl.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        info.addWidget(self.bright_lbl)
        info.addWidget(self.car_lbl)
        info.addWidget(self.sold_lbl)
        layout.addLayout(info)
        layout.addStretch()

    def show_result(
        self,
        pil_img,
        brightness: float,
        has_car: bool,
        is_sold: bool | None,
        threshold: int,
        sold_score: float | None = None,
    ) -> None:
        if pil_img is not None:
            self.thumb.setPixmap(_to_pixmap(pil_img))
        else:
            self.thumb.clear()
            self.thumb.setText("capture failed")

        self.bright_lbl.setText(f"Brightness: {brightness:.1f}  (cutoff: {threshold})")

        if has_car:
            self.car_lbl.setText("● HAS CAR")
            self.car_lbl.setStyleSheet("font-family: Consolas; font-size: 9pt; color: #4f4;")
        else:
            self.car_lbl.setText("● EMPTY")
            self.car_lbl.setStyleSheet("font-family: Consolas; font-size: 9pt; color: #888;")

        score_str = f"  [{sold_score:.2f}]" if sold_score is not None else ""
        if is_sold is None:
            txt = "badge: —" if has_car else "badge: (skipped)"
            color = "#666;"
        elif is_sold:
            txt = f"● SOLD{score_str}"
            color = "#f84;"
        else:
            txt = f"● AVAILABLE{score_str}"
            color = "#4af;"
        self.sold_lbl.setText(txt)
        self.sold_lbl.setStyleSheet(f"font-family: Consolas; font-size: 9pt; color: {color}")

    def clear(self) -> None:
        self.thumb.clear()
        self.thumb.setText("—")
        for lbl in (self.bright_lbl, self.car_lbl, self.sold_lbl):
            lbl.setText("—")
            lbl.setStyleSheet("font-family: Consolas; font-size: 9pt;")


# ── Main window ───────────────────────────────────────────────────────────────


class DetectionTestWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Row Detection Test")

        _init_win = window_utils.get_fh6_window()
        self._badge_params = _load_badge_params(
            _init_win.width if _init_win else None,
            _init_win.height if _init_win else None,
        )
        self._sold_ok = os.path.isfile(SOLD_TEMPLATE)
        self._scan_n = 0

        self._build_ui()
        self._show_asset_warnings()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._scan)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        self.win_lbl = QLabel("FH6: detecting…")
        self.win_lbl.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        root.addWidget(self.win_lbl)

        # Settings
        cfg = QHBoxLayout()
        cfg.addWidget(QLabel("Brightness cutoff:"))
        self.thresh = QSpinBox()
        self.thresh.setRange(5, 200)
        self.thresh.setValue(150)
        self.thresh.setFixedWidth(60)
        self.thresh.setToolTip(
            "Mean pixel brightness below this → row is EMPTY.\n"
            "Raise if empty rows are being called HAS CAR.\n"
            "Lower if filled rows are being called EMPTY."
        )
        cfg.addWidget(self.thresh)

        cfg.addSpacing(16)
        cfg.addWidget(QLabel("Sold confidence:"))
        self.conf = QDoubleSpinBox()
        self.conf.setRange(0.1, 1.0)
        self.conf.setSingleStep(0.01)
        self.conf.setDecimals(2)
        self.conf.setValue(0.72)
        self.conf.setFixedWidth(68)
        self.conf.setToolTip(
            "Template-match threshold for the Sold! badge.\n"
            "Lower → more sensitive (more false positives).\n"
            "Raise → stricter (may miss faint badges)."
        )
        cfg.addWidget(self.conf)

        self.sold_cb = QCheckBox("Check sold badge")
        self.sold_cb.setChecked(True)
        self.sold_cb.setToolTip(
            "Run detect_sold() on rows with a car.\nUncheck for a faster brightness-only scan."
        )
        cfg.addSpacing(16)
        cfg.addWidget(self.sold_cb)
        cfg.addStretch()
        root.addLayout(cfg)

        # Controls
        ctrl = QHBoxLayout()
        self.auto_cb = QCheckBox("Auto-scan  (1 s)")
        self.auto_cb.toggled.connect(self._toggle_auto)
        ctrl.addWidget(self.auto_cb)

        self.scan_btn = QPushButton("Scan Now")
        self.scan_btn.setFixedWidth(100)
        self.scan_btn.clicked.connect(self._scan)
        ctrl.addWidget(self.scan_btn)

        ctrl.addSpacing(16)
        self.save_cb = QCheckBox("Save captures")
        self.save_cb.setToolTip(
            f"Save each badge-region + full-row screenshot to tools/captures/\n"
            f"and append scores to captures/log.csv.\n"
            f"Destination: {CAPTURES_DIR}"
        )
        ctrl.addWidget(self.save_cb)
        ctrl.addStretch()
        root.addLayout(ctrl)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #555;")
        root.addWidget(sep)

        # Row result widgets
        self._rows: list[RowResult] = []
        for i in range(NUM_ROWS):
            rr = RowResult(i)
            root.addWidget(rr)
            self._rows.append(rr)

        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: #555;")
        root.addWidget(sep2)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size: 9pt; color: #aaa;")
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        self.setFixedWidth(540)

    def _show_asset_warnings(self) -> None:
        warnings = []
        if not self._badge_params:
            warnings.append("⚠  docs/sold_badge_region.json missing — run measure_sold_region.py")
        if not self._sold_ok:
            warnings.append("⚠  assets/sold_badge_template.png missing — sold detection disabled")
        if warnings:
            self.status_lbl.setText("\n".join(warnings))
            self.status_lbl.setStyleSheet("font-size: 9pt; color: #f84;")

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _toggle_auto(self, on: bool) -> None:
        self._timer.start() if on else self._timer.stop()

    def _scan(self) -> None:
        win = window_utils.get_fh6_window()
        if not win:
            self.win_lbl.setText("FH6: NOT FOUND — open the game")
            for rr in self._rows:
                rr.clear()
            return

        dpr = QApplication.primaryScreen().devicePixelRatio()
        lw, lh = int(win.width / dpr), int(win.height / dpr)
        regions, source = _get_row_regions(win)

        self.win_lbl.setText(
            f"FH6: {win.width}×{win.height} phys  ({lw}×{lh} logical)"
            f"  DPR={dpr:.2f}  rows: {source}"
        )

        if not regions:
            self.status_lbl.setText("⚠  Could not get row regions.")
            return

        self._scan_n += 1
        ts = time.strftime("%H%M%S")
        threshold = self.thresh.value()
        confidence = self.conf.value()
        check_sold = self.sold_cb.isChecked() and self._badge_params is not None and self._sold_ok
        saving = self.save_cb.isChecked()

        if saving:
            os.makedirs(CAPTURES_DIR, exist_ok=True)

        # Capture the full screen once so all rows come from the same GPU frame.
        # Per-row grabs each hit the DXGI pipeline independently and can land on
        # different frames; a shared capture fails consistently rather than
        # silently producing mixed-row results.
        full_img = vision_utils.grab_full_screen()

        for i, region in enumerate(regions):
            try:
                rx, ry, rw, rh = region
                pil_img = (
                    full_img.crop((rx, ry, rx + rw, ry + rh))
                    if full_img is not None
                    else vision_utils.grab_region(region)
                )
                gray = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
                brightness = float(np.mean(gray))
                has_car = brightness > threshold

                score: float | None = None
                badge_img = None
                if has_car and check_sold and self._badge_params is not None:
                    # Crop badge from already-captured row image — avoids a second
                    # grab_region call which can return a different (stale) frame.
                    rx, ry, rw, rh = region
                    bx = rx + int(rw * self._badge_params["badge_x_pct"])
                    by = ry + int(rh * self._badge_params["badge_y_pct"])
                    bw = max(1, int(rw * self._badge_params["badge_w_pct"]))
                    bh = max(1, int(rh * self._badge_params["badge_h_pct"]))
                    badge_img = pil_img.crop((bx - rx, by - ry, bx - rx + bw, by - ry + bh))
                    score = vision_utils.sold_badge_score(
                        region, self._badge_params, SOLD_TEMPLATE, row_img=pil_img
                    )
                    is_sold = score >= confidence
                else:
                    is_sold = None

                self._rows[i].show_result(pil_img, brightness, has_car, is_sold, threshold, score)

                if saving:
                    sc = f"{score:.2f}" if score is not None else "na"
                    stem = f"s{self._scan_n:04d}_{ts}_r{i + 1}_br{brightness:.0f}_score{sc}"
                    pil_img.save(os.path.join(CAPTURES_DIR, f"{stem}_row.png"))
                    if badge_img is not None:
                        badge_img.save(os.path.join(CAPTURES_DIR, f"{stem}_badge.png"))
                    csv_path = os.path.join(CAPTURES_DIR, "log.csv")
                    write_header = not os.path.isfile(csv_path)
                    with open(csv_path, "a", newline="") as f:
                        w = csv.writer(f)
                        if write_header:
                            w.writerow(
                                ["scan", "time", "row", "brightness", "has_car", "score", "is_sold"]
                            )
                        w.writerow(
                            [self._scan_n, ts, i + 1, f"{brightness:.1f}", has_car, sc, is_sold]
                        )

            except Exception as e:
                self._rows[i].clear()
                self.status_lbl.setText(f"Row {i + 1} error: {e}")
                return

        suffix = "  — saving to tools/captures/" if saving else ""
        self.status_lbl.setText(f"Scan #{self._scan_n} complete.{suffix}")
        self.status_lbl.setStyleSheet("font-size: 9pt; color: #8f8;")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    import signal

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        "QWidget { background: #2b2b2b; color: #e0e0e0; font-size: 10pt; }"
        "QPushButton { background: #4a4a4a; border: 1px solid #666;"
        " border-radius: 4px; padding: 4px 8px; }"
        "QPushButton:hover { background: #5a5a5a; }"
        "QSpinBox, QDoubleSpinBox { background: #333; border: 1px solid #666;"
        " border-radius: 3px; padding: 2px 4px; }"
        "QCheckBox { spacing: 6px; }"
    )
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    window = DetectionTestWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
