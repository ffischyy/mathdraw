"""Automated tests for recognition, uncertainty, calculus, geometry, gestures and state.

Covers acceptance tests 9, 10, 11 automatically and the logic behind 1-5, 12.
Run:  python -m pytest -q
"""
import math
import os
import sys

import numpy as np
import pytest
import sympy as sp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mathdraw.geometry import View, fit_rect, math_to_px, norm_to_math, px_to_math  # noqa: E402
from mathdraw.gestures import GestureController, classify, feature_vector, learn_custom  # noqa: E402
from mathdraw.math_engine.analyzer import analyze_stroke, curve_polylines, deserialize  # noqa: E402
from mathdraw.math_engine.functions import lambdify  # noqa: E402
from mathdraw.math_engine.grammar import X  # noqa: E402
from mathdraw.math_engine.regression import SearchConfig  # noqa: E402

RNG = np.random.default_rng(7)
CFG = SearchConfig(time_budget_s=6)


def noisy(f, a, b, n=240, rel=0.008):
    x = np.linspace(a, b, n)
    y = f(x)
    return np.c_[x, y + RNG.normal(0, rel * np.ptp(y), n)]


def recovered(res, f, a, b, tol=0.03):
    """Fitted expression matches the true function on the drawn domain."""
    g = lambdify(deserialize(res["exprs"]["main"]), X)
    x = np.linspace(a, b, 400)
    return np.sqrt(np.nanmean((g(x) - f(x)) ** 2)) < tol * np.ptp(f(x))


# --- Acceptance test 10: representative families --------------------------------
CASES = [
    ("quadratic", lambda x: 0.98 * x**2 + 0.12 * x - 0.05, -3, 3),
    ("x^2 sin x", lambda x: x**2 * np.sin(x), -6, 6),
    ("e^-x^2", lambda x: np.exp(-x**2), -3, 3),
    ("ln(x^2+1)", lambda x: np.log(x**2 + 1), -4, 4),
    ("sin x / x", lambda x: np.sin(x) / x, -12, 12),
    ("sqrt(x^2+1)", lambda x: np.sqrt(x**2 + 1), -4, 4),
    ("e^x cos 2x", lambda x: np.exp(x) * np.cos(2 * x), -2, 2),
    ("2^x", lambda x: 2.0**x, -3, 3),
    ("ln(x-1)", lambda x: np.log(x - 1), 1.1, 6),
    ("3 tanh x", lambda x: 3 * np.tanh(x), -4, 4),
    ("sinusoid", lambda x: 3 * np.sin(2 * x + 1) + 1, -4, 4),
    ("|x-1|", lambda x: 2 * np.abs(x - 1), -3, 3),
    ("1/(x-1)", lambda x: 1 / (x - 1), 1.3, 4),
    ("atan", lambda x: 2 * np.arctan(x), -6, 6),
    ("cubic", lambda x: 0.2 * x**3 - x, -3.5, 3.5),
]


@pytest.mark.parametrize("name,f,a,b", CASES, ids=[c[0] for c in CASES])
def test_recognition(name, f, a, b):
    res = analyze_stroke(noisy(f, a, b), CFG, with_calculus=False)
    assert res["ok"] and res["kind"] == "function"
    assert recovered(res, f, a, b), (name, res["latex"])
    assert not res["approximate"]


def test_exact_forms_for_spec_examples():
    exp = {
        "x^2 sin x": x_sym() ** 2 * sp.sin(x_sym()),
        "e^-x^2": sp.exp(-x_sym() ** 2),
        "sin x / x": sp.sin(x_sym()) / x_sym(),
    }
    for name, f, a, b in CASES:
        if name in exp:
            res = analyze_stroke(noisy(f, a, b, rel=0.004), CFG, with_calculus=False)
            e = deserialize(res["exprs"]["main"])
            assert sp.simplify(e - exp[name]) == 0, (name, e)


def x_sym():
    return X


