from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
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

# Preset values include the ~0.1s per keypress that PyAutoGUI's implicit
# PAUSE used to add before it was disabled (sniper.py sets PAUSE = 0) —
# the game needs that time to register inputs, so it now lives here
# explicitly instead of as hidden, untunable latency.
PRESETS = {
    "Faster": {
        # All values measured live as stable — the Enter presses register far
        # faster than the Escape screen transition, hence exit >> enter.
        "car_available_interval": 0.25,
        "nav_interval": 0.25,
        "confirm_buy_interval": 0.25,
        "post_buy_wait": 4.0,
        "exit_auction_interval": 0.65,
        "enter_auction_interval": 0.25,
        "load_cars_interval": 0.75,
    },
    "Fast": {
        "car_available_interval": 0.4,
        "nav_interval": 0.3,
        "confirm_buy_interval": 0.35,
        "post_buy_wait": 4.0,
        "exit_auction_interval": 0.725,
        "enter_auction_interval": 0.3,
        "load_cars_interval": 0.8,
    },
    "Mid": {
        "car_available_interval": 0.6,
        "nav_interval": 0.4,
        "confirm_buy_interval": 0.45,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.9,
        "enter_auction_interval": 0.4,
        "load_cars_interval": 0.9,
    },
    "Slow": {
        "car_available_interval": 0.8,
        "nav_interval": 0.7,
        "confirm_buy_interval": 0.75,
        "post_buy_wait": 6.0,
        "exit_auction_interval": 1.2,
        "enter_auction_interval": 0.7,
        "load_cars_interval": 1.2,
    },
}


