"""Buy-result template match visualiser.

Shows the FH6 game window with coloured overlays wherever the
"Buy successful" and "Buy failed" templates match on a captured frame.

Use this when a buy attempt reports the wrong result — capture the screen
at the moment the result appears, then see which template matched and where.

Controls:
  Capture     — grab the screen now and run template matching
  Checkboxes  — toggle the Success (green) / Failure (red) overlay boxes
  Threshold   — nudge the confidence cut-off (lower = more matches shown)
  Region      — define a sub-region to limit the search (saves to config)
  Save image  — write the annotated frame to docs/

Usage:
    1. In FH6, get the buy result screen visible (success or failure dialog).
    2. python tools/tune_buy_detection.py
    3. Click "Capture & Analyse" — the overlay appears over the game.
    4. Adjust threshold or region if needed, then capture again.
"""

import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import window_utils

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
CONFIG_FILE = window_utils.get_config_file()

SUCC_BASE = window_utils.resource_path("assets/buyout_successful_template.png")
FAIL_BASE = window_utils.resource_path("assets/buyout_failed_template.png")

REGION_KEY = "BUY_RESULT_REGION"


def _asset_variants(base: str) -> list[str]:
    """Return [full, med] variants only — small is excluded because it
    matches unrelated corner UI elements at ~0.81 regardless of content."""
    return [p for p in [base, base.replace(".png", "_med.png")] if os.path.isfile(p)]


# ── Config helpers ────────────────────────────────────────────────────────────


def _load_region() -> tuple[int, int, int, int] | None:
    try:
        with open(CONFIG_FILE) as f:
            d = json.load(f)
        r = d.get(REGION_KEY)
        return tuple(r) if r else None
    except Exception:
        return None


def _save_region_to_config(region: tuple[int, int, int, int]) -> None:
    try:
        try:
            with open(CONFIG_FILE) as f:
                d = json.load(f)
        except Exception:
            d = {}
        d[REGION_KEY] = list(region)
        with open(CONFIG_FILE, "w") as f:
            json.dump(d, f, indent=2)
    except Exception as e:
        print(f"Failed to save region: {e}")


# ── Screen capture ────────────────────────────────────────────────────────────


def _grab_bgr() -> np.ndarray | None:
    """Single full-screen capture — tries dxcam first, falls back to pyautogui."""
    try:
        import dxcam

        cam = dxcam.create(output_color="BGR")
        import time

        for _ in range(8):
            frame = cam.grab()
            if frame is not None:
                return frame
            time.sleep(0.016)
        del cam
    except Exception:
        pass
    try:
        import pyautogui

        img = pyautogui.screenshot()
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


# ── Template matching ─────────────────────────────────────────────────────────


_tpl_cache: dict[str, np.ndarray] = {}


def _load_gray(path: str) -> np.ndarray:
    if path not in _tpl_cache:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(path)
        _tpl_cache[path] = img
    return _tpl_cache[path]