# --- Acceptance test 11: ambiguity reported --------------------------------------
def test_short_arc_is_ambiguous():
    x = np.linspace(0.2, 1.0, 120)
    res = analyze_stroke(np.c_[x, x**2 + RNG.normal(0, 0.01, 120)], CFG, with_calculus=False)
    assert res["ambiguous"]
    assert res["confidence"] < 0.6
    assert res["alternatives"]
    assert r"\approx" in res["latex"]


def test_random_scribble_is_approximation():
    x = np.linspace(-3, 3, 250)
    y = np.cumsum(RNG.normal(0, 0.3, 250))
    res = analyze_stroke(np.c_[x, y], CFG, with_calculus=False)
    assert res["ok"] and (res["approximate"] or res["ambiguous"])


# --- non-function curves -------------------------------------------------------
def test_circle_closed_curve():
    t = np.linspace(0, 2 * np.pi, 200)
    res = analyze_stroke(np.c_[2 * np.cos(t) + 1, 2 * np.sin(t) - 1], CFG, with_calculus=False)
    assert res["kind"] in ("implicit", "polar")
    assert curve_polylines(res, (-5, 5, -5, 5))


def test_cardioid_polar():
    t = np.linspace(0, 2 * np.pi, 250)
    r = 1 + np.cos(t)
    res = analyze_stroke(np.c_[r * np.cos(t), r * np.sin(t)], CFG, with_calculus=False)
    assert res["kind"] == "polar"


def test_sideways_parabola_inverse():
    y = np.linspace(-2, 2, 200)
    res = analyze_stroke(np.c_[y**2, y], CFG, with_calculus=False)
    assert res["kind"] == "inverse"


# --- calculus module ----------------------------------------------------------------
def test_calculus_rational():
    x = np.linspace(1.3, 4, 120)
    res = analyze_stroke(np.c_[x, 1 / (x - 1)], CFG)
    labels = {i["label"]: i["latex"] for i in res["calculus"]["items"]}
    assert "Derivative" in labels and "Antiderivative" in labels
    assert r"\ln" in labels["Antiderivative"] or "log" in labels["Antiderivative"]
    num = res["calculus"]["numbers"]["integral_over_drawn_domain"]
    assert abs(num["quad"] - math.log(3 / 0.3)) < 1e-3
    assert num["simp_32_err"] < num["trap_8_err"]


def test_improper_gaussian():
    res = analyze_stroke(noisy(lambda x: np.exp(-x**2), -3, 3, rel=0.003), CFG)
    labels = [i["latex"] for i in res["calculus"]["items"] if i["label"] == "Improper integral"]
    assert any(r"\sqrt{\pi}" in l for l in labels)


# --- Acceptance test 9: resizing keeps math consistent ------------------------------
def test_resize_consistency():
    v = View(cx=1.5, cy=-0.5, half_w=6, aspect=16 / 9)
    for w, h in ((1280, 720), (800, 900), (1920, 600), (333, 777)):
        rect = fit_rect(w, h, v.aspect)
        assert abs(rect[2] / rect[3] - v.aspect) < 1e-9
        for x, y in ((0, 0), (3.2, -1.1), (-5, 2)):
            px, py = math_to_px(x, y, v, rect)
            x2, y2 = px_to_math(px, py, v, rect)
            assert abs(x - x2) < 1e-9 and abs(y - y2) < 1e-9
    # stroke stored in math coords is independent of widget size
    assert norm_to_math(0.5, 0.5, v) == (1.5, -0.5)


