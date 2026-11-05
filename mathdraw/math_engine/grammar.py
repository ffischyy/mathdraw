"""Configurable expression grammar for symbolic regression.

Every model has the form

    y = c_1*h_1(x; theta) + ... + c_m*h_m(x; theta) + d

where the basis functions h_i are generated from a grammar of primitive
functions, transformations (shift / scale / reflection), products and
compositions.  The *linear* coefficients c_i, d are solved exactly with least
squares for every candidate theta (variable projection); only the few
nonlinear parameters theta (frequencies, shifts, rates, exponents) are
searched numerically.  This keeps the search robust and bounded.

Nothing here encodes a specific target equation: x^2 sin(x), e^{-x^2},
ln(x^2+1), sin(x)/x, sqrt(x^2+1), e^x cos(2x) all *emerge* from generic
rules (polynomial-times-trig products, outer∘inner compositions, ...).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import sympy as sp

from .functions import RealCbrt

X = sp.Symbol("x", real=True)
F = sp.Float


@dataclass
class Ctx:
    """Data statistics used to produce sensible starting points / bounds."""

    x: np.ndarray
    y: np.ndarray

    def __post_init__(self):
        self.xmin, self.xmax = float(self.x.min()), float(self.x.max())
        self.xr = max(self.xmax - self.xmin, 1e-9)
        self.xc = 0.5 * (self.xmin + self.xmax)
        self.yr = max(float(np.ptp(self.y)), 1e-9)
        med = np.median(self.y)
        self.x_ext = float(self.x[np.argmax(np.abs(self.y - med))])
        self.x_min_y = float(self.x[np.argmin(self.y)])
        self.x_max_y = float(self.x[np.argmax(self.y)])
        self.omegas = _dominant_omegas(self.x, self.y)
        self.rate = 4.0 / self.xr  # a "natural" rate for exp/tanh over the window
        self.positive_x = self.xmin > 0
        self.has_zero = self.xmin < 0 < self.xmax


def _dominant_omegas(x, y, k=3):
    n = 256
    xs = np.linspace(x.min(), x.max(), n)
    ys = np.interp(xs, x, y)
    ys = ys - np.polyval(np.polyfit(xs, ys, 2), xs)
    spec = np.abs(np.fft.rfft(ys * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=(xs[1] - xs[0]))
    spec[0] = 0
    idx = np.argsort(spec)[::-1][:k]
    om = [2 * math.pi * freqs[i] for i in idx if freqs[i] > 0]
    base = 2 * math.pi / max(np.ptp(x), 1e-9)
    out = []
    for w in om + [base, 2 * base, 4 * base]:
        if w > 0 and all(abs(w - o) / o > 0.15 for o in out):
            out.append(w)
    return out[:5]


@dataclass
class Template:
    name: str
    family: str
    complexity: int
    basis: Callable  # (x, th) -> list[np.ndarray]
    sym: Callable  # (th: list[sp.Float]) -> list[sp.Expr]
    n_theta: int = 0
    init: Callable | None = None  # ctx -> list[list[float]]
    bounds: Callable | None = None  # ctx -> (lo, hi)
    build: Callable | None = None  # (coefs, const, th) -> sp.Expr
    const: bool = True
    valid: Callable | None = None  # ctx -> bool

    @property
    def n_params(self):
        return self.n_theta + len(self.sym([F(1)] * self.n_theta)) + int(self.const)


# --------------------------------------------------------------------------
# primitive building blocks
# --------------------------------------------------------------------------
# name -> (numpy, sympy, complexity, domain note)
OUTER = {
    "sin": (np.sin, sp.sin, 2),
    "cos": (np.cos, sp.cos, 2),
    "tan": (np.tan, sp.tan, 3),
    "sec": (lambda u: 1 / np.cos(u), sp.sec, 3),
    "csc": (lambda u: 1 / np.sin(u), sp.csc, 3),
    "cot": (lambda u: 1 / np.tan(u), sp.cot, 3),
    "exp": (np.exp, sp.exp, 2),
    "ln": (lambda u: np.where(u > 0, np.log(np.where(u > 0, u, 1)), np.nan), sp.log, 2),
    "sqrt": (lambda u: np.where(u >= 0, np.sqrt(np.abs(u)), np.nan), sp.sqrt, 2),
    "cbrt": (np.cbrt, RealCbrt, 3),
    "abs": (np.abs, sp.Abs, 2),
    "recip": (lambda u: 1 / u, lambda u: 1 / u, 2),
    "sinh": (np.sinh, sp.sinh, 3),
    "cosh": (np.cosh, sp.cosh, 3),
    "tanh": (np.tanh, sp.tanh, 3),
    "asinh": (np.arcsinh, sp.asinh, 3),
    "atan": (np.arctan, sp.atan, 3),
    "asin": (lambda u: np.where(np.abs(u) <= 1, np.arcsin(np.clip(u, -1, 1)), np.nan), sp.asin, 3),
    "acos": (lambda u: np.where(np.abs(u) <= 1, np.arccos(np.clip(u, -1, 1)), np.nan), sp.acos, 3),
    "logistic": (lambda u: 1 / (1 + np.exp(-u)), lambda u: 1 / (1 + sp.exp(-u)), 3),
    "erf": (None, sp.erf, 4),  # numpy impl filled lazily (scipy.special.erf)
}

# inner expressions p(x) used inside compositions outer(b*p(x)+c)
INNER = {
    "x^2": (lambda x: x**2, lambda: X**2, 1),
    "x^3": (lambda x: x**3, lambda: X**3, 2),
    "1/x": (lambda x: 1 / x, lambda: 1 / X, 2),
    "sqrt|x|": (lambda x: np.sqrt(np.abs(x)), lambda: sp.sqrt(sp.Abs(X)), 2),
    "e^x": (np.exp, lambda: sp.exp(X), 2),
    "sin x": (np.sin, lambda: sp.sin(X), 2),
}

# multiplicative prefactors p(x) used in products p(x)*g(x)
PREFACTOR = {
    "x": (lambda x: x, lambda: X, 1),
    "x^2": (lambda x: x**2, lambda: X**2, 2),
    "x^3": (lambda x: x**3, lambda: X**3, 3),
    "1/x": (lambda x: 1 / x, lambda: 1 / X, 2),
    "1/x^2": (lambda x: 1 / x**2, lambda: 1 / X**2, 3),
    "sqrt x": (lambda x: np.where(x >= 0, np.sqrt(np.abs(x)), np.nan), lambda: sp.sqrt(X), 2),
    "ln x": (lambda x: np.where(x > 0, np.log(np.abs(x) + 1e-300), np.nan), lambda: sp.log(X), 2),
}


def _erf_np():
    from scipy.special import erf

    return erf


def _o(name):
    f = OUTER[name][0]
    return _erf_np() if f is None else f


def _sum_build(coefs, const, th, syms):
    e = sum((F(c) * s for c, s in zip(coefs, syms)), sp.Integer(0))
    return e + F(const)


def _amp_phase(a, b):
    """a*sin(u)+b*cos(u) = R*sin(u+phi)."""
    return math.hypot(a, b), math.atan2(b, a)


# --------------------------------------------------------------------------
# grammar expansion
# --------------------------------------------------------------------------
@dataclass
class GrammarConfig:
    families: dict = field(default_factory=lambda: {k: True for k in FAMILIES})
    max_poly_degree: int = 6
    max_complexity: int = 10
    compositions: bool = True
    products: bool = True


FAMILIES = [
    "polynomial", "rational", "radical", "power", "absolute", "piecewise",
    "exponential", "logarithmic", "trigonometric", "reciprocal_trig",
    "inverse_trig", "hyperbolic", "sigmoid", "special", "composition", "product",
]


def build_templates(cfg: GrammarConfig) -> list[Template]:
    T: list[Template] = []
    fam = cfg.families

    def add(t: Template):
        if fam.get(t.family, True) and t.complexity <= cfg.max_complexity:
            T.append(t)

    # ---- polynomials -------------------------------------------------------
    names = {0: "Constant", 1: "Linear", 2: "Quadratic polynomial", 3: "Cubic polynomial",
             4: "Quartic polynomial", 5: "Quintic polynomial", 6: "Degree-6 polynomial"}
    for d in range(0, cfg.max_poly_degree + 1):
        add(Template(names.get(d, f"Degree-{d} polynomial"), "polynomial", d + 1,
                     basis=lambda x, th, d=d: [x**j for j in range(1, d + 1)],
                     sym=lambda th, d=d: [X**j for j in range(1, d + 1)]))

    # ---- shifted single-parameter primitives: a*g(x-h)+d --------------------
    def shift_init(ctx, where):
        if where == "left":  # h < xmin
            return [[ctx.xmin - f * ctx.xr] for f in (0.02, 0.2, 1.0)]
        if where == "right":
            return [[ctx.xmax + f * ctx.xr] for f in (0.02, 0.2, 1.0)]
        return [[ctx.x_ext], [ctx.xc], [ctx.x_min_y], [ctx.x_max_y]]

    def shift_bounds(ctx, where):
        if where == "left":
            return [ctx.xmin - 20 * ctx.xr], [ctx.xmin - 1e-4 * ctx.xr]
        if where == "right":
            return [ctx.xmax + 1e-4 * ctx.xr], [ctx.xmax + 20 * ctx.xr]
        return [ctx.xmin - 2 * ctx.xr], [ctx.xmax + 2 * ctx.xr]

    shifted = [
        # name, family, cx, np g(u), sympy g(u), sign(+1: x-h, -1: h-x), where
        ("Square-root function", "radical", 3, lambda u: np.sqrt(np.abs(u)), sp.sqrt, 1, "left"),
        ("Reflected square-root function", "radical", 3, lambda u: np.sqrt(np.abs(u)), sp.sqrt, -1, "right"),
        ("Cube-root function", "radical", 4, np.cbrt, RealCbrt, 1, "any"),
        ("Natural logarithm", "logarithmic", 3, lambda u: np.log(np.abs(u)), sp.log, 1, "left"),
        ("Reflected natural logarithm", "logarithmic", 3, lambda u: np.log(np.abs(u)), sp.log, -1, "right"),
        ("Logarithm of |x-h|", "logarithmic", 4, lambda u: np.log(np.abs(u)), lambda u: sp.log(sp.Abs(u)), 1, "any"),
        ("Absolute-value function", "absolute", 3, np.abs, sp.Abs, 1, "any"),
        ("Rational function (simple pole)", "rational", 3, lambda u: 1 / u, lambda u: 1 / u, 1, "any"),
        ("Rational function (double pole)", "rational", 4, lambda u: 1 / u**2, lambda u: 1 / u**2, 1, "any"),
    ]
    for name, fm, cx, g, gs, sgn, where in shifted:
        add(Template(
            name, fm, cx, n_theta=1,
            basis=lambda x, th, g=g, s=sgn: [g(s * (x - th[0]))],
            sym=lambda th, gs=gs, s=sgn: [gs(s * (X - th[0]))],
            init=lambda c, w=where: shift_init(c, w),
            bounds=lambda c, w=where: shift_bounds(c, w),
        ))

    # rational with oblique asymptote: a/(x-h) + m x + d
    add(Template("Rational function (oblique asymptote)", "rational", 5, n_theta=1,
                 basis=lambda x, th: [1 / (x - th[0]), x],
                 sym=lambda th: [1 / (X - th[0]), X],
                 init=lambda c: shift_init(c, "any"), bounds=lambda c: shift_bounds(c, "any")))
    # Lorentzian / x/(x^2+c)
    add(Template("Rational function 1/((x-h)^2+c)", "rational", 5, n_theta=2,
                 basis=lambda x, th: [1 / ((x - th[0]) ** 2 + th[1])],
                 sym=lambda th: [1 / ((X - th[0]) ** 2 + th[1])],
                 init=lambda c: [[c.x_ext, (c.xr / f) ** 2] for f in (4, 10, 30)],
                 bounds=lambda c: ([c.xmin - c.xr, 1e-6 * c.xr**2], [c.xmax + c.xr, 100 * c.xr**2])))
    add(Template("Rational function x/(x^2+c)", "rational", 5, n_theta=1,
                 basis=lambda x, th: [x / (x**2 + th[0])],
                 sym=lambda th: [X / (X**2 + th[0])],
                 init=lambda c: [[(c.xr / f) ** 2] for f in (4, 10, 30)],
                 bounds=lambda c: ([1e-6 * c.xr**2], [100 * c.xr**2])))

    # power function a*(x-h)^p + d  (fractional & negative powers)
    add(Template("Power function", "power", 5, n_theta=2,
                 basis=lambda x, th: [np.abs(x - th[0]) ** th[1]],
                 sym=lambda th: [(X - th[0]) ** th[1]],
                 init=lambda c: [[c.xmin - f * c.xr, p] for f in (0.02, 0.3) for p in (-1.0, 0.5, 1.5, 3.0)],
                 bounds=lambda c: ([c.xmin - 20 * c.xr, -4], [c.xmin - 1e-4 * c.xr, 6])))

    # sqrt((x-h)^2 + c), ln(b(x-h)^2 + 1): nested radicals/logs of quadratics
    add(Template("Square root of a quadratic", "radical", 5, n_theta=2,
                 basis=lambda x, th: [np.sqrt((x - th[0]) ** 2 + th[1])],
                 sym=lambda th: [sp.sqrt((X - th[0]) ** 2 + th[1])],
                 init=lambda c: [[c.x_min_y, (c.xr / f) ** 2] for f in (3, 10, 40)] + [[c.x_max_y, (c.xr / 10) ** 2]],
                 bounds=lambda c: ([c.xmin - c.xr, -0.5 * c.xr**2], [c.xmax + c.xr, 100 * c.xr**2])))
    add(Template("Logarithm of a quadratic", "logarithmic", 5, n_theta=2,
                 basis=lambda x, th: [np.log(th[1] * (x - th[0]) ** 2 + 1)],
                 sym=lambda th: [sp.log(th[1] * (X - th[0]) ** 2 + 1)],
                 init=lambda c: [[c.x_ext, (f / c.xr) ** 2] for f in (2, 6, 20)],
                 bounds=lambda c: ([c.xmin - c.xr, 1e-6 / c.xr**2], [c.xmax + c.xr, 1e4 / c.xr**2])))

    # ---- piecewise linear (one breakpoint) ---------------------------------
    def pw_build(coefs, const, th):
        m, k2 = coefs
        h = th[0]
        left = F(m) * X + F(const)
        right = F(m + k2) * X + F(const - k2 * float(h))
        return sp.Piecewise((left, X < h), (right, True))

    add(Template("Piecewise linear", "piecewise", 5, n_theta=1,
                 basis=lambda x, th: [x, np.maximum(x - th[0], 0)],
                 sym=lambda th: [X, sp.Max(X - th[0], 0)],
                 init=lambda c: [[c.xmin + f * c.xr] for f in (0.25, 0.5, 0.75)] + [[c.x_ext]],
                 bounds=lambda c: ([c.xmin + 0.05 * c.xr], [c.xmax - 0.05 * c.xr]),
                 build=pw_build))

    # ---- exponential ------------------------------------------------------
    rate_inits = lambda c: [[s * f * c.rate] for s in (1, -1) for f in (0.15, 0.5, 1.5)]
    rate_bounds = lambda c: ([-12 * c.rate], [12 * c.rate])

    def exp_build(coefs, const, th):
        b = float(th[0])
        base = math.exp(b)
        a = coefs[0]
        # present as an arbitrary base when it is a clean one (2, 3, 10, 1/2, ...)
        for nice in (2, 3, 4, 5, 10, 0.5, 0.25, 0.1):
            if abs(base - nice) / nice < 2e-3:
                return F(a) * sp.Pow(sp.nsimplify(nice), X, evaluate=False) + F(const)
        return F(a) * sp.exp(F(b) * X) + F(const)

    add(Template("Exponential function", "exponential", 3, n_theta=1,
                 basis=lambda x, th: [np.exp(th[0] * x)], sym=lambda th: [sp.exp(th[0] * X)],
                 init=rate_inits, bounds=rate_bounds, build=exp_build))
    add(Template("Gaussian (exponential of a quadratic)", "exponential", 5, n_theta=2,
                 basis=lambda x, th: [np.exp(-th[1] * (x - th[0]) ** 2)],
                 sym=lambda th: [sp.exp(-th[1] * (X - th[0]) ** 2)],
                 init=lambda c: [[c.x_ext, (f / c.xr) ** 2] for f in (2, 5, 12)],
                 bounds=lambda c: ([c.xmin - c.xr, 1e-4 / c.xr**2], [c.xmax + c.xr, 1e4 / c.xr**2])))

    # ---- trigonometric: a*sin(wx)+b*cos(wx)  ->  R sin(wx+phi) ---------------
    w_init = lambda c: [[w] for w in c.omegas]
    w_bounds = lambda c: ([0.05 * 2 * math.pi / c.xr], [60 * 2 * math.pi / c.xr])

    def sinus_build(prefix_sym=None, extra=0):
        def b(coefs, const, th):
            R, ph = _amp_phase(coefs[0], coefs[1])
            core = F(R) * sp.sin(F(th[-1]) * X + F(ph))
            if prefix_sym is not None:
                core = prefix_sym() * core
            rest = sum((F(c) * s for c, s in zip(coefs[2:], [X, X**2][:extra])), sp.Integer(0))
            return core + rest + F(const)
        return b

    add(Template("Sinusoid (amplitude, frequency, phase, shift)", "trigonometric", 4, n_theta=1,
                 basis=lambda x, th: [np.sin(th[0] * x), np.cos(th[0] * x)],
                 sym=lambda th: [sp.sin(th[0] * X), sp.cos(th[0] * X)],
                 init=w_init, bounds=w_bounds, build=sinus_build()))
    add(Template("Sinusoid plus linear trend", "trigonometric", 5, n_theta=1,
                 basis=lambda x, th: [np.sin(th[0] * x), np.cos(th[0] * x), x],
                 sym=lambda th: [sp.sin(th[0] * X), sp.cos(th[0] * X), X],
                 init=w_init, bounds=w_bounds, build=sinus_build(extra=1)))
    add(Template("Sinusoid plus quadratic", "trigonometric", 6, n_theta=1,
                 basis=lambda x, th: [np.sin(th[0] * x), np.cos(th[0] * x), x, x**2],
                 sym=lambda th: [sp.sin(th[0] * X), sp.cos(th[0] * X), X, X**2],
                 init=w_init, bounds=w_bounds, build=sinus_build(extra=2)))
    add(Template("Sum of two sinusoids", "trigonometric", 7, n_theta=2,
                 basis=lambda x, th: [np.sin(th[0] * x), np.cos(th[0] * x), np.sin(th[1] * x), np.cos(th[1] * x)],
                 sym=lambda th: [sp.sin(th[0] * X), sp.cos(th[0] * X), sp.sin(th[1] * X), sp.cos(th[1] * X)],
                 init=lambda c: [[c.omegas[i], c.omegas[j]] for i in range(len(c.omegas)) for j in range(i + 1, len(c.omegas))][:4],
                 bounds=lambda c: (w_bounds(c)[0] * 2, w_bounds(c)[1] * 2)))

    # ---- generic transformed primitives: a*g(b*x + c) + d --------------------
    trans = [
        ("tan", "Tangent function", "trigonometric", 4),
        ("sec", "Secant function", "reciprocal_trig", 5),
        ("csc", "Cosecant function", "reciprocal_trig", 5),
        ("cot", "Cotangent function", "reciprocal_trig", 5),
        ("atan", "Inverse tangent", "inverse_trig", 4),
        ("asin", "Inverse sine", "inverse_trig", 4),
        ("acos", "Inverse cosine", "inverse_trig", 4),
        ("sinh", "Hyperbolic sine", "hyperbolic", 4),
        ("cosh", "Hyperbolic cosine", "hyperbolic", 4),
        ("tanh", "Hyperbolic tangent", "hyperbolic", 4),
        ("asinh", "Inverse hyperbolic sine", "hyperbolic", 4),
        ("logistic", "Logistic (sigmoid) function", "sigmoid", 4),
        ("erf", "Error function (special)", "special", 5),
    ]
    for key, name, fm, cx in trans:
        def init(c, key=key):
            if key in ("asin", "acos"):
                return [[2 / c.xr * f, -2 * c.xc / c.xr * f] for f in (0.9, 1.0)]
            if key in ("tan", "sec", "csc", "cot"):
                return [[w / 2, p] for w in c.omegas[:3] for p in (0.0, 1.0)]
            return [[s * f * c.rate, -s * f * c.rate * xc] for s in (1, -1) for f in (0.3, 1.0)
                    for xc in (c.x_ext, c.xc)]

        add(Template(name, fm, cx, n_theta=2,
                     basis=lambda x, th, k=key: [_o(k)(th[0] * x + th[1])],
                     sym=lambda th, k=key: [OUTER[k][1](th[0] * X + th[1])],
                     init=init,
                     bounds=lambda c: ([-60 * c.rate, -1e3], [60 * c.rate, 1e3])))

    # ---- products p(x) * g(x) ----------------------------------------------
    if cfg.products:
        for pk, (pf, ps, pc) in PREFACTOR.items():
            valid = (lambda c: c.positive_x) if pk in ("sqrt x", "ln x") else None
            # p(x) * (a sin wx + b cos wx)
            add(Template(f"{pk} times sinusoid", "product", 4 + pc, n_theta=1,
                         basis=lambda x, th, pf=pf: [pf(x) * np.sin(th[0] * x), pf(x) * np.cos(th[0] * x)],
                         sym=lambda th, ps=ps: [ps() * sp.sin(th[0] * X), ps() * sp.cos(th[0] * X)],
                         init=w_init, bounds=w_bounds, build=sinus_build(prefix_sym=ps), valid=valid))
            # p(x) * e^{bx}
            add(Template(f"{pk} times exponential", "product", 3 + pc, n_theta=1,
                         basis=lambda x, th, pf=pf: [pf(x) * np.exp(th[0] * x)],
                         sym=lambda th, ps=ps: [ps() * sp.exp(th[0] * X)],
                         init=rate_inits, bounds=rate_bounds, valid=valid))
        # x*ln(x), x^2 ln x
        for pk in ("x", "x^2"):
            pf, ps, pc = PREFACTOR[pk]
            add(Template(f"{pk} times logarithm", "product", 3 + pc,
                         basis=lambda x, th, pf=pf: [pf(x) * np.log(np.where(x > 0, x, np.nan))],
                         sym=lambda th, ps=ps: [ps() * sp.log(X)], valid=lambda c: c.positive_x))
        # damped / growing oscillation e^{bx} (a sin wx + b cos wx)
        def damped_build(coefs, const, th):
            R, ph = _amp_phase(coefs[0], coefs[1])
            return F(R) * sp.exp(F(th[0]) * X) * sp.sin(F(th[1]) * X + F(ph)) + F(const)

        add(Template("Exponential times sinusoid", "product", 6, n_theta=2,
                     basis=lambda x, th: [np.exp(th[0] * x) * np.sin(th[1] * x), np.exp(th[0] * x) * np.cos(th[1] * x)],
                     sym=lambda th: [sp.exp(th[0] * X) * sp.sin(th[1] * X), sp.exp(th[0] * X) * sp.cos(th[1] * X)],
                     init=lambda c: [[s * f * c.rate, w] for s in (1, -1) for f in (0.2, 0.6) for w in c.omegas[:2]],
                     bounds=lambda c: ([-12 * c.rate, w_bounds(c)[0][0]], [12 * c.rate, w_bounds(c)[1][0]]),
                     build=damped_build))

    # ---- compositions outer(b*p(x) + c) ----------------------------------------
    if cfg.compositions:
        for ok in ("sin", "cos", "exp", "ln", "sqrt", "tanh", "atan", "recip", "cbrt"):
            onp, osp, oc = OUTER[ok]
            for ik, (inp, isp, ic) in INNER.items():
                if ok == "exp" and ik == "e^x":
                    continue
                cx = oc + ic + 2

                def init(c, ok=ok, ik=ik, inp=inp):
                    with np.errstate(all="ignore"):
                        pv = inp(c.x)
                    pv = pv[np.isfinite(pv)]
                    pr = max(float(np.ptp(pv)) if pv.size else 1.0, 1e-9)
                    pm = float(np.median(pv)) if pv.size else 0.0
                    if ok in ("sin", "cos"):
                        return [[s * w * c.xr / pr * 0.5, 0.0] for s in (1,) for w in c.omegas[:3]]
                    if ok in ("ln", "sqrt", "recip"):
                        return [[s / pr, o] for s in (1, -1) for o in (1.0, 0.1)] + [[s * 4 / pr, 1 - s * 4 * pm / pr] for s in (1, -1)]
                    return [[s * f / pr, -s * f * pm / pr] for s in (1, -1) for f in (0.5, 2.0, 4.0)]

                add(Template(f"Composition {ok}({ik})", "composition", cx, n_theta=2,
                             basis=lambda x, th, onp=onp, inp=inp: [onp(th[0] * inp(x) + th[1])],
                             sym=lambda th, osp=osp, isp=isp: [osp(th[0] * isp() + th[1])],
                             init=init,
                             bounds=lambda c: ([-1e4, -1e4], [1e4, 1e4]),
                             build=_canonical_build(ok, osp, isp)))
    return T


def _canonical_build(ok, osp, isp):
    """Factor the inner scale out of ln/sqrt/recip so e.g. ln(b x^2 + c) -> ln(x^2 + c/b) + const."""

    def b(coefs, const, th):
        a, (bb, cc) = coefs[0], (float(th[0]), float(th[1]))
        p = isp()
        if ok == "ln" and bb > 0:
            return F(a) * sp.log(p + F(cc / bb)) + F(const + a * math.log(bb))
        if ok == "sqrt" and bb > 0:
            return F(a * math.sqrt(bb)) * sp.sqrt(p + F(cc / bb)) + F(const)
        if ok == "recip" and bb != 0:
            return F(a / bb) / (p + F(cc / bb)) + F(const)
        return F(a) * osp(F(bb) * p + F(cc)) + F(const)

    return b



# Friendly model names for display ---------------------------------------
def pretty_name(template_name: str) -> str:
    n = template_name
    if n.startswith("Composition "):
        inner = n[len("Composition "):]
        return f"Composition {inner.replace('recip', '1/')}"
    return n
