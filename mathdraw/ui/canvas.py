"""Graph canvas (webcam or transparent background) and the top-right equation panel."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..geometry import (fit_rect, format_tick, grid_steps, grid_values, math_to_px, norm_to_math, px_to_math,
                        reset_view, zoom)
from ..gestures import DISPLAY_NAMES, HAND_CONNECTIONS
from ..math_engine.analyzer import curve_polylines
from ..math_engine.smoothing import smooth_stroke
from .math_render import render_latex


def qcolor(hexstr, alpha=1.0):
    c = QColor(hexstr)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class EquationPanel(QWidget):
    """Anchored to the parent's top-right corner; shows the *persisted* result."""

    def __init__(self, state, parent):
        super().__init__(parent)
        self.state = state
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.rows = []  # list of ("img", QImage) | ("text", str, size, color, bold)
        self.fade = 1.0
        self.rebuild()

    # -- content ---------------------------------------------------------------
    def rebuild(self):
        d = self.state.d
        res = self.state.p.last_result
        rows = []
        pt = d.panel_font_pt
        txt, acc = d.panel_text, d.panel_accent
        dpr = max(1.0, self.devicePixelRatioF())
        dpi = int(100 * dpr)
        maxw = (d.panel_width - 2 * d.panel_padding) * dpr
        if not res:
            rows.append(("text", "Detected function", pt * 0.55, acc, True))
            hint = {"pinch": "Aim with your index finger; pinch thumb + index to draw.",
                    "key": f"Aim with your index finger; hold {self.state.g.pen_key} to draw.",
                    "toggle": f"Turn the pen on ({self.state.g.hotkey_toggle_pen}), then point to draw.",
                    }.get(self.state.g.draw_mode, "Point with your index finger to draw.")
            rows.append(("text", hint, pt * 0.45, txt, False))
            if self.state.analysis_running:
                rows.append(("text", "Analysing…", pt * 0.45, acc, False))
        else:
            title = "Detected function"
            if res.get("kind") in ("parametric",):
                title = "Detected parametric curve"
            elif res.get("kind") == "polar":
                title = "Detected polar curve"
            elif res.get("kind") == "implicit":
                title = "Detected implicit curve"
            rows.append(("text", title, pt * 0.55, acc, True))
            img = render_latex(res["latex"], pt, txt, dpi)
            if img is not None:
                if img.width() > maxw:
                    img = img.scaledToWidth(int(maxw), Qt.TransformationMode.SmoothTransformation)
                img.setDevicePixelRatio(dpr)
                rows.append(("img", img))
            badges = []
            if res.get("approximate"):
                badges.append("Approximation")
            if res.get("ambiguous"):
                badges.append("Uncertain, see alternatives")
            if badges:
                rows.append(("text", "  ·  ".join(badges), pt * 0.42, acc, True))
            rows.append(("text", f"Model: {res.get('model', '')}", pt * 0.47, txt, False))
            m = res.get("metrics", {})
            err = f"Fit error: RMSE {m.get('rmse', float('nan')):.4g}"
            if m.get("nrmse") is not None:
                err += f"  ({100 * m['nrmse']:.2f}% of range)"
            if m.get("r2") is not None:
                err += f",  R² {m['r2']:.4f}"
            rows.append(("text", err, pt * 0.42, txt, False))
            rows.append(("text", f"Confidence: {100 * res.get('confidence', 0):.0f}%", pt * 0.42, txt, False))
            if d.show_alternatives and (res.get("ambiguous") or res.get("approximate")) and res.get("alternatives"):
                rows.append(("text", "Alternatives:", pt * 0.42, acc, True))
                rm = (res.get("metrics") or {}).get("rmse") or 0
                bc = res.get("best_complexity")
                plausible = [a for a in res["alternatives"]
                             if (bc is None or a.get("complexity", 0) <= bc + 3)
                             and (not a.get("rmse") or not rm or a["rmse"] <= 1.6 * rm)]
                if not plausible:
                    rows.pop()  # drop the "Alternatives:" heading
                for a in plausible[:2]:
                    im = render_latex(a["latex"], pt * 0.55, txt, dpi)
                    if im is not None:
                        if im.width() > maxw:
                            im = im.scaledToWidth(int(maxw), Qt.TransformationMode.SmoothTransformation)
                        im.setDevicePixelRatio(dpr)
                        rows.append(("img", im))
            if d.show_calculus and res.get("calculus"):
                items = [i for i in res["calculus"].get("items", []) if i["label"] in ("Derivative", "Antiderivative")]
                for it in items:
                    im = render_latex(it["latex"], pt * 0.55, txt, dpi)
                    if im is not None:
                        if im.width() > maxw:
                            im = im.scaledToWidth(int(maxw), Qt.TransformationMode.SmoothTransformation)
                        im.setDevicePixelRatio(dpr)
                        rows.append(("img", im))
            if self.state.analysis_running:
                rows.append(("text", "Analysing new stroke… (equation kept until it succeeds)", pt * 0.4, acc, False))
        self.rows = rows
        self.reposition()
        self.update()

    def _text_height(self, size):
        return int(size * 1.9)

    def content_height(self):
        d = self.state.d
        h = 2 * d.panel_padding
        for r in self.rows:
            if r[0] == "img":
                h += r[1].height() / r[1].devicePixelRatio() + 6
            else:
                h += self._text_height(r[2])
        return int(h)

    def reposition(self):
        p = self.parentWidget()
        if p is None:
            return
        d = self.state.d
        w = min(d.panel_width, max(200, p.width() - 2 * d.panel_margin))
        h = min(self.content_height(), max(80, p.height() - 2 * d.panel_margin))
        self.setGeometry(p.width() - w - d.panel_margin, d.panel_margin, w, h)

    def set_hand_overlap(self, overlapping: bool):
        target = 0.35 if overlapping else 1.0
        if abs(target - self.fade) > 1e-3:
            self.fade = target
            self.update()

    # -- painting --------------------------------------------------------------
    def paintEvent(self, e):
        d = self.state.d
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.fade)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(qcolor(d.panel_text, 0.08), 1))
        p.setBrush(qcolor(d.panel_bg, d.panel_opacity))
        p.drawRoundedRect(r, 12, 12)
        # signature: the card's edge is a little y-axis, ruled like the graph it reads
        p.setPen(QPen(qcolor(d.panel_accent, 0.55), 1))
        rx = 8.5
        p.drawLine(QPointF(rx, 12), QPointF(rx, self.height() - 12))
        tick = 12
        while tick <= self.height() - 12:
            p.drawLine(QPointF(rx - 2, tick), QPointF(rx + 2, tick))
            tick += 16
        y = d.panel_padding
        x = d.panel_padding
        for row in self.rows:
            if row[0] == "img":
                img = row[1]
                h = img.height() / img.devicePixelRatio()
                p.drawImage(QPointF(x, y), img)
                y += h + 6
            else:
                _, text, size, color, bold = row
                f = QFont("Segoe UI")
                f.setPointSizeF(max(6.0, size))
                f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
                p.setFont(f)
                # thin outline for legibility at low panel opacity
                path = QPainterPath()
                th = self._text_height(size)
                path.addText(QPointF(x, y + th * 0.72), f, self._elide(text, f))
                if d.panel_opacity < 0.5:
                    p.strokePath(path, QPen(QColor(0, 0, 0, 200), 3))
                p.fillPath(path, QColor(color))
                y += th
            if y > self.height():
                break
        p.end()

    def _elide(self, text, font):
        from PySide6.QtGui import QFontMetrics

        fm = QFontMetrics(font)
        return fm.elidedText(text, Qt.TextElideMode.ElideRight, self.width() - 2 * self.state.d.panel_padding)


