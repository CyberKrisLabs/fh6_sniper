from __future__ import annotations

import threading
import webbrowser

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

try:
    import requests  # type: ignore

    HAVE_REQUESTS = True
except Exception:
    requests = None  # type: ignore[assignment]
    HAVE_REQUESTS = False

__version__ = "1.3.1"


class InfoTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        root.addWidget(QLabel("<b style='font-size:14pt;'>FH6 Sniper</b>"))
        root.addWidget(QLabel(f"Version {__version__}"))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        gh_row = QHBoxLayout()
        gh_row.addWidget(QLabel("View the project on GitHub"))
        gh_btn = QPushButton("Open")
        gh_btn.setFixedWidth(80)
        gh_btn.clicked.connect(
            lambda: webbrowser.open("https://github.com/CyberKrisLabs/fh6_sniper")
        )
        gh_row.addWidget(gh_btn)
        gh_row.addStretch()
        root.addLayout(gh_row)

        pp_row = QHBoxLayout()
        pp_row.addWidget(QLabel("Support the project via PayPal"))
        pp_btn = QPushButton("Donate")
        pp_btn.setFixedWidth(80)
        pp_btn.clicked.connect(
            lambda: webbrowser.open("https://www.paypal.com/ncp/payment/W2FY4KHD58UEG")
        )
        pp_row.addWidget(pp_btn)
        pp_row.addStretch()
        root.addLayout(pp_row)

        upd_row = QHBoxLayout()
        self.update_btn = QPushButton("Check for Updates")
        self.update_btn.setFixedWidth(160)
        self.update_btn.clicked.connect(self._check_updates)
        upd_row.addWidget(self.update_btn)
        upd_row.addStretch()
        root.addLayout(upd_row)

        self.update_label = QLabel("")
        root.addWidget(self.update_label)

        root.addStretch()
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _check_updates(self):
        self.update_btn.setEnabled(False)
        self.update_label.setText("Checking…")

        def _work():
            if not HAVE_REQUESTS:
                self.update_label.setText("⚠️ 'requests' not installed — cannot check for updates")
                self.update_btn.setEnabled(True)
                return
            try:
                resp = requests.get(
                    "https://api.github.com/repos/CyberKrisLabs/fh6_sniper/releases/latest",
                    timeout=4,
                )
                if resp.ok:
                    tag = resp.json().get("tag_name", "")
                    latest = tag.lstrip("vV")
                    try:
                        newer = tuple(int(x) for x in latest.split(".")) > tuple(
                            int(x) for x in __version__.split(".")
                        )
                    except Exception:
                        newer = latest != __version__
                    if newer:
                        self.update_label.setText(f"🔄 Update available: {tag}")
                    else:
                        self.update_label.setText("✅ You are up to date")
                else:
                    self.update_label.setText("⚠️ Update check failed")
            except Exception:
                self.update_label.setText("⚠️ Update check failed (network error)")
            self.update_btn.setEnabled(True)

        threading.Thread(target=_work, daemon=True).start()
