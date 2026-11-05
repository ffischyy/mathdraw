"""Mode B: a floating, transparent desktop overlay window.

Uses Qt per-pixel transparency (WA_TranslucentBackground + frameless). The
window is painted with alpha 0 except for graph layers, the optional tint and
the equation panel, so the desktop genuinely shows through.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizeGrip, QVBoxLayout, QWidget

from .. import platform_win
from .canvas import GraphCanvas


class _Grip(QWidget):
    """Small drag handle (top-left) so a borderless window can be moved."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setFixedSize(84, 22)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._off = None
        self.setToolTip("Drag to move the overlay")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0, 120))
        p.setPen(QColor(255, 255, 255, 120))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Move")

    def mousePressEvent(self, e):
        self._off = e.globalPosition().toPoint() - self.win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._off is not None:
            self.win.move(e.globalPosition().toPoint() - self._off)

    def mouseReleaseEvent(self, e):
        self._off = None
        self.win.save_geometry()


class DesktopOverlay(QWidget):
    def __init__(self, state):
        super().__init__(None)
        self.state = state
        self.setWindowTitle("MathDraw overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.canvas = GraphCanvas(state, mode="desktop", parent=self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.grip = _Grip(self)
        self.sizegrip = QSizeGrip(self)
        self.sizegrip.setFixedSize(18, 18)
        self.click_mech = "none"
        self.capture_excluded = False
        self.apply_flags()
        g = state.d.overlay_geometry
        self.setGeometry(QRect(*[int(v) for v in g]))
        state.changed.connect(self._on_state)

    def apply_flags(self):
        d = self.state.d
        vis = self.isVisible()
        flags = Qt.WindowType.Tool
        if d.borderless:
            flags |= Qt.WindowType.FramelessWindowHint
        if d.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if vis:
            self.show()
        self._apply_native()

    def _apply_native(self):
        d = self.state.d
        if not self.isVisible():
            return
        self.click_mech = platform_win.set_click_through(self, d.click_through)
        self.capture_excluded = platform_win.set_exclude_from_capture(self, d.exclude_from_capture)
        self.grip.setVisible(not d.click_through)
        self.sizegrip.setVisible(not d.click_through)

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_native()

    def resizeEvent(self, e):
        self.grip.move(6, 6)
        self.sizegrip.move(self.width() - 18, self.height() - 18)
        super().resizeEvent(e)

    def moveEvent(self, e):
        super().moveEvent(e)

    def save_geometry(self):
        g = self.geometry()
        self.state.d.overlay_geometry = [g.x(), g.y(), g.width(), g.height()]
        self.state.touch("geometry")

    def mouseReleaseEvent(self, e):
        self.save_geometry()

    def sync_visibility(self):
        s = self.state
        want = s.d.mode == "desktop" and s.p.overlay_visible
        if want and not self.isVisible():
            self.show()
            self.raise_()
        elif not want and self.isVisible():
            self.save_geometry()
            self.hide()

    def _on_state(self, key):
        if key in ("visibility", "display"):
            self.sync_visibility()