# --- gestures -----------------------------------------------------------------------
def synthetic_hand(ext=(1, 1, 1, 1, 1), scale=0.2, shift=(0.5, 0.6), rot=0.0):
    """Crude 2D hand: fingers fanned upward; folded fingers curl back to the palm."""
    pts = np.zeros((21, 3))
    base = {"thumb": (1, -0.9), "index": (5, -0.35), "middle": (9, 0.0), "ring": (13, 0.3), "pinky": (17, 0.55)}
    mcp_pos = {"thumb": (-0.35, -0.25), "index": (-0.2, -0.9), "middle": (0.0, -1.0), "ring": (0.2, -0.95), "pinky": (0.38, -0.85)}
    for k, f in enumerate(["thumb", "index", "middle", "ring", "pinky"]):
        i0 = base[f][0]
        mx, my = mcp_pos[f]
        ang = base[f][1]
        dx, dy = math.sin(ang), -math.cos(ang)
        if f == "thumb":
            dx, dy = (-0.8, -0.6) if ext[k] else (0.6, -0.2)
            pts[1] = (-0.2, -0.15, 0)
            pts[2] = (mx, my, 0)
            if ext[k]:
                pts[3] = (mx + 0.3 * dx, my + 0.3 * dy, 0)
                pts[4] = (mx + 0.6 * dx, my + 0.6 * dy, 0)
            else:
                pts[3] = (mx + 0.25, my - 0.2, 0)
                pts[4] = (0.0, -0.75, 0)
            continue
        pts[i0] = (mx, my, 0)
        if ext[k]:
            for j in range(1, 4):
                pts[i0 + j] = (mx + 0.33 * j * dx, my + 0.33 * j * dy, 0)
        else:
            pts[i0 + 1] = (mx + 0.25 * dx, my + 0.25 * dy, 0)
            pts[i0 + 2] = (mx + 0.1 * dx, my - 0.05, 0)
            pts[i0 + 3] = (mx * 0.7, my * 0.55, 0)
    c, s = math.cos(rot), math.sin(rot)
    xy = pts[:, :2] @ np.array([[c, -s], [s, c]]).T
    pts[:, :2] = xy * scale + np.array(shift)
    return pts


def test_gesture_classification_scale_invariant():
    for scale in (0.08, 0.2, 0.4):
        for rot in (-0.4, 0.0, 0.4):
            palm = classify(synthetic_hand((1, 1, 1, 1, 1), scale, rot=rot))
            fist = classify(synthetic_hand((0, 0, 0, 0, 0), scale, rot=rot))
            point = classify(synthetic_hand((0, 1, 0, 0, 0), scale, rot=rot))
            assert max(palm, key=palm.get) == "open_palm"
            assert max(fist, key=fist.get) == "fist"
            assert max(point, key=point.get) == "point"


def test_feature_vector_invariance():
    a = feature_vector(synthetic_hand(scale=0.1, shift=(0.3, 0.3)))
    b = feature_vector(synthetic_hand(scale=0.35, shift=(0.7, 0.5)))
    assert np.allclose(a, b, atol=1e-6)


def test_custom_gesture_learning():
    samples = [synthetic_hand((0, 1, 1, 0, 1), 0.2) + RNG.normal(0, 0.002, (21, 3)) for _ in range(30)]
    model = learn_custom(samples)
    conf = classify(synthetic_hand((0, 1, 1, 0, 1), 0.3), {"mine": model})
    assert conf["mine"] > 0.8
    conf2 = classify(synthetic_hand((1, 1, 1, 1, 1), 0.3), {"mine": model})
    assert conf2["mine"] < conf["mine"]


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _gs(**kw):
    from mathdraw.state import GestureSettings

    g = GestureSettings()
    for k, v in kw.items():
        setattr(g, k, v)
    return g


def test_hold_cooldown_and_release():
    clk = FakeClock()
    c = GestureController(_gs(hold_s=0.8, cooldown_s=1.5), clock=clk)
    palm = {"open_palm": 0.95}
    fired = []
    for i in range(60):  # 3 s holding open palm at 20 fps
        clk.t = i * 0.05
        fired += [e.data for e in c.update(palm) if e.kind == "action"]
    assert fired == ["hide_overlay"]  # held longer than cooldown: still once (needs release)
    for i in range(10):
        clk.t = 3 + i * 0.05
        c.update({"fist": 0.3})  # release
    for i in range(30):
        clk.t = 4 + i * 0.05
        fired += [e.data for e in c.update({"thumbs_up": 0.9}) if e.kind == "action"]
    assert fired == ["hide_overlay", "show_overlay"]


