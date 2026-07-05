from __future__ import annotations

import builtins
import json
import os
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import calibrator
import settings
import sniper
import window_utils
from ui.log_bridge import _emit_log, _log_bridge
from ui.overlays.calibration import _CalibrationOverlay
from ui.overlays.ingame import _IngameOverlay


class SniperTab(QWidget):
    stats_updated = Signal(int, int, int, int, int)
    _sniper_done = Signal()
    _calib_mode_signal = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sniper_running = False
        self._stop_event = threading.Event()
        self._first_start = True
        self._calib_done_this_session = False
        self._elapsed = 0
        self._ingame_overlay = None
        self._calibration_in_progress = False
        self._calib_tab = None
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

        self._overlay_watcher = QTimer(self)
        self._overlay_watcher.setInterval(1000)
        self._overlay_watcher.timeout.connect(self._overlay_watcher_tick)
        self._overlay_watcher.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

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

        stats_row = QHBoxLayout()
        self.stats_label = QLabel("Buy attempts: 0 | Success: 0 | Fail: 0 | Refreshes: 0")
        self.stats_label.setStyleSheet("font-size: 11pt;")
        self.scans_label = QLabel(f"Scans left: {settings.get_scans()}")
        self.scans_label.setStyleSheet("font-size: 11pt;")
        stats_row.addWidget(self.stats_label)
        stats_row.addStretch()
        stats_row.addWidget(self.scans_label)
        root.addLayout(stats_row)

        log_box = QGroupBox("Status Log")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        log_layout.addWidget(self.log_view)
        root.addWidget(log_box)

        self._append_log("Ready...")

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
        total = settings.get_scans()
        if total == 0:
            self.scans_label.setText("Scans left: ∞")
        else:
            self.scans_label.setText(f"Scans left: {max(total - scans_done, 0)}")

    def _refresh_stats_display(self, attempts, successes, failures, refreshes):
        self.stats_label.setText(
            f"Buy attempts: {attempts} | Success: {successes}"
            f" | Fail: {failures} | Refreshes: {refreshes}"
        )
        _total = settings.get_scans()
        self.scans_label.setText("Scans left: ∞" if _total == 0 else f"Scans left: {_total}")

    def run_auto_from_overlay(self) -> None:
        self._set_calibration_mode(False)

        def _work():
            try:
                status_proxy = (
                    self._ingame_overlay._calib_status_proxy if self._ingame_overlay else None
                )

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
                success = result[0] if isinstance(result, tuple) else bool(result)
                if success:
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
        _root = os.path.dirname(os.path.abspath(__file__))
        _root = os.path.dirname(os.path.dirname(_root))
        tpl = os.path.join(_root, "assets", "auction_options_template_med.png")
        self._set_calibration_mode(False)
        self._active_cal_overlay = _CalibrationOverlay()
        self._active_cal_overlay.show_image(tpl)
        extra_y = self._ingame_overlay.height() if self._ingame_overlay else 0
        self._active_cal_overlay.reposition_for_ingame(extra_y=extra_y)
        cal_overlay = self._active_cal_overlay

        def _work():
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
        if self._calib_tab is None:
            _emit_log("❌ Calibration tab not ready")
            return
        _root = os.path.dirname(os.path.abspath(__file__))
        _root = os.path.dirname(os.path.dirname(_root))
        tpl = os.path.join(_root, "assets", "sold_badge_template_med.png")
        self._set_calibration_mode(False)
        self._active_cal_overlay = _CalibrationOverlay()
        self._active_cal_overlay.show_image(tpl)
        extra_y = self._ingame_overlay.height() if self._ingame_overlay else 0
        self._active_cal_overlay.reposition_for_ingame(extra_y=extra_y)
        cal_overlay = self._active_cal_overlay

        def _work():
            try:
                self._calib_tab._show_sold_badge_step(cal_overlay)
            finally:
                cal_overlay.destroy_later()
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
        scans = settings.get_scans() or 10_000_000
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
                should_close = True
                try:
                    last = getattr(self._ingame_overlay, "_last_interaction_time", 0)
                    if time.time() - last < 1.5:
                        should_close = False
                except Exception:
                    pass
                if should_close:
                    try:
                        self._ingame_overlay._user_closed = False
                    except Exception:
                        pass
                    self._ingame_overlay.close()
                    self._ingame_overlay = None
        except Exception:
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
            self._sniper_done.emit()

    def _on_sniper_done(self):
        self._sniper_running = False
        self._timer.stop()
        self._stop_event.clear()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

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