class SettingsTab(QWidget):
    def __init__(self, sniper_tab: SniperTab, parent=None):
        super().__init__(parent)
        self._sniper_tab = sniper_tab
        # Back-reference so the overlay's own Hide button can untick our box
        sniper_tab._settings_tab = self
        self._applying_preset = False
        self._build_ui()
        self._load_values()

    def _show_car_available_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Car Available Interval")
        dlg.setText("<b>Car Available Interval</b>")
        dlg.setInformativeText(
            "The delay (in seconds) after pressing 'Y' to open the buy dialog, before "
            "the sniper continues with the rest of the buy sequence.\n\n"
            "The dialog needs a moment to render before it's safe to send more key "
            "presses. This is usually the slowest of the buy-related intervals, since "
            "it's waiting on a menu to actually appear rather than just navigating one "
            "that's already open.\n\n"
            "Lower = faster buy attempt, but too low and the dialog may not have "
            "appeared yet, causing failed purchases. Raise it if purchases are failing "
            "because the dialog wasn't ready."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_nav_interval_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Nav Interval")
        dlg.setText("<b>Nav Interval</b>")
        dlg.setInformativeText(
            "The delay (in seconds) used specifically for up/down key presses: moving "
            "down to a specific auction row before buying, and the single down-arrow "
            "press used to select the buy option in the dialog.\n\n"
            "Because these are simple directional presses within a menu that's already "
            "open, they can usually fire faster than Car Available Interval, which "
            "accounts for waiting on a menu to appear in the first place.\n\n"
            "Lower = faster row navigation. Raise it if the sniper lands on the wrong "
            "row or the down-arrow press in the dialog isn't registering."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_confirm_buy_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Confirm Buy Interval")
        dlg.setText("<b>Confirm Buy Interval</b>")
        dlg.setInformativeText(
            "The delay (in seconds) between the two Enter presses that finalize the "
            "purchase, once the buy dialog is already open and the row is selected.\n\n"
            "Usually set slightly higher than Nav Interval, since confirming a "
            "purchase is a bit more failure-sensitive than plain row navigation — but "
            "still faster than Car Available Interval, since the dialog is already "
            "fully loaded.\n\n"
            "Lower = faster purchase confirmation. Raise it if purchases are failing "
            "because a confirm press isn't registering."
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

    def _show_exit_auction_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Exit Auction Interval")
        dlg.setText("<b>Exit Auction Interval</b>")
        dlg.setInformativeText(
            "The delay (in seconds) after pressing Escape to back out of the "
            "auction screen, before the sniper starts re-opening the search: "
            "Escape → THIS wait → Enter → Enter Auction wait → Enter.\n\n"
            "Backing out of the auction screen takes longer than the Enter "
            "presses that follow, so it has its own interval — this is usually "
            "the one to raise if reset keystrokes are being dropped.\n\n"
            "Also used after a buy attempt, for the wait after the Esc that "
            "dismisses the buy-result screen.\n\n"
            "Floored at 0.5s — testing shows the game won't reliably register "
            "these key presses any faster than that, no matter how fast the PC is."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_enter_auction_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Enter Auction Interval")
        dlg.setText("<b>Enter Auction Interval</b>")
        dlg.setInformativeText(
            "The delay (in seconds) after the first Enter that re-opens the "
            "auction search: Escape → Exit Auction wait → Enter → THIS wait → "
            "Enter.\n\n"
            "Menu confirmations register faster than the Escape transition, so "
            "this can be tuned much lower than Exit Auction Interval — live "
            "testing found 0.25s stable, and a really fast PC may go lower "
            "(minimum 0.1s).\n\n"
            "See Load Cars Interval for the wait after the final Enter, while "
            "the list actually loads.\n\n"
            "If the second Enter stops registering, you've gone too low."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_load_cars_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Load Cars Interval")
        dlg.setText("<b>Load Cars Interval</b>")
        dlg.setInformativeText(
            "The delay (in seconds) after the final Enter of the reset sequence, "
            "while the auction list actually reloads before the next scan.\n\n"
            "If the sniper is scanning before the list has finished loading, raise "
            "this value. If your connection is fast and cars are being missed due "
            "to unnecessary waiting, you can try lowering it — just verify the "
            "auction list is still loading reliably before committing to a lower "
            "value."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_buy_result_retry_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Buy Result Retry")
        dlg.setText("<b>Buy Result Retry</b>")
        dlg.setInformativeText(
            "After a buy attempt, the sniper screenshots the screen to check "
            "whether the purchase succeeded or failed. If the result screen "
            "hasn't rendered yet, it waits this long (in seconds) and re-checks, "
            "up to 3 times.\n\n"
            "Not part of the timing presets — it depends on how late FH6 renders "
            "the result screen, not on scan speed.\n\n"
            "If you see '⚠️ Buy result undetermined' in the log, raise this value."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_scans_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Number of Scans")
        dlg.setText("<b>Number of Scans</b>")
        dlg.setInformativeText(
            "How many times the sniper scans the auction listing before stopping. "
            "Each scan checks all visible car rows and buys at most one car — the "
            "last available row, where there's less competition from other snipers.\n\n"
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

    def _show_buy_last_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Buy Last Available Row")
        dlg.setText("<b>Buy Last Available Row</b>")
        dlg.setInformativeText(
            "Controls which available car the sniper buys when several rows "
            "are available.\n\n"
            "ON (default): buys the LAST available row. Most sniping bots "
            "always target row 1, so the last row usually has the least "
            "competition — you're probably not racing anyone for it.\n\n"
            "OFF: buys the FIRST available row. The attempt is ever so "
            "slightly faster (rows below the first available are never "
            "checked, and there are fewer arrow-down presses to reach the "
            "target), but you'll be competing against the inferior bots that "
            "don't have row detection and always hammer the top row.\n\n"
            "Takes effect the next time the sniper starts."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_overlay_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Show In-game Overlay")
        dlg.setText("<b>Show In-game Overlay</b>")
        dlg.setInformativeText(
            "Shows a small always-on-top HUD over the FH6 window with live "
            "stats (buy attempts, successes, failures, refreshes), start/stop "
            "buttons, and calibration shortcuts — so you can control the "
            "sniper without alt-tabbing.\n\n"
            "The overlay only appears while the FH6 window is focused, and "
            "hides automatically when you switch away.\n\n"
            "The Hide button on the overlay itself also unticks this setting."
        )
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    def _show_moving_bg_info(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Moving Background OFF")
        dlg.setText("<b>Moving Background OFF</b>")
        dlg.setInformativeText(
            "Tick this if you've turned off FH6's 'Moving Backgrounds' accessibility "
            "setting.\n\n"
            "With Moving Backgrounds off, the Auction Options button has a plain white "
            "background instead of the default animated one, so the sniper needs a "
            "different template to detect it.\n\n"
            "This affects both the live sniper and Auto Calibration — re-run Auto "
            "Calibration after changing this.\n\n"
            "The switch from black to white background can make detection less "
            "reliable if Load Cars Interval is set too low — the sniper may scan "
            "before the background has finished changing. If you enable this, try "
            "raising Load Cars Interval a bit.\n\n"
            "That said, if the animated background is what's slowing your PC down, "
            "turning it off (and accepting a slightly higher Load Cars Interval) can "
            "still be the better overall option."
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
        self.preset_combo.addItems(["Custom", "Faster", "Fast", "Mid", "Slow"])
        self.preset_combo.setFixedWidth(120)
        self.preset_combo.setToolTip(
            "Mid is recommended for most setups.\n"
            "Fast may miss cars on slower PCs or connections.\n"
            "Faster is the most aggressive — high-end PC and very fast connection only.\n"
            "Slow is for high-latency setups."
        )
        self.preset_combo.currentTextChanged.connect(self._on_preset_change)
        preset_box_layout.addWidget(self.preset_combo)
        preset_box_layout.addStretch()
        left_col.addWidget(preset_box)

        timing_box = QGroupBox("Timing Values")
        timing_layout = QVBoxLayout(timing_box)
        timing_layout.setSpacing(6)
        self.car_available_spin = self._make_float_row(
            timing_layout,
            "Car Available (s)",
            0.1,
            20.0,
            "Delay after pressing Y, waiting for the buy dialog to render.",
            self._show_car_available_info,
        )
        self.nav_interval_spin = self._make_float_row(
            timing_layout,
            "Nav Interval (s)",
            0.1,
            20.0,
            "Delay between up/down key presses (row navigation, buy dialog down-arrow).",
            self._show_nav_interval_info,
        )
        self.confirm_buy_spin = self._make_float_row(
            timing_layout,
            "Confirm Buy (s)",
            0.1,
            20.0,
            "Delay between the two Enter presses that confirm the purchase.",
            self._show_confirm_buy_info,
        )
        self.post_buy_spin = self._make_float_row(
            timing_layout,
            "Post Buy Wait (s)",
            0.1,
            20.0,
            "Wait time after a buy attempt for the game to respond.",
            self._show_post_buy_info,
        )
        self.exit_auction_spin = self._make_float_row(
            timing_layout,
            "Exit Auction (s)",
            0.5,
            20.0,
            "Delay after Escape backs out of the auction screen. Can't go below 0.5s.",
            self._show_exit_auction_info,
        )
        self.enter_auction_spin = self._make_float_row(
            timing_layout,
            "Enter Auction (s)",
            0.1,
            20.0,
            "Delay after the first Enter that re-opens the auction search.",
            self._show_enter_auction_info,
        )
        self.load_cars_spin = self._make_float_row(
            timing_layout,
            "Load Cars (s)",
            0.1,
            20.0,
            "Delay after the final Enter of the reset sequence, while the auction list reloads.",
            self._show_load_cars_info,
        )
        self.buy_result_retry_spin = self._make_float_row(
            timing_layout,
            "Buy Result Retry (s)",
            0.1,
            20.0,
            "Wait between re-checks when the buy success/fail screen hasn't appeared yet.",
            self._show_buy_result_retry_info,
        )
        for spin in (
            self.car_available_spin,
            self.nav_interval_spin,
            self.confirm_buy_spin,
            self.post_buy_spin,
            self.exit_auction_spin,
            self.enter_auction_spin,
            self.load_cars_spin,
            self.buy_result_retry_spin,
        ):
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
        bl_row = QHBoxLayout()
        self.buy_last_cb = QCheckBox("Buy last available row")
        self.buy_last_cb.setChecked(True)
        bl_info_btn = QPushButton("ⓘ")
        bl_info_btn.setFixedSize(22, 22)
        bl_info_btn.setFlat(True)
        bl_info_btn.setStyleSheet(
            "QPushButton { font-size: 13pt; color: #2196f3; border: none; padding: 0; }"
            "QPushButton:hover { color: #64b5f6; }"
        )
        bl_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bl_info_btn.clicked.connect(self._show_buy_last_info)
        bl_row.addWidget(self.buy_last_cb)
        bl_row.addWidget(bl_info_btn)
        bl_row.addStretch()
        scan_layout.addLayout(bl_row)
        self.buy_last_cb.toggled.connect(self._on_buy_last_toggled)
        self.scans_spin.valueChanged.connect(self._on_value_changed)
        self.buyout_target_spin.valueChanged.connect(self._on_value_changed)
        scan_layout.addStretch()
        right_col.addWidget(scan_box)

        bg_box = QGroupBox("Auction Screen")
        bg_layout = QVBoxLayout(bg_box)
        bg_layout.setSpacing(6)
        bg_row = QHBoxLayout()
        self.moving_bg_off_cb = QCheckBox("Moving Background OFF")
        bg_info_btn = QPushButton("ⓘ")
        bg_info_btn.setFixedSize(22, 22)
        bg_info_btn.setFlat(True)
        bg_info_btn.setStyleSheet(
            "QPushButton { font-size: 13pt; color: #2196f3; border: none; padding: 0; }"
            "QPushButton:hover { color: #64b5f6; }"
        )
        bg_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bg_info_btn.clicked.connect(self._show_moving_bg_info)
        bg_row.addWidget(self.moving_bg_off_cb)
        bg_row.addWidget(bg_info_btn)
        bg_row.addStretch()
        bg_layout.addLayout(bg_row)
        self.moving_bg_off_cb.toggled.connect(self._on_moving_bg_toggled)
        right_col.addWidget(bg_box)

        ui_box = QGroupBox("Interface")
        ui_layout = QVBoxLayout(ui_box)
        ui_layout.setSpacing(6)
        ov_row = QHBoxLayout()
        self.overlay_cb = QCheckBox("Show In-game Overlay")
        self.overlay_cb.setChecked(False)
        ov_info_btn = QPushButton("ⓘ")
        ov_info_btn.setFixedSize(22, 22)
        ov_info_btn.setFlat(True)
        ov_info_btn.setStyleSheet(
            "QPushButton { font-size: 13pt; color: #2196f3; border: none; padding: 0; }"
            "QPushButton:hover { color: #64b5f6; }"
        )
        ov_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ov_info_btn.clicked.connect(self._show_overlay_info)
        ov_row.addWidget(self.overlay_cb)
        ov_row.addWidget(ov_info_btn)
        ov_row.addStretch()
        ui_layout.addLayout(ov_row)
        self.overlay_cb.toggled.connect(self._on_overlay_toggled)
        right_col.addWidget(ui_box)
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

    def _load_values(self):
        self._applying_preset = True
        try:
            timings = settings.load_timings()
            self.scans_spin.setValue(settings.get_scans())
            buyout_val = settings.get_buyout_target()
            self.buyout_target_spin.setValue(0 if buyout_val is None else buyout_val)
            defaults = settings.DEFAULT_TIMINGS
            for key, spin in (
                ("car_available_interval", self.car_available_spin),
                ("nav_interval", self.nav_interval_spin),
                ("confirm_buy_interval", self.confirm_buy_spin),
                ("post_buy_wait", self.post_buy_spin),
                ("exit_auction_interval", self.exit_auction_spin),
                ("enter_auction_interval", self.enter_auction_spin),
                ("load_cars_interval", self.load_cars_spin),
                ("buy_result_retry_wait", self.buy_result_retry_spin),
            ):
                spin.setValue(timings.get(key, defaults[key]))
            self.moving_bg_off_cb.setChecked(settings.get_moving_background_off())
            self.buy_last_cb.setChecked(settings.get_buy_last_available())
            self.overlay_cb.setChecked(settings.get_show_ingame_overlay())
        finally:
            self._applying_preset = False
        self._detect_preset()

    def _on_moving_bg_toggled(self, checked: bool) -> None:
        if self._applying_preset:
            return
        settings.set_moving_background_off(checked)
        self.feedback_label.setText("Settings saved")
        self.feedback_label.setStyleSheet("color: #4caf50;")
        QTimer.singleShot(2000, lambda: self.feedback_label.setText(""))

    def _on_buy_last_toggled(self, checked: bool) -> None:
        if self._applying_preset:
            return
        settings.set_buy_last_available(checked)
        self.feedback_label.setText("Settings saved")
        self.feedback_label.setStyleSheet("color: #4caf50;")
        QTimer.singleShot(2000, lambda: self.feedback_label.setText(""))

    def _on_overlay_toggled(self, checked: bool) -> None:
        if self._applying_preset:
            return
        settings.set_show_ingame_overlay(checked)
        self._sniper_tab.set_overlay_enabled(checked)
        self.feedback_label.setText("Settings saved")
        self.feedback_label.setStyleSheet("color: #4caf50;")
        QTimer.singleShot(2000, lambda: self.feedback_label.setText(""))

    def sync_overlay_checkbox(self, checked: bool) -> None:
        """Reflect an overlay state change made elsewhere (e.g. its Hide button)."""
        self._applying_preset = True
        try:
            self.overlay_cb.setChecked(checked)
        finally:
            self._applying_preset = False

    def _detect_preset(self):
        current = {
            "car_available_interval": self.car_available_spin.value(),
            "nav_interval": self.nav_interval_spin.value(),
            "confirm_buy_interval": self.confirm_buy_spin.value(),
            "post_buy_wait": self.post_buy_spin.value(),
            "exit_auction_interval": self.exit_auction_spin.value(),
            "enter_auction_interval": self.enter_auction_spin.value(),
            "load_cars_interval": self.load_cars_spin.value(),
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
            self.car_available_spin.setValue(vals["car_available_interval"])
            self.nav_interval_spin.setValue(vals["nav_interval"])
            self.confirm_buy_spin.setValue(vals["confirm_buy_interval"])
            self.post_buy_spin.setValue(vals["post_buy_wait"])
            self.exit_auction_spin.setValue(vals["exit_auction_interval"])
            self.enter_auction_spin.setValue(vals["enter_auction_interval"])
            self.load_cars_spin.setValue(vals["load_cars_interval"])
        finally:
            self._applying_preset = False
        self._save(message=f"✅ {name} preset applied and saved")

    def _on_value_changed(self):
        if not self._applying_preset:
            self._detect_preset()
            self._save()

    def _save(self, message=None):
        timings = {
            "car_available_interval": self.car_available_spin.value(),
            "nav_interval": self.nav_interval_spin.value(),
            "confirm_buy_interval": self.confirm_buy_spin.value(),
            "post_buy_wait": self.post_buy_spin.value(),
            "exit_auction_interval": self.exit_auction_spin.value(),
            "enter_auction_interval": self.enter_auction_spin.value(),
            "load_cars_interval": self.load_cars_spin.value(),
            "buy_result_retry_wait": self.buy_result_retry_spin.value(),
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
            self.car_available_spin.setValue(corrected["timings"]["car_available_interval"])
            self.nav_interval_spin.setValue(corrected["timings"]["nav_interval"])
            self.confirm_buy_spin.setValue(corrected["timings"]["confirm_buy_interval"])
            self.post_buy_spin.setValue(corrected["timings"]["post_buy_wait"])
            self.exit_auction_spin.setValue(corrected["timings"]["exit_auction_interval"])
            self.enter_auction_spin.setValue(corrected["timings"]["enter_auction_interval"])
            self.load_cars_spin.setValue(corrected["timings"]["load_cars_interval"])
            self.buy_result_retry_spin.setValue(corrected["timings"]["buy_result_retry_wait"])
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
