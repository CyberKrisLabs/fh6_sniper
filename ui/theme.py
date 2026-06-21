"""Dark Forza-inspired theme for FH6 Sniper.

Apply with:  app.setStyleSheet(STYLESHEET)
"""

STYLESHEET = """
/* ── Base ───────────────────────────────────────────────────────────────── */

QWidget {
    background-color: #12121A;
    color: #E0E0E8;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */

QTabWidget::pane {
    border: 1px solid #2A2A3A;
    background-color: #12121A;
}

QTabBar::tab {
    background-color: #1C1C28;
    color: #888899;
    padding: 7px 18px;
    border: 1px solid #2A2A3A;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #12121A;
    color: #E0E0E8;
    border-bottom: 2px solid #FF6B1A;
}

QTabBar::tab:hover:!selected {
    background-color: #1E1E2C;
    color: #C0C0D0;
}

/* ── Group boxes ─────────────────────────────────────────────────────────── */

QGroupBox {
    border: 1px solid #2A2A3A;
    border-radius: 5px;
    margin-top: 10px;
    padding-top: 8px;
    font-size: 11px;
    color: #888899;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    color: #888899;
}

/* ── Labels (semantic classes) ──────────────────────────────────────────── */

QLabel[class="app-title"] {
    font-size: 18px;
    font-weight: bold;
    color: #FF6B1A;
    letter-spacing: 1px;
}

QLabel[class="app-subtitle"] {
    font-size: 10px;
    color: #888899;
    letter-spacing: 2px;
}

QLabel[class="section-label"] {
    font-size: 10px;
    font-weight: bold;
    color: #FF6B1A;
    letter-spacing: 2px;
}

QLabel[class="stat-title"] {
    font-size: 10px;
    color: #888899;
    letter-spacing: 1px;
}

QLabel[class="stat-value"] {
    font-size: 22px;
    font-weight: bold;
    color: #E0E0E8;
}

QLabel[class="small-label"] {
    font-size: 11px;
    color: #777788;
}

QLabel[class="status-label"] {
    font-size: 11px;
    color: #AAAACC;
    padding: 4px;
    background-color: #1C1C28;
    border-radius: 4px;
}

/* ── Frames ──────────────────────────────────────────────────────────────── */

QFrame[class="stat-card"] {
    background-color: #1C1C28;
    border: 1px solid #2A2A3A;
    border-radius: 6px;
    padding: 4px;
}

QFrame[class="separator"] {
    background-color: #2A2A3A;
    max-height: 1px;
    border: none;
}

/* ── Buttons ─────────────────────────────────────────────────────────────── */

QPushButton {
    background-color: #2A2A3A;
    color: #C0C0D0;
    border: 1px solid #3A3A4E;
    border-radius: 5px;
    padding: 6px 12px;
    font-size: 12px;
}

QPushButton:hover {
    background-color: #34344A;
    color: #E0E0F0;
}

QPushButton:pressed {
    background-color: #202030;
}

QPushButton:disabled {
    color: #444458;
    background-color: #1A1A26;
    border-color: #242434;
}

QPushButton[class="primary-btn"] {
    background-color: #FF6B1A;
    color: #FFFFFF;
    font-weight: bold;
    border: none;
}

QPushButton[class="primary-btn"]:hover {
    background-color: #FF7F35;
}

QPushButton[class="primary-btn"]:pressed {
    background-color: #E05510;
}

QPushButton[class="primary-btn"]:disabled {
    background-color: #5A2A10;
    color: #886655;
}

QPushButton[class="accent-btn"] {
    background-color: #1A6AFF;
    color: #FFFFFF;
    font-weight: bold;
    border: none;
}

QPushButton[class="accent-btn"]:hover {
    background-color: #357FFF;
}

QPushButton[class="accent-btn"]:pressed {
    background-color: #1055CC;
}

QPushButton[class="accent-btn"]:disabled {
    background-color: #1A2A5A;
    color: #445588;
}

QPushButton[class="danger-btn"] {
    background-color: #3A1A1A;
    color: #FF6666;
    border: 1px solid #5A2A2A;
    font-weight: bold;
}

QPushButton[class="danger-btn"]:hover {
    background-color: #4A2020;
}

/* ── Text edit (log area) ────────────────────────────────────────────────── */

QTextEdit {
    background-color: #0E0E18;
    color: #C8C8D8;
    border: 1px solid #2A2A3A;
    border-radius: 4px;
    font-family: Consolas, monospace;
    font-size: 11px;
}

/* ── Inputs ──────────────────────────────────────────────────────────────── */

QSpinBox, QDoubleSpinBox {
    background-color: #1C1C28;
    color: #E0E0E8;
    border: 1px solid #3A3A4E;
    border-radius: 4px;
    padding: 3px 6px;
}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #2A2A3A;
    border: none;
    width: 16px;
}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #888899;
}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #888899;
}

QComboBox {
    background-color: #1C1C28;
    color: #E0E0E8;
    border: 1px solid #3A3A4E;
    border-radius: 4px;
    padding: 3px 8px;
}

QComboBox::drop-down {
    background-color: #2A2A3A;
    border: none;
    border-left: 1px solid #3A3A4E;
    width: 22px;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}

QComboBox QAbstractItemView {
    background-color: #1C1C28;
    color: #E0E0E8;
    border: 1px solid #3A3A4E;
    selection-background-color: #FF6B1A;
    selection-color: #FFFFFF;
}

/* ── Checkboxes ──────────────────────────────────────────────────────────── */

QCheckBox {
    spacing: 7px;
    color: #C0C0D0;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #3A3A4E;
    border-radius: 3px;
    background-color: #1C1C28;
}

QCheckBox::indicator:checked {
    background-color: #FF6B1A;
    border-color: #FF6B1A;
}

QCheckBox::indicator:hover {
    border-color: #FF6B1A;
}

/* ── Progress bar ────────────────────────────────────────────────────────── */

QProgressBar {
    background-color: #1C1C28;
    border: 1px solid #2A2A3A;
    border-radius: 5px;
    text-align: center;
    color: #E0E0E8;
    font-size: 11px;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #FF6B1A;
    border-radius: 4px;
}

/* ── Dialogs ─────────────────────────────────────────────────────────────── */

QDialog {
    background-color: #16161F;
}

QMessageBox {
    background-color: #16161F;
}

QDialogButtonBox QPushButton {
    min-width: 80px;
}

/* ── Scrollbars ──────────────────────────────────────────────────────────── */

QScrollBar:vertical {
    background: #12121A;
    width: 8px;
    border: none;
}

QScrollBar::handle:vertical {
    background: #3A3A4E;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: #FF6B1A;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #12121A;
    height: 8px;
    border: none;
}

QScrollBar::handle:horizontal {
    background: #3A3A4E;
    border-radius: 4px;
}

/* ── Splitter ────────────────────────────────────────────────────────────── */

QSplitter::handle {
    background: #2A2A3A;
    width: 2px;
}

/* ── Tooltips ────────────────────────────────────────────────────────────── */

QToolTip {
    background-color: #1C1C28;
    color: #E0E0E8;
    border: 1px solid #3A3A4E;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
}
"""
