"""Symbolic/numeric calculus on an identified expression (separate from recognition).

Every SymPy call that can be slow runs under a timeout; failures are reported
as "not determined" rather than guessed.
"""
from __future__ import annotations

import math
import threading

import numpy as np
import sympy as sp
from scipy import integrate as sint
from scipy.optimize import brentq

from .functions import lambdify


def with_timeout(fn, seconds, default=None):
    out = {"v": default}

    def run():
        try:
            out["v"] = fn()
        except Exception:
            out["v"] = default

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(seconds)
    return out["v"] if not th.is_alive() else default


def L(e):
    from .render_util import to_latex

    return to_latex(e)


_RULE_NAMES = {
    "URule": "u-substitution",
    "PartsRule": "integration by parts",
    "CyclicPartsRule": "cyclic integration by parts",
    "TrigSubstitutionRule": "trigonometric substitution",
    "PartialFractionRule": "partial fractions",
    "RewriteRule": "algebraic rewrite",
    "ExpRule": "exponential rule",
    "PowerRule": "power rule",
    "TrigRule": "basic trig integral",
    "ArctanRule": "arctan form",
    "ArcsinRule": "arcsin form",
    "ReciprocalRule": "logarithm (1/u) rule",
}


def integration_techniques(expr, x):
    try:
        from sympy.integrals.manualintegrate import integral_steps
    except Exception:
        return []
    steps = with_timeout(lambda: integral_steps(expr, x), 3.0)
    found = []

    def walk(s, depth=0):
        if s is None or depth > 40:
            return
        name = type(s).__name__
        if name in _RULE_NAMES and _RULE_NAMES[name] not in found:
            found.append(_RULE_NAMES[name])
        for attr in getattr(s, "__dataclass_fields__", {}) or {}:
            v = getattr(s, attr, None)
            if isinstance(v, (list, tuple)):
                for it in v:
                    if hasattr(it, "__dataclass_fields__"):
                        walk(it, depth + 1)
            elif hasattr(v, "__dataclass_fields__"):
                walk(v, depth + 1)

    walk(steps)
    if steps is not None and type(steps).__name__ == "DontKnowRule":
        return []
    return found


def numeric_integral_report(f, a, b):
    """Quadrature with trapezoid/Simpson comparison (numerical approximation & error)."""
    xs = np.linspace(a, b, 2001)
    ys = f(xs)
    if not np.all(np.isfinite(ys)):
        return None
    ref, est_err = sint.quad(lambda t: float(f(np.array([t]))[0]), a, b, limit=200)
    rep = {"quad": ref, "quad_err": est_err}
    for n in (8, 32):
        xn = np.linspace(a, b, n + 1)
        yn = f(xn)
        tr = float(np.trapezoid(yn, xn)) if hasattr(np, "trapezoid") else float(np.trapz(yn, xn))
        si = float(sint.simpson(yn, x=xn))
        rep[f"trap_{n}"] = tr
        rep[f"simp_{n}"] = si
        rep[f"trap_{n}_err"] = abs(tr - ref)
        rep[f"simp_{n}_err"] = abs(si - ref)
    return rep


