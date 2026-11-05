"""Hand-gesture recognition from MediaPipe landmarks.

Features are translation-, scale- and rotation-invariant: landmarks are
expressed relative to the wrist, divided by palm size (wrist -> middle-finger
MCP) and rotated so the palm axis points up.  Finger extension is measured as
a *ratio* of distances, so it does not depend on how far the hand is from the
camera.

``GestureController`` turns per-frame classifications into actions with a
stability (hold) requirement, a per-action cooldown, a release requirement,
and a priority rule that prevents conflicts with the drawing gesture.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

WRIST = 0
TIPS = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIPS = {"thumb": 3, "index": 6, "middle": 10, "ring": 14, "pinky": 18}
MCPS = {"thumb": 2, "index": 5, "middle": 9, "ring": 13, "pinky": 17}
FINGERS = ["thumb", "index", "middle", "ring", "pinky"]

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]

# built-in gestures: required finger states (1 extended, 0 folded, None = don't care)
BUILTIN = {
    "open_palm": {"thumb": 1, "index": 1, "middle": 1, "ring": 1, "pinky": 1},
    "fist": {"thumb": 0, "index": 0, "middle": 0, "ring": 0, "pinky": 0},
    "point": {"index": 1, "middle": 0, "ring": 0, "pinky": 0},
    "peace": {"index": 1, "middle": 1, "ring": 0, "pinky": 0},
    "three": {"index": 1, "middle": 1, "ring": 1, "pinky": 0},
    "four": {"thumb": 0, "index": 1, "middle": 1, "ring": 1, "pinky": 1},
    "thumbs_up": {"thumb": 1, "index": 0, "middle": 0, "ring": 0, "pinky": 0},
    "rock": {"index": 1, "middle": 0, "ring": 0, "pinky": 1},
    "call_me": {"thumb": 1, "index": 0, "middle": 0, "ring": 0, "pinky": 1},
    "pinch": None,  # special: thumb tip near index tip
}
DISPLAY_NAMES = {
    "none": "(none)", "open_palm": "Open palm", "fist": "Fist", "point": "Index point", "peace": "Peace / V",
    "three": "Three fingers", "four": "Four fingers (thumb in)", "thumbs_up": "Thumbs up",
    "rock": "Rock (index + pinky)", "call_me": "Call me (thumb + pinky)", "pinch": "Pinch (thumb-index)",
}


def _sig(z):
    return 1 / (1 + math.exp(-z))


def normalize(lm: np.ndarray) -> np.ndarray:
    """(21,3) -> invariant (21,3)."""
    p = np.asarray(lm, float)[:, :3].copy()
    p -= p[WRIST]
    scale = np.linalg.norm(p[MCPS["middle"], :2]) or 1e-6
    p /= scale
    ang = math.atan2(p[MCPS["middle"], 0], -p[MCPS["middle"], 1])  # angle from "up" (image y is down)
    c, s = math.cos(-ang), math.sin(-ang)
    R = np.array([[c, -s], [s, c]])
    p[:, :2] = p[:, :2] @ R.T
    return p


def finger_scores(lm: np.ndarray) -> dict:
    """Probability-like extension score per finger (scale invariant)."""
    p = np.asarray(lm, float)[:, :3]
    palm = np.linalg.norm(p[MCPS["middle"]] - p[WRIST]) or 1e-6
    out = {}
    for f in FINGERS[1:]:
        r = np.linalg.norm(p[TIPS[f]] - p[WRIST]) / (np.linalg.norm(p[PIPS[f]] - p[WRIST]) or 1e-6)
        out[f] = _sig((r - 1.12) * 14)
    # thumb: tip far from index MCP and from palm centre relative to palm size
    d = np.linalg.norm(p[TIPS["thumb"]] - p[MCPS["index"]]) / palm
    d2 = np.linalg.norm(p[TIPS["thumb"]] - p[MCPS["pinky"]]) / palm
    out["thumb"] = _sig((d - 0.55) * 9) * _sig((d2 - 0.9) * 6)
    return out


def feature_vector(lm) -> np.ndarray:
    n = normalize(lm)
    fs = finger_scores(lm)
    return np.concatenate([n[:, :2].ravel(), 0.5 * n[:, 2], [2 * fs[f] for f in FINGERS]])


def classify(lm, custom: dict | None = None) -> dict:
    """Return {gesture_name: confidence in [0,1]} for built-in and custom gestures."""
    fs = finger_scores(lm)
    out = {}
    p = np.asarray(lm, float)[:, :3]
    palm = np.linalg.norm(p[MCPS["middle"]] - p[WRIST]) or 1e-6
    for name, req in BUILTIN.items():
        if req is None:
            continue
        conf = 1.0
        for f, want in req.items():
            conf *= fs[f] if want else (1 - fs[f])
        out[name] = conf
    # thumbs up must actually point up (in normalized-up frame of the image)
    if "thumbs_up" in out:
        up = (p[MCPS["thumb"], 1] - p[TIPS["thumb"], 1]) / palm
        out["thumbs_up"] *= _sig((up - 0.3) * 8)
    pinch_d = np.linalg.norm(p[TIPS["thumb"]] - p[TIPS["index"]]) / palm
    out["pinch"] = _sig((0.35 - pinch_d) * 18)
    if custom:
        fv = feature_vector(lm)
        for name, model in custom.items():
            mean = np.asarray(model["mean"])
            std = np.asarray(model["std"])
            if mean.shape != fv.shape:
                continue
            z = np.abs(fv - mean) / (std + 0.08)
            d = float(np.sqrt(np.mean(z**2)))
            out[name] = float(np.clip(1.3 - d / 2.0, 0, 1))
    return out


def best_gesture(conf: dict):
    if not conf:
        return "none", 0.0
    k = max(conf, key=conf.get)
    return k, float(conf[k])


def learn_custom(samples: list[np.ndarray]) -> dict:
    F = np.array([feature_vector(s) for s in samples])
    return {"mean": F.mean(axis=0).tolist(), "std": F.std(axis=0).tolist(), "n": len(samples)}


@dataclass
class Event:
    kind: str  # "draw_start" | "draw_point" | "draw_end" | "action" | "would_fire"
    data: object = None


class GestureController:
    """Stateful debouncing of gestures into events."""

    def __init__(self, settings, test_mode=False, clock=time.monotonic):
        self.s = settings
        self.test_mode = test_mode
        self.clock = clock
        self.cand = "none"
        self.cand_since = 0.0
        self.fired_for = None  # gesture that must be released before re-firing
        self.last_fire: dict[str, float] = {}
        self.drawing = False
        self.last_draw_seen = 0.0
        self.draw_cand_since = None

    def action_map(self):
        s = self.s
        m = {}
        if s.hide_gesture == s.show_gesture and s.hide_gesture != "none":
            m[s.hide_gesture] = "toggle_overlay"
        else:
            if s.hide_gesture != "none":
                m[s.hide_gesture] = "hide_overlay"
            if s.show_gesture != "none":
                m[s.show_gesture] = "show_overlay"
        if s.panel_toggle_gesture not in ("none", None):
            m.setdefault(s.panel_toggle_gesture, "toggle_panel")
        if s.clear_gesture not in ("none", None):
            m.setdefault(s.clear_gesture, "clear")
        pt = getattr(s, "pen_toggle_gesture", "none")
        if pt not in ("none", None):
            m.setdefault(pt, "toggle_pen")
        dg = self.draw_trigger_gesture()
        if dg:
            m.pop(dg, None)  # drawing always wins: no conflicting actions
        return m

    def draw_trigger_gesture(self):
        """Gesture that puts the pen down in the current mode (None for key mode)."""
        mode = getattr(self.s, "draw_mode", "gesture")
        if mode == "pinch":
            return "pinch"
        if mode == "key":
            return None
        return self.s.draw_gesture

    def conflicts(self):
        s = self.s
        out = []
        dg = self.draw_trigger_gesture()
        for k in ("hide_gesture", "show_gesture", "panel_toggle_gesture", "clear_gesture", "pen_toggle_gesture"):
            if dg and getattr(s, k, "none") == dg:
                out.append(f"{k.replace('_', ' ')} equals the drawing gesture")
        return out

    def update(self, conf: dict | None, tip_uv=None, pen: bool | None = None) -> list[Event]:
        """conf=None means no hand detected.

        pen: external pen state — key held ("key" mode) or pen switched on ("toggle" mode).
        """
        now = self.clock()
        ev: list[Event] = []
        g, c = best_gesture(conf or {})
        thr = self.s.confidence
        draw_conf = (conf or {}).get(self.s.draw_gesture, 0.0)

        # ---- drawing (highest priority) ----
        mode = getattr(self.s, "draw_mode", "gesture")
        gesture_draw = conf is not None and draw_conf >= min(thr, 0.6) and (g == self.s.draw_gesture or draw_conf >= 0.8)
        if conf is None:
            is_draw = False
        elif mode == "pinch":
            # hysteresis: easier to keep drawing than to start, so strokes don't break mid-line
            is_draw = (conf or {}).get("pinch", 0.0) >= (0.3 if self.drawing else min(thr, 0.6))
        elif mode == "key":
            is_draw = bool(pen)
        elif mode == "toggle":
            is_draw = bool(pen) and gesture_draw
        else:
            is_draw = gesture_draw
        if is_draw:
            self.last_draw_seen = now
            if not self.drawing:
                if self.draw_cand_since is None:
                    self.draw_cand_since = now
                if now - self.draw_cand_since >= self.s.draw_hold_s:
                    self.drawing = True
                    ev.append(Event("draw_start"))
            if self.drawing and tip_uv is not None:
                ev.append(Event("draw_point", tip_uv))
            self.cand = "none"
            return ev
        self.draw_cand_since = None
        if self.drawing and now - self.last_draw_seen >= self.s.stroke_end_s:
            self.drawing = False
            ev.append(Event("draw_end"))
        if self.drawing:
            return ev  # brief tracking glitch inside a stroke: ignore other gestures

        # ---- control gestures ----
        amap = self.action_map()
        if conf is None or c < thr or g not in amap:
            if g != self.fired_for:
                self.fired_for = None
            self.cand = "none"
            return ev
        if g != self.cand:
            self.cand, self.cand_since = g, now
        if g == self.fired_for:
            return ev  # must release before firing again
        if now - self.cand_since >= self.s.hold_s:
            action = amap[g]
            if now - self.last_fire.get(action, -1e9) >= self.s.cooldown_s:
                self.last_fire[action] = now
                self.fired_for = g
                ev.append(Event("would_fire" if self.test_mode else "action", action))
        return ev

    def hold_progress(self):
        if self.cand == "none":
            return 0.0
        return float(np.clip((self.clock() - self.cand_since) / max(self.s.hold_s, 1e-3), 0, 1))
