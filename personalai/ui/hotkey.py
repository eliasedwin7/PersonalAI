"""Optional Windows global hotkey support without another dependency."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
HOTKEY_ID = 0x4E58  # "NX"


class _WindowsHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.callback()
        return False, 0


class GlobalHotkey:
    """Registers Ctrl+Alt+N only when the user enables it in Settings."""

    def __init__(self, app: QApplication, callback: Callable[[], None]) -> None:
        self.app = app
        self.filter = _WindowsHotkeyFilter(callback)
        self.registered = False
        if sys.platform == "win32":
            app.installNativeEventFilter(self.filter)

    def configure(self, enabled: bool) -> None:
        if sys.platform != "win32":
            return
        if not enabled:
            self.close()
            return
        if not self.registered:
            self.registered = bool(ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, ord("N"),
            ))

    def close(self) -> None:
        if sys.platform == "win32" and self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            self.registered = False
