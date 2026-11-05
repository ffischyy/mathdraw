"""Main window: owns the tracker, gesture controller, analysis jobs, menus and both display modes."""
from __future__ import annotations

import base64
import logging
import math
import os
import time
import traceback

import numpy as np
from PySide6.QtCore import (QBuffer, QByteArray, QEvent, QIODevice, QObject, QRect, QRunnable, QStandardPaths, Qt,
                            QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QLabel, QMainWindow, QMessageBox,
                               QTextBrowser, QToolBar, QToolButton, QVBoxLayout)

from .. import branding as B
from .. import platform_win
from ..geometry import equal_axes, fit_points, norm_to_math, reset_view, set_window, zoom
from ..gestures import DISPLAY_NAMES, GestureController, best_gesture, classify
from ..licensing import evaluate
from ..math_engine.analyzer import analyze_stroke, curve_polylines, plain_text
from ..math_engine.regression import SearchConfig
from ..resources import asset
from ..tracking import TrackerThread
from .canvas import GraphCanvas
from .dialogs import AboutDialog, ActivationDialog, ShortcutsDialog, TextFileDialog, WelcomeDialog
from .math_render import render_latex
from .overlay_window import DesktopOverlay
from .settings_dialog import SettingsDialog

log = logging.getLogger(__name__)

DRAW_MODES = [
    ("pinch", "Pinch to draw"),
    ("key", "Hold key to draw"),
    ("toggle", "Pen on/off switch"),
    ("gesture", "Always draw when pointing"),
]

# (label, grid_mode, density, step_x, step_y, x_pi)
GRID_PRESETS = [
    ("Auto", "auto", "normal", None, None, False),
    ("Auto — fine", "auto", "fine", None, None, False),
    ("Auto — coarse", "auto", "coarse", None, None, False),
    ("0.1", "custom", None, 0.1, 0.1, False),
    ("0.25", "custom", None, 0.25, 0.25, False),
    ("0.5", "custom", None, 0.5, 0.5, False),
    ("1", "custom", None, 1, 1, False),
    ("2", "custom", None, 2, 2, False),
    ("5", "custom", None, 5, 5, False),
    ("10", "custom", None, 10, 10, False),
    ("π/2 (trig)", "custom", None, 0.5, 1, True),
    ("Auto π (trig)", "auto", "normal", None, None, True),
]