class GraphCanvas(QWidget):
    """Draws (optionally) the webcam frame, then grid / axes / strokes / fit.

    mode="webcam": camera frame as background (Mode A)
    mode="desktop": nothing painted except the graph layers (Mode B, transparent window)
    """

    def __init__(self, state, mode="webcam", parent=None):
        super().__init__(parent)
        self.state = state
        self.mode = mode
        self.frame: QImage | None = None
        self.landmarks = None
        self.tip_uv = None
        self.gesture_text = ""
        self.hold_progress = 0.0
        self._poly_cache = None
        self._poly_key = None
        self.panel = EquationPanel(state, self)
        self.setMouseTracking(True)
        self._drag = None
        self.export_mode = None  # None, or background colour string while rendering an export image
        self._smooth_cache = (None, None)
        self.setMinimumSize(320, 180)
        if mode == "desktop":
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAutoFillBackground(False)
        state.changed.connect(self._on_state)
        self._sync_panel_visibility()

    # -- state reactions ---------------------------------------------------------
    def _on_state(self, key):
        if key in ("result", "display", "view", "analysis"):
            self._poly_key = None
            self._smooth_cache = (None, None)
        if key in ("result", "display", "analysis_status"):
            self.panel.rebuild()
        if key in ("visibility", "display"):
            self._sync_panel_visibility()
        self.update()

    def _sync_panel_visibility(self):
        s = self.state
        self.panel.setVisible(s.p.overlay_visible and s.p.panel_visible and s.d.show_panel)
        self.panel.reposition()

    def set_frame(self, img: QImage):
        self.frame = img
        a = img.width() / max(img.height(), 1)
        if abs(a - self.state.view.aspect) > 1e-3:
            self.state.view.aspect = a
            self.state.touch("view")
        if self.mode == "webcam":
            self.update()

    def set_hand(self, lm, tip_uv, gesture_text, hold):
        self.landmarks = lm
        self.tip_uv = tip_uv
        self.gesture_text = gesture_text
        self.hold_progress = hold
        if tip_uv is not None and self.panel.isVisible():
            px, py = self._norm_to_px(*tip_uv)
            self.panel.set_hand_overlap(self.panel.geometry().adjusted(-30, -30, 30, 30).contains(int(px), int(py)))
        else:
            self.panel.set_hand_overlap(False)
        self.update()

    # -- geometry -------------------------------------------------------------
    def graph_rect(self):
        return fit_rect(self.width(), self.height(), self.state.view.aspect)

    def _norm_to_px(self, u, v):
        rx, ry, rw, rh = self.graph_rect()
        return rx + u * rw, ry + v * rh

    def resizeEvent(self, e):
        self.panel.reposition()
        super().resizeEvent(e)

    # -- interaction: wheel zoom, right-drag pan, double-click reset ------------
    def wheelEvent(self, e):
        """Wheel: zoom both axes.  Shift+wheel: x only.  Ctrl+wheel: y only."""
        v = self.state.view
        rect = self.graph_rect()
        about = px_to_math(e.position().x(), e.position().y(), v, rect)
        delta = e.angleDelta().y() or e.angleDelta().x()  # Shift+wheel arrives as horizontal on Windows
        if not delta:
            return
        f = 0.85 if delta > 0 else 1 / 0.85
        mods = e.modifiers()
        axis = "x" if mods & Qt.KeyboardModifier.ShiftModifier else "y" if mods & Qt.KeyboardModifier.ControlModifier else "both"
        zoom(v, f, about, axis)
        self.state.touch("view")

    def mousePressEvent(self, e):
        if e.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag = (e.position(), self.state.view.cx, self.state.view.cy)

    def mouseMoveEvent(self, e):
        if self._drag:
            p0, cx, cy = self._drag
            rx, ry, rw, rh = self.graph_rect()
            v = self.state.view
            v.cx = cx - (e.position().x() - p0.x()) / rw * 2 * v.half_w
            v.cy = cy + (e.position().y() - p0.y()) / rh * 2 * v.half_h
            self.state.touch("view")

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        reset_view(self.state.view)
        self.state.touch("view")

    # -- painting -------------------------------------------------------------
    def paintEvent(self, e):
        s = self.state
        d = s.d
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.graph_rect()
        rx, ry, rw, rh = rect
        R = QRectF(rx, ry, rw, rh)
        if self.export_mode:
            p.fillRect(self.rect(), QColor(self.export_mode))
        elif self.mode == "webcam":
            p.fillRect(self.rect(), QColor(15, 15, 16))
            if self.frame is not None:
                p.drawImage(R, self.frame)
            else:
                p.setPen(QColor(161, 161, 166))
                p.drawText(R, Qt.AlignmentFlag.AlignCenter, "Waiting for camera…")
        else:
            # Mode B: start fully transparent; only the optional tint is painted
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        graph_on = s.p.overlay_visible and s.p.graph_visible
        if graph_on:
            if d.background_opacity > 0:
                p.fillRect(R, qcolor(d.background_color, d.background_opacity * d.overall_opacity))
            p.save()
            p.setClipRect(R)
            p.setOpacity(d.overall_opacity)
            if d.show_grid:
                self._grid(p, rect, d)
            if d.show_axes:
                self._axes(p, rect, d)
            if d.show_drawing:
                self._strokes(p, rect, d)
            if d.show_fit:
                self._fit(p, rect, d)
            p.restore()
        elif self.mode == "desktop":
            pass  # hidden: window itself is hidden by the overlay window

        # current stroke is always shown while drawing, even if layers are hidden
        if s.current_stroke and not (graph_on and d.show_drawing):
            self._polyline(p, rect, self._display_stroke(s.current_stroke), qcolor(d.curve_color, 0.6), d.curve_width)

        if self.export_mode:
            p.end()
            return
        self._hand(p, rect, d)
        self._status(p)
        if self.mode == "desktop" and not d.click_through:
            p.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()

    def steps(self):
        d = self.state.d
        return grid_steps(self.state.view, d.grid_mode, d.grid_density, d.grid_step_x, d.grid_step_y,
                          d.grid_x_pi, d.grid_minor)

    def _grid(self, p, rect, d):
        v = self.state.view
        xmin, xmax, ymin, ymax = v.bounds()
        sx, sy, mx, my, _ = self.steps()
        for step_x, step_y, alpha in ((mx, my, d.grid_opacity * 0.4), (sx, sy, d.grid_opacity)):
            pen = QPen(qcolor(d.grid_color, alpha), 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            for x in grid_values(xmin, xmax, step_x):
                p.drawLine(QPointF(*math_to_px(x, ymin, v, rect)), QPointF(*math_to_px(x, ymax, v, rect)))
            for y in grid_values(ymin, ymax, step_y):
                p.drawLine(QPointF(*math_to_px(xmin, y, v, rect)), QPointF(*math_to_px(xmax, y, v, rect)))

    def _axes(self, p, rect, d):
        v = self.state.view
        xmin, xmax, ymin, ymax = v.bounds()
        col = qcolor(d.axes_color, d.axes_opacity)
        p.setPen(QPen(col, 1.6))
        if ymin <= 0 <= ymax:
            p.drawLine(QPointF(*math_to_px(xmin, 0, v, rect)), QPointF(*math_to_px(xmax, 0, v, rect)))
        if xmin <= 0 <= xmax:
            p.drawLine(QPointF(*math_to_px(0, ymin, v, rect)), QPointF(*math_to_px(0, ymax, v, rect)))
        if not d.show_tick_labels:
            return
        sx, sy, _, _, _ = self.steps()
        f = QFont("Segoe UI")
        f.setPointSizeF(d.tick_label_pt)
        p.setFont(f)
        fm = p.fontMetrics()
        # label every major line, skipping some if labels would overlap
        lab_x = sx * max(1, math.ceil((fm.horizontalAdvance("-00.00") + 8) / max(rect[2] * sx / (xmax - xmin), 1)))
        lab_y = sy * max(1, math.ceil((fm.height() + 4) / max(rect[3] * sy / (ymax - ymin), 1)))
        ax_y = min(max(0, ymin), ymax)
        ax_x = min(max(0, xmin), xmax)
        for x in grid_values(xmin, xmax, lab_x):
            if abs(x) > sx * 1e-6:
                px, py = math_to_px(x, ax_y, v, rect)
                p.drawLine(QPointF(px, py - 4), QPointF(px, py + 4))
                self._label(p, QPointF(px + 3, min(py + 15, rect[1] + rect[3] - 4)), format_tick(x, lab_x, d.grid_x_pi))
        for y in grid_values(ymin, ymax, lab_y):
            if abs(y) > sy * 1e-6:
                px, py = math_to_px(ax_x, y, v, rect)
                p.drawLine(QPointF(px - 4, py), QPointF(px + 4, py))
                self._label(p, QPointF(px + 6, py - 3), format_tick(y, lab_y))

    def _label(self, p, pt, text):
        """Tick label with a dark halo so it stays readable over the camera image."""
        path = QPainterPath()
        path.addText(pt, p.font(), text)
        p.save()
        p.strokePath(path, QPen(QColor(0, 0, 0, 150), 3))
        p.fillPath(path, p.pen().color())
        p.restore()

    def _polyline(self, p, rect, pts, color, width):
        if len(pts) < 2:
            return
        v = self.state.view
        path = QPainterPath()
        first = True
        for x, y in pts:
            px, py = math_to_px(x, y, v, rect)
            if first:
                path.moveTo(px, py)
                first = False
            else:
                path.lineTo(px, py)
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _display_stroke(self, pts):
        """Stroke as shown on screen: auto-smoothed when enabled (cached per stroke length)."""
        a = self.state.a
        if not a.smoothing_enabled or len(pts) < 6:
            return pts
        key = (id(pts), len(pts), a.smoothing_strength)
        if self._smooth_cache[0] != key:
            self._smooth_cache = (key, smooth_stroke(np.asarray(pts, float), a.smoothing_strength).tolist())
        return self._smooth_cache[1]

    def _strokes(self, p, rect, d):
        s = self.state
        replaced = s.a.clean_replace and s.p.last_result and d.show_fit
        if s.p.last_stroke and not replaced:
            pts = smooth_stroke(np.asarray(s.p.last_stroke), s.a.smoothing_strength).tolist() \
                if s.a.smoothing_enabled and len(s.p.last_stroke) > 5 else s.p.last_stroke
            self._polyline(p, rect, pts, qcolor(d.curve_color, d.drawing_opacity * (0.55 if s.current_stroke else 1)), d.curve_width)
        if s.current_stroke:
            self._polyline(p, rect, self._display_stroke(s.current_stroke), qcolor(d.curve_color, 1.0), d.curve_width + 1)

    def _fit(self, p, rect, d):
        res = self.state.p.last_result
        if not res:
            return
        bounds = self.state.view.bounds()
        key = (id(res), tuple(round(b, 9) for b in bounds))
        if key != self._poly_key:
            full = curve_polylines(res, bounds)
            inside = None
            dom = res.get("domain")
            if res.get("kind") in ("function", "inverse") and dom and d.fit_extension_opacity < 0.999:
                xmin, xmax, ymin, ymax = bounds
                if res["kind"] == "function":
                    b2 = (max(xmin, dom[0]), min(xmax, dom[1]), ymin, ymax)
                    ok = b2[0] < b2[1]
                else:
                    b2 = (xmin, xmax, max(ymin, dom[0]), min(ymax, dom[1]))
                    ok = b2[2] < b2[3]
                inside = curve_polylines(res, b2) if ok else []
            self._poly_cache = (full, inside)
            self._poly_key = key
        full, inside = self._poly_cache
        if inside is None:
            for line in full:
                self._polyline(p, rect, line.tolist(), qcolor(d.fit_color, d.fit_opacity), d.fit_width)
            return
        # beyond the drawn range: dimmer; across the drawn range: full strength
        for line in full:
            self._polyline(p, rect, line.tolist(), qcolor(d.fit_color, d.fit_opacity * d.fit_extension_opacity), d.fit_width)
        for line in inside:
            self._polyline(p, rect, line.tolist(), qcolor(d.fit_color, d.fit_opacity), d.fit_width + 0.5)

    def _hand(self, p, rect, d):
        lm = self.landmarks
        if lm is None:
            return
        pts = [QPointF(*self._norm_to_px(u, v)) for u, v, _ in lm]
        if d.show_landmarks and self.mode == "webcam":
            p.setPen(QPen(QColor(237, 237, 237, 110), 1.5))
            for a, b in HAND_CONNECTIONS:
                p.drawLine(pts[a], pts[b])
            p.setBrush(QColor(237, 237, 237, 170))
            p.setPen(Qt.PenStyle.NoPen)
            for q in pts:
                p.drawEllipse(q, 2.5, 2.5)
        tip = pts[8]
        drawing = self.state.drawing_active
        p.setPen(QPen(qcolor(d.fit_color, 1.0) if drawing else QColor(237, 237, 237, 220), 2))
        p.setBrush(qcolor(d.fit_color, 0.6) if drawing else Qt.BrushStyle.NoBrush)
        p.drawEllipse(tip, 9, 9)
        if self.hold_progress > 0:
            p.setPen(QPen(qcolor(d.fit_color, 1.0), 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(tip.x() - 18, tip.y() - 18, 36, 36), 90 * 16, int(-360 * 16 * self.hold_progress))

    def _status(self, p):
        s = self.state
        bits = ["Camera on" if s.webcam_available else "Camera off",
                "Hand found" if s.hand_detected else "No hand"]
        mode = s.g.draw_mode
        if s.drawing_active:
            bits.append("Drawing")
        elif mode == "toggle":
            bits.append("Pen on" if s.pen_armed else f"Pen off ({s.g.hotkey_toggle_pen})")
        elif mode == "pinch":
            bits.append("Pen up — pinch to draw")
        elif mode == "key":
            bits.append(f"Pen up — hold {s.g.pen_key} to draw")
        if self.gesture_text:
            bits.append(self.gesture_text)
        if not s.p.overlay_visible:
            bits.append(f"overlay hidden ({s.g.hotkey_toggle_overlay} / {DISPLAY_NAMES.get(s.g.show_gesture, s.g.show_gesture)} to show)")
        if s.analysis_message:
            bits.append(s.analysis_message)
        text = "  ·  ".join(bits)
        f = QFont("Segoe UI")
        f.setPointSizeF(9)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 16
        r = QRectF(8, self.height() - 32, w, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor(237, 237, 237))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
