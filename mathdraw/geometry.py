"""Coordinate systems — kept strictly separate:

* camera-normalised  (u, v) in [0,1]^2, origin top-left of the (mirrored) camera frame
* mathematical       (x, y) Cartesian, defined by a View (centre, half-width, aspect)
* widget / window    pixels, only ever produced by ``math_to_px`` for painting

The math view always has the camera's aspect ratio, and is mapped onto a
letter-boxed rectangle of the same aspect inside whatever widget draws it.
Resizing the window therefore changes pixels only, never the mathematics.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class View:
    cx: float = 0.0
    cy: float = 0.0
    half_w: float = 8.0
    aspect: float = 16 / 9
    y_ratio: float = 1.0  # y units per x unit on screen (1 = equal scale; >1 = y zoomed out)

    @property
    def half_h(self) -> float:
        return self.half_w / self.aspect * self.y_ratio

    def bounds(self):
        return (self.cx - self.half_w, self.cx + self.half_w, self.cy - self.half_h, self.cy + self.half_h)

    def to_dict(self):
        return {"cx": self.cx, "cy": self.cy, "half_w": self.half_w, "aspect": self.aspect, "y_ratio": self.y_ratio}

    @classmethod
    def from_dict(cls, d):
        v = cls()
        for k in ("cx", "cy", "half_w", "aspect", "y_ratio"):
            if k in d:
                setattr(v, k, float(d[k]))
        return v


def fit_rect(w: float, h: float, aspect: float):
    """Largest rect of the given aspect centred in (w, h). Returns (x, y, rw, rh)."""
    if w <= 0 or h <= 0:
        return 0.0, 0.0, 1.0, 1.0
    if w / h > aspect:
        rh = h
        rw = h * aspect
    else:
        rw = w
        rh = w / aspect
    return (w - rw) / 2, (h - rh) / 2, rw, rh


def norm_to_math(u: float, v: float, view: View):
    xmin, xmax, ymin, ymax = view.bounds()
    return xmin + u * (xmax - xmin), ymax - v * (ymax - ymin)


def math_to_norm(x: float, y: float, view: View):
    xmin, xmax, ymin, ymax = view.bounds()
    return (x - xmin) / (xmax - xmin), (ymax - y) / (ymax - ymin)


def math_to_px(x, y, view: View, rect):
    rx, ry, rw, rh = rect
    u, v = math_to_norm(x, y, view)
    return rx + u * rw, ry + v * rh


def px_to_math(px, py, view: View, rect):
    rx, ry, rw, rh = rect
    return norm_to_math((px - rx) / rw, (py - ry) / rh, view)


def nice_step(span: float, target_lines: int = 12) -> float:
    raw = span / max(target_lines, 1)
    if raw <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


# ---------------------------------------------------------------------------
# zoom / window helpers (all operate on mathematical coordinates only)
# ---------------------------------------------------------------------------
MIN_HALF, MAX_HALF = 1e-4, 1e6
DEFAULT_HALF_W = 8.0


def _clip(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def zoom(view: View, factor: float, about=None, axis: str = "both"):
    """factor < 1 zooms in.  axis: 'both' | 'x' | 'y'.  `about` (x, y) stays fixed on screen."""
    ax, ay = about if about is not None else (view.cx, view.cy)
    if axis in ("both", "x"):
        new = _clip(view.half_w * factor, MIN_HALF, MAX_HALF)
        f = new / view.half_w
        view.cx = ax + (view.cx - ax) * f
        view.half_w = new
        if axis == "x":
            view.y_ratio = _clip(view.y_ratio / f, 1e-6, 1e6)  # keep the y extent unchanged
        else:
            view.cy = ay + (view.cy - ay) * f
    if axis == "y":
        old = view.half_h
        view.y_ratio = _clip(view.y_ratio * factor, 1e-6, 1e6)
        f = view.half_h / old
        view.cy = ay + (view.cy - ay) * f
    return view


def set_window(view: View, xmin, xmax, ymin, ymax):
    if not (xmax > xmin and ymax > ymin):
        raise ValueError("max must be greater than min")
    view.cx, view.cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    view.half_w = _clip((xmax - xmin) / 2, MIN_HALF, MAX_HALF)
    view.y_ratio = ((ymax - ymin) / 2) / (view.half_w / view.aspect)
    return view


def reset_view(view: View):
    view.cx = view.cy = 0.0
    view.half_w = DEFAULT_HALF_W
    view.y_ratio = 1.0
    return view


def equal_axes(view: View):
    view.y_ratio = 1.0
    return view


def fit_points(view: View, pts, margin=0.15, keep_ratio=True):
    """Zoom/pan so all points are visible."""
    import numpy as np

    p = np.asarray(pts, float)
    p = p[np.isfinite(p).all(axis=1)] if p.ndim == 2 and len(p) else p
    if p is None or len(p) < 1:
        return view
    xmin, ymin = (float(v) for v in p.min(axis=0))
    xmax, ymax = (float(v) for v in p.max(axis=0))
    xr, yr = max(xmax - xmin, 1e-3), max(ymax - ymin, 1e-3)
    view.cx, view.cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    if keep_ratio:
        view.half_w = _clip(max(xr / 2, yr / 2 * view.aspect / view.y_ratio) * (1 + margin), MIN_HALF, MAX_HALF)
    else:
        set_window(view, view.cx - xr / 2 * (1 + margin), view.cx + xr / 2 * (1 + margin),
                   view.cy - yr / 2 * (1 + margin), view.cy + yr / 2 * (1 + margin))
    return view


# ---------------------------------------------------------------------------
# grid spacing
# ---------------------------------------------------------------------------
DENSITY = {"fine": 32, "normal": 16, "coarse": 8}
MAX_LINES = 300
PI_STEPS = [math.pi / 12, math.pi / 6, math.pi / 4, math.pi / 2, math.pi, 2 * math.pi, 4 * math.pi, 8 * math.pi,
            16 * math.pi, 32 * math.pi]


def _pi_step(span, target):
    raw = span / max(target, 1)
    for s in PI_STEPS:
        if s >= raw:
            return s
    return nice_step(span, target)


def _coarsen(step, span, limit):
    n = 0
    while span / step > limit and n < 60:
        step *= 2 if n % 2 == 0 else 2.5
        n += 1
    return step


def grid_steps(view: View, mode="auto", density="normal", step_x=1.0, step_y=1.0, x_pi=False, minor=0):
    """Return (major_x, major_y, minor_x, minor_y, coarsened).  minor_* = 0 means no minor lines.

    Custom steps that would draw an unreadable number of lines at the current
    zoom are automatically multiplied up (coarsened=True) instead of freezing the UI.
    """
    xmin, xmax, ymin, ymax = view.bounds()
    xs, ys = xmax - xmin, ymax - ymin
    target = DENSITY.get(density, 16)
    target_y = max(3, target / max(view.aspect, 1e-6))
    coarsened = False
    if mode == "custom":
        sx = abs(step_x) * (math.pi if x_pi else 1.0) or 1.0
        sy = abs(step_y) or 1.0
        nx, ny = _coarsen(sx, xs, MAX_LINES), _coarsen(sy, ys, MAX_LINES)
        coarsened = nx != sx or ny != sy
        sx, sy = nx, ny
    else:
        sx = _pi_step(xs, target) if x_pi else nice_step(xs, target)
        sy = nice_step(ys, target_y)
        if abs(view.y_ratio - 1) < 1e-9 and not x_pi:
            sy = sx = min(sx, sy) if xs / min(sx, sy) <= MAX_LINES else sx  # equal scale: square grid
    mx = sx / minor if minor and minor > 1 and xs / (sx / minor) <= 2 * MAX_LINES else 0.0
    my = sy / minor if minor and minor > 1 and ys / (sy / minor) <= 2 * MAX_LINES else 0.0
    return sx, sy, mx, my, coarsened


def grid_values(lo, hi, step):
    """Multiples of step within [lo, hi] (index-based, so no float drift)."""
    if step <= 0:
        return []
    k0, k1 = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
    if k1 - k0 > 5000:
        return []
    return [k * step for k in range(k0, k1 + 1)]


def format_tick(v: float, step: float, pi: bool = False) -> str:
    if abs(v) < step * 1e-6:
        return "0"
    if pi:
        from fractions import Fraction

        fr = Fraction(v / math.pi).limit_denominator(12)
        if abs(float(fr) * math.pi - v) < step * 1e-3:
            num, den = fr.numerator, fr.denominator
            sign = "-" if num < 0 else ""
            num = abs(num)
            top = "π" if num == 1 else f"{num}π"
            return sign + (top if den == 1 else f"{top}/{den}")
    dec = max(0, -math.floor(math.log10(step) + 1e-9)) if step < 1 else 0
    if step < 1 and abs(step * 10 ** dec - round(step * 10 ** dec)) > 1e-6:
        dec += 1
    if abs(v) >= 1e5 or (abs(v) < 1e-3):
        return f"{v:.3g}"
    out = f"{v:.{dec}f}"
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out
