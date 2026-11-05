"""Stroke smoothing ("auto-smoothing").

Hand tracking produces jittery strokes.  ``smooth_stroke`` removes the shake
while keeping the start/end points and the overall shape:

1. resample uniformly along arc length (so slow and fast parts of a stroke
   are treated the same);
2. Gaussian-filter x and y along arc length;
3. pad with a point reflection about each end, which preserves the end
   points and the local slope there (ordinary padding pulls the ends inward).

Strength 0..1 maps to a filter width of 0 .. 5 % of the stroke length.
The equation search still fits the *raw* data (its noise model expects real
tracking noise); smoothing is used for display, for deciding what kind of
curve was drawn, and for parametric / closed-curve fitting.
"""
from __future__ import annotations

import numpy as np


def arclength_resample(pts, n=None):
    p = np.asarray(pts, float)
    p = p[np.isfinite(p).all(axis=1)]
    if len(p) < 3:
        return p
    keep = np.r_[True, np.any(np.diff(p, axis=0) != 0, axis=1)]
    p = p[keep]
    seg = np.hypot(*np.diff(p, axis=0).T)
    s = np.r_[0.0, np.cumsum(seg)]
    if s[-1] <= 0:
        return p[:1]
    if n is None:
        n = int(np.clip(len(p), 40, 400))
    t = np.linspace(0.0, s[-1], n)
    return np.column_stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])])


def _gauss_kernel(sigma):
    r = max(1, int(np.ceil(3 * sigma)))
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum(), r


def smooth_stroke(pts, strength: float = 0.5, closed: bool | None = None):
    """Return a smoothed copy of a stroke (N,2).  strength in [0, 1]."""
    return smooth_pair(pts, strength, closed)[1]


def smooth_pair(pts, strength: float = 0.5, closed: bool | None = None):
    """(resampled raw stroke, smoothed stroke) with matching indices."""
    p = np.asarray(pts, float)
    if len(p) < 5 or strength <= 0:
        return p.copy(), p.copy()
    q = arclength_resample(p)
    n = len(q)
    if n < 5:
        return p.copy(), p.copy()
    sigma = float(np.clip(strength, 0, 1)) * 0.05 * n
    if sigma < 0.3:
        return q, q.copy()
    sigma = min(sigma, (n - 2) / 3)  # kernel radius must fit inside the stroke
    k, r = _gauss_kernel(sigma)
    if closed is None:
        span = np.ptp(q, axis=0).max() or 1.0
        closed = np.linalg.norm(q[0] - q[-1]) < 0.05 * span and n > 20
    out = np.empty_like(q)
    for j in range(2):
        v = q[:, j]
        if closed:
            pad = np.r_[v[-r - 1:-1], v, v[1:r + 1]]
        else:
            # point reflection: keeps endpoints and end slopes
            head = 2 * v[0] - v[r:0:-1]
            tail = 2 * v[-1] - v[-2:-r - 2:-1]
            pad = np.r_[head, v, tail]
        out[:, j] = np.convolve(pad, k, mode="valid")
    if not closed:
        out[0], out[-1] = q[0], q[-1]
    return q, out


def jitter_sigma(q, sm):
    """Robust jitter size: MAD of the signed distance from the smoothed curve, along its normal.

    Measured perpendicular to the curve, so steep slopes don't inflate it, and
    with a median, so the few places where smoothing rounds off a real sharp
    peak don't count as shake.
    """
    if len(q) < 7 or len(q) != len(sm):
        return 0.0
    t = np.gradient(sm, axis=0)
    nrm = np.linalg.norm(t, axis=1, keepdims=True)
    nrm[nrm == 0] = 1
    t = t / nrm
    normal = np.column_stack([-t[:, 1], t[:, 0]])
    d = np.sum((q - sm) * normal, axis=1)[2:-2]
    return float(1.4826 * np.median(np.abs(d - np.median(d))))


def roughness(pts):
    """Mean |second difference| after arc-length resampling, relative to stroke size (jitter metric)."""
    q = arclength_resample(pts, 200)
    if len(q) < 5:
        return 0.0
    span = np.ptp(q, axis=0).max() or 1.0
    return float(np.mean(np.linalg.norm(np.diff(q, 2, axis=0), axis=1)) / span)


def vertical_jitter(raw, sm, axis=0):
    """Robust size of the shake as seen by a fit of y=f(x) (axis=0) or x=g(y) (axis=1).

    Residual of the raw points from the smoothed curve, measured along the
    dependent axis (that is what the equation fit minimises), with a median
    so rounded-off real peaks don't count as shake.
    """
    raw, sm = np.asarray(raw, float), np.asarray(sm, float)
    if len(raw) < 7 or len(sm) < 7:
        return 0.0
    a, b = axis, 1 - axis
    o = np.argsort(sm[:, a])
    r = raw[:, b] - np.interp(raw[:, a], sm[o, a], sm[o, b])
    r = r[np.isfinite(r)]
    if not len(r):
        return 0.0
    return float(1.4826 * np.median(np.abs(r - np.median(r))))