def _best_match(
    screen_gray: np.ndarray,
    template_paths: list[str],
    scale_min: float = 0.5,
    scale_max: float = 1.0,
    scale_steps: int = 18,
) -> tuple[float, tuple[int, int, int, int] | None, str]:
    """Return (best_score, best_loc_xywh, matched_template_name)."""
    sh, sw = screen_gray.shape[:2]
    best_score = 0.0
    best_loc = None
    best_name = ""

    for path in template_paths:
        try:
            tpl = _load_gray(path)
        except FileNotFoundError:
            continue
        th, tw = tpl.shape[:2]
        name = os.path.basename(path)
        for scale in np.linspace(scale_max, scale_min, scale_steps):
            rh = int(th * scale)
            rw = int(tw * scale)
            if rh <= 0 or rw <= 0 or rh > sh or rw > sw:
                continue
            resized = cv2.resize(tpl, (rw, rh), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = max_val
                best_loc = (max_loc[0], max_loc[1], rw, rh)
                best_name = name

    return best_score, best_loc, best_name


# ── Overlay ───────────────────────────────────────────────────────────────────


class BuyOverlay(QWidget):
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

        self._show_succ = True
        self._show_fail = True
        self._succ_loc: tuple[int, int, int, int] | None = None  # logical px
        self._fail_loc: tuple[int, int, int, int] | None = None
        self._succ_score = 0.0
        self._fail_score = 0.0
        self._region: tuple[int, int, int, int] | None = None  # logical px
        self._threshold = 0.72
        self.show()

    def update_state(
        self,
        succ_loc,
        succ_score,
        fail_loc,
        fail_score,
        region,
        threshold,
        show_succ,
        show_fail,
    ) -> None:
        self._succ_loc = succ_loc
        self._succ_score = succ_score
        self._fail_loc = fail_loc
        self._fail_score = fail_score
        self._region = region
        self._threshold = threshold
        self._show_succ = show_succ
        self._show_fail = show_fail
        self.update()

    def clear(self) -> None:
        self._succ_loc = None
        self._fail_loc = None
        self._succ_score = 0.0
        self._fail_score = 0.0
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Search region outline
        if self._region:
            rx, ry, rw, rh = self._region
            pen = QPen(QColor(255, 255, 255, 140), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rx, ry, rw, rh)
            p.setPen(QColor(255, 255, 255, 180))
            p.drawText(rx + 4, ry - 6, "Search region")

        def _draw_box(loc, score, color: QColor, label: str, show: bool) -> None:
            if not show or loc is None:
                return
            bx, by, bw, bh = loc
            found = score >= self._threshold
            c = QColor(color)
            c.setAlpha(220 if found else 90)
            pen = QPen(c, 3 if found else 2)
            if not found:
                pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            fill = QColor(color)
            fill.setAlpha(50 if found else 15)
            p.setBrush(fill)
            p.drawRect(bx, by, bw, bh)
            tag_color = QColor(color)
            tag_color.setAlpha(255)
            p.setPen(tag_color)
            tag = f"{label}  {score:.3f}" + (" ✓" if found else "")
            p.drawText(bx + 4, by - 6, tag)

        _draw_box(self._succ_loc, self._succ_score, QColor(60, 220, 60), "SUCCESS", self._show_succ)
        _draw_box(self._fail_loc, self._fail_score, QColor(220, 60, 60), "FAIL", self._show_fail)


# ── Control panel ─────────────────────────────────────────────────────────────


class ControlPanel(QWidget):
    # Signal to update UI safely from the background capture thread
    _done = Signal(dict)

    def __init__(self, overlay: BuyOverlay) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("Buy Detection Visualiser")
        self._overlay = overlay
        self._dpr = QApplication.primaryScreen().devicePixelRatio()
        self._busy = False

        # Region in logical Qt pixels (None = full FH6 window)
        saved = _load_region()
        if saved:
            sx, sy, sw, sh = saved
            self._region: tuple[int, int, int, int] | None = (
                int(sx / self._dpr),
                int(sy / self._dpr),
                int(sw / self._dpr),
                int(sh / self._dpr),
            )
        else:
            self._region = None

        self._threshold = 0.72
        self._show_succ = True
        self._show_fail = True

        # Last captured frame (BGR) — kept so "Save image" can annotate it
        self._last_frame: np.ndarray | None = None
        self._last_succ_score = 0.0
        self._last_fail_score = 0.0
        self._last_succ_loc_log: tuple[int, int, int, int] | None = None
        self._last_fail_loc_log: tuple[int, int, int, int] | None = None

        self._done.connect(self._on_done)
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        self._win_label = QLabel("FH6: —")
        self._win_label.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        root.addWidget(self._win_label)

        # Main action button
        self._capture_btn = QPushButton("📷  Capture & Analyse")
        self._capture_btn.setFixedHeight(38)
        self._capture_btn.setStyleSheet(
            "font-weight: bold; font-size: 11pt;"
            "background: #2a5a2a; border: 1px solid #4a8a4a; border-radius: 5px;"
        )
        self._capture_btn.clicked.connect(self._start_capture)
        root.addWidget(self._capture_btn)

        self._status_label = QLabel("Click Capture to grab the current screen.")
        self._status_label.setStyleSheet("font-size: 9pt; color: #aaa;")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        sep0 = QLabel()
        sep0.setFixedHeight(1)
        sep0.setStyleSheet("background: #555;")
        root.addWidget(sep0)

        # Visibility toggles
        vis_box = QGroupBox("Show overlays")
        vis_row = QHBoxLayout(vis_box)
        self._chk_succ = QCheckBox("Success (green)")
        self._chk_succ.setChecked(True)
        self._chk_succ.toggled.connect(self._on_vis_changed)
        self._chk_fail = QCheckBox("Failure (red)")
        self._chk_fail.setChecked(True)
        self._chk_fail.toggled.connect(self._on_vis_changed)
        vis_row.addWidget(self._chk_succ)
        vis_row.addWidget(self._chk_fail)
        vis_row.addStretch()
        root.addWidget(vis_box)

        # Scores
        score_box = QGroupBox("Match scores (last capture)")
        score_layout = QVBoxLayout(score_box)
        self._succ_label = QLabel("Success: —")
        self._succ_label.setStyleSheet("font-family: Consolas; color: #5d5; font-size: 9pt;")
        self._fail_label = QLabel("Failure: —")
        self._fail_label.setStyleSheet("font-family: Consolas; color: #d55; font-size: 9pt;")
        score_layout.addWidget(self._succ_label)
        score_layout.addWidget(self._fail_label)
        root.addWidget(score_box)

        # Threshold slider
        thr_box = QGroupBox("Confidence threshold  (re-capture to apply)")
        thr_layout = QVBoxLayout(thr_box)
        self._thr_label = QLabel(f"{self._threshold:.2f}")
        self._thr_label.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        self._thr_slider = QSlider(Qt.Orientation.Horizontal)
        self._thr_slider.setRange(30, 99)
        self._thr_slider.setValue(int(self._threshold * 100))
        self._thr_slider.valueChanged.connect(self._on_threshold)
        thr_layout.addWidget(self._thr_label)
        thr_layout.addWidget(self._thr_slider)
        root.addWidget(thr_box)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #555;")
        root.addWidget(sep)

        # Search region
        region_box = QGroupBox("Search region  (limit where templates are matched)")
        region_layout = QVBoxLayout(region_box)
        self._region_label = QLabel("Using full FH6 window")
        self._region_label.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        self._region_label.setWordWrap(True)
        region_layout.addWidget(self._region_label)
        self._update_region_label()

        region_layout.addWidget(
            self._nudge_group(
                "X",
                [("◀◀ 20", -20), ("◀ 5", -5), ("5 ▶", 5), ("20 ▶▶", 20)],
                lambda d: self._adj_region(dx=d),
            )
        )
        region_layout.addWidget(
            self._nudge_group(
                "Y",
                [("▲▲ 20", -20), ("▲ 5", -5), ("5 ▼", 5), ("20 ▼▼", 20)],
                lambda d: self._adj_region(dy=d),
            )
        )
        region_layout.addWidget(
            self._nudge_group(
                "Width",
                [("◀◀ 20", -20), ("◀ 5", -5), ("5 ▶", 5), ("20 ▶▶", 20)],
                lambda d: self._adj_region(dw=d),
            )
        )
        region_layout.addWidget(
            self._nudge_group(
                "Height",
                [("▲▲ 20", -20), ("▲ 5", -5), ("5 ▼", 5), ("20 ▼▼", 20)],
                lambda d: self._adj_region(dh=d),
            )
        )

        region_btn_row = QHBoxLayout()
        reset_btn = QPushButton("Use full window")
        reset_btn.clicked.connect(self._reset_region)
        save_region_btn = QPushButton("Save region ✓")
        save_region_btn.setStyleSheet("font-weight: bold;")
        save_region_btn.clicked.connect(self._save_region)
        region_btn_row.addWidget(reset_btn)
        region_btn_row.addWidget(save_region_btn)
        region_layout.addLayout(region_btn_row)
        root.addWidget(region_box)

        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: #555;")
        root.addWidget(sep2)

        save_btn = QPushButton("💾  Save annotated image to docs/")
        save_btn.clicked.connect(self._save_image)
        root.addWidget(save_btn)

        self.setFixedWidth(440)

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

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_threshold(self, value: int) -> None:
        self._threshold = value / 100.0
        self._thr_label.setText(f"{self._threshold:.2f}")

    def _on_vis_changed(self) -> None:
        self._show_succ = self._chk_succ.isChecked()
        self._show_fail = self._chk_fail.isChecked()
        # Update overlay immediately without re-capturing
        self._overlay._show_succ = self._show_succ
        self._overlay._show_fail = self._show_fail
        self._overlay.update()

    def _adj_region(self, dx=0, dy=0, dw=0, dh=0) -> None:
        if self._region is None:
            win = window_utils.get_fh6_window()
            if not win:
                self._status_label.setText("⚠ FH6 window not found")
                return
            self._region = (
                int(win.left / self._dpr),
                int(win.top / self._dpr),
                int(win.width / self._dpr),
                int(win.height / self._dpr),
            )
        x, y, w, h = self._region
        self._region = (x + dx, y + dy, max(50, w + dw), max(50, h + dh))
        self._update_region_label()
        # Update the region outline on the overlay immediately
        self._overlay._region = self._region
        self._overlay.update()

    def _reset_region(self) -> None:
        self._region = None
        self._update_region_label()
        self._overlay._region = None
        self._overlay.update()

    def _save_region(self) -> None:
        if self._region is None:
            self._status_label.setText("⚠ No custom region — nothing to save")
            return
        x, y, w, h = self._region
        phys = (int(x * self._dpr), int(y * self._dpr), int(w * self._dpr), int(h * self._dpr))
        _save_region_to_config(phys)
        self._status_label.setText(f"✅ Saved BUY_RESULT_REGION {phys}")

    def _update_region_label(self) -> None:
        if self._region is None:
            self._region_label.setText("Using full FH6 window")
        else:
            x, y, w, h = self._region
            self._region_label.setText(f"x={x}  y={y}  w={w}  h={h}  (logical px)")

    # ── Capture (background thread) ───────────────────────────────────────────

    def _start_capture(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._capture_btn.setEnabled(False)
        self._status_label.setText("Capturing…")
        QApplication.processEvents()

        win = window_utils.get_fh6_window()
        if win:
            self._win_label.setText(
                f"FH6: ({win.left},{win.top})  {win.width}×{win.height}  DPR={self._dpr:.1f}"
            )

        # Copy state so the thread doesn't touch Qt objects
        region = self._region
        threshold = self._threshold
        dpr = self._dpr

        def _work():
            result = {"error": None}
            try:
                frame = _grab_bgr()
                if frame is None:
                    result["error"] = "Screen capture returned nothing"
                    self._done.emit(result)
                    return

                fh, fw = frame.shape[:2]

                # Determine physical search area.
                # The buy result popup always appears in the center of the window,
                # so default to the center 2/3 × 2/3 of the window to avoid
                # false positives from off-center UI chrome.
                if region is not None:
                    rx_p = int(region[0] * dpr)
                    ry_p = int(region[1] * dpr)
                    rw_p = int(region[2] * dpr)
                    rh_p = int(region[3] * dpr)
                elif win:
                    ww, wh = win.width, win.height
                    cx, cy = max(0, win.left) + ww // 2, max(0, win.top) + wh // 2
                    rw_p = ww * 2 // 3
                    rh_p = wh * 2 // 3
                    rx_p = cx - rw_p // 2
                    ry_p = cy - rh_p // 2
                else:
                    rw_p, rh_p = fw * 2 // 3, fh * 2 // 3
                    rx_p, ry_p = (fw - rw_p) // 2, (fh - rh_p) // 2

                rx_p = max(0, min(rx_p, fw - 1))
                ry_p = max(0, min(ry_p, fh - 1))
                rw_p = max(1, min(rw_p, fw - rx_p))
                rh_p = max(1, min(rh_p, fh - ry_p))

                crop = frame[ry_p : ry_p + rh_p, rx_p : rx_p + rw_p]
                crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

                succ_score, succ_loc_crop, succ_tpl = _best_match(
                    crop_gray, _asset_variants(SUCC_BASE)
                )
                fail_score, fail_loc_crop, fail_tpl = _best_match(
                    crop_gray, _asset_variants(FAIL_BASE)
                )

                def _to_log(loc_crop):
                    if loc_crop is None:
                        return None
                    cx, cy, cw, ch = loc_crop
                    return (
                        int((rx_p + cx) / dpr),
                        int((ry_p + cy) / dpr),
                        int(cw / dpr),
                        int(ch / dpr),
                    )

                result.update(
                    {
                        "frame": frame,
                        "succ_score": succ_score,
                        "succ_tpl": succ_tpl,
                        "fail_score": fail_score,
                        "fail_tpl": fail_tpl,
                        "succ_loc_log": _to_log(succ_loc_crop),
                        "fail_loc_log": _to_log(fail_loc_crop),
                        "region_log": (
                            int(rx_p / dpr),
                            int(ry_p / dpr),
                            int(rw_p / dpr),
                            int(rh_p / dpr),
                        )
                        if region is not None
                        else None,
                        "threshold": threshold,
                    }
                )
            except Exception as e:
                result["error"] = str(e)
            self._done.emit(result)

        threading.Thread(target=_work, daemon=True).start()

    def _on_done(self, result: dict) -> None:
        self._busy = False
        self._capture_btn.setEnabled(True)

        if result.get("error"):
            self._status_label.setText(f"⚠ {result['error']}")
            return

        succ_score = result["succ_score"]
        fail_score = result["fail_score"]
        succ_loc = result["succ_loc_log"]
        fail_loc = result["fail_loc_log"]

        self._last_frame = result["frame"]
        self._last_succ_score = succ_score
        self._last_fail_score = fail_score
        self._last_succ_loc_log = succ_loc
        self._last_fail_loc_log = fail_loc

        threshold = result["threshold"]

        succ_tpl = result.get("succ_tpl", "")
        fail_tpl = result.get("fail_tpl", "")

        def _score_text(label, score, loc, tpl):
            found = score >= threshold
            mark = "✓ MATCH" if found else "· below threshold"
            pos = f"  ({loc[0]},{loc[1]})  {loc[2]}×{loc[3]} px" if loc else ""
            tpl_name = f"  [{tpl}]" if tpl else ""
            return f"{label}: {score:.4f}  {mark}{pos}{tpl_name}"

        self._succ_label.setText(_score_text("Success", succ_score, succ_loc, succ_tpl))
        self._fail_label.setText(_score_text("Failure", fail_score, fail_loc, fail_tpl))

        verdict = "—"
        if succ_score >= threshold:
            verdict = "✅ Would report: Buy successful"
        elif fail_score >= threshold:
            verdict = "❌ Would report: Buy failed"
        else:
            verdict = "⚠ Would report: Undetermined"
        self._status_label.setText(verdict)

        self._overlay.update_state(
            succ_loc=succ_loc,
            succ_score=succ_score,
            fail_loc=fail_loc,
            fail_score=fail_score,
            region=result.get("region_log"),
            threshold=threshold,
            show_succ=self._show_succ,
            show_fail=self._show_fail,
        )

    # ── Save annotated image ──────────────────────────────────────────────────

    def _save_image(self) -> None:
        if self._last_frame is None:
            self._status_label.setText("⚠ No capture yet — click Capture first")
            return

        annotated = self._last_frame.copy()
        dpr = self._dpr

        def _draw(loc_log, score, color_bgr, label):
            if loc_log is None:
                return
            lx, ly, lw, lh = loc_log
            px, py = int(lx * dpr), int(ly * dpr)
            pw, ph = int(lw * dpr), int(lh * dpr)
            found = score >= self._threshold
            c = color_bgr if found else tuple(v // 2 for v in color_bgr)
            cv2.rectangle(annotated, (px, py), (px + pw, py + ph), c, 3 if found else 1)
            tag = f"{label} {score:.3f}" + (" MATCH" if found else "")
            cv2.putText(
                annotated,
                tag,
                (px, max(py - 6, 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                c,
                2,
                cv2.LINE_AA,
            )

        _draw(self._last_succ_loc_log, self._last_succ_score, (60, 220, 60), "SUCCESS")
        _draw(self._last_fail_loc_log, self._last_fail_score, (60, 60, 220), "FAIL")

        os.makedirs(DOCS, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(DOCS, f"buy_detect_{ts}.png")
        cv2.imwrite(path, annotated)
        self._status_label.setText(f"✅ Saved → docs/buy_detect_{ts}.png")
        try:
            subprocess.Popen(["explorer", path])
        except Exception:
            pass


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
        "QSlider::groove:horizontal { height: 6px; background: #555; border-radius: 3px; }"
        "QSlider::handle:horizontal { width: 14px; height: 14px; background: #8af;"
        " border-radius: 7px; margin: -4px 0; }"
    )
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    overlay = BuyOverlay()
    panel = ControlPanel(overlay)
    panel.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
