"""Application entry point.

    python -m mathdraw              run the app
    python -m mathdraw --selftest   check that every component loads (used after building the installer)
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import time
import traceback

from . import branding as B

log = logging.getLogger("mathdraw")


def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, B.APP_ID)
    os.makedirs(path, exist_ok=True)
    return path


def log_dir() -> str:
    path = os.path.join(data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def setup_logging():
    h = logging.handlers.RotatingFileHandler(os.path.join(log_dir(), "app.log"), maxBytes=1_000_000, backupCount=3,
                                             encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    if sys.stderr:
        root.addHandler(logging.StreamHandler())
    log.info("%s %s starting (Python %s, %s)", B.APP_NAME, B.VERSION, sys.version.split()[0], sys.platform)


def install_excepthook():
    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        log.error("Unhandled exception:\n%s", text)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance():
                box = QMessageBox(QMessageBox.Icon.Critical, f"{B.APP_NAME} — unexpected error",
                                  f"Something went wrong, but your drawing and settings are safe.\n\n{value}\n\n"
                                  f"If this keeps happening, please e-mail {B.SUPPORT_EMAIL} and attach the log file "
                                  f"from Help ▸ Open log folder.")
                box.setDetailedText(text)
                box.exec()
        except Exception:
            pass

    sys.excepthook = hook


# Chalkboard: graphite surfaces, chalk yellow only on the selection and the fitted curve.
STYLESHEET = """
QMenuBar, QMenu { background: #141415; }
QMenuBar::item { padding: 4px 8px; background: transparent; }
QMenuBar::item:selected, QMenu::item:selected { background: #232325; color: #ededed; }
QMenu { border: 1px solid rgba(237,237,237,0.08); padding: 4px; }
QMenu::item { padding: 4px 24px 4px 12px; }
QMenu::separator { height: 1px; background: rgba(237,237,237,0.08); margin: 4px 8px; }
QToolBar { spacing: 4px; padding: 4px 8px; border: none; border-bottom: 1px solid rgba(237,237,237,0.08); background: #141415; }
QToolBar::separator { width: 1px; background: rgba(237,237,237,0.08); margin: 4px 8px; }
QToolBar QLabel { color: #a1a1a6; padding: 0 4px; }
QToolButton { padding: 4px 8px; border: none; border-radius: 6px; background: transparent; }
QToolButton:hover { background: #232325; }
QToolButton:checked { background: #232325; color: #e8c547; }
QToolButton:focus { border: 1px solid #a1a1a6; }
QPushButton { background: #232325; border: 1px solid rgba(237,237,237,0.08); border-radius: 8px; padding: 4px 12px; min-height: 20px; }
QPushButton:hover { background: #2c2c2f; }
QPushButton:focus { border-color: #a1a1a6; }
QPushButton:pressed { background: #19191b; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QKeySequenceEdit {
    background: #232325; border: 1px solid rgba(237,237,237,0.08); border-radius: 8px; padding: 4px 8px; min-height: 20px; }
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: rgba(237,237,237,0.24); }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #a1a1a6; }
QComboBox QAbstractItemView { background: #232325; border: 1px solid rgba(237,237,237,0.08); selection-background-color: #2c2c2f; selection-color: #ededed; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid rgba(237,237,237,0.24); border-radius: 4px; background: #232325; }
QCheckBox::indicator:checked { background: #e8c547; border-color: #e8c547; }
QTabWidget::pane { border: none; border-top: 1px solid rgba(237,237,237,0.08); }
QTabBar::tab { background: transparent; color: #a1a1a6; padding: 8px 12px; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: #ededed; }
QTabBar::tab:selected { color: #ededed; border-bottom: 2px solid #e8c547; }
QGroupBox { border: 1px solid rgba(237,237,237,0.08); border-radius: 12px; margin-top: 12px; padding: 12px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #a1a1a6; }
QSlider::groove:horizontal { height: 2px; background: rgba(237,237,237,0.16); }
QSlider::sub-page:horizontal { background: #ededed; }
QSlider::handle:horizontal { background: #ededed; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }
QProgressBar { border: none; background: #232325; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #e8c547; border-radius: 4px; }
QToolTip { background: #232325; color: #ededed; border: 1px solid rgba(237,237,237,0.08); padding: 4px; }
QStatusBar { color: #a1a1a6; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: rgba(237,237,237,0.16); border-radius: 4px; min-height: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
"""


def apply_theme(app):
    from PySide6.QtGui import QColor, QPalette

    app.setStyle("Fusion")
    pal = QPalette()
    c = {
        QPalette.ColorRole.Window: "#141415", QPalette.ColorRole.WindowText: "#ededed",
        QPalette.ColorRole.Base: "#19191b", QPalette.ColorRole.AlternateBase: "#19191b",
        QPalette.ColorRole.ToolTipBase: "#232325", QPalette.ColorRole.ToolTipText: "#ededed",
        QPalette.ColorRole.Text: "#ededed", QPalette.ColorRole.Button: "#232325",
        QPalette.ColorRole.ButtonText: "#ededed", QPalette.ColorRole.BrightText: "#e5484d",
        QPalette.ColorRole.Highlight: "#e8c547", QPalette.ColorRole.HighlightedText: "#171717",
        QPalette.ColorRole.Link: "#e8c547", QPalette.ColorRole.PlaceholderText: "#85858b",
    }
    for role, col in c.items():
        pal.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#85858b"))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


def _migrate_old_state(new_path):
    """Earlier versions kept state.json in Qt's per-app config folder; bring it over once."""
    if os.path.exists(new_path):
        return
    try:
        from PySide6.QtCore import QStandardPaths

        old = os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation), "state.json")
        if os.path.exists(old):
            import shutil

            shutil.copy2(old, new_path)
            log.info("Migrated settings from %s", old)
    except Exception:
        log.exception("Settings migration failed")


def selftest() -> int:
    """Exercise each subsystem without a camera; prints a report. Exit code 0 = OK."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    ok = True
    report_path = os.path.join(data_dir(), "selftest.txt")
    lines = []

    def out(msg):
        lines.append(msg)
        if sys.stdout:  # windowed builds have no console
            print(msg, flush=True)

    def check(name, fn):
        nonlocal ok
        t = time.time()
        try:
            info = fn()
            out(f"[ OK ] {name} ({time.time() - t:.1f}s) {info or ''}")
        except Exception as e:
            ok = False
            out(f"[FAIL] {name}: {e}\n{traceback.format_exc()}")

    def qt():
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        return "PySide6"

    def engine():
        import numpy as np

        from .math_engine.analyzer import analyze_stroke, plain_text
        from .math_engine.regression import SearchConfig

        x = np.linspace(-3, 3, 150)
        r = analyze_stroke(np.c_[x, 0.5 * x ** 2 - 1], SearchConfig(time_budget_s=3, smoothing=0.5))
        assert r["ok"] and r["kind"] == "function", r
        return plain_text(r)

    def render():
        from .ui.math_render import render_latex

        assert render_latex(r"f(x) = \frac{\sin x}{x}", 20, "#ffffff") is not None

    def mediapipe():
        from mediapipe.tasks.python import vision  # noqa: F401

        from .tracking import model_path

        p = model_path()
        if getattr(sys, "frozen", False) and not os.path.exists(p):
            raise RuntimeError(f"hand model not bundled ({p}) — run tools/fetch_model.py before building")
        return f"model {'present' if os.path.exists(p) else 'not downloaded yet'}: {p}"

    def opencv():
        import cv2

        return cv2.__version__

    def licensing():
        from .licensing import load_public_key

        return "enabled" if load_public_key() is not None else "disabled (no public key)"

    for n, f in (("Qt", qt), ("Equation engine", engine), ("Math rendering", render), ("MediaPipe", mediapipe),
                 ("OpenCV", opencv), ("Licensing", licensing)):
        check(n, f)
    out(f"{B.APP_NAME} {B.VERSION} SELFTEST " + ("PASSED" if ok else "FAILED"))
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    from PySide6.QtCore import QLockFile, QSettings, Qt
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    setup_logging()
    install_excepthook()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(B.APP_ID)
    app.setApplicationDisplayName(B.APP_NAME)
    app.setApplicationVersion(B.VERSION)
    app.setOrganizationName(B.APP_ID)
    from .resources import asset

    app.setWindowIcon(QIcon(asset("icon.ico")))
    apply_theme(app)

    # one instance at a time (two would fight over the webcam)
    lock = QLockFile(os.path.join(data_dir(), "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, B.APP_NAME, f"{B.APP_NAME} is already running.")
        return

    from .licensing import evaluate
    from .state import StateManager
    from .ui.dialogs import ActivationDialog, WelcomeDialog
    from .ui.main_window import MainWindow

    state_path = os.path.join(data_dir(), "state.json")
    _migrate_old_state(state_path)
    state = StateManager(state_path)
    state.load()  # restores overlay config, gestures, last stroke and last equation

    # trial start: earliest of the state file and the registry (QSettings), so deleting one doesn't reset it
    qs = QSettings(B.APP_ID, B.APP_ID)
    stamps = [t for t in (state.p.first_run_ts, float(qs.value("install_ts", 0) or 0)) if t > 0]
    first = min(stamps) if stamps else time.time()
    state.p.first_run_ts = first
    qs.setValue("install_ts", first)
    state.save()

    status = evaluate(state.p.license_key, state.p.first_run_ts)
    log.info("Licence status: %s", status.state)
    if not status.allowed:
        if not ActivationDialog(state, required=True).exec():
            return

    win = MainWindow(state)
    win.show()
    if not state.p.welcome_shown:
        state.p.welcome_shown = True
        state.touch("welcome")
        WelcomeDialog(win).exec()
    code = app.exec()
    lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
