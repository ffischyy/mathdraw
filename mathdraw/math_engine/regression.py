"""Symbolic regression: discover an equation from measured stroke points.

Pipeline
--------
1. Preprocess the stroke (smooth, decide whether it is y=f(x), x=g(y),
   a closed curve, or a general parametric curve).
2. For explicit functions, search the grammar (see ``grammar.py``) under a
   time budget and complexity limit.  Each template is fitted with variable
   projection + multi-start bounded least squares.
3. Score with a noise-aware information criterion:
       score = n*ln(MSE + tau*sigma^2) + lambda * k * ln(n)
   where sigma is the estimated tracking noise, k the number of parameters and
   lambda the user's simplicity setting.  Candidates whose held-out
   validation error is much worse than their training error are flagged as
   overfitting.
4. Group candidates that predict the same curve (equivalent forms), compute
   relative evidence weights, and report ambiguity / approximation status.
5. "Snap" coefficients to clean values (integers, halves, multiples of pi)
   when that does not measurably worsen the fit.
"""
from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass, field

import numpy as np
import sympy as sp
from scipy.optimize import least_squares

from .functions import lambdify
from .grammar import X, Ctx, GrammarConfig, Template, build_templates, pretty_name

T_SYM = sp.Symbol("t", real=True)
THETA = sp.Symbol("theta", real=True)
Y_SYM = sp.Symbol("y", real=True)


@dataclass
class SearchConfig:
    simplicity: float = 0.5  # 0 = favour complex/accurate, 1 = favour simple
    time_budget_s: float = 4.0
    max_complexity: int = 10
    families: dict | None = None
    max_alternatives: int = 4
    approx_threshold: float = 0.04  # normalized RMSE above which result is "approximate"
    smoothing: float = 0.0  # auto-smoothing strength 0..1 (0 = off)

    @property
    def lam(self):
        return 0.6 + 3.4 * float(np.clip(self.simplicity, 0, 1))


@dataclass
class Fit:
    template: Template
    theta: np.ndarray
    coefs: np.ndarray
    const: float
    mse: float
    mse_val: float
    k: int
    expr: sp.Expr | None = None
    score: float = math.inf
    overfit: bool = False
    pred: np.ndarray | None = None