class OneEuro:
    """One-Euro filter for jitter-free fingertip tracking."""

    def __init__(self, mincutoff=1.2, beta=0.02, dcutoff=1.0):
        self.mc, self.beta, self.dc = mincutoff, beta, dcutoff
        self.x = self.dx = None
        self.t = None

    @staticmethod
    def _a(cut, dt):
        tau = 1 / (2 * math.pi * cut)
        return 1 / (1 + tau / dt)

    def __call__(self, x, t):
        x = np.asarray(x, float)
        if self.x is None:
            self.x, self.dx, self.t = x, np.zeros_like(x), t
            return x
        dt = max(t - self.t, 1e-3)
        self.t = t
        dx = (x - self.x) / dt
        a_d = self._a(self.dc, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cut = self.mc + self.beta * np.linalg.norm(self.dx)
        a = self._a(cut, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x

    def reset(self):
        self.x = None


class _JobSignals(QObject):
    done = Signal(int, object, object)  # job id, result, stroke


class AnalysisJob(QRunnable):
    def __init__(self, jid, stroke, cfg):
        super().__init__()
        self.jid, self.stroke, self.cfg = jid, stroke, cfg
        self.signals = _JobSignals()

    def run(self):
        try:
            res = analyze_stroke(np.asarray(self.stroke), self.cfg)
        except Exception as e:
            log.exception("Analysis failed")
            res = {"ok": False, "error": f"{e}", "trace": traceback.format_exc()}
        self.signals.done.emit(self.jid, res, self.stroke)


class MainWindow(QMainWindow):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.setWindowIcon(QIcon(asset("icon.ico")))
        self.canvas = GraphCanvas(state, mode="webcam")
        self.setCentralWidget(self.canvas)
        self.overlay = DesktopOverlay(state)
        self.overlay.setWindowIcon(QIcon(asset("icon.ico")))
        self.ctrl = GestureController(state.g)
        self.filter = OneEuro()
        self._apply_filter_strength()
        self.pool = QThreadPool.globalInstance()
        self.job_id = 0
        self.latest_job = 0
        self._job_final = {}
        self.live_timer = QTimer(self)
        self.live_timer.setInterval(900)
        self.live_timer.timeout.connect(self._live_tick)
        self.settings_dlg = None
        self.hotkeys = platform_win.GlobalHotkeys()
        self.hotkeys.install(QApplication.instance())
        self._shortcuts = []
        self._build_menus()
        self._build_toolbar()
        self._register_hotkeys()
        QApplication.instance().installEventFilter(self)
        state.changed.connect(self._on_state)
        self.resize(1280, 800)
        self._apply_main_flags()
        self._update_title()
        self.tracker = None
        self.start_camera()
        QTimer.singleShot(0, self.overlay.sync_visibility)

    # ---- menus ----------------------------------------------------------------------
    def _act(self, text, cb, shortcut=None, tip=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(cb)
        return a

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addAction(self._act("Export graph image…", self.export_image, "Ctrl+E", "Save the graph (without the camera image) as PNG"))
        m.addAction(self._act("Export graph with camera…", lambda: self.export_image(with_camera=True)))
        m.addSeparator()
        m.addAction(self._act("Quit", self.close, "Ctrl+Q"))

        m = mb.addMenu("&Edit")
        m.addAction(self._act("Copy equation (LaTeX)", self.copy_latex, "Ctrl+Shift+C"))
        m.addAction(self._act("Copy equation (plain text)", self.copy_plain))
        m.addSeparator()
        m.addAction(self._act("Clear drawing + equation", self.clear_all))
        m.addAction(self._act("Dismiss equation (keep drawing)", self.state.clear_equation))
        m.addAction(self._act("Re-analyse last stroke", self.reanalyse))
        m.addSeparator()
        m.addAction(self._act("Settings…", self.open_settings, "Ctrl+,"))

        m = mb.addMenu("&View")
        self.m_mode = self._act("Switch to desktop overlay", self.toggle_mode)
        m.addAction(self.m_mode)
        self.m_overlay = self._act("Hide overlay", self.toggle_overlay)
        m.addAction(self.m_overlay)
        self.m_panel = self._act("Hide equation panel", self.toggle_panel)
        m.addAction(self.m_panel)
        m.addAction(self._act("Equation details…", self.show_details, "Ctrl+I"))
        m.addSeparator()
        m.addAction(self._act("Restart camera", self.start_camera))

        m = mb.addMenu("&Draw")
        self.draw_mode_actions = {}
        for key, label in DRAW_MODES:
            a = self._act(label, lambda _c=False, k=key: self.set_draw_mode(k), checkable=True)
            self.draw_mode_actions[key] = a
            m.addAction(a)
        m.addSeparator()
        self.m_pen = self._act("Pen on/off", self.toggle_pen)
        m.addAction(self.m_pen)
        self.m_smooth = self._act("Auto-smoothing", self.toggle_smoothing, checkable=True,
                                  tip="Remove hand shake and replace the stroke with its clean function")
        m.addAction(self.m_smooth)

        m = mb.addMenu("&Graph")
        m.addAction(self._act("Zoom in", lambda: self.zoom(1 / 1.25), "Ctrl+="))
        m.addAction(self._act("Zoom out", lambda: self.zoom(1.25), "Ctrl+-"))
        m.addAction(self._act("Zoom in (x only)", lambda: self.zoom(1 / 1.25, "x")))
        m.addAction(self._act("Zoom out (x only)", lambda: self.zoom(1.25, "x")))
        m.addAction(self._act("Zoom in (y only)", lambda: self.zoom(1 / 1.25, "y")))
        m.addAction(self._act("Zoom out (y only)", lambda: self.zoom(1.25, "y")))
        m.addSeparator()
        m.addAction(self._act("Fit to drawing", self.fit_view, "Ctrl+F"))
        m.addAction(self._act("Equal axes (1:1)", self.equal_axes))
        m.addAction(self._act("Standard window (−10…10)", lambda: self.preset_window(-10, 10, -10, 10)))
        m.addAction(self._act("Trig window (−2π…2π)", self.trig_window))
        m.addAction(self._act("Reset view", self.reset_view, "Ctrl+0"))
        m.addSeparator()
        m.addAction(self._act("Graph settings (grid size, window)…", lambda: self.open_settings("Graph"), "Ctrl+G"))
        # Ctrl++ on keyboards without '=' on the same key
        sc = QShortcut(QKeySequence("Ctrl++"), self)
        sc.activated.connect(lambda: self.zoom(1 / 1.25))

        m = mb.addMenu("&Help")
        m.addAction(self._act("Quick start", self.show_welcome, "F1"))
        m.addAction(self._act("Keyboard shortcuts", lambda: ShortcutsDialog(self.state, self).exec()))
        m.addSeparator()
        self.m_license = self._act("Enter licence key…", self.open_activation)
        m.addAction(self.m_license)
        m.addAction(self._act(f"Buy {B.APP_NAME}…", lambda: QDesktopServices.openUrl(QUrl(B.BUY_URL))))
        m.addSeparator()
        m.addAction(self._act("Licence agreement (EULA)", lambda: TextFileDialog("Licence agreement", "EULA.txt", self).exec()))
        m.addAction(self._act("Privacy policy", lambda: TextFileDialog("Privacy policy", "PRIVACY.txt", self).exec()))
        m.addAction(self._act("Third-party notices", lambda: TextFileDialog("Third-party notices", "THIRD_PARTY_NOTICES.txt", self).exec()))
        m.addAction(self._act("Open log folder", self.open_logs))
        m.addAction(self._act(f"Contact support", lambda: QDesktopServices.openUrl(QUrl(f"mailto:{B.SUPPORT_EMAIL}"))))
        m.addSeparator()
        m.addAction(self._act(f"About {B.APP_NAME}", lambda: AboutDialog(self.state, self).exec()))

    # ---- toolbar ----------------------------------------------------------------
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)

        def add(text, cb, tip="", checkable=False):
            a = QAction(text, self)
            a.setToolTip(tip or text)
            a.setCheckable(checkable)
            a.triggered.connect(cb)
            tb.addAction(a)
            return a

        self.a_mode = add("Webcam", self.toggle_mode, "Switch between webcam view and transparent desktop overlay")
        tb.addSeparator()
        tb.addWidget(QLabel("Draw"))
        self.draw_mode_box = QComboBox()
        for key, label in DRAW_MODES:
            self.draw_mode_box.addItem(label, key)
        self.draw_mode_box.setToolTip("Choose what makes your finger draw")
        self.draw_mode_box.currentIndexChanged.connect(lambda i: self.set_draw_mode(self.draw_mode_box.itemData(i)))
        tb.addWidget(self.draw_mode_box)
        self.a_pen = add("Pen off", self.toggle_pen, "Switch the pen on/off (pen on/off mode)")
        self.a_smooth = add("Smooth", self.toggle_smoothing,
                            "Auto-smoothing: remove hand shake and show the clean function", checkable=True)
        tb.addSeparator()
        add("−", lambda: self.zoom(1.25), "Zoom out (Ctrl −)")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setToolTip("Zoom level relative to the default view")
        tb.addWidget(self.zoom_label)
        add("+", lambda: self.zoom(1 / 1.25), "Zoom in (Ctrl =)")
        add("Fit", self.fit_view, "Zoom to fit the drawing (Ctrl F)")
        tb.addWidget(QLabel("Grid"))
        self.grid_box = QComboBox()
        for p in GRID_PRESETS:
            self.grid_box.addItem(p[0])
        self.grid_box.addItem("Custom…")
        self.grid_box.setToolTip("Grid line spacing")
        self.grid_box.activated.connect(self._on_grid_box)
        tb.addWidget(self.grid_box)
        tb.addSeparator()
        add("Clear", self.clear_all, "Clear drawing and equation")
        add("Details", self.show_details, "Full calculus report for the current equation")
        add("Settings", self.open_settings, "All settings (Ctrl ,)")
        self._sync_toolbar()

    def _apply_grid_preset(self, idx):
        label, mode, density, sx, sy, xpi = GRID_PRESETS[idx]
        d = self.state.d
        d.grid_mode = mode
        d.grid_x_pi = xpi
        if density:
            d.grid_density = density
        if sx is not None:
            d.grid_step_x, d.grid_step_y = float(sx), float(sy)
        self.state.touch("display")

    def _on_grid_box(self, i):
        if i < len(GRID_PRESETS):
            self._apply_grid_preset(i)
        else:
            self.open_settings("Graph")

    def _grid_box_index(self):
        d = self.state.d
        for i, (_, mode, density, sx, sy, xpi) in enumerate(GRID_PRESETS):
            if mode != d.grid_mode or xpi != d.grid_x_pi:
                continue
            if mode == "auto" and density == d.grid_density:
                return i
            if mode == "custom" and abs(sx - d.grid_step_x) < 1e-12 and abs(sy - d.grid_step_y) < 1e-12:
                return i
        return len(GRID_PRESETS)  # Custom…

    # ---- draw modes / pen / smoothing ---------------------------------------------
    def set_draw_mode(self, mode):
        if mode and mode != self.state.g.draw_mode:
            self.state.g.draw_mode = mode
            self.state.pen_armed = False
            self.state.touch("gestures")
            self.statusBar().showMessage(self._draw_hint(), 6000)
        self._sync_toolbar()

    def _draw_hint(self):
        g = self.state.g
        dg = DISPLAY_NAMES.get(g.draw_gesture, g.draw_gesture)
        return {
            "pinch": "Move your index finger to aim; touch thumb to index finger to draw, separate them to lift the pen.",
            "key": f"Aim with your index finger; draw only while holding {g.pen_key}.",
            "toggle": f"Press {g.hotkey_toggle_pen} (or the Pen button) to turn the pen on; then '{dg}' draws.",
            "gesture": f"'{dg}' always draws.",
        }.get(g.draw_mode, "")

    def toggle_pen(self):
        s = self.state
        if s.g.draw_mode != "toggle":
            s.g.draw_mode = "toggle"
            s.touch("gestures")
        s.pen_armed = not s.pen_armed
        s.touch("tracking", persist=False)
        self._sync_toolbar()
        self.statusBar().showMessage(f"Pen {'on' if s.pen_armed else 'off'}", 2000)

    def toggle_smoothing(self):
        a = self.state.a
        a.smoothing_enabled = not a.smoothing_enabled
        self.state.touch("analysis")
        self.statusBar().showMessage(
            "Auto-smoothing on: hand shake is removed and your stroke becomes a clean function" if a.smoothing_enabled
            else "Auto-smoothing off: raw strokes are shown", 4000)

    def _apply_filter_strength(self):
        a = self.state.a
        st = a.smoothing_strength if a.smoothing_enabled else 0.0
        # stronger smoothing -> lower cut-off (steadier cursor, slightly more lag)
        self.filter.mc = 1.4 * (1 - 0.65 * st)
        self.filter.beta = 0.02 * (1 + st)

    def _sync_toolbar(self):
        s = self.state
        i = self.draw_mode_box.findData(s.g.draw_mode)
        if i >= 0 and i != self.draw_mode_box.currentIndex():
            self.draw_mode_box.blockSignals(True)
            self.draw_mode_box.setCurrentIndex(i)
            self.draw_mode_box.blockSignals(False)
        for k, a in self.draw_mode_actions.items():
            a.setChecked(k == s.g.draw_mode)
        self.a_pen.setVisible(s.g.draw_mode == "toggle")
        self.a_pen.setText("Pen on" if s.pen_armed else "Pen off")
        self.a_smooth.setChecked(s.a.smoothing_enabled)
        self.m_smooth.setChecked(s.a.smoothing_enabled)
        self.a_mode.setText("Webcam" if s.d.mode == "webcam" else "Desktop overlay")
        self.m_mode.setText("Switch to desktop overlay" if s.d.mode == "webcam" else "Switch to webcam view")
        self.m_overlay.setText("Hide overlay" if s.p.overlay_visible else "Show overlay")
        self.m_panel.setText("Hide equation panel" if s.p.panel_visible else "Show equation panel")
        gi = self._grid_box_index()
        if gi != self.grid_box.currentIndex():
            self.grid_box.setCurrentIndex(gi)
        v = s.view
        zx = 8.0 / v.half_w
        self.zoom_label.setText(f"{zx * 100:.0f}%" if abs(v.y_ratio - 1) < 1e-6
                                else f"x {zx * 100:.0f}% · y {zx / v.y_ratio * 100:.0f}%")

    # ---- zoom / window --------------------------------------------------------------
    def zoom(self, factor, axis="both"):
        zoom(self.state.view, factor, None, axis)
        self.state.touch("view")

    def reset_view(self):
        reset_view(self.state.view)
        self.state.touch("view")

    def equal_axes(self):
        equal_axes(self.state.view)
        self.state.touch("view")

    def preset_window(self, xmin, xmax, ymin, ymax):
        set_window(self.state.view, xmin, xmax, ymin, ymax)
        self.state.touch("view")

    def trig_window(self):
        d = self.state.d
        d.grid_mode, d.grid_x_pi, d.grid_step_x, d.grid_step_y = "custom", True, 0.5, 1.0
        self.preset_window(-2 * math.pi, 2 * math.pi, -3, 3)
        self.state.touch("display")

    def fit_view(self):
        s = self.state
        pts = list(s.current_stroke) or list(s.p.last_stroke)
        if not pts and s.p.last_result:
            for line in curve_polylines(s.p.last_result, s.view.bounds()):
                pts.extend(line.tolist())
        if not pts:
            self.statusBar().showMessage("Nothing drawn yet to fit", 2500)
            return
        fit_points(s.view, pts)
        s.touch("view")

    # ---- hotkeys --------------------------------------------------------------------
    def _register_hotkeys(self):
        self.hotkeys.unregister_all()
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts = []
        g = self.state.g
        for seq, cb in ((g.hotkey_toggle_overlay, self.toggle_overlay), (g.hotkey_toggle_panel, self.toggle_panel),
                        (g.hotkey_toggle_clickthrough, self.toggle_click_through), (g.hotkey_clear, self.clear_all),
                        (g.hotkey_toggle_pen, self.toggle_pen)):
            if not seq:
                continue
            if not self.hotkeys.register(seq, cb):
                sc = QShortcut(QKeySequence(seq), self)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                sc.activated.connect(cb)
                self._shortcuts.append(sc)

    # ---- camera ----------------------------------------------------------------
    def start_camera(self):
        if self.tracker is not None:
            self.tracker.stop()
        d = self.state.d
        self.tracker = TrackerThread(d.camera_index, d.mirror_camera)
        self.tracker.frame_ready.connect(self.canvas.set_frame)
        self.tracker.hand.connect(self.on_hand)
        self.tracker.status.connect(self._on_cam_status)
        self.tracker.start()

    def _on_cam_status(self, ok, msg):
        log.info("Camera status: %s %s", ok, msg)
        self.state.set_tracking(webcam_available=ok, analysis_message=msg if not ok or "Loading" in msg or "unavailable" in msg else self.state.analysis_message)
        self.statusBar().showMessage(msg, 6000)
        if not ok and not getattr(self, "_cam_warned", False):
            self._cam_warned = True
            QMessageBox.warning(self, "Camera not available",
                                f"{msg}.\n\nCheck that a webcam is connected, that no other app (Zoom, Teams, Camera) is "
                                "using it, and that Windows camera privacy settings allow desktop apps to use the camera. "
                                "You can pick another camera in Settings ▸ Camera, then use View ▸ Restart camera.")

    # ---- per-frame hand handling ------------------------------------------------------
    def on_hand(self, lm):
        s = self.state
        now = time.monotonic()
        conf = classify(lm, s.g.custom) if lm is not None else None
        tip_uv = None
        if lm is not None:
            tip_uv = tuple(self.filter(lm[8, :2], now))
        else:
            self.filter.reset()
        pen = None
        if s.g.draw_mode == "key":
            down = platform_win.key_is_down(s.g.pen_key)
            pen = s.pen_key_down if down is None else down
        elif s.g.draw_mode == "toggle":
            pen = s.pen_armed
        events = self.ctrl.update(conf, tip_uv, pen)
        for ev in events:
            if ev.kind == "draw_start":
                s.current_stroke = []
                s.drawing_active = True
                if s.a.live_update:
                    self.live_timer.start()
            elif ev.kind == "draw_point":
                x, y = norm_to_math(ev.data[0], ev.data[1], s.view)
                if not s.current_stroke or math.dist(s.current_stroke[-1], (x, y)) > 1e-3 * s.view.half_w:
                    s.current_stroke.append((x, y))
            elif ev.kind == "draw_end":
                s.drawing_active = False
                self.live_timer.stop()
                self._finish_stroke()
            elif ev.kind == "action":
                self._do_action(ev.data)
        g, c = best_gesture(conf or {})
        gtxt = f"{DISPLAY_NAMES.get(g, g)} {100 * c:.0f}%" if lm is not None else ""
        hold = self.ctrl.hold_progress()
        s.hand_detected = lm is not None
        s.current_gesture = (g, c)
        self.canvas.set_hand(lm, tip_uv, gtxt, hold)
        self.overlay.canvas.set_hand(lm, tip_uv, gtxt, hold)
        if self.settings_dlg is not None:
            self.settings_dlg.on_hand(lm, conf)

    def _do_action(self, action):
        s = self.state
        if action == "hide_overlay":
            s.set_overlay_visible(False)
        elif action == "show_overlay":
            s.set_overlay_visible(True)
        elif action == "toggle_overlay":
            s.set_overlay_visible(not s.p.overlay_visible)
        elif action == "toggle_panel":
            s.set_panel_visible(not s.p.panel_visible)
        elif action == "clear":
            self.clear_all()
        elif action == "toggle_pen":
            self.toggle_pen()
        self.statusBar().showMessage(f"Gesture action: {action.replace('_', ' ')}", 2500)

    # ---- analysis ----------------------------------------------------------------
    def _cfg(self):
        a = self.state.a
        return SearchConfig(simplicity=a.simplicity, time_budget_s=a.time_budget_s, max_complexity=a.max_complexity,
                            families=a.families or None,
                            smoothing=a.smoothing_strength if a.smoothing_enabled else 0.0)

    def _launch(self, stroke, final=True):
        self.job_id += 1
        self.latest_job = self.job_id
        job = AnalysisJob(self.job_id, list(stroke), self._cfg())
        self._job_final[self.job_id] = final
        # Bound method of a QObject => Qt queues the call onto the UI thread.
        # (A lambda here would run in the worker thread and crash when touching widgets.)
        job.signals.done.connect(self._on_job_done, Qt.ConnectionType.QueuedConnection)
        self.state.analysis_running = True
        self.state.analysis_message = "Analysing…"
        self.state.touch("analysis_status", persist=False)
        self.pool.start(job)

    def _finish_stroke(self):
        s = self.state
        stroke = list(s.current_stroke)
        if len(stroke) < s.a.min_points:
            s.analysis_message = f"Stroke too short ({len(stroke)} pts) — previous equation kept"
            s.current_stroke = []
            s.touch("analysis_status", persist=False)
            return
        self._launch(stroke)

    def _live_tick(self):
        s = self.state
        if s.drawing_active and len(s.current_stroke) >= s.a.min_points and not s.analysis_running:
            self._launch(list(s.current_stroke), final=False)

    def reanalyse(self):
        if self.state.p.last_stroke:
            self._launch(self.state.p.last_stroke)
        else:
            self.statusBar().showMessage("Nothing to re-analyse yet", 2500)

    def _on_job_done(self, jid, res, stroke):
        self._on_result(jid, res, stroke, self._job_final.pop(jid, True))

    def _on_result(self, jid, res, stroke, final):
        s = self.state
        if jid != self.latest_job:
            return  # stale
        s.analysis_running = False
        if res.get("ok"):
            s.analysis_message = f"Analysed in {res.get('elapsed_s', 0)} s"
            if final:
                s.current_stroke = []
            s.set_result(res, stroke)  # persisted; replaces previous only on success
        else:
            log.warning("Analysis failed: %s", res.get("error"))
            s.analysis_message = f"Analysis failed ({res.get('error')}) — previous equation kept"
            if final:
                s.current_stroke = []
        s.touch("analysis_status", persist=False)

    # ---- export / copy ------------------------------------------------------------
    def copy_latex(self):
        res = self.state.p.last_result
        if not res:
            self.statusBar().showMessage("No equation yet", 2500)
            return
        QGuiApplication.clipboard().setText(res["latex"])
        self.statusBar().showMessage("Equation copied as LaTeX", 2500)

    def copy_plain(self):
        txt = plain_text(self.state.p.last_result)
        if not txt:
            self.statusBar().showMessage("No equation yet", 2500)
            return
        QGuiApplication.clipboard().setText(txt)
        self.statusBar().showMessage(f"Copied: {txt}", 4000)

    def export_image(self, with_camera=False):
        pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        name = time.strftime(f"{B.APP_NAME}-%Y%m%d-%H%M%S.png")
        path, _ = QFileDialog.getSaveFileName(self, "Export graph image", os.path.join(pics, name), "PNG image (*.png)")
        if not path:
            return
        c = self.canvas
        if not with_camera:
            c.export_mode = "#141415"
        try:
            img = c.grab()
        finally:
            c.export_mode = None
            c.update()
        if img.save(path, "PNG"):
            self.statusBar().showMessage(f"Saved {path}", 5000)
        else:
            QMessageBox.warning(self, "Export failed", f"Could not write {path}")

    # ---- user commands ------------------------------------------------------------
    def toggle_overlay(self):
        self.state.set_overlay_visible(not self.state.p.overlay_visible)

    def toggle_panel(self):
        self.state.set_panel_visible(not self.state.p.panel_visible)

    def toggle_click_through(self):
        d = self.state.d
        d.click_through = not d.click_through
        self.state.touch("display")
        self.statusBar().showMessage(f"Click-through {'on' if d.click_through else 'off'}", 2500)

    def toggle_mode(self):
        d = self.state.d
        d.mode = "desktop" if d.mode == "webcam" else "webcam"
        self.state.touch("display")

    def clear_all(self):
        self.state.clear_all()

    def open_settings(self, tab=None):
        if self.settings_dlg is None:
            self.settings_dlg = SettingsDialog(self.state, self)
            self.settings_dlg.reanalyse_requested.connect(self.reanalyse)
            self.settings_dlg.hotkeys_changed.connect(self._register_hotkeys)
            self.settings_dlg.fit_requested.connect(self.fit_view)
            self.settings_dlg.camera_restart_requested.connect(self.start_camera)
            self.settings_dlg.finished.connect(lambda _r: setattr(self, "settings_dlg", None))
            self.settings_dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if tab:
            self.settings_dlg.select_tab(tab)
        self.settings_dlg.show()
        self.settings_dlg.raise_()

    def show_welcome(self):
        WelcomeDialog(self).exec()

    def open_activation(self):
        if ActivationDialog(self.state, parent=self).exec():
            self._update_title()

    def open_logs(self):
        from ..app import log_dir

        QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir()))

    def _update_title(self):
        st = evaluate(self.state.p.license_key, self.state.p.first_run_ts)
        self.setWindowTitle(f"{B.APP_NAME}{st.title_suffix()}")
        self.m_license.setVisible(st.state != "disabled")

    def show_details(self):
        res = self.state.p.last_result
        dlg = QDialog(self)
        dlg.setWindowTitle("Equation details")
        dlg.resize(820, 680)
        tb = QTextBrowser()
        tb.setStyleSheet("QTextBrowser { background: #19191b; color: #ededed; border: none; }")
        html = ["<body style='font-family:Segoe UI; margin:8px'>"]

        def img(latex, size=16):
            im = render_latex(latex, size, "#ededed", 110)
            if im is None:
                return f"<code>{latex}</code>"
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            im.save(buf, "PNG")
            return f"<img src='data:image/png;base64,{base64.b64encode(bytes(ba)).decode()}'/>"

        if not res:
            html.append("<p>No equation yet.</p>")
        else:
            html.append(f"<h2>{res['model']}</h2><p>{img(res['latex'], 20)}</p>")
            html.append(f"<p><code>{plain_text(res)}</code></p>")
            m = res.get("metrics", {})
            html.append(f"<p>RMSE {m.get('rmse', 0):.5g}; normalised {100 * (m.get('nrmse') or 0):.3f}%; "
                        f"R² {m.get('r2') if m.get('r2') is None else round(m['r2'], 5)}; estimated tracking noise σ "
                        f"{m.get('sigma') if m.get('sigma') is None else round(m['sigma'], 5)}; models evaluated {m.get('n_models', '—')}; "
                        f"confidence {100 * res.get('confidence', 0):.0f}%"
                        f"{'; <b>approximation</b>' if res.get('approximate') else ''}{'; <b>ambiguous</b>' if res.get('ambiguous') else ''}</p>")
            if res.get("truncated"):
                html.append("<p style='color:#a1a1a6'>The search reached its time limit before trying every model; raise it in "
                            "Settings ▸ Analysis for harder curves.</p>")
            if res.get("smoothing"):
                html.append(f"<p>Auto-smoothing strength {res['smoothing']:.2f}; measured hand jitter ≈ {res.get('jitter', 0):.3g} units.</p>")
            if res.get("note"):
                html.append(f"<p style='color:#a1a1a6'>{res['note']}</p>")
            if res.get("alternatives"):
                html.append("<h3>Alternative candidates</h3><ul>")
                for a in res["alternatives"]:
                    w = a.get("weight")
                    html.append(f"<li>{a['model']} ({'' if w is None else f'{100 * w:.1f}%'}): {img(a['latex'], 14)}</li>")
                html.append("</ul>")
            if res.get("equivalents"):
                html.append("<h3>Equivalent forms</h3><ul>" + "".join(f"<li>{img(e, 14)}</li>" for e in res["equivalents"]) + "</ul>")
            cal = res.get("calculus") or {}
            if cal.get("items"):
                html.append("<h3>Calculus</h3><table cellpadding=4>")
                for it in cal["items"]:
                    html.append(f"<tr><td><b>{it['label']}</b></td><td>{img(it['latex'], 14)}</td></tr>")
                html.append("</table>")
            if cal.get("techniques"):
                html.append("<p>Integration techniques used: " + ", ".join(cal["techniques"]) + "</p>")
            num = (cal.get("numbers") or {}).get("integral_over_drawn_domain")
            if num:
                html.append("<h3>Numerical integration & error</h3><table cellpadding=3><tr><th>Method</th><th>Value</th><th>|Error| vs adaptive quad</th></tr>")
                html.append(f"<tr><td>Adaptive quadrature</td><td>{num['quad']:.8g}</td><td>est. {num['quad_err']:.2g}</td></tr>")
                for n in (8, 32):
                    html.append(f"<tr><td>Trapezoid n={n}</td><td>{num[f'trap_{n}']:.8g}</td><td>{num[f'trap_{n}_err']:.2g}</td></tr>")
                    html.append(f"<tr><td>Simpson n={n}</td><td>{num[f'simp_{n}']:.8g}</td><td>{num[f'simp_{n}_err']:.2g}</td></tr>")
                html.append("</table>")
            html.append("<p style='color:#a1a1a6'>A hand-drawn curve cannot uniquely determine an arbitrary formula; "
                        "results are the best-supported candidates given tracking noise.</p>")
        tb.setHtml("".join(html))
        lay = QVBoxLayout(dlg)
        lay.addWidget(tb)
        dlg.show()

    # ---- state / window flags ----------------------------------------------------------
    def _apply_main_flags(self):
        d = self.state.d
        on_top = d.always_on_top and d.mode == "webcam"
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != on_top:
            vis = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
            if vis:
                self.show()

    def _on_state(self, key):
        if key == "display":
            self._apply_main_flags()
            self.overlay.apply_flags()
            self.overlay.sync_visibility()
        if key == "overlay_geometry":
            self.overlay.setGeometry(QRect(*[int(v) for v in self.state.d.overlay_geometry]))
        if key == "gestures":
            self.ctrl.s = self.state.g
        if key == "analysis":
            self._apply_filter_strength()
        if key == "license":
            self._update_title()
        self._sync_toolbar()

    def eventFilter(self, obj, ev):
        """Fallback for the hold-to-draw key when global polling is unavailable."""
        t = ev.type()
        if t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and not ev.isAutoRepeat():
            seq = QKeySequence(self.state.g.pen_key)
            if not seq.isEmpty() and ev.key() == seq[0].key():
                self.state.pen_key_down = t == QEvent.Type.KeyPress
                if self.state.g.draw_mode == "key":
                    return True  # don't let Space press toolbar buttons
        return False

    def closeEvent(self, e):
        if self.overlay.isVisible():
            self.overlay.save_geometry()
        if self.tracker:
            self.tracker.stop()
        self.hotkeys.unregister_all()
        self.state.save()
        self.overlay.close()
        super().closeEvent(e)
