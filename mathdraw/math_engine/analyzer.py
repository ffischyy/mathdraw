"""Top-level stroke analysis: chooses the curve representation and builds a
JSON-serialisable result (so the last successful equation can persist)."""
from __future__ import annotations

import math
import time

import numpy as np
import sympy as sp

from . import calculus
from .functions import lambdify
from .grammar import X, pretty_name
from .regression import (THETA, T_SYM, Y_SYM, SearchConfig, circle_expr, classify_stroke, conic_expr,
                         fit_conic, parametric_templates, polar_templates, resample_function,
                         round_for_display, search_function)
from .render_util import to_latex
from .smoothing import jitter_sigma, smooth_pair, vertical_jitter

LOCALS = {"x": X, "t": T_SYM, "theta": THETA, "y": Y_SYM}


def _ser(e):
    return sp.srepr(e)


def deserialize(s):
    from .functions import RealCbrt

    ns = {k: getattr(sp, k) for k in dir(sp) if not k.startswith("_")}
    ns["RealCbrt"] = RealCbrt
    return eval(s, ns)  # srepr round-trip of our own data only


def _alts(fs, lhs, subs=None, start=1):
    out = []
    for f, w in list(zip(fs.ranked, fs.weights))[start:]:
        if f.expr is None:
            continue
        e = f.expr.xreplace(subs) if subs else f.expr
        out.append({"latex": f"{lhs} \\approx " + to_latex(e), "model": pretty_name(f.template.name),
                    "weight": float(w), "complexity": int(f.template.complexity), "rmse": math.sqrt(f.mse)})
    return out


def analyze_stroke(points, cfg: SearchConfig | None = None, with_calculus=True):
    """points: (N,2) math coordinates in drawing order."""
    cfg = cfg or SearchConfig()
    p = np.asarray(points, float)
    p = p[np.isfinite(p).all(axis=1)]
    if len(p) < 10:
        return {"ok": False, "error": "Not enough points"}
    t0 = time.monotonic()
    # Auto-smoothing: the de-jittered stroke decides what kind of curve this is
    # (shake can make a left-to-right stroke step backwards), and drives the
    # parametric fit.  Explicit/closed fits use the raw points: their noise
    # model expects real tracking noise, and smoothing would shrink circles.
    if cfg.smoothing > 0:
        q, sm = smooth_pair(p, cfg.smoothing)
        jit = jitter_sigma(q, sm)
    else:
        sm, jit = p, 0.0
    kind = classify_stroke(sm)
    vj = {0: vertical_jitter(p, sm, 0), 1: vertical_jitter(p, sm, 1)} if cfg.smoothing > 0 else {0: 0.0, 1: 0.0}
    res = None
    if kind == "function":
        res = _explicit(p[:, 0], p[:, 1], cfg, inverse=False, sigma_floor=vj[0])
    elif kind == "inverse":
        res = _explicit(p[:, 1], p[:, 0], cfg, inverse=True, sigma_floor=vj[1])
    elif kind == "closed":
        res = _closed(p, cfg)
    if res is None:
        res = _parametric(sm, cfg)
    if res is None:
        return {"ok": False, "error": "No model could be fitted"}
    res["smoothing"] = float(cfg.smoothing)
    res["jitter"] = jit
    res["ok"] = True
    res["stroke_type"] = kind
    res["elapsed_s"] = round(time.monotonic() - t0, 2)
    res["timestamp"] = time.time()
    if with_calculus:
        try:
            res["calculus"] = run_calculus(res)
        except Exception as e:  # never fail recognition because of the calculus module
            res["calculus"] = {"items": [], "error": str(e)}
    return res


def _metrics(fs):
    return {"rmse": math.sqrt(fs.best.mse), "nrmse": fs.nrmse, "r2": fs.r2, "sigma": fs.sigma,
            "n_models": fs.n_evaluated}