def test_short_flash_does_not_fire():
    clk = FakeClock()
    c = GestureController(_gs(hold_s=0.8), clock=clk)
    ev = []
    for i in range(10):  # 0.45 s only
        clk.t = i * 0.05
        ev += c.update({"open_palm": 0.95})
    assert not [e for e in ev if e.kind == "action"]


def test_drawing_has_priority_and_conflicts_detected():
    clk = FakeClock()
    s = _gs(hide_gesture="point", draw_mode="gesture")
    c = GestureController(s, clock=clk)
    assert c.conflicts()
    kinds = []
    for i in range(40):
        clk.t = i * 0.05
        kinds += [e.kind for e in c.update({"point": 0.95}, (0.5, 0.5))]
    assert "action" not in kinds and "draw_start" in kinds
    for i in range(20):
        clk.t = 2 + i * 0.05
        kinds += [e.kind for e in c.update(None)]  # hand lost ends stroke
    assert kinds.count("draw_end") == 1


def test_test_mode_never_acts():
    clk = FakeClock()
    c = GestureController(_gs(), test_mode=True, clock=clk)
    ev = []
    for i in range(40):
        clk.t = i * 0.05
        ev += c.update({"open_palm": 0.95})
    assert [e.kind for e in ev] == ["would_fire"]


# --- state persistence (acceptance 1-4, 12 logic) -----------------------------------
def test_state_persistence(tmp_path):
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    from mathdraw.state import StateManager

    path = str(tmp_path / "s.json")
    s = StateManager(path)
    s.set_result({"ok": True, "latex": "f(x) = x^{2}"}, [[0, 0], [1, 1]])
    s.set_overlay_visible(False)  # hiding never deletes data
    assert s.p.last_result and s.p.last_stroke
    s.set_tracking(hand_detected=False, drawing_active=False)  # losing the hand doesn't clear it
    assert s.p.last_result["latex"] == "f(x) = x^{2}"
    s.d.grid_opacity = 0.12
    s.g.hide_gesture = "fist"
    s.save()
    s2 = StateManager(path)
    s2.load()
    assert s2.p.last_result["latex"] == "f(x) = x^{2}"
    assert s2.p.overlay_visible is False and s2.d.grid_opacity == 0.12 and s2.g.hide_gesture == "fist"
    s2.set_overlay_visible(True)
    assert s2.p.last_result is not None


# --- drawing trigger modes (pen up / pen down control) -------------------------------
def _run(c, clk, conf, pen=None, n=20, t0=0.0, tip=(0.5, 0.5)):
    kinds = []
    for i in range(n):
        clk.t = t0 + i * 0.05
        kinds += [e.kind for e in c.update(conf, tip, pen)]
    return kinds


def test_pinch_mode_pointing_does_not_draw():
    clk = FakeClock()
    c = GestureController(_gs(draw_mode="pinch"), clock=clk)
    assert "draw_start" not in _run(c, clk, {"point": 0.95, "pinch": 0.05})
    k = _run(c, clk, {"point": 0.9, "pinch": 0.9}, t0=2)
    assert "draw_start" in k and "draw_point" in k
    # slight loosening of the pinch keeps drawing (hysteresis); full release lifts the pen
    assert "draw_end" not in _run(c, clk, {"pinch": 0.45}, t0=4)
    assert "draw_end" in _run(c, clk, {"point": 0.9, "pinch": 0.05}, t0=6)


def test_key_mode_draws_only_while_held():
    clk = FakeClock()
    c = GestureController(_gs(draw_mode="key"), clock=clk)
    assert "draw_start" not in _run(c, clk, {"point": 0.95}, pen=False)
    assert "draw_start" in _run(c, clk, {"open_palm": 0.9}, pen=True, t0=2)  # any pose while key held
    assert "draw_end" in _run(c, clk, {"point": 0.95}, pen=False, t0=4)


def test_toggle_mode_requires_pen_on():
    clk = FakeClock()
    c = GestureController(_gs(draw_mode="toggle"), clock=clk)
    assert "draw_start" not in _run(c, clk, {"point": 0.95}, pen=False)
    assert "draw_start" in _run(c, clk, {"point": 0.95}, pen=True, t0=2)


