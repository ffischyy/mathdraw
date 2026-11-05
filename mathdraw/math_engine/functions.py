"""Custom SymPy functions needed for real-valued display and numeric evaluation."""
from __future__ import annotations

import numpy as np
import sympy as sp


class RealCbrt(sp.Function):
    """Real cube root (defined for negative arguments, unlike x**(1/3) in SymPy)."""

    nargs = 1

    @classmethod
    def eval(cls, a):
        if a.is_Number and a.is_real:
            return sp.sign(a) * sp.Abs(a) ** sp.Rational(1, 3)
        return None

    def fdiff(self, argindex=1):
        return 1 / (3 * RealCbrt(self.args[0]) ** 2)

    def _latex(self, printer, exp=None):
        s = r"\sqrt[3]{%s}" % printer._print(self.args[0])
        return s if exp is None else r"\left(%s\right)^{%s}" % (s, exp)

    def _eval_rewrite_as_Pow(self, a, **kw):
        return sp.sign(a) * sp.Abs(a) ** sp.Rational(1, 3)


NUMPY_MODULES = [{"RealCbrt": np.cbrt}, "numpy", "scipy"]


def lambdify(expr, sym):
    """Numpy function for an expression; always returns an array of x's shape."""
    f = sp.lambdify(sym, expr, modules=NUMPY_MODULES)

    def g(x):
        x = np.asarray(x, dtype=float)
        with np.errstate(all="ignore"):
            try:
                v = f(x)
            except Exception:
                return np.full_like(x, np.nan)
        v = np.asarray(v, dtype=complex if np.iscomplexobj(v) else float)
        if np.iscomplexobj(v):
            v = np.where(np.abs(v.imag) < 1e-9, v.real, np.nan)
        return np.broadcast_to(v, x.shape).astype(float)

    return g