def analyze_function(expr, x, domain):
    a, b = map(float, domain)
    out = {"items": [], "numbers": {}}
    items = out["items"]
    f = lambdify(expr, x)

    def add(label, latex):
        items.append({"label": label, "latex": latex})

    d1 = with_timeout(lambda: sp.simplify(sp.diff(expr, x)), 3.0) or sp.diff(expr, x)
    add("Derivative", r"f'(x) = " + L(d1))
    d2 = with_timeout(lambda: sp.simplify(sp.diff(d1, x)), 3.0)
    if d2 is not None:
        add("Second derivative", r"f''(x) = " + L(d2))

    anti = with_timeout(lambda: sp.integrate(expr, x), 6.0)
    if anti is not None and not anti.has(sp.Integral):
        add("Antiderivative", r"\int f(x)\,dx = " + L(anti) + r" + C")
    else:
        add("Antiderivative", r"\mathrm{no\ elementary\ form\ found\ (timeout\ or\ non\text{-}elementary)}")
    tech = integration_techniques(expr, x)
    if tech:
        out["techniques"] = tech

    rep = numeric_integral_report(f, a, b)
    if rep:
        out["numbers"]["integral_over_drawn_domain"] = rep
        add("Definite integral (drawn domain)",
            r"\int_{%.3g}^{%.3g} f(x)\,dx \approx %.6g" % (a, b, rep["quad"]))

    # tangent line at the domain midpoint
    x0 = 0.5 * (a + b)
    fx0 = f(np.array([x0]))[0]
    df = lambdify(d1, x)(np.array([x0]))[0]
    if np.isfinite(fx0) and np.isfinite(df):
        add("Tangent line at midpoint", r"y = %.4g\,(x - %.4g) + %.4g" % (df, x0, fx0))

    # critical / inflection points (numeric root finding on sampled sign changes)
    def roots_of(g, lo, hi):
        xs = np.linspace(lo, hi, 1500)
        v = g(xs)
        rts = []
        for i in range(len(xs) - 1):
            if np.isfinite(v[i]) and np.isfinite(v[i + 1]) and v[i] * v[i + 1] < 0:
                try:
                    r = brentq(lambda t: g(np.array([t]))[0], xs[i], xs[i + 1])
                    if abs(f(np.array([r]))[0]) < 1e12:
                        rts.append(r)
                except Exception:
                    pass
        return rts[:8]

    g1 = lambdify(d1, x)
    crit = roots_of(g1, a, b)
    if crit:
        g2 = lambdify(d2, x) if d2 is not None else None
        parts = []
        for c in crit:
            kind = ""
            if g2 is not None:
                s = g2(np.array([c]))[0]
                kind = r"\,\mathrm{(max)}" if s < 0 else (r"\,\mathrm{(min)}" if s > 0 else "")
            parts.append(r"x\approx %.4g%s" % (c, kind))
        add("Critical points", ",\\ ".join(parts))
    if d2 is not None:
        infl = roots_of(lambdify(d2, x), a, b)
        if infl:
            add("Inflection points", ",\\ ".join(r"x\approx %.4g" % c for c in infl))

    # limits / asymptotic behaviour
    lims = {}
    for side, pt in (("+", sp.oo), ("-", -sp.oo)):
        lv = with_timeout(lambda pt=pt: sp.limit(expr, x, pt), 3.0)
        if lv is not None:
            lims[side] = lv
    if lims:
        add("Limits at infinity", r",\quad ".join(
            r"\lim_{x\to%s\infty} f(x) = %s" % ("" if s == "+" else "-", L(v)) for s, v in lims.items()))
    sing = with_timeout(lambda: sp.calculus.util.singularities(expr, x, sp.Interval(a - (b - a), b + (b - a))), 3.0)
    if sing is not None and isinstance(sing, sp.FiniteSet) and len(sing) <= 6:
        pts = [s for s in sing if s.is_real]
        if pts:
            add("Discontinuities / singularities", r",\ ".join("x = " + L(s) for s in pts))
    else:
        cont = with_timeout(lambda: sp.calculus.util.continuous_domain(expr, x, sp.Reals), 3.0)
        if cont is not None:
            add("Continuous on", L(cont))

    # improper integrals when the function decays
    for lo, hi, cond in ((0, sp.oo, lims.get("+") == 0), (-sp.oo, sp.oo, lims.get("+") == 0 and lims.get("-") == 0)):
        if cond:
            iv = with_timeout(lambda lo=lo, hi=hi: sp.integrate(expr, (x, lo, hi)), 6.0)
            if iv is not None and not iv.has(sp.Integral):
                add("Improper integral", r"\int_{%s}^{%s} f(x)\,dx = %s" % (L(lo), L(hi), L(iv)))

    # Taylor series (Calc II): about 0 if f is analytic there, else at the midpoint
    centre = 0 if a <= 0 <= b and np.isfinite(f(np.array([0.0]))[0]) else round(x0, 2)
    ser = with_timeout(lambda: sp.series(expr, x, centre, 5).removeO(), 4.0)
    if ser is not None and not ser.has(sp.O):
        add("Taylor polynomial (order 4)", r"T_4(x) = " + L(sp.nsimplify(ser, rational=False) if False else ser) +
            (r"\quad (\mathrm{about}\ x=%s)" % centre))

    # series sum f(n), n>=1 (sequences & series when meaningful)
    if lims.get("+") == 0:
        n = sp.Symbol("n", integer=True, positive=True)
        conv = with_timeout(lambda: sp.Sum(expr.subs(x, n), (n, 1, sp.oo)).is_convergent(), 4.0)
        if conv is not None:
            add("Series test", r"\sum_{n=1}^{\infty} f(n)\ \mathrm{%s}" % ("converges" if conv else "diverges"))
    elif "+" in lims and lims["+"] != 0:
        add("Series test", r"\sum f(n)\ \mathrm{diverges\ (n\text{-}th\ term\ test)}")
    return out


