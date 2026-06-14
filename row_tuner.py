"""Row fine-tuning tool for FH6 auction list.

Shows all 4 rows with coloured borders plus the "Sold!" badge scan region
inside each one.  Select a row with 1-4 keys (or the row buttons) then:

  Arrow keys          - move selected row (X / Y)
  Shift + Arrow keys  - resize selected row (width / height)
  Nudge buttons       - same in 1 px or 10 px steps

Saves per-row (x_pct, y_pct, w_pct, h_pct) relative to the logical window
to the user data directory (docs/ from source, %APPDATA%\\FH6Sniper\\ when
compiled). The sniper and preview tools load this file automatically.

Launched automatically by the main app's Row Calibration tab.
Can also be run standalone:  python row_tuner.py
"""

import json
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

import vision_utils
import window_utils
from window_utils import (
    ROW_HEIGHT_PCT,
    ROW_STEP_PCT,
    ROW_WIDTH_PCT,
    ROW_X_PCT,
    ROW_Y_START_PCT,
)

NUM_ROWS = 4

ROW_COLORS = [
    QColor(255, 60, 60, 220),
    QColor(60, 210, 60, 220),
    QColor(60, 150, 255, 220),
    QColor(220, 120, 255, 220),
]
SEL_ALPHA = 255
BADGE_COLOR = QColor(255, 220, 40, 200)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _dpr() -> float:
    return QApplication.primaryScreen().devicePixelRatio()


def _base_rows(win_x: int, win_y: int, win_w: int, win_h: int) -> list[tuple[int, int, int, int]]:
    dpr = _dpr()
    x = int(win_x / dpr + (win_w / dpr) * ROW_X_PCT)
    w = int(win_w * ROW_WIDTH_PCT)
    h = int(win_h * ROW_HEIGHT_PCT)
    y0 = win_y + int(win_h * ROW_Y_START_PCT)
    step = int(win_h * ROW_STEP_PCT)
    return [(x, y0 + i * step, w, h) for i in range(NUM_ROWS)]


def _load_badge_params(win_w: int | None = None, win_h: int | None = None) -> dict | None:
    return window_utils.load_badge_params(win_w, win_h)


def _load_tuned(win_w: int | None = None, win_h: int | None = None) -> list[dict] | None:
    path = window_utils.get_user_data_file("row_regions_tuned.json")
    try:
        with open(path) as f:
            data = json.load(f)
        if "profiles" in data:
            profiles = data["profiles"]
            if not profiles:
                return None
            if win_w and win_h:
                dpr = _dpr()
                profile = window_utils.best_matching_row_profile(profiles, win_w, win_h, dpr)
            else:
                profile = profiles[0]
            return profile.get("rows")
        return data.get("rows")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Overlay ───────────────────────────────────────────────────────────────────


class TuneOverlay(QWidget):
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
        self._rows: list[tuple[int, int, int, int]] = []
        self._badge: dict | None = None
        self._sel: int = 0
        self.show()

    def set_state(
        self,
        rows: list[tuple[int, int, int, int]],
        badge: dict | None,
        sel: int,
    ) -> None:
        self._rows = rows
        self._badge = badge
        self._sel = sel
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._rows:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for i, (rx, ry, rw, rh) in enumerate(self._rows):
            is_sel = i == self._sel
            base = ROW_COLORS[i % len(ROW_COLORS)]

            c = QColor(base)
            c.setAlpha(SEL_ALPHA if is_sel else 160)
            pen = QPen(c)
            pen.setWidth(4 if is_sel else 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rx, ry, rw, rh)

            lc = QColor(c)
            lc.setAlpha(255)
            painter.setPen(lc)
            label = f"Row {i + 1}" if not is_sel else f"Row {i + 1}"
            painter.drawText(rx + 6, ry + 20, label)

            if self._badge:
                bx, by, bw, bh = vision_utils.badge_scan_region(
                    (rx, ry, rw, rh), self._badge
                )
                bp = QPen(BADGE_COLOR)
                bp.setWidth(2)
                bp.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(bp)
                fill = QColor(BADGE_COLOR)
                fill.setAlpha(25)
                painter.setBrush(fill)
                painter.drawRect(bx, by, bw, bh)
                painter.setPen(QColor(BADGE_COLOR))
                painter.drawText(bx + 3, by + 14, '"Sold!"')


