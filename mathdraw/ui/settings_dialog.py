"""Settings: display/overlay (live), analysis (live), gestures (staged + test mode), shortcuts."""
from __future__ import annotations

import copy
import time

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QProgressBar, QPushButton, QSlider, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from ..gestures import BUILTIN, DISPLAY_NAMES, HAND_CONNECTIONS, GestureController, best_gesture, learn_custom
from ..branding import APP_NAME
from ..math_engine.grammar import FAMILIES


def _slider(val, lo, hi, cb, scale=100):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(int(lo * scale), int(hi * scale))
    s.setValue(int(val * scale))
    lab = QLabel(f"{val:.2f}")
    lab.setMinimumWidth(40)

    def ch(v):
        lab.setText(f"{v / scale:.2f}")
        cb(v / scale)

    s.valueChanged.connect(ch)
    h.addWidget(s, 1)
    h.addWidget(lab)
    return w


class ColorButton(QPushButton):
    def __init__(self, color, cb):
        super().__init__()
        self.color = color
        self.cb = cb
        self.setFixedWidth(90)
        self._paint()
        self.clicked.connect(self._pick)

    def _paint(self):
        c = QColor(self.color)
        fg = "#000" if c.lightness() > 128 else "#fff"
        self.setText(self.color)
        self.setStyleSheet(f"background:{self.color}; color:{fg}; border:1px solid rgba(237,237,237,0.16); border-radius:8px; padding:4px")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Choose colour")
        if c.isValid():
            self.color = c.name()
            self._paint()
            self.cb(self.color)


class LandmarkPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.lm = None
        self.setMinimumSize(260, 220)

    def set(self, lm):
        self.lm = lm
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(25, 25, 27))
        if self.lm is None:
            p.setPen(QColor(161, 161, 166))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No hand detected")
            return
        pts = np.asarray(self.lm)[:, :2]
        mn, mx = pts.min(0), pts.max(0)
        span = max(mx - mn) or 1e-6
        sc = 0.8 * min(self.width(), self.height()) / span
        c = (mn + mx) / 2
        P = [QPointF(self.width() / 2 + (x - c[0]) * sc, self.height() / 2 + (y - c[1]) * sc) for x, y in pts]
        p.setPen(QPen(QColor(237, 237, 237, 170), 1.5))
        for a, b in HAND_CONNECTIONS:
            p.drawLine(P[a], P[b])
        p.setPen(Qt.PenStyle.NoPen)
        for i, q in enumerate(P):
            p.setBrush(QColor("#e8c547") if i in (4, 8, 12, 16, 20) else QColor(237, 237, 237))
            p.drawEllipse(q, 4, 4)