def analyze_parametric(xe, ye, t, trange):
    a, b = trange
    items = []
    dx, dy = sp.diff(xe, t), sp.diff(ye, t)
    dydx = with_timeout(lambda: sp.simplify(dy / dx), 3.0) or dy / dx
    items.append({"label": "Slope", "latex": r"\frac{dy}{dx} = " + L(dydx)})
    fx, fy = lambdify(dx, t), lambdify(dy, t)
    ts = np.linspace(a, b, 4001)
    speed = np.hypot(fx(ts), fy(ts))
    arc = float(sint.simpson(speed, x=ts))
    items.append({"label": "Arc length", "latex": r"\int_{%.3g}^{%.3g}\sqrt{x'(t)^2+y'(t)^2}\,dt \approx %.5g" % (a, b, arc)})
    X_, Y_ = lambdify(xe, t)(ts), lambdify(ye, t)(ts)
    area = 0.5 * float(sint.simpson(X_ * fy(ts) - Y_ * fx(ts), x=ts))
    items.append({"label": "Signed enclosed area (Green)", "latex": r"A \approx %.5g" % area})
    return {"items": items}


def analyze_polar(re, th, trange):
    a, b = trange
    items = []
    dr = sp.diff(re, th)
    slope = with_timeout(lambda: sp.simplify((dr * sp.sin(th) + re * sp.cos(th)) / (dr * sp.cos(th) - re * sp.sin(th))), 3.0)
    if slope is not None:
        items.append({"label": "Slope", "latex": r"\frac{dy}{dx} = " + L(slope)})
    ts = np.linspace(a, b, 4001)
    r = lambdify(re, th)(ts)
    rp = lambdify(dr, th)(ts)
    area = 0.5 * float(sint.simpson(r**2, x=ts))
    arc = float(sint.simpson(np.sqrt(r**2 + rp**2), x=ts))
    items.append({"label": "Area", "latex": r"\tfrac{1}{2}\int r^2\,d\theta \approx %.5g" % area})
    items.append({"label": "Arc length", "latex": r"\int\sqrt{r^2+(dr/d\theta)^2}\,d\theta \approx %.5g" % arc})
    return {"items": items}


def analyze_implicit(Fexpr, xs, ys):
    items = []
    dydx = with_timeout(lambda: sp.simplify(-sp.diff(Fexpr, xs) / sp.diff(Fexpr, ys)), 3.0)
    if dydx is not None:
        items.append({"label": "Implicit derivative", "latex": r"\frac{dy}{dx} = " + L(dydx)})
    return {"items": items}