def test_pinch_classifier_scale_invariant():
    for scale in (0.08, 0.3):
        h = synthetic_hand((1, 1, 0, 0, 0), scale)
        h[4] = h[8] + (h[8] - h[0]) * 0.02  # thumb tip touching index tip
        assert classify(h)["pinch"] > 0.9
        assert classify(synthetic_hand((1, 1, 1, 1, 1), scale))["pinch"] < 0.2


# --- auto-smoothing --------------------------------------------------------------------
from mathdraw.math_engine.smoothing import roughness, smooth_pair, smooth_stroke  # noqa: E402


def _tremor(rng, n, amp):
    return np.convolve(rng.normal(0, 1, n + 20), np.ones(7) / 7, "same")[10:-10] * amp * 2.6


def test_smoothing_removes_shake_and_keeps_endpoints():
    rng = np.random.default_rng(1)
    x = np.linspace(-3, 3, 200)
    raw = np.c_[x + _tremor(rng, 200, 0.06), 0.5 * x**2 - 2 + _tremor(rng, 200, 0.06)]
    sm = smooth_stroke(raw, 0.5)
    assert roughness(sm) < 0.2 * roughness(raw)
    assert np.allclose(sm[0], raw[0]) and np.allclose(sm[-1], raw[-1])
    assert np.allclose(smooth_stroke(raw, 0), raw)


def test_smoothing_preserves_shape():
    x = np.linspace(-3, 3, 200)
    clean = np.c_[x, np.sin(x)]
    q, sm = smooth_pair(clean, 0.5)
    assert np.max(np.abs(sm - q)) < 0.05  # a clean curve is barely changed


def test_shaky_stroke_becomes_clean_function():
    rng = np.random.default_rng(4)
    x = np.linspace(-4, 4, 160)
    t = _tremor(rng, 160, 0.1)
    pts = np.c_[x + 0.6 * t, 0.4 * x**2 - 3 + t]
    res = analyze_stroke(pts, SearchConfig(time_budget_s=5, smoothing=0.5), with_calculus=False)
    assert res["kind"] == "function" and res["model"].startswith("Quadratic"), res["model"]
    assert recovered(res, lambda v: 0.4 * v**2 - 3, -4, 4)
    assert res["jitter"] > 0


def test_smoothing_fixes_backtracking_classification():
    """Shake that makes a left-to-right stroke step backwards must still be read as y = f(x)."""
    rng = np.random.default_rng(2)
    x = np.linspace(-3, 3, 220)
    t = np.convolve(rng.normal(0, 1, 240), np.ones(5) / 5, "same")[10:-10] * 0.2 * 2.2
    pts = np.c_[x + t, np.sin(x) + rng.normal(0, 0.02, 220)]
    from mathdraw.math_engine.regression import classify_stroke

    assert classify_stroke(pts) != "function"  # raw shake looks like a scribble
    res = analyze_stroke(pts, SearchConfig(time_budget_s=4, smoothing=0.5), with_calculus=False)
    assert res["kind"] == "function"
    assert recovered(res, np.sin, -3, 3, tol=0.05)


def test_plain_text_export():
    from mathdraw.math_engine.analyzer import plain_text

    x = np.linspace(-3, 3, 150)
    res = analyze_stroke(np.c_[x, 0.5 * x**2 - 1], CFG, with_calculus=False)
    assert plain_text(res).replace(" ", "") in ("f(x)=x**2/2-1", "f(x)=0.5*x**2-1")


# --- zoom & grid -----------------------------------------------------------------------
from mathdraw.geometry import (equal_axes, fit_points, format_tick, grid_steps, grid_values, reset_view,  # noqa: E402
                               set_window, zoom)