# ── Control panel ─────────────────────────────────────────────────────────────


class ControlPanel(QWidget):
    def __init__(self, overlay: TuneOverlay) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("Row Fine-Tuning")
        self._overlay = overlay
        self._sel = 0
        self._adjs: list[list[int]] = [[0, 0, 0, 0] for _ in range(NUM_ROWS)]
        self._base: list[tuple[int, int, int, int]] = []
        self._win_phys: tuple[int, int, int, int] | None = None
        self._badge: dict | None = None
        self._badge_loaded = False

        self._build_ui()
        self._try_load_tuned()

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _try_load_tuned(self) -> None:
        self._pending_tuned = True

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(5)

        self.win_label = QLabel("FH6: detecting...")
        self.win_label.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        root.addWidget(self.win_label)

        sel_box = QGroupBox("Selected row  (keys 1-4)")
        sel_row = QHBoxLayout(sel_box)
        sel_row.setContentsMargins(4, 4, 4, 4)
        sel_row.setSpacing(4)
        self._sel_btns: list[QPushButton] = []
        for i in range(NUM_ROWS):
            c = ROW_COLORS[i]
            hex_c = f"#{c.red():02x}{c.green():02x}{c.blue():02x}"
            btn = QPushButton(f"Row {i + 1}")
            btn.setFixedWidth(70)
            btn.setStyleSheet(
                f"QPushButton {{ border: 2px solid {hex_c}; border-radius: 4px; }}"
                f"QPushButton:checked {{ background: {hex_c}; color: #111; font-weight: bold; }}"
            )
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, idx=i: self._select(idx))
            sel_row.addWidget(btn)
            self._sel_btns.append(btn)
        sel_row.addStretch()
        root.addWidget(sel_box)

        self.row_info = QLabel("Row: -")
        self.row_info.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        self.row_info.setWordWrap(True)
        root.addWidget(self.row_info)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #555;")
        root.addWidget(sep)

        root.addWidget(
            self._nudge_group(
                "X  (<- ->  or  Shift+<- -> arrows - move/resize width)",
                [("<<  10", -10), ("< 1", -1), ("1 >", 1), ("10 >>", 10)],
                lambda d: self._adj(dx=d),
            )
        )
        root.addWidget(
            self._nudge_group(
                "Y  (up/down arrows - move)",
                [("^^ 10", -10), ("^ 1", -1), ("1 v", 1), ("10 vv", 10)],
                lambda d: self._adj(dy=d),
            )
        )
        root.addWidget(
            self._nudge_group(
                "Width  (Shift+<- ->)",
                [("<<  10", -10), ("< 1", -1), ("1 >", 1), ("10 >>", 10)],
                lambda d: self._adj(dw=d),
            )
        )
        root.addWidget(
            self._nudge_group(
                "Height  (Shift+up/down)",
                [("^^ 10", -10), ("^ 1", -1), ("1 v", 1), ("10 vv", 10)],
                lambda d: self._adj(dh=d),
            )
        )

        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: #555;")
        root.addWidget(sep2)

        btn_row = QHBoxLayout()

        self.reset_row_btn = QPushButton("Reset row")
        self.reset_row_btn.setToolTip("Reset selected row to formula defaults")
        self.reset_row_btn.clicked.connect(self._reset_row)
        btn_row.addWidget(self.reset_row_btn)

        self.copy_btn = QPushButton("Copy to all")
        self.copy_btn.setToolTip("Apply selected row adjustments to every row")
        self.copy_btn.clicked.connect(self._copy_to_all)
        btn_row.addWidget(self.copy_btn)

        root.addLayout(btn_row)

        self.save_btn = QPushButton("Save all rows")
        self.save_btn.setFixedHeight(34)
        self.save_btn.setStyleSheet("font-weight: bold;")
        self.save_btn.clicked.connect(self._save)
        root.addWidget(self.save_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 9pt; color: #8f8;")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.setFixedWidth(440)
        self._select(0)

    def _nudge_group(self, title: str, steps: list, fn) -> QGroupBox:
        box = QGroupBox(title)
        box.setStyleSheet("QGroupBox { font-size: 9pt; }")
        row = QHBoxLayout(box)
        row.setContentsMargins(4, 2, 4, 4)
        row.setSpacing(4)
        for label, delta in steps:
            btn = QPushButton(label)
            btn.setFixedWidth(68)
            btn.clicked.connect(lambda _, d=delta: fn(d))
            row.addWidget(btn)
        row.addStretch()
        return box

    def _select(self, idx: int) -> None:
        self._sel = idx
        for i, btn in enumerate(self._sel_btns):
            btn.setChecked(i == idx)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if Qt.Key.Key_1 <= key <= Qt.Key.Key_4:
            self._select(key - Qt.Key.Key_1)
            return

        if key == Qt.Key.Key_Left:
            self._adj(dw=-1) if shift else self._adj(dx=-1)
        elif key == Qt.Key.Key_Right:
            self._adj(dw=1) if shift else self._adj(dx=1)
        elif key == Qt.Key.Key_Up:
            self._adj(dh=-1) if shift else self._adj(dy=-1)
        elif key == Qt.Key.Key_Down:
            self._adj(dh=1) if shift else self._adj(dy=1)

    def _adj(self, dx: int = 0, dy: int = 0, dw: int = 0, dh: int = 0) -> None:
        a = self._adjs[self._sel]
        a[0] += dx
        a[1] += dy
        a[2] += dw
        if self._base:
            _, _, _, base_h = self._base[self._sel]
            a[3] = max(10 - base_h, a[3] + dh)
        else:
            a[3] += dh

    def _reset_row(self) -> None:
        self._adjs[self._sel] = [0, 0, 0, 0]

    def _copy_to_all(self) -> None:
        src = list(self._adjs[self._sel])
        for i in range(NUM_ROWS):
            self._adjs[i] = list(src)

    def _current_rows(self) -> list[tuple[int, int, int, int]]:
        if not self._base:
            return []
        result = []
        for i, (bx, by, bw, bh) in enumerate(self._base):
            dx, dy, dw, dh = self._adjs[i]
            result.append((bx + dx, by + dy, max(10, bw + dw), max(10, bh + dh)))
        return result

    def _refresh(self) -> None:
        win = window_utils.get_fh6_window()
        if not win:
            self.win_label.setText("FH6: NOT FOUND - open the game")
            self._overlay.set_state([], self._badge, self._sel)
            return

        dpr = _dpr()
        ww_l, wh_l = int(win.width / dpr), int(win.height / dpr)
        self.win_label.setText(
            f"FH6: {win.width}x{win.height} phys  ({ww_l}x{wh_l} logical)  DPR={dpr:.2f}"
        )

        self._base = _base_rows(win.left, win.top, win.width, win.height)
        self._win_phys = (win.left, win.top, win.width, win.height)

        if not self._badge_loaded:
            self._badge = _load_badge_params(win.width, win.height)
            self._badge_loaded = True

        if hasattr(self, "_pending_tuned") and self._win_phys:
            wx, wy, ww, wh = self._win_phys
            rows_to_apply = _load_tuned(ww, wh)
            if rows_to_apply:
                for i, row_pct in enumerate(rows_to_apply[:NUM_ROWS]):
                    bx, by, bw, bh = self._base[i]
                    tx = int(wx / dpr + (ww / dpr) * row_pct["x_pct"])
                    ty = wy + int(wh * row_pct["y_pct"])
                    tw = int(ww * row_pct["w_pct"])
                    th = int(wh * row_pct["h_pct"])
                    self._adjs[i] = [tx - bx, ty - by, tw - bw, th - bh]
            del self._pending_tuned

        rows = self._current_rows()
        self._overlay.set_state(rows, self._badge, self._sel)

        if rows:
            rx, ry, rw, rh = rows[self._sel]
            bx, by, bw, bh = self._base[self._sel]
            wx, wy, ww, wh = self._win_phys
            dx, dy, dw, dh = self._adjs[self._sel]
            x_pct = (rx - wx / dpr) / (ww / dpr) if ww else 0
            y_pct = (ry - wy) / wh if wh else 0
            w_pct = rw / ww if ww else 0
            h_pct = rh / wh if wh else 0
            self.row_info.setText(
                f"Row {self._sel + 1}:  ({rx},{ry})  {rw}x{rh} px\n"
                f"  adj: dx={dx:+d} dy={dy:+d} dw={dw:+d} dh={dh:+d}\n"
                f"  pct: x={x_pct * 100:.2f}%  y={y_pct * 100:.2f}%  "
                f"w={w_pct * 100:.2f}%  h={h_pct * 100:.2f}%"
            )

    def _save(self) -> None:
        if not self._base or not self._win_phys:
            self.status_label.setText("ERROR: FH6 window not found.")
            return

        wx, wy, ww, wh = self._win_phys
        dpr = _dpr()
        rows = self._current_rows()
        row_data = []
        for rx, ry, rw, rh in rows:
            row_data.append(
                {
                    "x_pct": round((rx - wx / dpr) / (ww / dpr), 4) if ww else 0,
                    "y_pct": round((ry - wy) / wh, 4) if wh else 0,
                    "w_pct": round(rw / ww, 4) if ww else 0,
                    "h_pct": round(rh / wh, 4) if wh else 0,
                }
            )

        out_path = window_utils.get_user_data_file("row_regions_tuned.json")

        try:
            with open(out_path) as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}

        if "profiles" in existing:
            profiles = list(existing["profiles"])
        elif "rows" in existing:
            old_ref = existing.get("window_ref_physical", {})
            old_w = old_ref.get("width", ww)
            old_h = old_ref.get("height", wh)
            profiles = [
                {
                    "label": f"{old_w}x{old_h}",
                    "window_ref_physical": old_ref,
                    "rows": existing["rows"],
                }
            ]
        else:
            profiles = []

        new_profile: dict = {
            "label": f"{ww}x{wh}",
            "window_ref_physical": {"width": ww, "height": wh, "dpr": dpr},
            "rows": row_data,
        }
        curr_log_w = ww / dpr
        curr_log_h = wh / dpr
        replaced = False
        for idx, p in enumerate(profiles):
            ref = p.get("window_ref_physical", {})
            ref_dpr = ref.get("dpr", 1.0)
            ref_log_w = ref.get("width", 1) / ref_dpr
            ref_log_h = ref.get("height", 1) / ref_dpr
            score = max(abs(curr_log_w / ref_log_w - 1), abs(curr_log_h / ref_log_h - 1))
            if score <= 0.05:
                profiles[idx] = new_profile
                replaced = True
                break
        if not replaced:
            profiles.append(new_profile)

        result = {
            "profiles": profiles,
            "note": (
                "Multi-profile format. Each profile stores row percentages calibrated at "
                "a specific window size. Load with window_utils.get_tuned_row_regions()."
            ),
        }

        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)

        self.status_label.setText(
            f"Saved ({len(profiles)} profile(s))\n"
            + "\n".join(
                f"  Row {i + 1}: y={r['y_pct'] * 100:.2f}%  h={r['h_pct'] * 100:.2f}%"
                for i, r in enumerate(row_data)
            )
        )

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
        " margin-top: 8px; padding-top: 2px; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 6px; }"
        "QPushButton { background: #4a4a4a; border: 1px solid #666;"
        " border-radius: 4px; padding: 4px 6px; }"
        "QPushButton:hover { background: #5a5a5a; }"
        "QPushButton:checked { background: #336; border-color: #88f; }"
    )
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    overlay = TuneOverlay()
    panel = ControlPanel(overlay)
    panel.show()
    app.exec()


if __name__ == "__main__":
    main()
