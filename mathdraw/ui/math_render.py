"""Render LaTeX (mathtext subset) to QImage with transparent background, cached."""
from __future__ import annotations

import io
from functools import lru_cache

from PySide6.QtGui import QImage

import matplotlib

matplotlib.use("Agg")
from matplotlib.font_manager import FontProperties  # noqa: E402

matplotlib.rcParams["mathtext.fontset"] = "cm"


@lru_cache(maxsize=256)
def _png(latex: str, size_pt: float, color: str, dpi: int) -> bytes | None:
    buf = io.BytesIO()
    try:
        from matplotlib.figure import Figure
        from matplotlib.mathtext import MathTextParser

        prop = FontProperties(size=size_pt)
        w, h, depth, *_ = MathTextParser("path").parse(f"${latex}$", dpi=72, prop=prop)
        fig = Figure(figsize=((w + 4) / 72, (h + 4) / 72))
        fig.patch.set_alpha(0)
        fig.text(2 / ((w + 4)), (depth + 2) / (h + 4), f"${latex}$", fontproperties=prop, color=color)
        fig.savefig(buf, dpi=dpi, format="png", transparent=True)
        return buf.getvalue()
    except Exception:
        return None


def render_latex(latex: str, size_pt: float, color: str, dpi: int = 110) -> QImage | None:
    data = _png(latex, float(size_pt), color, int(dpi))
    if data is None:
        # degrade gracefully: plain-text rendering of the source
        data = _png(r"\mathrm{" + latex.replace("\\", "").replace("{", "(").replace("}", ")").replace(" ", r"\ ")[:180] + "}",
                    float(size_pt) * 0.7, color, int(dpi))
        if data is None:
            return None
    img = QImage()
    img.loadFromData(data, "PNG")
    return img