def test_zoom_about_point_and_single_axis():
    v = View()
    zoom(v, 0.5, about=(4.0, 1.0))
    xmin, xmax, ymin, ymax = v.bounds()
    assert abs((xmax - xmin) - 8) < 1e-9
    # the anchor stays at the same relative screen position
    assert abs((4.0 - xmin) / (xmax - xmin) - 0.75) < 1e-9
    h = v.half_h
    zoom(v, 0.5, axis="x")
    assert abs(v.half_h - h) < 1e-9 and abs(v.half_w - 2) < 1e-9
    zoom(v, 2, axis="y")
    assert abs(v.half_h - 2 * h) < 1e-9 and abs(v.half_w - 2) < 1e-9
    equal_axes(v)
    assert v.y_ratio == 1.0
    reset_view(v)
    assert v.bounds()[:2] == (-8.0, 8.0)


def test_set_window_and_resize_consistency():
    v = View(aspect=16 / 9)
    set_window(v, -1, 1, -50, 50)
    assert np.allclose(v.bounds(), (-1, 1, -50, 50))
    for w, h in ((1280, 720), (500, 900)):
        rect = fit_rect(w, h, v.aspect)
        px = math_to_px(0.5, 25, v, rect)
        assert np.allclose(px_to_math(*px, v, rect), (0.5, 25))
    with pytest.raises(ValueError):
        set_window(v, 1, -1, 0, 1)


def test_fit_points():
    v = View()
    fit_points(v, [(10, 10), (14, 12)])
    xmin, xmax, ymin, ymax = v.bounds()
    assert xmin <= 10 and xmax >= 14 and ymin <= 10 and ymax >= 12


def test_grid_spacing_auto_custom_and_pi():
    v = View()
    sx, sy, mx, my, c = grid_steps(v)
    assert sx == sy == 1 and not c
    sx, sy, mx, my, c = grid_steps(v, density="coarse", minor=5)
    assert sx == 2 and abs(mx - 0.4) < 1e-12
    sx, sy, *_ , c = grid_steps(v, mode="custom", step_x=0.5, step_y=0.25)
    assert (sx, sy, c) == (0.5, 0.25, False)
    # an absurdly fine custom grid is widened instead of drawing 100k lines
    sx, sy, *_, c = grid_steps(v, mode="custom", step_x=1e-4, step_y=1e-4)
    assert c and 16 / sx <= 300
    sx, *_ = grid_steps(v, mode="custom", step_x=0.5, x_pi=True)
    assert abs(sx - math.pi / 2) < 1e-12
    assert [format_tick(t, math.pi / 2, True) for t in grid_values(-3.5, 3.5, math.pi / 2)] == ["-π", "-π/2", "0", "π/2", "π"]
    assert [format_tick(t, 0.25) for t in grid_values(-0.5, 0.5, 0.25)] == ["-0.5", "-0.25", "0", "0.25", "0.5"]
    assert format_tick(0.1 + 0.2, 0.1) == "0.3"


# --- licensing ---------------------------------------------------------------------------
def test_license_sign_verify_and_trial():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from mathdraw import licensing as L

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    key = L.sign_license(priv, "Ada Lovelace", "ada@example.com")
    assert L.verify_license(key, pub)["n"] == "Ada Lovelace"
    # e-mail clients may wrap the key
    assert L.verify_license(key[:30] + "\n  " + key[30:], pub)
    # tampering (e.g. changing the name) breaks the signature
    body, sig = key[len(L.KEY_PREFIX):].split(".")
    import base64
    import json

    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["n"] = "Mallory"
    forged = L.KEY_PREFIX + L._b64e(json.dumps(payload, separators=(",", ":")).encode()) + "." + sig
    assert L.verify_license(forged, pub) is None
    # a key signed by someone else is rejected
    other = Ed25519PrivateKey.generate()
    assert L.verify_license(L.sign_license(other, "x", "y"), pub) is None
    now = 1_800_000_000
    assert L.evaluate("", now - 3 * 86400, now, pub).state == "trial"
    assert L.evaluate("", now - 3 * 86400, now, pub).days_left == L.TRIAL_DAYS - 3
    assert L.evaluate("", now - (L.TRIAL_DAYS + 1) * 86400, now, pub).state == "expired"
    assert L.evaluate(key, now - 999 * 86400, now, pub).state == "licensed"
    assert L.evaluate("", 0, now, None).state == "disabled"