def _explicit(xv, yv, cfg, inverse, sigma_floor=0.0):
    x, y = resample_function(xv, yv)
    fs = search_function(x, y, cfg, sigma_floor=sigma_floor)
    if fs is None:
        return None
    lhs = "x" if inverse else "f(x)"
    expr = fs.best.expr
    if inverse:
        expr_disp = expr.xreplace({X: Y_SYM})
        lhs_full = "x"
        latex = r"x \approx " + to_latex(expr_disp)
    else:
        expr_disp = expr
        latex = (r"f(x) \approx " if fs.approximate or fs.ambiguous else r"f(x) = ") + to_latex(expr)
    alts = _alts(fs, "x" if inverse else "f(x)", {X: Y_SYM} if inverse else None)
    return {
        "kind": "inverse" if inverse else "function",
        "model": pretty_name(fs.best.template.name) + (" (x as a function of y)" if inverse else ""),
        "latex": latex,
        "exprs": {"main": _ser(expr)},
        "domain": [float(x.min()), float(x.max())],
        "metrics": _metrics(fs),
        "confidence": float(fs.confidence),
        "ambiguous": bool(fs.ambiguous),
        "approximate": bool(fs.approximate),
        "truncated": bool(fs.truncated),
        "alternatives": alts,
        "best_complexity": int(fs.best.template.complexity),
        "equivalents": [to_latex(f.expr) for f in fs.equivalents if f.expr is not None],
    }


def _polar_fit(p, centre, cfg, budget):
    d = p - centre
    th = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    r = np.hypot(d[:, 0], d[:, 1])
    if np.ptp(th) < math.pi:  # must sweep enough angle
        return None
    if np.any(np.diff(th) * np.sign(th[-1] - th[0]) < -0.15):
        return None
    o = np.argsort(th)
    tth, rr = th[o], r[o]
    tt, rs = resample_function(tth, rr, 180)
    fs = search_function(tt, rs, cfg, templates=polar_templates(cfg), budget_s=budget)
    if fs is None:
        return None
    return fs, (float(tt.min()), float(tt.max()))


def _closed(p, cfg):
    x, y = p[:, 0], p[:, 1]
    vec, samp, kind = fit_conic(x, y)
    h, k, rad, crms = circle_expr(x, y)
    diam = float(np.max(np.ptp(p, axis=0)))
    cands = []
    xs, ys = sp.symbols("x y", real=True)
    if crms < max(1.15 * samp, 0.012 * diam):
        Fe = (xs - sp.Float(h)) ** 2 + (ys - sp.Float(k)) ** 2 - sp.Float(rad) ** 2
        lat = to_latex(round_for_display((xs - sp.Float(h)) ** 2 + (ys - sp.Float(k)) ** 2)) + " = " + to_latex(sp.Float(rad) ** 2)
        cands.append(("implicit", "Circle", crms, {"F": _ser(Fe)}, lat, 3))
    Fe, xs, ys = conic_expr(vec)
    cands.append(("implicit", kind + " (general conic)", samp, {"F": _ser(Fe)}, to_latex(round_for_display(Fe, 3)) + " = 0", 6))
    cfg2 = SearchConfig(**{**cfg.__dict__, "time_budget_s": min(2.0, cfg.time_budget_s / 2)})
    for centre in (np.array([0.0, 0.0]), p.mean(axis=0)):
        pf = _polar_fit(p, centre, cfg2, cfg2.time_budget_s / 2)
        if pf:
            fs, rng = pf
            e = fs.best.expr.xreplace({X: THETA})
            at = "" if np.allclose(centre, 0) else " about (%.3g, %.3g)" % tuple(centre)
            cands.append(("polar", "Polar curve" + at + ": " + pretty_name(fs.best.template.name), math.sqrt(fs.best.mse),
                          {"r": _ser(e)}, r"r(\theta) \approx " + to_latex(e), fs.best.k,
                          {"centre": centre.tolist(), "domain": list(rng)}))
    # choose by error with a mild complexity penalty
    def score(c):
        return c[2] / max(diam, 1e-9) + 0.002 * c[5]

    cands.sort(key=score)
    best = cands[0]
    extra = best[6] if len(best) > 6 else {}
    nrmse = best[2] / max(diam, 1e-9)
    res = {
        "kind": best[0], "model": best[1], "latex": best[4], "exprs": best[3],
        "domain": extra.get("domain", [0, 2 * math.pi]), "centre": extra.get("centre", [0, 0]),
        "metrics": {"rmse": best[2], "nrmse": nrmse, "r2": None, "sigma": None},
        "ambiguous": len(cands) > 1 and score(cands[1]) - score(best) < 0.004,
        "approximate": nrmse > cfg.approx_threshold,
        "truncated": False,
        "alternatives": [{"latex": c[4], "model": c[1], "weight": None} for c in cands[1:4]],
        "equivalents": [],
    }
    w = np.array([math.exp(-(score(c) - score(best)) * 300) for c in cands])
    res["confidence"] = float(w[0] / w.sum())
    for a, wi in zip(res["alternatives"], w[1:] / w.sum()):
        a["weight"] = float(wi)
    return res


