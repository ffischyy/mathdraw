"""Product dialogs: welcome / quick start, About, licence activation, shortcuts, legal texts."""
from __future__ import annotations

import platform

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QTextBrowser, QVBoxLayout)

from .. import branding as B
from ..licensing import evaluate, load_public_key, verify_license
from ..resources import asset, doc


def _logo(size=64):
    lab = QLabel()
    pm = QPixmap(asset("icon.png"))
    if not pm.isNull():
        lab.setPixmap(pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    return lab


QUICK_START = f"""
<h2>Welcome to {B.APP_NAME}</h2>
<p>Draw a curve in the air with your finger and {B.APP_NAME} works out its equation — then shows its
derivative, integral, limits and more.</p>
<h3>Three steps</h3>
<ol>
<li><b>Aim</b> with your index finger — a white ring follows your fingertip.</li>
<li><b>Pinch</b> your thumb and index finger together to put the pen down, and draw.
    (Prefer a key or an on/off switch? Change it with the <b>Draw:</b> box on the toolbar.)</li>
<li><b>Release</b> the pinch. A clean function replaces your shaky line, and the equation appears top-right.</li>
</ol>
<h3>Handy controls</h3>
<ul>
<li><b>Zoom:</b> mouse wheel (Shift = x only, Ctrl = y only), the + / − buttons, or Ctrl + / Ctrl −.
    <b>Fit</b> zooms to your drawing; double-click resets.</li>
<li><b>Grid size:</b> the <b>Grid</b> box on the toolbar, or Graph ▸ Graph settings for exact spacing and π steps.</li>
<li><b>Smoothing:</b> the <b>Smooth</b> button removes hand shake. Strength is in Settings ▸ Drawing.</li>
<li><b>Hide everything:</b> hold an open palm (thumbs-up brings it back), or press Ctrl+Alt+O.</li>
<li><b>Copy the equation:</b> Edit ▸ Copy equation — as LaTeX or plain text.</li>
</ul>
<h3>Privacy</h3>
<p>Your camera image is processed only on this computer. {B.APP_NAME} never records, stores or uploads video,
and needs no internet connection.</p>
"""


class WelcomeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {B.APP_NAME}")
        self.resize(620, 620)
        tb = QTextBrowser()
        tb.setHtml(QUICK_START)
        tb.setOpenExternalLinks(True)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(_logo(56))
        top.addWidget(QLabel(f"<b style='font-size:16px'>{B.APP_NAME}</b><br>Version {B.VERSION}"), 1)
        lay.addLayout(top)
        lay.addWidget(tb, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Start drawing")
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


SHORTCUTS = [
    ("Ctrl + =  /  Ctrl + −", "Zoom in / out"),
    ("Ctrl + 0", "Reset view"),
    ("Ctrl + F", "Fit view to drawing"),
    ("Mouse wheel (+Shift / +Ctrl)", "Zoom (x only / y only)"),
    ("Right-drag", "Pan"),
    ("Ctrl + Shift + C", "Copy equation (LaTeX)"),
    ("Ctrl + E", "Export graph image"),
    ("Ctrl + ,", "Settings"),
    ("F1", "Quick start"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        g = state.g
        rows = SHORTCUTS + [
            (g.hotkey_toggle_overlay, "Show / hide overlay (global)"),
            (g.hotkey_toggle_panel, "Show / hide equation panel (global)"),
            (g.hotkey_toggle_pen, "Pen on / off (global)"),
            (g.hotkey_toggle_clickthrough, "Toggle click-through (global)"),
            (g.hotkey_clear, "Clear drawing + equation (global)"),
            (g.pen_key, "Hold to draw (in Hold-key mode)"),
        ]
        html = "<table cellpadding=5>" + "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>"
        lab = QLabel(html)
        lab.setTextFormat(Qt.TextFormat.RichText)
        lay = QVBoxLayout(self)
        lay.addWidget(lab)
        lay.addWidget(QLabel("Global shortcuts can be changed in Settings ▸ Shortcuts."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class TextFileDialog(QDialog):
    def __init__(self, title, filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 640)
        path = doc(filename)
        text = f"{filename} was not found next to the application."
        if path:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        ed = QPlainTextEdit(text)
        ed.setReadOnly(True)
        lay = QVBoxLayout(self)
        lay.addWidget(ed)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class AboutDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {B.APP_NAME}")
        st = evaluate(state.p.license_key, state.p.first_run_ts)
        lic = {"disabled": "Developer build (licensing not configured)",
               "licensed": f"Licensed to {st.licensee}",
               "trial": f"Trial — {st.days_left} days left",
               "expired": "Trial expired"}[st.state]
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(_logo(72))
        info = QLabel(f"<h2>{B.APP_NAME}</h2>Version {B.VERSION}<br>{lic}<br><br>"
                      f"© {B.COPYRIGHT_YEAR} {B.PUBLISHER}<br>"
                      f"<a href='{B.WEBSITE}'>{B.WEBSITE}</a> · <a href='mailto:{B.SUPPORT_EMAIL}'>{B.SUPPORT_EMAIL}</a>")
        info.setOpenExternalLinks(True)
        top.addWidget(info, 1)
        lay.addLayout(top)
        lay.addWidget(QLabel(f"<small>Python {platform.python_version()} · {platform.system()} {platform.release()}<br>"
                             "Uses Qt / PySide6 (LGPLv3), MediaPipe, OpenCV, NumPy, SciPy, SymPy and Matplotlib — "
                             "see Help ▸ Third-party notices.</small>"))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class ActivationDialog(QDialog):
    """Paste a licence key.  If `required`, cancelling means the app will quit."""

    def __init__(self, state, required=False, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle(f"Activate {B.APP_NAME}")
        self.resize(560, 330)
        st = evaluate(state.p.license_key, state.p.first_run_ts)
        lay = QVBoxLayout(self)
        if st.state == "expired":
            msg = f"Your {B.TRIAL_DAYS}-day trial has ended. Enter your licence key to keep using {B.APP_NAME}."
        elif st.state == "disabled":
            msg = "Licensing isn't configured in this build (no public key), so no key is needed."
        elif st.state == "licensed":
            msg = f"This copy is licensed to <b>{st.licensee}</b>. You can replace the key below."
        else:
            msg = f"Enter the licence key from your purchase e-mail. ({st.days_left} trial days left.)"
        m = QLabel(msg)
        m.setWordWrap(True)
        lay.addWidget(m)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("MD1-…")
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        buy = QPushButton(f"Buy {B.APP_NAME}…")
        buy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(B.BUY_URL)))
        row.addWidget(buy)
        row.addStretch(1)
        act = QPushButton("Activate")
        act.setDefault(True)
        act.clicked.connect(self._activate)
        cancel = QPushButton("Quit" if required else "Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(act)
        row.addWidget(cancel)
        lay.addLayout(row)
        lay.addWidget(QLabel(f"<small>Problems? <a href='mailto:{B.SUPPORT_EMAIL}'>{B.SUPPORT_EMAIL}</a></small>",
                             openExternalLinks=True))

    def _activate(self):
        key = self.edit.toPlainText().strip()
        payload = verify_license(key, load_public_key())
        if not payload:
            QMessageBox.warning(self, "Invalid key", "That licence key isn't valid for this product. "
                                "Copy the whole key from your e-mail, including the MD1- prefix.")
            return
        self.state.p.license_key = "".join(key.split())
        self.state.save()
        QMessageBox.information(self, "Thank you!", f"{B.APP_NAME} is now licensed to {payload.get('n', 'you')}.")
        self.accept()
