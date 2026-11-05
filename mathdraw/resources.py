"""Locate bundled resources both from source and inside a PyInstaller build."""
from __future__ import annotations

import os
import sys

PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def asset(name: str) -> str:
    return os.path.join(PKG_DIR, "assets", name)


def app_root() -> str:
    """Folder holding EULA/notices: the install dir when frozen, the project root from source."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(PKG_DIR)


def doc(name: str) -> str | None:
    for base in (app_root(), os.path.join(app_root(), "_internal"), getattr(sys, "_MEIPASS", "")):
        p = os.path.join(base, name)
        if base and os.path.exists(p):
            return p
    return None
