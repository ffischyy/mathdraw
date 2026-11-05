"""LaTeX helpers shared by the engine and the UI (mathtext-compatible output)."""
from __future__ import annotations

import re

import sympy as sp

from .regression import round_for_display


def to_latex(e, digits=4):
    try:
        e = round_for_display(sp.sympify(e), digits) if isinstance(e, sp.Basic) else e
        s = sp.latex(e, ln_notation=True, inv_trig_style="power")
    except Exception:
        s = str(e)
    return mathtext_safe(s)


def mathtext_safe(s: str) -> str:
    """Adapt SymPy LaTeX to matplotlib mathtext's supported subset."""
    s = s.replace(r"\operatorname{", r"\mathrm{")
    s = re.sub(r"\\begin\{cases\}(.*?)\\end\{cases\}", lambda m: _cases(m.group(1)), s, flags=re.S)
    s = s.replace(r"\text{otherwise}", r"\mathrm{otherwise}").replace(r"\text{for}\:", r"\mathrm{for}\ ")
    s = s.replace(r"\text{", r"\mathrm{").replace(r"\:", r"\ ").replace(r"\,", r"\ ")
    s = s.replace(r"\tfrac", r"\frac")
    return s


def _cases(body):
    rows = [r.strip() for r in body.split(r"\\") if r.strip()]
    parts = []
    for r in rows:
        r = r.replace("&", r"\ ")
        parts.append(r)
    return r"\{\ " + r";\ \ ".join(parts) + r"\ \}"