class SettingsDialog(QDialog):
    reanalyse_requested = Signal()
    hotkeys_changed = Signal()
    fit_requested = Signal()
    camera_restart_requested = Signal()

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle(f"{APP_NAME} settings")
        self.resize(760, 680)
        self.tabs = tabs = QTabWidget()
        tabs.addTab(self._drawing_tab(), "Drawing")
        tabs.addTab(self._graph_tab(), "Graph")
        tabs.addTab(self._display_tab(), "Display")
        tabs.addTab(self._overlay_tab(), "Overlay && camera")
        tabs.addTab(self._analysis_tab(), "Analysis")
        tabs.addTab(self._gesture_tab(), "Gestures")
        tabs.addTab(self._shortcut_tab(), "Shortcuts")
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        row = QHBoxLayout()
        reset = QPushButton("Reset all settings to defaults…")
        reset.clicked.connect(self._reset_defaults)
        row.addWidget(reset)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        state.changed.connect(self._on_state)

    def select_tab(self, name):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).lower().startswith(name.lower()):
                self.tabs.setCurrentIndex(i)
                return

    def _reset_defaults(self):
        if QMessageBox.question(self, "Reset settings",
                                "Reset display, drawing, graph, analysis and gesture settings to their defaults?\n"
                                "Your drawing, equation and licence are kept.") != QMessageBox.StandardButton.Yes:
            return
        from ..geometry import reset_view
        from ..state import AnalysisSettings, DisplaySettings, GestureSettings

        p = self.state.p
        geo = p.display.overlay_geometry
        p.display, p.analysis, p.gestures = DisplaySettings(), AnalysisSettings(), GestureSettings()
        p.display.overlay_geometry = geo
        reset_view(self.state.view)
        for k in ("display", "analysis", "gestures", "view", "visibility"):
            self.state.touch(k)
        self.hotkeys_changed.emit()
        self.close()

    # ---- Drawing (smoothing) ------------------------------------------------------
    def _drawing_tab(self):
        a = self.state.a
        w = QWidget()
        f = QFormLayout(w)
        intro = QLabel("Auto-smoothing removes the shake from hand-drawn lines. Your stroke is cleaned up while you draw, "
                       "and after analysis it is replaced by the clean mathematical function it represents.")
        intro.setWordWrap(True)
        f.addRow(intro)
        f.addRow(self._check(a, "smoothing_enabled", "Auto-smoothing on", "analysis"))
        f.addRow("Smoothing strength", _slider(a.smoothing_strength, 0.05, 1, self._set(a, "smoothing_strength", "analysis")))
        hint = QLabel("Low keeps small details; high irons out strong shake (the cursor also becomes steadier, with a little more lag).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a1a1a6")
        f.addRow(hint)
        f.addRow(self._check(a, "clean_replace", "After analysis, replace my drawing with the clean function", "analysis"))
        d = self.state.d
        f.addRow("Function beyond the drawn range (opacity)",
                 _slider(d.fit_extension_opacity, 0, 1, self._set(d, "fit_extension_opacity")))
        b = QPushButton("Re-analyse last stroke with these settings")
        b.clicked.connect(self.reanalyse_requested.emit)
        f.addRow(b)
        return w

    # ---- Graph (grid + window) -----------------------------------------------------
    def _graph_tab(self):
        d = self.state.d
        w = QWidget()
        v = QVBoxLayout(w)
        grid = QGroupBox("Grid size")
        g = QFormLayout(grid)
        self.g_mode = QComboBox()
        self.g_mode.addItem("Automatic (adapts to zoom)", "auto")
        self.g_mode.addItem("Fixed spacing", "custom")
        self.g_mode.setCurrentIndex(0 if d.grid_mode == "auto" else 1)
        g.addRow("Spacing", self.g_mode)
        self.g_density = QComboBox()
        for k, lab in (("fine", "Fine"), ("normal", "Normal"), ("coarse", "Coarse")):
            self.g_density.addItem(lab, k)
        self.g_density.setCurrentIndex(max(0, self.g_density.findData(d.grid_density)))
        g.addRow("Automatic density", self.g_density)
        self.g_sx, self.g_sy = QDoubleSpinBox(), QDoubleSpinBox()
        for sb, val in ((self.g_sx, d.grid_step_x), (self.g_sy, d.grid_step_y)):
            sb.setDecimals(4)
            sb.setRange(0.0001, 100000)
            sb.setValue(val)
            sb.setStepType(QDoubleSpinBox.StepType.AdaptiveDecimalStepType)
        g.addRow("Fixed x spacing", self.g_sx)
        g.addRow("Fixed y spacing", self.g_sy)
        self.g_pi = QCheckBox("x axis in multiples of π (e.g. spacing 0.5 = π/2)")
        self.g_pi.setChecked(d.grid_x_pi)
        g.addRow(self.g_pi)
        self.g_minor = QComboBox()
        for n, lab in ((0, "None"), (2, "2 per cell"), (4, "4 per cell"), (5, "5 per cell"), (10, "10 per cell")):
            self.g_minor.addItem(lab, n)
        self.g_minor.setCurrentIndex(max(0, self.g_minor.findData(d.grid_minor)))
        g.addRow("Minor grid lines", self.g_minor)
        g.addRow(self._check(d, "show_tick_labels", "Show axis numbers"))
        ls = QDoubleSpinBox()
        ls.setRange(6, 24)
        ls.setValue(d.tick_label_pt)
        ls.valueChanged.connect(self._set(d, "tick_label_pt"))
        g.addRow("Axis number size (pt)", ls)
        self.g_note = QLabel()
        self.g_note.setStyleSheet("color:#e0703a")
        g.addRow(self.g_note)
        for wdg, sig in ((self.g_mode, "currentIndexChanged"), (self.g_density, "currentIndexChanged"),
                         (self.g_sx, "valueChanged"), (self.g_sy, "valueChanged"), (self.g_pi, "toggled"),
                         (self.g_minor, "currentIndexChanged")):
            getattr(wdg, sig).connect(self._grid_changed)
        v.addWidget(grid)

        win = QGroupBox("Graph window (visible range)")
        f = QFormLayout(win)
        self.w_spins = {}
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        for key, row in (("xmin", row1), ("xmax", row1), ("ymin", row2), ("ymax", row2)):
            sb = QDoubleSpinBox()
            sb.setDecimals(4)
            sb.setRange(-1e6, 1e6)
            sb.setStepType(QDoubleSpinBox.StepType.AdaptiveDecimalStepType)
            self.w_spins[key] = sb
            row.addWidget(QLabel(key))
            row.addWidget(sb, 1)
        f.addRow(row1)
        f.addRow(row2)
        btns = QHBoxLayout()
        for text, cb in (("Apply window", self._apply_window), ("Zoom to drawing", self.fit_requested.emit),
                         ("Equal axes 1:1", self._equal_axes), ("Reset view", self._reset_view)):
            b = QPushButton(text)
            b.clicked.connect(cb)
            btns.addWidget(b)
        f.addRow(btns)
        tip = QLabel("Mouse: wheel zooms (Shift = x only, Ctrl = y only), right-drag pans, double-click resets. "
                     "Keyboard: Ctrl + / Ctrl − / Ctrl 0.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #a1a1a6")
        f.addRow(tip)
        v.addWidget(win)
        v.addStretch(1)
        self._refresh_window_fields()
        self._grid_note()
        return w

    def _grid_changed(self, *_):
        d = self.state.d
        d.grid_mode = self.g_mode.currentData()
        d.grid_density = self.g_density.currentData()
        d.grid_step_x = self.g_sx.value()
        d.grid_step_y = self.g_sy.value()
        d.grid_x_pi = self.g_pi.isChecked()
        d.grid_minor = self.g_minor.currentData()
        self.g_density.setEnabled(d.grid_mode == "auto")
        self.g_sx.setEnabled(d.grid_mode == "custom")
        self.g_sy.setEnabled(d.grid_mode == "custom")
        self.state.touch("display")

    def _grid_note(self):
        from ..geometry import grid_steps

        d = self.state.d
        self.g_density.setEnabled(d.grid_mode == "auto")
        self.g_sx.setEnabled(d.grid_mode == "custom")
        self.g_sy.setEnabled(d.grid_mode == "custom")
        *_, coarsened = grid_steps(self.state.view, d.grid_mode, d.grid_density, d.grid_step_x, d.grid_step_y,
                                   d.grid_x_pi, d.grid_minor)
        self.g_note.setText("At this zoom the fixed spacing would draw too many lines, so it is temporarily widened. "
                            "Zoom in to see it." if coarsened else "")

    def _sync_graph_widgets(self):
        d = self.state.d
        pairs = ((self.g_mode, self.g_mode.findData(d.grid_mode)), (self.g_density, self.g_density.findData(d.grid_density)),
                 (self.g_minor, self.g_minor.findData(d.grid_minor)))
        for wdg, idx in pairs:
            if idx >= 0 and wdg.currentIndex() != idx:
                wdg.blockSignals(True)
                wdg.setCurrentIndex(idx)
                wdg.blockSignals(False)
        for wdg, val in ((self.g_sx, d.grid_step_x), (self.g_sy, d.grid_step_y)):
            if not wdg.hasFocus() and abs(wdg.value() - val) > 1e-12:
                wdg.blockSignals(True)
                wdg.setValue(val)
                wdg.blockSignals(False)
        if self.g_pi.isChecked() != d.grid_x_pi:
            self.g_pi.blockSignals(True)
            self.g_pi.setChecked(d.grid_x_pi)
            self.g_pi.blockSignals(False)

    def _refresh_window_fields(self):
        if any(sb.hasFocus() for sb in self.w_spins.values()):
            return
        xmin, xmax, ymin, ymax = self.state.view.bounds()
        for k, val in (("xmin", xmin), ("xmax", xmax), ("ymin", ymin), ("ymax", ymax)):
            sb = self.w_spins[k]
            sb.blockSignals(True)
            sb.setValue(val)
            sb.blockSignals(False)

    def _apply_window(self):
        from ..geometry import set_window

        v = {k: sb.value() for k, sb in self.w_spins.items()}
        try:
            set_window(self.state.view, v["xmin"], v["xmax"], v["ymin"], v["ymax"])
        except ValueError:
            QMessageBox.warning(self, "Invalid window", "Each maximum must be larger than its minimum.")
            return
        self.state.touch("view")

    def _equal_axes(self):
        from ..geometry import equal_axes

        equal_axes(self.state.view)
        self.state.touch("view")

    def _reset_view(self):
        from ..geometry import reset_view

        reset_view(self.state.view)
        self.state.touch("view")

    def _on_state(self, key):
        if key == "view":
            self._refresh_window_fields()
            self._grid_note()
        elif key == "display":
            self._sync_graph_widgets()
            self._grid_note()

    # ---- helpers ----------------------------------------------------------------
    def _set(self, obj, attr, key="display"):
        def f(v):
            setattr(obj, attr, v)
            self.state.touch(key)
        return f

    def _check(self, obj, attr, text, key="display"):
        c = QCheckBox(text)
        c.setChecked(bool(getattr(obj, attr)))
        c.toggled.connect(self._set(obj, attr, key))
        return c

    # ---- Display ---------------------------------------------------------------
    def _display_tab(self):
        d = self.state.d
        w = QWidget()
        v = QVBoxLayout(w)
        mode = QComboBox()
        mode.addItem("Mode A — Webcam mathematical overlay", "webcam")
        mode.addItem("Mode B — Transparent desktop overlay", "desktop")
        mode.setCurrentIndex(0 if d.mode == "webcam" else 1)
        mode.currentIndexChanged.connect(lambda i: self._set(d, "mode")(mode.itemData(i)))
        v.addWidget(mode)

        op = QGroupBox("Opacity (graph layers blend; equation panel stays legible)")
        f = QFormLayout(op)
        for attr, label in (("overall_opacity", "Overall graph opacity"), ("grid_opacity", "Grid"),
                            ("axes_opacity", "Axes"), ("drawing_opacity", "Original drawing"),
                            ("fit_opacity", "Fitted function"), ("background_opacity", "Background tint"),
                            ("panel_opacity", "Equation panel background")):
            f.addRow(label, _slider(getattr(d, attr), 0, 1, self._set(d, attr)))
        v.addWidget(op)

        col = QGroupBox("Colours")
        f2 = QFormLayout(col)
        for attr, label in (("curve_color", "Drawing"), ("fit_color", "Fitted curve"), ("axes_color", "Axes"),
                            ("grid_color", "Grid"), ("background_color", "Background tint"),
                            ("panel_bg", "Panel background"), ("panel_text", "Panel text"), ("panel_accent", "Panel accent")):
            f2.addRow(label, ColorButton(getattr(d, attr), self._set(d, attr)))
        v.addWidget(col)

        pan = QGroupBox("Equation panel (top-right)")
        f3 = QFormLayout(pan)
        for attr, label, lo, hi in (("panel_font_pt", "Font size (pt)", 10, 60), ("panel_width", "Width (px)", 220, 1400),
                                    ("panel_padding", "Padding (px)", 4, 60), ("panel_margin", "Margin (px)", 0, 80)):
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setValue(getattr(d, attr))
            sb.valueChanged.connect(self._set(d, attr))
            f3.addRow(label, sb)
        v.addWidget(pan)

        lay = QGroupBox("Visible layers")
        h = QHBoxLayout(lay)
        for attr, t in (("show_grid", "Grid"), ("show_axes", "Axes"), ("show_drawing", "Drawing"),
                        ("show_fit", "Fitted function"), ("show_panel", "Equation panel"),
                        ("show_calculus", "Calculus in panel"), ("show_alternatives", "Alternatives"),
                        ("show_landmarks", "Hand skeleton")):
            h.addWidget(self._check(d, attr, t))
        v.addWidget(lay)
        v.addStretch(1)
        return w

    # ---- Overlay window ------------------------------------------------------------
    def _overlay_tab(self):
        d = self.state.d
        w = QWidget()
        f = QFormLayout(w)
        f.addRow(self._check(d, "always_on_top", "Always on top"))
        f.addRow(self._check(d, "borderless", "Borderless"))
        f.addRow(self._check(d, "click_through", "Click-through (mouse passes to windows below)"))
        f.addRow(self._check(d, "exclude_from_capture", "Exclude overlay from screen capture (prevents feedback loops)"))
        f.addRow(self._check(d, "mirror_camera", "Mirror camera (selfie view) — takes effect when the camera restarts"))
        cam = QComboBox()
        names = []
        try:
            from PySide6.QtMultimedia import QMediaDevices

            names = [c.description() for c in QMediaDevices.videoInputs()]
        except Exception:
            pass
        for i in range(max(len(names), d.camera_index + 1, 3)):
            cam.addItem(f"{i}: {names[i]}" if i < len(names) else f"Camera {i}", i)
        cam.setCurrentIndex(d.camera_index)
        cam.currentIndexChanged.connect(lambda i: self._set(d, "camera_index")(cam.itemData(i)))
        f.addRow("Camera", cam)
        rb = QPushButton("Restart camera now")
        rb.clicked.connect(self.camera_restart_requested.emit)
        f.addRow(rb)
        geo = d.overlay_geometry
        spins = []
        for i, lab in enumerate(("X", "Y", "Width", "Height")):
            sb = QSpinBox()
            sb.setRange(-10000 if i < 2 else 200, 10000)
            sb.setValue(int(geo[i]))
            spins.append(sb)
            f.addRow(f"Overlay {lab}", sb)

        def apply_geo():
            d.overlay_geometry = [s.value() for s in spins]
            self.state.touch("overlay_geometry")

        b = QPushButton("Apply position / size")
        b.clicked.connect(apply_geo)
        f.addRow(b)
        note = QLabel("Tip: with click-through on, use the click-through hotkey (Shortcuts tab) to regain mouse control.")
        note.setWordWrap(True)
        f.addRow(note)
        return w

    # ---- Analysis ----------------------------------------------------------------
    def _analysis_tab(self):
        a = self.state.a
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Simpler ⟵ equations ⟶ more complex",
                 _slider(1 - a.simplicity, 0, 1, lambda v: self._set(a, "simplicity", "analysis")(1 - v)))
        tb = QDoubleSpinBox()
        tb.setRange(0.5, 60)
        tb.setSingleStep(0.5)
        tb.setValue(a.time_budget_s)
        tb.setSuffix(" s")
        tb.valueChanged.connect(self._set(a, "time_budget_s", "analysis"))
        f.addRow("Analysis time budget", tb)
        mc = QSpinBox()
        mc.setRange(2, 14)
        mc.setValue(a.max_complexity)
        mc.valueChanged.connect(self._set(a, "max_complexity", "analysis"))
        f.addRow("Max expression complexity", mc)
        mp = QSpinBox()
        mp.setRange(8, 400)
        mp.setValue(a.min_points)
        mp.valueChanged.connect(self._set(a, "min_points", "analysis"))
        f.addRow("Minimum stroke points", mp)
        f.addRow(self._check(a, "live_update",
                             "Automatic updates: replace the equation live while drawing (off = keep previous until new analysis succeeds)",
                             "analysis"))
        fam = QGroupBox("Function families searched")
        g = QVBoxLayout(fam)
        row = None
        for i, name in enumerate(FAMILIES):
            if i % 4 == 0:
                row = QHBoxLayout()
                g.addLayout(row)
            c = QCheckBox(name.replace("_", " "))
            c.setChecked(a.families.get(name, True))
            c.toggled.connect(lambda v, n=name: (a.families.__setitem__(n, v), self.state.touch("analysis")))
            row.addWidget(c)
        f.addRow(fam)
        b = QPushButton("Re-analyse last stroke with these settings")
        b.clicked.connect(self.reanalyse_requested.emit)
        f.addRow(b)
        return w

    # ---- Gestures (staged) ------------------------------------------------------------
    def _gesture_names(self):
        return ["none"] + [k for k in BUILTIN] + list(self.pending.custom.keys())

    def _gesture_tab(self):
        self.pending = copy.deepcopy(self.state.g)
        self.test_ctrl = GestureController(self.pending, test_mode=True)
        w = QWidget()
        outer = QHBoxLayout(w)
        left = QVBoxLayout()
        right = QVBoxLayout()
        outer.addLayout(left, 1)
        outer.addLayout(right, 1)

        form = QFormLayout()
        self.draw_mode_cb = QComboBox()
        for key, label in (("pinch", "Pinch to draw (thumb touches index finger)"),
                           ("key", "Hold a key to draw"),
                           ("toggle", "Pen on/off switch + draw gesture"),
                           ("gesture", "Always draw with the draw gesture")):
            self.draw_mode_cb.addItem(label, key)
        self.draw_mode_cb.setCurrentIndex(max(0, self.draw_mode_cb.findData(self.pending.draw_mode)))
        self.draw_mode_cb.currentIndexChanged.connect(lambda _i: self._pending_set("draw_mode", self.draw_mode_cb.currentData()))
        form.addRow("Drawing trigger", self.draw_mode_cb)
        self.pen_key_edit = QKeySequenceEdit(QKeySequence(self.pending.pen_key))
        self.pen_key_edit.setMaximumSequenceLength(1)
        self.pen_key_edit.editingFinished.connect(lambda: self._pending_set("pen_key", self.pen_key_edit.keySequence().toString() or "Space"))
        form.addRow("Hold-to-draw key", self.pen_key_edit)
        self.combos = {}
        for attr, label in (("draw_gesture", "Draw gesture (switch / always modes)"), ("hide_gesture", "Hide overlay"), ("show_gesture", "Show overlay"),
                            ("panel_toggle_gesture", "Hide/show equation panel only"), ("clear_gesture", "Clear drawing + equation"),
                            ("pen_toggle_gesture", "Pen on/off (switch mode)")):
            cb = QComboBox()
            self.combos[attr] = cb
            cb.currentIndexChanged.connect(lambda _i, a=attr, c=cb: self._pending_set(a, c.currentData()))
            form.addRow(label, cb)
        self._fill_combos()
        form.addRow("Confidence threshold", _slider(self.pending.confidence, 0.3, 0.99, lambda v: self._pending_set("confidence", v)))
        form.addRow("Hold duration (s)", _slider(self.pending.hold_s, 0.1, 3.0, lambda v: self._pending_set("hold_s", v)))
        form.addRow("Cooldown (s)", _slider(self.pending.cooldown_s, 0.0, 5.0, lambda v: self._pending_set("cooldown_s", v)))
        form.addRow("Stroke end delay (s)", _slider(self.pending.stroke_end_s, 0.1, 1.5, lambda v: self._pending_set("stroke_end_s", v)))
        left.addLayout(form)
        self.conflict_lbl = QLabel()
        self.conflict_lbl.setStyleSheet("color:#e0703a")
        self.conflict_lbl.setWordWrap(True)
        left.addWidget(self.conflict_lbl)

        rec = QGroupBox("Record a custom gesture")
        rv = QFormLayout(rec)
        self.custom_name = QLineEdit()
        self.custom_name.setPlaceholderText("e.g. my_ok_sign")
        rv.addRow("Name", self.custom_name)
        self.rec_btn = QPushButton("Record (hold pose for 3 s)")
        self.rec_btn.clicked.connect(self._start_record)
        self.rec_bar = QProgressBar()
        self.rec_bar.setRange(0, 100)
        rv.addRow(self.rec_btn, self.rec_bar)
        self.custom_list = QListWidget()
        self.custom_list.addItems(list(self.pending.custom.keys()))
        rv.addRow("Custom gestures", self.custom_list)
        delb = QPushButton("Delete selected custom gesture")
        delb.clicked.connect(self._delete_custom)
        rv.addRow(delb)
        left.addWidget(rec)

        btns = QHBoxLayout()
        self.test_box = QCheckBox("Test mode (shows what would trigger; nothing happens)")
        self.test_box.setChecked(True)
        save = QPushButton("Save gesture settings")
        save.clicked.connect(self._save_gestures)
        revert = QPushButton("Revert")
        revert.clicked.connect(self._revert_gestures)
        btns.addWidget(save)
        btns.addWidget(revert)
        left.addWidget(self.test_box)
        left.addLayout(btns)
        left.addStretch(1)

        right.addWidget(QLabel("Live landmark preview"))
        self.preview = LandmarkPreview()
        right.addWidget(self.preview, 1)
        self.live_lbl = QLabel("—")
        self.live_lbl.setStyleSheet("font-size:14px; font-weight:500")
        right.addWidget(self.live_lbl)
        self.hold_bar = QProgressBar()
        self.hold_bar.setRange(0, 100)
        self.hold_bar.setFormat("hold %p%")
        right.addWidget(self.hold_bar)
        self.test_log = QListWidget()
        right.addWidget(QLabel("Test-mode triggers"))
        right.addWidget(self.test_log, 1)
        self.recording = None
        self._update_conflicts()
        return w

    def _fill_combos(self):
        names = self._gesture_names()
        for attr, cb in self.combos.items():
            cb.blockSignals(True)
            cb.clear()
            for n in names:
                if attr == "draw_gesture" and n == "none":
                    continue
                cb.addItem(DISPLAY_NAMES.get(n, f"Custom: {n}"), n)
            idx = cb.findData(getattr(self.pending, attr))
            cb.setCurrentIndex(max(idx, 0))
            cb.blockSignals(False)

    def _pending_set(self, attr, v):
        setattr(self.pending, attr, v)
        self._update_conflicts()

    def _update_conflicts(self):
        c = GestureController(self.pending).conflicts()
        msg = ("Conflict: " + "; ".join(c) + " — that action will be ignored.") if c else ""
        if self.pending.hide_gesture == self.pending.show_gesture and self.pending.hide_gesture != "none":
            msg += ("\n" if msg else "") + "Hide and show use the same gesture: it will act as a toggle."
        self.conflict_lbl.setText(msg)

    def _save_gestures(self):
        if GestureController(self.pending).conflicts():
            QMessageBox.warning(self, "Gesture conflict", self.conflict_lbl.text())
            return
        g = self.state.p.gestures
        for k, v in vars(copy.deepcopy(self.pending)).items():
            setattr(g, k, v)
        self.state.touch("gestures")
        self.hotkeys_changed.emit()
        self.test_log.addItem("✓ Saved")

    def _revert_gestures(self):
        self.pending.__dict__.update(copy.deepcopy(self.state.g).__dict__)
        self.custom_list.clear()
        self.custom_list.addItems(list(self.pending.custom.keys()))
        self._fill_combos()
        self._update_conflicts()

    def _start_record(self):
        name = self.custom_name.text().strip().replace(" ", "_")
        if not name or name in BUILTIN or name == "none":
            QMessageBox.information(self, "Name needed", "Enter a unique name for the custom gesture.")
            return
        self.recording = {"name": name, "start": time.monotonic() + 1.0, "samples": []}
        self.rec_btn.setText("Get ready…")

    def _delete_custom(self):
        it = self.custom_list.currentItem()
        if it:
            self.pending.custom.pop(it.text(), None)
            self.custom_list.takeItem(self.custom_list.row(it))
            self._fill_combos()

    # called by main window for every tracked frame
    def on_hand(self, lm, conf):
        if not self.isVisible():
            return
        self.preview.set(lm)
        if lm is None:
            self.live_lbl.setText("No hand")
        else:
            from ..gestures import classify

            conf_p = classify(lm, self.pending.custom)
            g, c = best_gesture(conf_p)
            self.live_lbl.setText(f"{DISPLAY_NAMES.get(g, g)}  —  {100 * c:.0f}%")
            if self.test_box.isChecked():
                pen = None
                if self.pending.draw_mode == "key":
                    from .. import platform_win
                    k = platform_win.key_is_down(self.pending.pen_key)
                    pen = self.state.pen_key_down if k is None else k
                elif self.pending.draw_mode == "toggle":
                    pen = self.state.pen_armed
                for ev in self.test_ctrl.update(conf_p, None, pen):
                    if ev.kind in ("would_fire", "action"):
                        self.test_log.insertItem(0, f"{time.strftime('%H:%M:%S')}  would trigger: {ev.data}  ({DISPLAY_NAMES.get(g, g)})")
                    elif ev.kind in ("draw_start", "draw_end"):
                        self.test_log.insertItem(0, f"{time.strftime('%H:%M:%S')}  {ev.kind.replace('_', ' ')}")
                self.hold_bar.setValue(int(100 * self.test_ctrl.hold_progress()))
        r = self.recording
        if r:
            now = time.monotonic()
            if now < r["start"]:
                return
            if lm is not None:
                r["samples"].append(np.asarray(lm))
            prog = (now - r["start"]) / 3.0
            self.rec_bar.setValue(int(100 * min(prog, 1)))
            self.rec_btn.setText("Recording…")
            if prog >= 1:
                self.recording = None
                self.rec_btn.setText("Record (hold pose for 3 s)")
                if len(r["samples"]) < 10:
                    QMessageBox.warning(self, "Not enough data", "The hand was not visible long enough. Try again.")
                    return
                self.pending.custom[r["name"]] = learn_custom(r["samples"])
                self.custom_list.addItem(r["name"])
                self._fill_combos()
                self.test_log.insertItem(0, f"Learned '{r['name']}' from {len(r['samples'])} frames (not saved yet)")

    # ---- Shortcuts --------------------------------------------------------------
    def _shortcut_tab(self):
        g = self.state.g
        w = QWidget()
        f = QFormLayout(w)
        for attr, label in (("hotkey_toggle_overlay", "Show/hide overlay"), ("hotkey_toggle_panel", "Show/hide equation panel"),
                            ("hotkey_toggle_clickthrough", "Toggle click-through"), ("hotkey_clear", "Clear drawing + equation"),
                            ("hotkey_toggle_pen", "Pen on/off (switches to pen on/off mode)")):
            e = QKeySequenceEdit(QKeySequence(getattr(g, attr)))

            def done(a=attr, ed=e):
                setattr(g, a, ed.keySequence().toString())
                self.state.touch("gestures")
                self.hotkeys_changed.emit()

            e.editingFinished.connect(done)
            f.addRow(label, e)
        n = QLabel("On Windows these are registered as global hotkeys, so they work even when the overlay is "
                   "click-through or another app has focus. Elsewhere they work when a MathDraw window is focused.")
        n.setWordWrap(True)
        f.addRow(n)
        return w