def _parametric(p, cfg):
    seg = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
    if seg[-1] <= 0:
        return None
    t = seg / seg[-1]
    cfgp = SearchConfig(**{**cfg.__dict__, "time_budget_s": cfg.time_budget_s / 2})
    tmpl = parametric_templates(cfg)
    fx = search_function(t, p[:, 0], cfgp, templates=tmpl)
    fy = search_function(t, p[:, 1], cfgp, templates=tmpl)
    if fx is None or fy is None:
        return None
    xe = fx.best.expr.xreplace({X: T_SYM})
    ye = fy.best.expr.xreplace({X: T_SYM})
    rmse = math.sqrt(fx.best.mse + fy.best.mse)
    diam = float(np.max(np.ptp(p, axis=0))) or 1
    return {
        "kind": "parametric",
        "model": f"Parametric curve (x: {pretty_name(fx.best.template.name)}, y: {pretty_name(fy.best.template.name)})",
        "latex": r"x(t) \approx " + to_latex(xe) + r",\quad y(t) \approx " + to_latex(ye),
        "exprs": {"x": _ser(xe), "y": _ser(ye)},
        "domain": [0.0, 1.0],
        "metrics": {"rmse": rmse, "nrmse": rmse / diam, "r2": None, "sigma": None},
        "confidence": float(fx.confidence * fy.confidence),
        "ambiguous": bool(fx.ambiguous or fy.ambiguous),
        "approximate": True if rmse / diam > cfg.approx_threshold else bool(fx.approximate or fy.approximate),
        "truncated": bool(fx.truncated or fy.truncated),
        "alternatives": [], "equivalents": [],
        "note": "t is normalised arc length of the drawn stroke (0 at start, 1 at end).",
    }


def run_calculus(res):
    k = res["kind"]
    if k in ("function",):
        e = deserialize(res["exprs"]["main"])
        return calculus.analyze_function(e, X, res["domain"])
    if k == "inverse":
        e = deserialize(res["exprs"]["main"])
        out = calculus.analyze_function(e, X, res["domain"])
        for it in out["items"]:
            it["latex"] = it["latex"].replace("f", "g")
        out["note"] = "Calculus is reported for x = g(y) (variable shown as x)."
        return out
    if k == "parametric":
        return calculus.analyze_parametric(deserialize(res["exprs"]["x"]), deserialize(res["exprs"]["y"]), T_SYM, res["domain"])
    if k == "polar":
        return calculus.analyze_polar(deserialize(res["exprs"]["r"]), THETA, res["domain"])
    if k == "implicit":
        xs, ys = sp.symbols("x y", real=True)
        return calculus.analyze_implicit(deserialize(res["exprs"]["F"]), xs, ys)
    return {"items": []}


