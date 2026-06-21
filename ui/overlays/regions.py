from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class _AuctionRegionOverlay(QWidget):
    """Frameless transparent always-on-top overlay showing the auction button region.

    Draws a red rectangle with a countdown so the user can verify the
    detection box is placed over the Auction Options button.
    """

    def __init__(self, region: tuple[int, int, int, int], duration_ms: int = 5000):
        super().__init__(
            None,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        rx, ry, rw, rh = region
        dpr = QApplication.primaryScreen().devicePixelRatio()
        lx = int(rx / dpr)
        ly = int(ry / dpr)
        lw = int(rw / dpr)
        lh = int(rh / dpr)

        TEXT_H = 48
        MARGIN = 8
        _label_text = "Auction Options button should be inside the red box  (9s)"
        from PySide6.QtGui import QFontMetrics

        _fm = QFontMetrics(QApplication.font())
        _text_min_w = _fm.horizontalAdvance(_label_text) + MARGIN * 4
        ow = max(lw + MARGIN * 2, _text_min_w)
        box_x = (ow - lw) // 2
        self.setGeometry(
            lx - (ow - lw) // 2 - MARGIN, ly - TEXT_H - MARGIN, ow, lh + TEXT_H + MARGIN * 2
        )
        self._box = (box_x, TEXT_H + MARGIN, lw, lh)
        self._ow = ow
        self._th = TEXT_H
        self._seconds = max(1, duration_ms // 1000)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()
        QTimer.singleShot(duration_ms, self.close)
        self.show()

    def _tick(self):
        self._seconds = max(0, self._seconds - 1)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bx, by, bw, bh = self._box
        p.setPen(QPen(QColor(255, 60, 60), 3))
        p.setBrush(QColor(255, 60, 60, 25))
        p.drawRect(bx, by, bw, bh)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 200))
        p.drawRoundedRect(4, 4, self._ow - 8, self._th - 8, 6, 6)
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            4,
            4,
            self._ow - 8,
            self._th - 8,
            Qt.AlignmentFlag.AlignCenter,
            f"Auction Options button should be inside the red box  ({self._seconds}s)",
        )


class _BadgeRegionOverlay(QWidget):
    """Full-screen transparent overlay that draws the sold-badge scan regions.

    Shows the badge detection box for each row so the user can confirm it is
    correctly aligned over the Sold! badge on visible car cards.
    Dismissed by clicking anywhere or after *duration_ms* milliseconds.
    """

    _COLOURS = [
        QColor(255, 220, 0),
        QColor(80, 200, 255),
        QColor(180, 255, 80),
        QColor(255, 130, 50),
    ]

    def __init__(
        self,
        badge_rects: list[tuple[int, int, int, int]],
        row_rects: list[tuple[int, int, int, int]],
        duration_ms: int = 4000,
    ):
        super().__init__(
            None,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        dpr = QApplication.primaryScreen().devicePixelRatio()

        def _log(r):
            x, y, w, h = r
            return (int(x / dpr), int(y / dpr), int(w / dpr), int(h / dpr))

        self._badge_rects = [_log(r) for r in badge_rects]
        self._row_rects = [_log(r) for r in row_rects]
        self._seconds = max(1, duration_ms // 1000)

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()
        QTimer.singleShot(duration_ms, self.close)
        self.show()

    def _tick(self):
        self._seconds = max(0, self._seconds - 1)
        self.update()

    def mousePressEvent(self, _event):
        self.close()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        for i, (rx, ry, rw, rh) in enumerate(self._row_rects):
            col = self._COLOURS[i % len(self._COLOURS)]
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 80), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rx, ry, rw, rh)

        for i, (bx, by, bw, bh) in enumerate(self._badge_rects):
            col = self._COLOURS[i % len(self._COLOURS)]
            p.setPen(QPen(col, 3))
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 45))
            p.drawRect(bx, by, bw, bh)
            p.setPen(col)
            p.drawText(bx + 4, by - 4, f"Row {i + 1}")

        sw = self.width()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 195))
        p.drawRoundedRect(sw // 2 - 310, 20, 620, 42, 8, 8)
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            sw // 2 - 310,
            20,
            620,
            42,
            Qt.AlignmentFlag.AlignCenter,
            f"Sold badge scan regions (coloured boxes) — click to dismiss  ({self._seconds}s)",
        )
