"""Windows-specific window behaviour, isolated with safe fallbacks.

* ``set_click_through``  — adds WS_EX_LAYERED | WS_EX_TRANSPARENT to the
  window's extended style so mouse input passes to windows underneath.
  Fallback (non-Windows or failure): Qt's ``WindowTransparentForInput`` flag.
* ``set_exclude_from_capture`` — SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)
  (Windows 10 2004+) so screen recorders / screen capture never see the
  overlay, preventing feedback loops.  Returns False when unsupported.
* ``GlobalHotkeys`` — RegisterHotKey-based shortcuts that work even when the
  overlay is click-through or unfocused (recovery if hand tracking fails).
  Fallback: application-level QShortcuts (registered by the main window).

Transparency itself is done by Qt (WA_TranslucentBackground + frameless),
which on Windows creates a per-pixel-alpha layered window: pixels painted
with alpha 0 really are transparent; nothing is painted as a solid colour.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtGui import QKeySequence

IS_WIN = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11


def _user32():
    import ctypes

    return ctypes.windll.user32


def set_click_through(widget, enable: bool) -> str:
    """Returns the mechanism used: 'win32', 'qt' or 'none'."""
    if IS_WIN:
        try:
            import ctypes

            u = _user32()
            hwnd = int(widget.winId())
            get = u.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else u.GetWindowLongW
            setf = u.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else u.SetWindowLongW
            get.restype = ctypes.c_ssize_t
            style = get(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_LAYERED | WS_EX_TRANSPARENT) if enable else (style & ~WS_EX_TRANSPARENT)
            setf(hwnd, GWL_EXSTYLE, style)
            return "win32"
        except Exception:
            pass
    try:
        vis = widget.isVisible()
        widget.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enable)
        if vis:
            widget.show()
        return "qt"
    except Exception:
        return "none"


def set_exclude_from_capture(widget, enable: bool) -> bool:
    if not IS_WIN:
        return False
    try:
        return bool(_user32().SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE if enable else WDA_NONE))
    except Exception:
        return False


def _vk_for_key(key: int):
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value or Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
        return key  # same codes as Windows virtual keys
    if Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F24.value:
        return 0x70 + (key - Qt.Key.Key_F1.value)
    special = {Qt.Key.Key_Shift.value: 0x10, Qt.Key.Key_Control.value: 0x11, Qt.Key.Key_Alt.value: 0x12,
               Qt.Key.Key_CapsLock.value: 0x14, Qt.Key.Key_Tab.value: 0x09, Qt.Key.Key_Space.value: 0x20, Qt.Key.Key_Escape.value: 0x1B, Qt.Key.Key_Home.value: 0x24,
               Qt.Key.Key_End.value: 0x23, Qt.Key.Key_Insert.value: 0x2D, Qt.Key.Key_Delete.value: 0x2E}
    return special.get(key)


class GlobalHotkeys(QAbstractNativeEventFilter):
    def __init__(self):
        super().__init__()
        self._cbs: dict[int, callable] = {}
        self._next = 0xB000
        self.active = False

    def install(self, app):
        if IS_WIN:
            app.installNativeEventFilter(self)
            self.active = True
        return self.active

    def register(self, seq_text: str, cb) -> bool:
        if not IS_WIN or not seq_text:
            return False
        seq = QKeySequence(seq_text)
        if seq.isEmpty():
            return False
        comb = seq[0]
        key = comb.key().value
        mods = comb.keyboardModifiers()
        m = MOD_NOREPEAT
        if mods & Qt.KeyboardModifier.ControlModifier:
            m |= MOD_CONTROL
        if mods & Qt.KeyboardModifier.AltModifier:
            m |= MOD_ALT
        if mods & Qt.KeyboardModifier.ShiftModifier:
            m |= MOD_SHIFT
        if mods & Qt.KeyboardModifier.MetaModifier:
            m |= MOD_WIN
        vk = _vk_for_key(key)
        if vk is None:
            return False
        hid = self._next
        self._next += 1
        try:
            if not _user32().RegisterHotKey(None, hid, m, vk):
                return False
        except Exception:
            return False
        self._cbs[hid] = cb
        return True

    def unregister_all(self):
        if IS_WIN:
            for hid in list(self._cbs):
                try:
                    _user32().UnregisterHotKey(None, hid)
                except Exception:
                    pass
        self._cbs.clear()

    def nativeEventFilter(self, eventType, message):
        try:
            if bytes(eventType) == b"windows_generic_MSG":
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam in self._cbs:
                    self._cbs[msg.wParam]()
                    return True, 0
        except Exception:
            pass
        return False, 0


def key_is_down(seq_text: str):
    """Global "is this key held right now" (Windows GetAsyncKeyState).

    Returns True/False on Windows, or None when unsupported so the caller can
    fall back to Qt key events (which need a MathDraw window to have focus).
    """
    if not IS_WIN or not seq_text:
        return None
    seq = QKeySequence(seq_text)
    if seq.isEmpty():
        return None
    vk = _vk_for_key(seq[0].key().value)
    if vk is None:
        return None
    try:
        return bool(_user32().GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return None
