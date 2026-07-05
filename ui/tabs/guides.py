from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import window_utils


class GuidesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    @staticmethod
    def _make_scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(20, 16, 20, 24)
        root.setSpacing(6)
        scroll.setWidget(container)
        return scroll, root

    @staticmethod
    def _add_section(root: QVBoxLayout, title: str) -> None:
        if root.count():
            root.addSpacing(10)
        lbl = QLabel(f"<b style='font-size:13pt;'>{title}</b>")
        root.addWidget(lbl)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame { color: #555; }")
        root.addWidget(sep)

    @staticmethod
    def _add_para(root: QVBoxLayout, text: str, color: str = "#ccc") -> None:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"font-size:10pt; color:{color}; padding-top:4px;")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(lbl)

    @staticmethod
    def _add_subhead(root: QVBoxLayout, text: str) -> None:
        lbl = QLabel(f"<b style='font-size:10pt; color:#aaddff;'>{text}</b>")
        lbl.setStyleSheet("padding-top:8px;")
        root.addWidget(lbl)

    @staticmethod
    def _add_image(root: QVBoxLayout, img_name: str, max_w: int = 620) -> None:
        img_path = window_utils.resource_path(f"assets/guide/{img_name}")
        if not os.path.isfile(img_path):
            return
        pix = QPixmap(img_path)
        if pix.isNull():
            return
        if pix.width() > max_w:
            pix = pix.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        lbl = QLabel()
        lbl.setPixmap(pix)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("margin-top: 6px; margin-bottom: 4px;")
        root.addWidget(lbl)

    @staticmethod
    def _add_step(
        root: QVBoxLayout,
        number: int,
        title: str,
        body: str,
        img_name: str | list[str] | None = None,
    ) -> None:
        root.addSpacing(12)
        heading = QLabel(f"<b style='font-size:12pt;'>Step {number} — {title}</b>")
        root.addWidget(heading)
        names = [] if img_name is None else ([img_name] if isinstance(img_name, str) else img_name)
        for name in names:
            img_path = window_utils.resource_path(f"assets/guide/{name}")
            if os.path.isfile(img_path):
                pix = QPixmap(img_path)
                if not pix.isNull():
                    max_w = 620
                    if pix.width() > max_w:
                        pix = pix.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
                    img_lbl = QLabel()
                    img_lbl.setPixmap(pix)
                    img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    img_lbl.setStyleSheet("margin-top: 6px; margin-bottom: 4px;")
                    root.addWidget(img_lbl)
        if body:
            body_lbl = QLabel(body)
            body_lbl.setWordWrap(True)
            body_lbl.setStyleSheet("font-size:10pt; color:#ccc; padding-top:4px;")
            root.addWidget(body_lbl)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        outer.addWidget(tabs)

        setup_page, setup_root = self._make_scroll_page()
        self._populate_setup_tab(setup_root)
        tabs.addTab(setup_page, "Set Up the Sniper")

        start_page, start_root = self._make_scroll_page()
        self._populate_starting_tab(start_root)
        tabs.addTab(start_page, "Starting the Sniper")

        ref_page, ref_root = self._make_scroll_page()
        self._populate_reference_tab(ref_root)
        tabs.addTab(ref_page, "General")

    def _populate_setup_tab(self, root: QVBoxLayout) -> None:
        self._add_section(root, "Row Tuner")
        self._add_para(
            root,
            "The sniper watches 4 row regions on screen for available cars and sold badges. "
            "You need to align these rows to match your game's auction listing.",
        )
        row_warn = QLabel(
            "⚠  Run the Row Tuner on first setup, and again whenever you change your "
            "game resolution or Windows display scaling — the row positions will shift "
            "and need to be realigned."
        )
        row_warn.setWordWrap(True)
        row_warn.setStyleSheet("font-size:10pt; color:#f44336; padding: 6px 0px 2px 0px;")
        root.addWidget(row_warn)

        self._add_step(
            root,
            1,
            "Open Row Tuner",
            "Go to the Calibration tab in FH6 Sniper and click Open Row Tuner.",
            "row_calibration.png",
        )
        self._add_step(
            root,
            2,
            "Check Default Row Positions",
            "Four coloured border rows will appear showing their default positions. "
            "If they already line up with the auction rows in the game you can skip "
            "adjustment and just close the Row Tuner.",
            "default_settings.png",
        )
        self._add_step(
            root,
            3,
            "Adjust Row 1 and Copy to All Rows",
            "Select Row 1 and adjust its size and position until it matches the first "
            "auction card in the game. Once Row 1 is correct, click Copy to all rows — "
            "this resizes all other rows to match. Then click each remaining row and "
            "move it into position.\n\n"
            "Tip: row buttons are tick boxes — you can tick more than one row at a time "
            "(click several, or press their number keys) so arrow keys and the "
            "move/resize buttons act on all ticked rows together. Handy once rows are "
            "roughly aligned and just need the same small nudge.",
            "adjust_rows.png",
        )
        self._add_step(
            root,
            4,
            "Save and Close",
            "When all rows are lined up with the auction cards, click Save all rows and "
            "close the Row Tuner.\n\n"
            "Note: row profiles are saved per resolution and display scaling. If you "
            "significantly change your resolution or Windows display scale you will get "
            "a new profile — that is why the Calibration tab shows a profile count.",
            ["adjusted_rows.png", "save_rows.png"],
        )

        self._add_section(root, "Detection Calibration")
        self._add_para(
            root,
            "The sniper needs to know where the Auction Options button and the Sold badge "
            "are on your screen. Run Auto Calibration first — fall back to Manual only if "
            "auto fails.",
        )
        self._add_para(
            root,
            "ℹ  If you've turned off FH6's 'Moving Backgrounds' accessibility setting, "
            "tick Moving Background OFF on the Settings tab first — the Auction Options "
            "button looks different without it and calibration won't find it otherwise.",
            color="#64b5f6",
        )
        warn_lbl = QLabel(
            "⚠  Re-run calibration every time you start Forza Horizon 6. "
            "If you always play in fullscreen the position should stay the same, but "
            "if you use windowed mode and resize or move the window the calibration "
            "will be off and needs to be redone."
        )
        warn_lbl.setWordWrap(True)
        warn_lbl.setStyleSheet("font-size:10pt; color:#f44336; padding: 6px 0px 2px 0px;")
        root.addWidget(warn_lbl)
        self._add_image(root, "detection_calibration.png")

        self._add_subhead(root, "Auto Calibration")

        self._add_step(
            root,
            1,
            "Search for Available Cars",
            "Use the auction filter to search for any available car — this is the fastest "
            "way to get cars with a Sold badge showing in the listing.",
            "auction_filter_sold.png",
        )
        self._add_step(
            root,
            2,
            "Wait for a Sold Car",
            "Once cars appear, wait until at least one row shows a car marked as Sold. "
            "The sold car can be on any of the 4 rows.",
            "list_with_sold_car.png",
        )
        self._add_step(
            root,
            3,
            "Run Auto Calibration",
            "Click Run Auto Calibration in the Calibration tab, or use the Auto Calibrate "
            "button in the in-game overlay (toggle it from the Sniper tab). You have "
            "5 seconds — make sure the FH6 window is fully visible so both the Auction "
            "Options button and the Sold badge are on screen. Let the calibrator finish.",
        )
        self._add_step(
            root,
            4,
            "Confirm Calibration Succeeded",
            "Check the calibration status in the app. You can test both the auction "
            "button and sold badge detection using the test buttons at the bottom of the "
            "Calibration tab — make sure the FH6 window is not covered by the sniper app "
            "when clicking them.",
            "auto_calibration_success.png",
        )

        self._add_subhead(root, "Manual Calibration")

        self._add_step(
            root,
            1,
            "Calibrate Manually",
            "If Auto Calibration fails, switch to the Manual Calibration tab. You need to "
            "calibrate the Auction Options button and the Sold badge separately. Follow "
            "the on-screen countdown — hover your mouse over the top-left corner of the "
            "button or badge, wait, then move to the bottom-right corner and wait again. "
            "Once done, test both detections using the buttons at the bottom of the "
            "Calibration tab the same way as described in the Auto Calibration steps above.",
            "manual_calibration.png",
        )

        root.addStretch()

    def _populate_starting_tab(self, root: QVBoxLayout) -> None:
        intro = QLabel(
            "Follow these steps to get to the right place in Forza Horizon 6 "
            "before starting the sniper."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size:10pt; color:#ccc;")
        root.addWidget(intro)

        self._add_step(
            root,
            1,
            "Navigate to the Auction House",
            "Open the Festival menu and go to the Buy & Sell tab, then select Auction House.",
            "auction_house.png",
        )
        self._add_step(
            root,
            2,
            "Open Search Auctions",
            "Click Search Auctions to open the full auction browser.",
            "search_auctions.png",
        )
        self._add_step(
            root,
            3,
            "Set Up Your Filters",
            "Use the auction filters to find the car you want. Make sure to set the maximum "
            "buyout price — the sniper will only attempt to buy cars at or below this price.",
            "auction_filter.png",
        )
        self._add_step(
            root,
            4,
            "Start the Sniper",
            "This is the screen you should be on when you click Start Sniper in the app. "
            "The sniper will continuously refresh the listing and automatically attempt to "
            "buy any available car it finds.",
            "start.png",
        )

        root.addStretch()

    def _populate_reference_tab(self, root: QVBoxLayout) -> None:
        def _section(title: str) -> None:
            self._add_section(root, title)

        def _para(text: str, color: str = "#ccc") -> None:
            self._add_para(root, text, color)

        def _subhead(text: str) -> None:
            self._add_subhead(root, text)

        _section("Requirements")
        _para(
            "• Windows 10 or 11\n"
            "• Forza Horizon 6 installed and running\n"
            '• The game must be set to English — the sniper reads the "Sold!" badge text '
            "using OCR, other languages will not be detected\n"
            "• Windowed or borderless windowed mode is recommended for calibration"
        )

        _section("Quick Start")
        _para(
            "1.  Launch FH6 and navigate to the Auction House.\n"
            "2.  In this app, open the Calibration tab.\n"
            "3.  Before running calibration, check that the row regions line up with the "
            "auction cards on screen. Open the Row Tuner (Step 1) and adjust the rows — "
            "they are likely out of alignment on first use or after a resolution change.\n"
            "4.  Run Auto Calibration (Step 2) — make sure at least one row shows a car "
            'with the yellow "Sold!" badge before clicking Run.\n'
            "5.  Go to Settings and pick Mid as your starting timing preset.\n"
            "6.  Return to the Sniper tab and hit Start."
        )

        _section("Calibration")

        _subhead("Row Calibration")
        _para(
            "The sniper watches 4 row regions for sold badges and available cars. "
            "At different resolutions or display-scaling levels the formula estimate may not "
            "line up perfectly with the actual cards.\n\n"
            "Open the Row Tuner, tick a row with the numbered buttons (or keys 1–4), "
            "then use the right panel to move the row up/down/left/right and the left panel "
            "to resize it until the coloured overlay box sits on the auction card. "
            "You can tick multiple rows at once to move or resize them together — handy "
            "once rows are roughly aligned and only need a shared nudge. "
            "Use Copy to all rows once the first row is correct, then fine-tune the rest. "
            "Hit Save — profiles are stored per resolution so rows stay correct after "
            "resolution changes."
        )

        _subhead("Auto Calibration (recommended)")
        _para(
            "Automatically finds the Auction Options button and picks the best sold-badge "
            "template for your screen.\n\n"
            "How to use:\n"
            "  1. Open the Auction House in FH6.\n"
            '  2. Wait until at least one row shows a car with the yellow "Sold!" badge.\n'
            "  3. Click Run Auto Calibration.\n\n"
            "If it fails, make sure the game is fully visible (not covered by other windows) "
            "and retry. Windowed mode works best."
        )

        _subhead("Manual Calibration")
        _para(
            "Use this if Auto Calibration cannot find the button, or if you have an unusual "
            "window layout.\n\n"
            "Both the auction button and sold badge use the same method: hover your mouse "
            "over the top-left corner when prompted, wait for the countdown, then move to "
            "the bottom-right corner and wait again. Just follow the on-screen countdown "
            "and hold still at each corner.\n\n"
            "Tip: the in-game overlay (toggle in the Sniper tab) has Calib Auction and "
            "Calib Badge buttons so you can calibrate without alt-tabbing."
        )

        _section("Settings")

        _subhead("Timing Presets")
        _para(
            "Timing controls how fast keystrokes are sent during buy attempts and "
            "auction resets.\n\n"
            "Mid  —  recommended starting point. Reliable detection for most setups.\n"
            "Fast  —  aggressive timing; may cause available cars to be missed at high "
            "speed. Only try this once Mid is working well and you want more speed.\n"
            "Slow  —  for slower PCs or laggy connections.\n\n"
            "If available cars are being missed, switch to Mid or Slow and re-run calibration."
        )

        _subhead("Number of Scans")
        _para(
            "How many auction listings the sniper will scan before stopping automatically. "
            "0 = Infinite. Set to 0 or leave at the default (1000) for a long session."
        )

        _subhead("Buyout Target")
        _para(
            "How many successful purchases to make before stopping automatically. "
            "0 = Infinite. Set a number if you only want to buy a fixed amount of cars."
        )

        _subhead("Moving Background OFF")
        _para(
            "Only relevant if you've turned off FH6's 'Moving Backgrounds' accessibility "
            "setting. With it off, the Auction Options button has a plain white background "
            "instead of the default animated one, which needs a different template to "
            "detect. Tick this box to match, then re-run Auto Calibration — it affects "
            "both Auto Calibration and the live sniper."
        )

        _section("Buyout Attempt Detection")
        _para(
            "After each buyout attempt the sniper waits and tries to detect whether the "
            "purchase succeeded or failed. This detection step has a short built-in delay "
            "to account for slower internet connections and laggy servers — the game needs "
            "a moment to confirm the transaction before the result can be read.\n\n"
            "If you are on a slower connection and buyouts are being logged as failed even "
            "when they succeed, try increasing the Post Buy Wait value in Settings."
        )

        _section("In-game Overlay")
        _para(
            "Toggle the overlay from the Sniper tab. It floats above the FH6 window and "
            "lets you start/stop the sniper, trigger calibration, and open the Row Tuner "
            "without alt-tabbing.\n\n"
            "The overlay auto-hides when FH6 loses focus and reappears when it's active "
            "again. Click Hide or uncheck the toggle to close it permanently."
        )

        _section("Tips & Troubleshooting")
        _para(
            "• Recalibrate after resizing, moving, or switching FH6 between windowed and "
            "fullscreen — the button position changes.\n"
            "• Only one calibration type (Auto or Manual) can be active at a time. "
            "Remove the current one before switching.\n"
            "• If the sniper stops detecting after a game update, re-run Auto Calibration.\n"
            "• If Auto Calibration can't find the Auction Options button but it's clearly "
            "visible, check whether you've disabled Moving Backgrounds in FH6 — tick "
            "Moving Background OFF in Settings and re-run calibration.\n"
            "• Config is saved at  %APPDATA%\\FH6Sniper\\config.json\n"
            "• Logs are shown in the Status Log panel on the Sniper tab."
        )

        root.addStretch()
