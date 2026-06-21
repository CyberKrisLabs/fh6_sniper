from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import settings

if TYPE_CHECKING:
    from ui.tabs.sniper import SniperTab

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

    def _show_buy_interval_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Buy Interval")
        dlg.setText("<b>Buy Interval</b>")
        dlg.setInformativeText(
            "The delay (in seconds) between each key press during the buy sequence.\n\n"
            "When the sniper spots an available car it presses a series of keys to open "
            "the buy dialog and confirm the purchase. This interval is the pause between "
            "each of those key presses.\n\n"
            "Lower = faster buy attempt, but too low and the game may not register inputs "
            "in time. Raise it if purchases are failing due to missed key presses."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_post_buy_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Post Buy Wait")
        dlg.setText("<b>Post Buy Wait</b>")
        dlg.setInformativeText(
            "How long (in seconds) the sniper waits after completing the buy sequence "
            "before checking whether the purchase succeeded.\n\n"
            "The game needs a moment to process the transaction and display the result. "
            "On slower connections or laggy servers this takes longer.\n\n"
            "If successful buys are being logged as failed, try increasing this value."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_reset_interval_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Reset Interval")
        dlg.setText("<b>Reset Interval</b>")
        dlg.setInformativeText(
            "The delay (in seconds) between each key press when the sniper resets the "
            "auction list to refresh it for the next scan cycle.\n\n"
            "After each pass through the auction rows the sniper navigates back to "
            "trigger a fresh list. This interval controls how fast those navigation "
            "key presses fire.\n\n"
            "Lower = faster refresh between scans. Raise it if the auction list is not "
            "loading correctly between cycles."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_scans_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Number of Scans")
        dlg.setText("<b>Number of Scans</b>")
        dlg.setInformativeText(
            "How many times the sniper scans the auction listing before stopping. "
            "Each scan checks all visible car rows and buys any that are available.\n\n"
            "0 = Infinite: keeps scanning until you stop it manually or "
            "the Buyout Target is reached.\n\n"
            "Default is 1000, which is plenty for most sessions."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_buyout_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Buyout Target")
        dlg.setText("<b>Buyout Target</b>")
        dlg.setInformativeText(
            "Limits how many cars the sniper will buy in one session.\n\n"
            "Once this many purchases succeed the sniper stops automatically — "
            "so if you only want 1 or 2 cars it won't keep buying.\n\n"
            "0 = Infinite: runs until you stop it manually or Number of Scans target is reached.\n"
            "Range: 0 (Infinite) – 100."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        root.addWidget(QLabel("<b style='font-size:14pt;'>Settings</b>"))

        columns_row = QHBoxLayout()
        columns_row.setSpacing(16)
        columns_row.setAlignment(Qt.AlignTop)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        preset_box = QGroupBox("Timing Preset")
        preset_box_layout = QHBoxLayout(preset_box)
        preset_box_layout.setContentsMargins(10, 8, 10, 8)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Custom", "Fast", "Mid", "Slow"])
        self.preset_combo.setFixedWidth(120)
        self.preset_combo.setToolTip(
            "Mid is recommended for most setups.\n"
            "Fast may miss cars on slower PCs or connections.\n"
            "Slow is for high-latency setups."
        )
        self.preset_combo.currentTextChanged.connect(self._on_preset_change)
        preset_box_layout.addWidget(self.preset_combo)
        preset_box_layout.addStretch()
        left_col.addWidget(preset_box)

        timing_box = QGroupBox("Timing Values")
        timing_layout = QVBoxLayout(timing_box)
        timing_layout.setSpacing(6)
        self.buy_interval_spin = self._make_float_row(
            timing_layout,
            "Buy Interval (s)",
            0.1,
            20.0,
            "Delay between keypresses during buy navigation.",
            self._show_buy_interval_info,
        )
        self.post_buy_spin = self._make_float_row(
            timing_layout,
            "Post Buy Wait (s)",
            0.1,
            20.0,
            "Wait time after a buy attempt for the game to respond.",
            self._show_post_buy_info,
        )
        self.reset_interval_spin = self._make_float_row(
            timing_layout,
            "Reset Interval (s)",
            0.1,
            20.0,
            "Delay between keypresses during auction list reset.",
            self._show_reset_interval_info,
        )
        for spin in (self.buy_interval_spin, self.post_buy_spin, self.reset_interval_spin):
            spin.valueChanged.connect(self._on_value_changed)
        left_col.addWidget(timing_box)
        left_col.addStretch()

        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        scan_box = QGroupBox("Scan Settings")
        scan_layout = QVBoxLayout(scan_box)
        scan_layout.setSpacing(6)
        sc_row = QHBoxLayout()
        sc_lbl = QLabel("Number of Scans")
        sc_lbl.setFixedWidth(160)
        self.scans_spin = QSpinBox()
        self.scans_spin.setRange(0, 1000000)
        self.scans_spin.setValue(1000)
        self.scans_spin.setFixedWidth(100)
        self.scans_spin.setSpecialValueText("Infinite")
        sc_info_btn = QPushButton("ⓘ")
        sc_info_btn.setFixedSize(22, 22)
        sc_info_btn.setFlat(True)
        sc_info_btn.setStyleSheet(
            "QPushButton { font-size: 13pt; color: #2196f3; border: none; padding: 0; }"
            "QPushButton:hover { color: #64b5f6; }"
        )
        sc_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_info_btn.clicked.connect(self._show_scans_info)
        sc_row.addWidget(sc_lbl)
        sc_row.addWidget(self.scans_spin)
        sc_row.addWidget(sc_info_btn)
        sc_row.addStretch()
        scan_layout.addLayout(sc_row)
        bt_row = QHBoxLayout()
        bt_lbl = QLabel("Buyout Target")
        bt_lbl.setFixedWidth(160)
        self.buyout_target_spin = QSpinBox()
        self.buyout_target_spin.setRange(0, 100)
        self.buyout_target_spin.setValue(0)
        self.buyout_target_spin.setFixedWidth(100)
        self.buyout_target_spin.setSpecialValueText("Infinite")
        bt_info_btn = QPushButton("ⓘ")
        bt_info_btn.setFixedSize(22, 22)
        bt_info_btn.setFlat(True)
        bt_info_btn.setStyleSheet(
            "QPushButton { font-size: 13pt; color: #2196f3; border: none; padding: 0; }"
            "QPushButton:hover { color: #64b5f6; }"
        )
        bt_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bt_info_btn.clicked.connect(self._show_buyout_info)
        bt_row.addWidget(bt_lbl)
        bt_row.addWidget(self.buyout_target_spin)
        bt_row.addWidget(bt_info_btn)
        bt_row.addStretch()
        scan_layout.addLayout(bt_row)
        self.scans_spin.valueChanged.connect(self._on_value_changed)
        self.buyout_target_spin.valueChanged.connect(self._on_value_changed)
        scan_layout.addStretch()
        right_col.addWidget(scan_box)
        right_col.addStretch()

        columns_row.addLayout(left_col)
        columns_row.addLayout(right_col)
        root.addLayout(columns_row)

        self.feedback_label = QLabel("")
        self.feedback_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.feedback_label)

        root.addStretch()

    @staticmethod
    def _make_float_row(
        parent_layout, label: str, mn: float, mx: float, tip: str, info_callback=None
    ):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(160)
        lbl.setToolTip(tip)
        spin = QDoubleSpinBox()
        spin.setRange(mn, mx)
        spin.setSingleStep(0.001)
        spin.setDecimals(3)
        spin.setFixedWidth(100)
        row.addWidget(lbl)
        row.addWidget(spin)
        if info_callback:
            btn = QPushButton("ⓘ")
            btn.setFixedSize(22, 22)
            btn.setFlat(True)
            btn.setStyleSheet(
                "QPushButton { font-size: 13pt; color: #2196f3; border: none; padding: 0; }"
                "QPushButton:hover { color: #64b5f6; }"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(info_callback)
            row.addWidget(btn)
        row.addStretch()
        parent_layout.addLayout(row)
        return spin

    @staticmethod
    def _make_int_row(parent_layout, label: str, mn: int, mx: int, tip: str):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(160)
        lbl.setToolTip(tip)
        spin = QSpinBox()
        spin.setRange(mn, mx)
        spin.setFixedWidth(100)
        row.addWidget(lbl)
        row.addWidget(spin)
        row.addStretch()
        parent_layout.addLayout(row)
        return spin

    @staticmethod
    def _make_combo_row(parent_layout, label: str, items: list[str], tip: str):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(160)
        lbl.setToolTip(tip)
        combo = QComboBox()
        combo.addItems(items)
        combo.setFixedWidth(120)
        row.addWidget(lbl)
        row.addWidget(combo)
        row.addStretch()
        parent_layout.addLayout(row)
        return combo

    def _load_values(self):
        self._applying_preset = True
        try:
            timings = settings.load_timings()
            self.scans_spin.setValue(settings.get_scans())
            buyout_val = settings.get_buyout_target()
            self.buyout_target_spin.setValue(0 if buyout_val is None else buyout_val)
            self.buy_interval_spin.setValue(timings.get("buy_attempt_interval", 0.6))
            self.post_buy_spin.setValue(timings.get("post_buy_wait", 5.0))
            self.reset_interval_spin.setValue(timings.get("reset_interval", 0.9))
        finally:
            self._applying_preset = False
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
        self._applying_preset = True
        try:
            self.buy_interval_spin.setValue(vals["buy_attempt_interval"])
            self.post_buy_spin.setValue(vals["post_buy_wait"])
            self.reset_interval_spin.setValue(vals["reset_interval"])
        finally:
            self._applying_preset = False
        self._save(message=f"✅ {name} preset applied and saved")

    def _on_value_changed(self):
        if not self._applying_preset:
            self._detect_preset()
            self._save()

    def _save(self, message=None):
        timings = {
            "buy_attempt_interval": self.buy_interval_spin.value(),
            "post_buy_wait": self.post_buy_spin.value(),
            "reset_interval": self.reset_interval_spin.value(),
        }
        raw = self.buyout_target_spin.value()
        buyout_target = None if raw == 0 else raw
        is_valid, error_msg, corrected = settings.save_timings_ui(
            timings,
            self.scans_spin.value(),
            buyout_target,
        )
        self._applying_preset = True
        try:
            self.scans_spin.setValue(corrected["scans"])
            self.buy_interval_spin.setValue(corrected["timings"]["buy_attempt_interval"])
            self.post_buy_spin.setValue(corrected["timings"]["post_buy_wait"])
            self.reset_interval_spin.setValue(corrected["timings"]["reset_interval"])
        finally:
            self._applying_preset = False
        self._sniper_tab.scans_label.setText(f"Scans left: {corrected['scans']}")
        if message:
            self.feedback_label.setText(message)
            self.feedback_label.setStyleSheet("color: #4caf50;")
        elif is_valid:
            self.feedback_label.setText("Settings saved")
            self.feedback_label.setStyleSheet("color: #4caf50;")
        else:
            self.feedback_label.setText(f"⚠️ {error_msg} (auto-corrected and saved)")
            self.feedback_label.setStyleSheet("color: #ff9800;")
        QTimer.singleShot(2000, lambda: self.feedback_label.setText(""))