# ---------------------------------------------------------------------------
# sampling the fitted curve for drawing
# ---------------------------------------------------------------------------
def curve_polylines(res, bounds, n=900):
    """Return list of (N,2) arrays in math coordinates. bounds=(xmin,xmax,ymin,ymax)."""
    if not res or not res.get("ok"):
        return []
    xmin, xmax, ymin, ymax = bounds
    k = res["kind"]
    try:
        if k in ("function", "inverse"):
            f = lambdify(deserialize(res["exprs"]["main"]), X)
            lo, hi = (xmin, xmax) if k == "function" else (ymin, ymax)
            s = np.linspace(lo, hi, n)
            v = f(s)
            pts = np.column_stack([s, v]) if k == "function" else np.column_stack([v, s])
            span = (ymax - ymin) if k == "function" else (xmax - xmin)
            col = 1 if k == "function" else 0
            bad = ~np.isfinite(pts[:, col]) | (np.abs(pts[:, col]) > 1e6)
            jump = np.r_[False, np.abs(np.diff(pts[:, col])) > 2.5 * span]
            return _split(pts, bad | jump)
        if k == "parametric":
            t = np.linspace(*res["domain"], n)
            xs = lambdify(deserialize(res["exprs"]["x"]), T_SYM)(t)
            ys = lambdify(deserialize(res["exprs"]["y"]), T_SYM)(t)
            pts = np.column_stack([xs, ys])
            return _split(pts, ~np.isfinite(pts).all(axis=1))
        if k == "polar":
            a, b = res["domain"]
            th = np.linspace(a, b, n)
            r = lambdify(deserialize(res["exprs"]["r"]), THETA)(th)
            c = res.get("centre", [0, 0])
            pts = np.column_stack([c[0] + r * np.cos(th), c[1] + r * np.sin(th)])
            return _split(pts, ~np.isfinite(pts).all(axis=1))
        if k == "implicit":
            xs, ys = sp.symbols("x y", real=True)
            F = sp.lambdify((xs, ys), deserialize(res["exprs"]["F"]), "numpy")
            gx, gy = np.meshgrid(np.linspace(xmin, xmax, 300), np.linspace(ymin, ymax, 300))
            Z = F(gx, gy)
            from contourpy import contour_generator

            cg = contour_generator(gx, gy, Z)
            return [np.asarray(l) for l in cg.lines(0) if len(l) > 1]
    except Exception:
        return []
    return []


def _split(pts, bad):
    out, cur = [], []
    for p, b in zip(pts, bad):
        if b:
            if len(cur) > 1:
                out.append(np.array(cur))
            cur = []
        else:
            cur.append(p)
    if len(cur) > 1:
        out.append(np.array(cur))
    return out


def plain_text(res):
    """Copy-friendly plain-text form of a result, e.g. 'f(x) = 0.4*x**2 - 3'."""
    if not res or not res.get("ok"):
        return ""
    rel = "≈" if (res.get("approximate") or res.get("ambiguous")) else "="
    k = res["kind"]
    try:
        if k == "function":
            return f"f(x) {rel} " + sp.sstr(round_for_display(deserialize(res["exprs"]["main"]), 4))
        if k == "inverse":
            return f"x {rel} " + sp.sstr(round_for_display(deserialize(res["exprs"]["main"]).xreplace({X: Y_SYM}), 4))
        if k == "parametric":
            return (f"x(t) {rel} " + sp.sstr(round_for_display(deserialize(res["exprs"]["x"]), 4)) +
                    f";  y(t) {rel} " + sp.sstr(round_for_display(deserialize(res["exprs"]["y"]), 4)) + "   (0 <= t <= 1)")
        if k == "polar":
            return f"r(theta) {rel} " + sp.sstr(round_for_display(deserialize(res["exprs"]["r"]), 4))
        if k == "implicit":
            return sp.sstr(round_for_display(deserialize(res["exprs"]["F"]), 4)) + " = 0"
    except Exception:
        pass
    return res.get("latex", "")
