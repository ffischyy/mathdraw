"""Persistent overlay state manager.

Separates *runtime tracking state* (webcam availability, hand detection,
current drawing activity) from *persistent mathematical / display state*
(last completed stroke, last successfully analysed equation, visibility,
mode, gestures, calibration, theme).  Visibility never depends on whether a
hand is detected, and toggling visibility never deletes data.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields

from PySide6.QtCore import QObject, QStandardPaths, QTimer, Signal

from .geometry import View


@dataclass
class DisplaySettings:
    mode: str = "webcam"  # "webcam" (Mode A) | "desktop" (Mode B)
    overall_opacity: float = 1.0  # graph layers
    grid_opacity: float = 0.14
    axes_opacity: float = 0.70
    drawing_opacity: float = 0.9
    fit_opacity: float = 1.0
    background_opacity: float = 0.0  # tint behind graph (0 = fully transparent)
    background_color: str = "#000000"
    panel_opacity: float = 0.88
    panel_bg: str = "#19191b"
    panel_text: str = "#ededed"
    panel_accent: str = "#e8c547"
    panel_font_pt: int = 24
    panel_width: int = 470
    panel_padding: int = 16
    panel_margin: int = 14
    curve_color: str = "#ededed"  # original drawing
    fit_color: str = "#e8c547"  # fitted function
    axes_color: str = "#ededed"
    grid_color: str = "#ededed"
    curve_width: float = 3.0
    fit_width: float = 3.0
    show_grid: bool = True
    show_axes: bool = True
    show_drawing: bool = True
    show_fit: bool = True
    show_panel: bool = True
    show_calculus: bool = True
    show_alternatives: bool = True
    show_landmarks: bool = True
    # graph grid
    grid_mode: str = "auto"  # "auto" | "custom"
    grid_density: str = "normal"  # auto mode: "fine" | "normal" | "coarse"
    grid_step_x: float = 1.0  # custom mode (multiples of pi when grid_x_pi)
    grid_step_y: float = 1.0
    grid_x_pi: bool = False  # x axis in multiples of pi (trig)
    grid_minor: int = 0  # minor subdivisions per major cell (0 = off)
    show_tick_labels: bool = True
    tick_label_pt: float = 9.0
    fit_extension_opacity: float = 0.35  # fitted curve beyond the drawn range
    always_on_top: bool = True
    borderless: bool = True
    click_through: bool = False
    exclude_from_capture: bool = True
    overlay_geometry: list = field(default_factory=lambda: [80, 80, 960, 540])
    mirror_camera: bool = True
    camera_index: int = 0


@dataclass
class AnalysisSettings:
    simplicity: float = 0.5  # 0 = complex/accurate ... 1 = simplest
    time_budget_s: float = 4.0
    max_complexity: int = 10
    live_update: bool = False  # automatic replacement while drawing (off = persistence)
    smoothing_enabled: bool = True  # auto-smoothing of hand jitter
    smoothing_strength: float = 0.5  # 0..1
    clean_replace: bool = True  # after analysis, show the clean function instead of the shaky stroke
    min_points: int = 25
    families: dict = field(default_factory=dict)  # family -> enabled (empty = all)


@dataclass
class GestureSettings:
    # what puts the "pen" down:
    #   "pinch"   - index finger moves a cursor; touch thumb to index finger to draw (default)
    #   "key"     - draw only while holding pen_key (works globally on Windows)
    #   "toggle"  - pen on/off switch (toolbar, hotkey or gesture); when on, the draw gesture draws
    #   "gesture" - the draw gesture always draws (original behaviour)
    draw_mode: str = "pinch"
    draw_gesture: str = "point"
    pen_key: str = "Space"
    pen_toggle_gesture: str = "none"
    hide_gesture: str = "open_palm"
    show_gesture: str = "thumbs_up"
    panel_toggle_gesture: str = "peace"  # hide/show only the equation panel
    clear_gesture: str = "none"
    confidence: float = 0.75
    hold_s: float = 0.8
    cooldown_s: float = 1.5
    draw_hold_s: float = 0.08
    stroke_end_s: float = 0.35
    custom: dict = field(default_factory=dict)  # name -> {"mean": [...], "std": [...]}
    hotkey_toggle_overlay: str = "Ctrl+Alt+O"
    hotkey_toggle_panel: str = "Ctrl+Alt+E"
    hotkey_toggle_clickthrough: str = "Ctrl+Alt+T"
    hotkey_clear: str = "Ctrl+Alt+C"
    hotkey_toggle_pen: str = "Ctrl+Alt+D"


@dataclass
class Persisted:
    display: DisplaySettings = field(default_factory=DisplaySettings)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    gestures: GestureSettings = field(default_factory=GestureSettings)
    view: dict = field(default_factory=lambda: View().to_dict())
    overlay_visible: bool = True
    graph_visible: bool = True
    panel_visible: bool = True
    last_stroke: list = field(default_factory=list)  # [[x, y], ...] math coords
    last_result: dict | None = None  # last successfully analysed equation
    license_key: str = ""
    first_run_ts: float = 0.0
    welcome_shown: bool = False


def _load_into(dc, data: dict):
    for f in fields(dc):
        if f.name in data:
            cur = getattr(dc, f.name)
            val = data[f.name]
            if hasattr(cur, "__dataclass_fields__") and isinstance(val, dict):
                _load_into(cur, val)
            else:
                setattr(dc, f.name, val)
    return dc


class StateManager(QObject):
    changed = Signal(str)  # key: "display" | "visibility" | "result" | "stroke" | "tracking" | "view" | "gestures" | "analysis"

    def __init__(self, path: str | None = None):
        super().__init__()
        if path is None:
            base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation) or os.path.expanduser("~/.mathdraw")
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, "state.json")
        self.path = path
        self.p = Persisted()
        self.view = View()
        # runtime (never persisted)
        self.webcam_available = False
        self.hand_detected = False
        self.drawing_active = False
        self.current_stroke: list = []
        self.current_gesture = ("none", 0.0)
        self.analysis_running = False
        self.pen_armed = False  # "toggle" draw mode: pen on/off (starts off every launch)
        self.pen_key_down = False  # "key" draw mode
        self.analysis_message = ""
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.save)

    # ---- persistence ------------------------------------------------------
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                _load_into(self.p, json.load(fh))
        except FileNotFoundError:
            pass
        except Exception as e:  # corrupt file: keep defaults, don't crash
            print("State load failed:", e)
        self.view = View.from_dict(self.p.view)

    def save(self):
        self.p.view = self.view.to_dict()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self.p), fh, indent=1)
        os.replace(tmp, self.path)

    def touch(self, key: str, persist=True):
        self.changed.emit(key)
        if persist:
            self._save_timer.start()

    # ---- convenience accessors -------------------------------------------
    @property
    def d(self) -> DisplaySettings:
        return self.p.display

    @property
    def g(self) -> GestureSettings:
        return self.p.gestures

    @property
    def a(self) -> AnalysisSettings:
        return self.p.analysis

    # ---- visibility (never touches data) ------------------------------------
    def set_overlay_visible(self, v: bool):
        self.p.overlay_visible = bool(v)
        self.touch("visibility")

    def set_panel_visible(self, v: bool):
        self.p.panel_visible = bool(v)
        self.touch("visibility")

    def set_graph_visible(self, v: bool):
        self.p.graph_visible = bool(v)
        self.touch("visibility")

    # ---- mathematical data ---------------------------------------------------
    def set_result(self, result: dict, stroke: list):
        """Store a *successful* analysis; this is the only way the equation changes."""
        self.p.last_result = result
        self.p.last_stroke = [list(map(float, pt)) for pt in stroke]
        self.touch("result")

    def clear_equation(self):
        self.p.last_result = None
        self.touch("result")

    def clear_all(self):
        self.p.last_result = None
        self.p.last_stroke = []
        self.current_stroke = []
        self.touch("result")
        self.touch("stroke", persist=False)

    def set_tracking(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.touch("tracking", persist=False)
