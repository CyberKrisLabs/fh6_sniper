from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

import pyautogui
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import calibrator
import sniper
import vision_utils
import window_utils
from sniper import SOLD_THRESHOLD
from ui.log_bridge import _emit_log
from ui.overlays.calibration import _CalibrationOverlay, _QtCalibrationStatusProxy
from ui.overlays.regions import _AuctionRegionOverlay, _BadgeRegionOverlay

if TYPE_CHECKING:
    from ui.tabs.sniper import SniperTab

_BADGE_MARGIN = 20


def _save_badge_from_clicks(badge_x: int, badge_y: int, badge_w: int, badge_h: int) -> bool:
    """Convert hover-captured coords to row-relative badge params and save."""
    try:
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


class CalibrationTab(QWidget):
    _status_changed = Signal(str, bool)
    _auction_done = Signal(object, str)
    _badge_done = Signal(str)

    def __init__(self, sniper_tab: SniperTab, parent=None):
        super().__init__(parent)
        self._sniper_tab = sniper_tab
        self._active_cal_overlay: _CalibrationOverlay | None = None
        self._row_tuner_panel: QWidget | None = None
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
        # Walk up two levels: ui/tabs/ -> project root
        _root_dir = os.path.dirname(os.path.dirname(_root_dir))

        _step_style = (
            "QGroupBox { font-weight:bold; font-size:11pt;"
            " border:1px solid #555; border-radius:6px;"
            " margin-top:14px; padding-top:6px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; }"
        )

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

        if self._row_tuner_panel is not None and self._row_tuner_panel.isVisible():
            self._row_tuner_panel.raise_()
            self._row_tuner_panel.activateWindow()
            return

        overlay = TuneOverlay()
        panel = ControlPanel(overlay)
        panel.closed.connect(self._refresh_status)
        panel.show()
        self._row_tuner_panel = panel

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
            if result and result is not False:
                unpacked = result if isinstance(result, tuple) else (result, None, None)
                success = unpacked[0]
                verified = unpacked[1] if len(unpacked) > 1 else None
                badge_ok = unpacked[2] if len(unpacked) > 2 else None
            else:
                success, verified, badge_ok = False, None, None

            if success:
                self._sniper_tab.mark_calibration_done()
                badge_line = (
                    "   Sold badge position calibrated."
                    if badge_ok
                    else "   Sold badge position not detected — using built-in templates."
                )
                if verified:
                    _emit_log("✅ Auto calibration complete and verified")
                    self.result_label.setText(f"✅ Calibration saved and verified.\n{badge_line}")
                else:
                    _emit_log("⚠️ Auto calibration saved but verification failed")
                    self.result_label.setText(
                        "⚠️ Calibration saved but could not be verified.\n"
                        "   Try recalibrating with the auction screen clearly visible.\n"
                        f"{badge_line}"
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
        self.result_label.setText(
            "Auction button — follow the countdown, then hover over the Buy Options button"
        )
        self.progress_label.setText("")
        self._set_calibration_buttons(False)
        self._active_cal_overlay = _CalibrationOverlay()
        ingame = self._sniper_tab._ingame_overlay
        extra_y = ingame.height() if (ingame and ingame.isVisible()) else 0
        self._active_cal_overlay.reposition_for_ingame(extra_y=extra_y)
        overlay = self._active_cal_overlay

        def _work():
            status_proxy = _QtCalibrationStatusProxy(self.progress_label)

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
        overlay = self._active_cal_overlay

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

    def _show_sold_badge_step(self, overlay: _CalibrationOverlay | None = None) -> str:
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

        assert overlay is not None
        try:
            for i in range(5, 0, -1):
                overlay.config(text=f"Move mouse to TOP-LEFT corner of sold badge ({i})")
                time.sleep(1)
            pt1 = pyautogui.position()

            for i in range(5, 0, -1):
                overlay.config(text=f"Move mouse to BOTTOM-RIGHT corner of sold badge ({i})")
                time.sleep(1)
            pt2 = pyautogui.position()
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
        root = os.path.dirname(os.path.dirname(root))
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