# ---------------------------------------------------------------------------
# preprocessing
# ---------------------------------------------------------------------------
def _smooth(a, k=5):
    if len(a) < k + 2:
        return a
    ker = np.ones(k) / k
    pad = np.pad(a, (k // 2, k // 2), mode="edge")
    return np.convolve(pad, ker, mode="valid")


def backward_fraction(v):
    """Fraction of path length that moves against the net direction."""
    d = np.diff(_smooth(np.asarray(v, float)))
    tot = np.abs(d).sum()
    if tot == 0:
        return 1.0
    net = np.sign(d.sum()) or 1.0
    return float(np.abs(d[np.sign(d) == -net]).sum() / tot)


def resample_function(x, y, nbins=160):
    order = np.argsort(x)
    x, y = np.asarray(x, float)[order], np.asarray(y, float)[order]
    edges = np.linspace(x[0], x[-1], min(nbins, len(x)) + 1)
    idx = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, len(edges) - 2)
    xs, ys = [], []
    for b in range(len(edges) - 1):
        m = idx == b
        if m.any():
            xs.append(x[m].mean())
            ys.append(np.median(y[m]))
    return np.array(xs), np.array(ys)


def estimate_noise(y):
    if len(y) < 6:
        return 0.0
    d2 = np.diff(y, 2)
    return float(np.median(np.abs(d2 - np.median(d2))) / 0.6745 / math.sqrt(6))


# ---------------------------------------------------------------------------
# fitting a single template
# ---------------------------------------------------------------------------
def _design(t: Template, x, th):
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cols = [np.broadcast_to(np.asarray(c, float), x.shape) for c in t.basis(x, th)]
    if t.const:
        cols.append(np.ones_like(x))
    return np.column_stack(cols) if cols else np.zeros((len(x), 0))


def _solve(A, y, penalty):
    good = np.isfinite(A).all(axis=1) & (np.abs(A) < 1e150).all(axis=1)
    if good.sum() <= A.shape[1]:
        return None, np.full(len(y), penalty)
    Ag = A[good]
    norms = np.linalg.norm(Ag, axis=0)
    norms[norms == 0] = 1
    coef, *_ = np.linalg.lstsq(Ag / norms, y[good], rcond=None)
    coef = coef / norms
    r = np.full(len(y), penalty)
    r[good] = Ag @ coef - y[good]
    return coef, r


def fit_template(t: Template, ctx: Ctx, x, y, deadline):
    penalty = 5.0 * ctx.yr
    if t.n_theta == 0:
        coef, r = _solve(_design(t, x, []), y, penalty)
        if coef is None:
            return None
        return np.array([]), coef, float(np.mean(r**2))
    lo, hi = t.bounds(ctx) if t.bounds else ([-np.inf] * t.n_theta, [np.inf] * t.n_theta)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    best = None
    for th0 in t.init(ctx):
        if time.monotonic() > deadline:
            break
        th0 = np.clip(np.asarray(th0, float), lo + 1e-12 * (hi - lo), hi - 1e-12 * (hi - lo))

        def fun(th):
            return _solve(_design(t, x, th), y, penalty)[1]

        try:
            res = least_squares(fun, th0, bounds=(lo, hi), method="trf", max_nfev=40 * (t.n_theta + 1),
                                x_scale="jac", diff_step=1e-6)
        except Exception:
            continue
        mse = float(np.mean(res.fun**2))
        if best is None or mse < best[2]:
            best = (res.x, None, mse)
    if best is None:
        return None
    coef, r = _solve(_design(t, x, best[0]), y, penalty)
    if coef is None:
        return None
    return best[0], coef, float(np.mean(r**2))


def _expr_of(t: Template, th, coef):
    ths = [sp.Float(float(v)) for v in th]
    if t.const:
        lin, const = coef[:-1], float(coef[-1])
    else:
        lin, const = coef, 0.0
    if t.build is not None:
        return t.build([float(c) for c in lin], const, ths)
    syms = t.sym(ths)
    return sum((sp.Float(float(c)) * s for c, s in zip(lin, syms)), sp.Integer(0)) + sp.Float(const)


# ---------------------------------------------------------------------------
# coefficient snapping
# ---------------------------------------------------------------------------
def _nice_values(v):
    out = [0.0, round(v), round(v * 2) / 2, round(v, 1)]
    for m in (1, 2, 3, 4, 6) if abs(v) < 4 * math.pi else ():
        k = round(v * m / math.pi)
        if k:
            out.append(k * math.pi / m)
    seen, res = set(), []
    for o in out:
        if o not in seen:
            seen.add(o)
            res.append(o)
    return res


def _to_sym_nice(o):
    for m in (1, 2, 3, 4, 6):
        k = o * m / math.pi
        if abs(k - round(k)) < 1e-12 and round(k) != 0 and abs(o - round(o * 2) / 2) > 1e-9:
            return sp.Rational(int(round(k)), m) * sp.pi
    if abs(o - round(o)) < 1e-12:
        return sp.Integer(int(round(o)))
    if abs(o * 2 - round(o * 2)) < 1e-12:
        return sp.Rational(int(round(o * 2)), 2)
    return sp.Float(o)


def snap_expr(expr, sym, x, y, sigma, max_tries=40):
    f = lambdify(expr, sym)
    base = float(np.nanmean((f(x) - y) ** 2))
    if not np.isfinite(base):
        return expr, base
    tol = base * 0.03 + 0.25 * sigma**2 + 1e-12 * (np.ptp(y) ** 2 + 1)
    tries = 0
    floats = sorted(expr.atoms(sp.Float), key=lambda a: -abs(float(a)))
    for fl in floats:
        v = float(fl)
        for o in _nice_values(v):
            if tries > max_tries:
                break
            if abs(o - v) > 0.15 * max(abs(v), 1e-9) + 0.05:
                continue
            tries += 1
            cand = expr.xreplace({fl: _to_sym_nice(o)})
            try:
                m = float(np.nanmean((lambdify(cand, sym)(x) - y) ** 2))
            except Exception:
                continue
            if np.isfinite(m) and m <= base + tol and np.isfinite(lambdify(cand, sym)(x)).mean() > 0.95:
                expr, base = cand, max(m, base)
                break
    return expr, base


def round_for_display(expr, digits=3):
    rep = {}
    for fl in expr.atoms(sp.Float):
        v = float(fl)
        s = float(f"{v:.{digits}g}")
        rep[fl] = sp.Integer(int(s)) if s == int(s) and abs(s) < 1e6 else sp.Float(s)
    return expr.xreplace(rep)


# ---------------------------------------------------------------------------
# explicit-function search
# ---------------------------------------------------------------------------
@dataclass
class FunctionSearch:
    best: Fit
    ranked: list  # list[Fit] cluster representatives sorted by score
    weights: list
    sigma: float
    nrmse: float
    r2: float
    ambiguous: bool
    approximate: bool
    truncated: bool
    n_evaluated: int
    equivalents: list
    confidence: float = 1.0
    competitors: int = 0


def search_function(x, y, cfg: SearchConfig, templates: list[Template] | None = None,
                    sym=X, budget_s=None, sigma_floor: float = 0.0) -> FunctionSearch | None:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 8:
        return None
    ctx = Ctx(x, y)
    # sigma_floor: jitter measured by auto-smoothing.  Hand tremor is slow and
    # correlated, which the 2nd-difference estimate underestimates; without the
    # floor, wiggly formulas get rewarded for fitting the shake.
    sigma = max(estimate_noise(y), 1e-4 * ctx.yr, min(float(sigma_floor), 0.03 * ctx.yr))
    n = len(x)
    val_mask = np.zeros(n, bool)
    val_mask[2::5] = True
    tr = ~val_mask
    if templates is None:
        gc = GrammarConfig(max_complexity=cfg.max_complexity)
        if cfg.families:
            gc.families.update(cfg.families)
        templates = build_templates(gc)
    templates = sorted((t for t in templates if t.valid is None or t.valid(ctx)), key=lambda t: t.complexity)
    start = time.monotonic()
    budget = cfg.time_budget_s if budget_s is None else budget_s
    deadline = start + budget
    fits: list[Fit] = []
    truncated = False
    evaluated = 0
    tau = 0.5
    for t in templates:
        if time.monotonic() > deadline:
            truncated = True
            break
        try:
            r = fit_template(t, ctx, x[tr], y[tr], deadline)
        except Exception:
            r = None
        evaluated += 1
        if r is None:
            continue
        th, coef, mse_tr = r
        A = _design(t, x, th)
        good = np.isfinite(A).all(axis=1)
        if good.mean() < 0.97:
            continue
        pred = A @ coef
        mse_all = float(np.mean((pred - y) ** 2))
        mse_val = float(np.mean((pred[val_mask] - y[val_mask]) ** 2)) if val_mask.any() else mse_all
        if not np.isfinite(mse_all):
            continue
        k = len(coef) + len(th)
        fit = Fit(t, th, coef, float(coef[-1]) if t.const else 0.0, mse_all, mse_val, k, pred=pred)
        fit.overfit = mse_val > 4 * mse_tr + 2 * sigma**2
        fit.score = n * math.log(mse_all + tau * sigma**2) + cfg.lam * (k + 0.3 * t.complexity) * math.log(n)
        if fit.overfit:
            fit.score += 10 * math.log(n)
        fits.append(fit)
    if not fits:
        return None
    fits.sort(key=lambda f: f.score)

    # cluster equivalent predictions (e.g. tanh vs logistic forms)
    reps, equivalents = [], {}
    for f in fits:
        for rep in reps:
            if np.sqrt(np.mean((f.pred - rep.pred) ** 2)) < 0.004 * ctx.yr + 0.3 * sigma:
                equivalents.setdefault(id(rep), []).append(f)
                break
        else:
            reps.append(f)
    s0 = reps[0].score
    # temperature = penalty of one extra parameter: a model that fits equally well
    # but needs one more parameter keeps weight e^-1 relative to the best.
    temp = cfg.lam * math.log(n)
    w = np.array([math.exp(-(r.score - s0) / temp) for r in reps])
    w = w / w.sum()
    # competitors that fit the data (almost) as well => evidence cannot single out one formula
    rb = math.sqrt(reps[0].mse)
    competing = [r for r in reps[1:8] if math.sqrt(r.mse) <= max(1.15 * rb, rb + 0.5 * sigma)
                 and r.template.complexity <= reps[0].template.complexity + 3 and not r.overfit]

    for r in reps[: cfg.max_alternatives + 1]:
        r.expr = _expr_of(r.template, r.theta, r.coefs)
        try:
            r.expr, _ = snap_expr(r.expr, sym if sym is X else X, x, y, sigma)
        except Exception:
            pass
        if sym is not X:
            r.expr = r.expr.xreplace({X: sym})
    best = reps[0]
    rmse = math.sqrt(best.mse)
    nrmse = rmse / ctx.yr
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-12
    r2 = 1 - best.mse * n / ss_tot
    approximate = (nrmse > cfg.approx_threshold and rmse > 3 * sigma) or best.overfit
    ambiguous = (w[0] < 0.6) or approximate or bool(competing)
    eq = [f for f in equivalents.get(id(best), [])][:3]
    for f in eq:
        f.expr = _expr_of(f.template, f.theta, f.coefs)
    conf = float(w[0])
    if competing:
        conf = min(conf, 1.0 / (1 + len(competing)))
    if approximate:
        conf = min(conf, 0.5)
    return FunctionSearch(best, reps[: cfg.max_alternatives + 1], list(w[: cfg.max_alternatives + 1]),
                          sigma, nrmse, r2, ambiguous, approximate, truncated, evaluated, eq, conf, len(competing))


# ---------------------------------------------------------------------------
# curve type detection and non-function curves
# ---------------------------------------------------------------------------
def classify_stroke(pts):
    p = np.asarray(pts, float)
    diam = float(np.max(np.ptp(p, axis=0))) or 1e-9
    closed = np.linalg.norm(p[0] - p[-1]) < 0.18 * diam and len(p) > 20
    bx, by = backward_fraction(p[:, 0]), backward_fraction(p[:, 1])
    if closed:
        return "closed"
    if bx < 0.12:
        return "function"
    if by < 0.12:
        return "inverse"
    return "parametric"


def fit_conic(x, y):
    """Algebraic conic fit (normalized), returns coefficients and Sampson RMS distance."""
    mx, my = x.mean(), y.mean()
    s = max(np.std(x), np.std(y), 1e-9)
    u, v = (x - mx) / s, (y - my) / s
    D = np.column_stack([u * u, u * v, v * v, u, v, np.ones_like(u)])
    _, _, Vt = np.linalg.svd(D)
    a = Vt[-1]
    # de-normalize: substitute u=(x-mx)/s, v=(y-my)/s symbolically
    xs, ys = sp.symbols("x y", real=True)
    U, V = (xs - mx) / s, (ys - my) / s
    poly = sp.expand(sum(float(c) * m for c, m in zip(a, [U * U, U * V, V * V, U, V, 1])))
    P = sp.Poly(poly, xs, ys)
    coeffs = {mon: float(c) for mon, c in zip(P.monoms(), P.coeffs())}
    A, B, C = coeffs.get((2, 0), 0), coeffs.get((1, 1), 0), coeffs.get((0, 2), 0)
    Dd, E, Fc = coeffs.get((1, 0), 0), coeffs.get((0, 1), 0), coeffs.get((0, 0), 0)
    vec = np.array([A, B, C, Dd, E, Fc])
    vec = vec / (np.max(np.abs(vec[:3])) or 1)
    A, B, C, Dd, E, Fc = vec
    val = A * x * x + B * x * y + C * y * y + Dd * x + E * y + Fc
    gx, gy = 2 * A * x + B * y + Dd, B * x + 2 * C * y + E
    samp = np.sqrt(np.mean(val**2 / (gx**2 + gy**2 + 1e-12)))
    disc = B * B - 4 * A * C
    if abs(disc) < 0.02 * (A * A + C * C + B * B):
        kind = "Parabola (implicit conic)"
    elif disc < 0:
        kind = "Circle" if abs(A - C) < 0.08 * max(abs(A), abs(C)) and abs(B) < 0.08 * max(abs(A), abs(C)) else "Ellipse"
    else:
        kind = "Hyperbola"
    return vec, float(samp), kind


def conic_expr(vec, digits=4):
    xs, ys = sp.symbols("x y", real=True)
    A, B, C, D, E, Fc = vec
    terms = [A * xs**2, B * xs * ys, C * ys**2, D * xs, E * ys, Fc]
    return sum((t for t in terms), sp.Integer(0)), xs, ys


def circle_expr(x, y):
    A = np.column_stack([x, y, np.ones_like(x)])
    b = x * x + y * y
    c, *_ = np.linalg.lstsq(A, b, rcond=None)
    h, k = c[0] / 2, c[1] / 2
    r = math.sqrt(max(c[2] + h * h + k * k, 1e-12))
    rms = float(np.sqrt(np.mean((np.hypot(x - h, y - k) - r) ** 2)))
    return h, k, r, rms


def polar_templates(cfg):
    """Restricted grammar for r(theta)."""
    gc = GrammarConfig(max_complexity=min(cfg.max_complexity, 7), compositions=False, products=False,
                       max_poly_degree=2)
    allowed = {"Constant", "Linear", "Quadratic polynomial", "Sinusoid (amplitude, frequency, phase, shift)",
               "Exponential function"}
    return [t for t in build_templates(gc) if t.name in allowed]


def parametric_templates(cfg):
    gc = GrammarConfig(max_complexity=min(cfg.max_complexity, 7), compositions=False, products=False,
                       max_poly_degree=5)
    allowed_prefix = ("Constant", "Linear", "Quadratic", "Cubic", "Quartic", "Quintic", "Sinusoid", "Sum of two")
    return [t for t in build_templates(gc) if t.name.startswith(allowed_prefix)]
