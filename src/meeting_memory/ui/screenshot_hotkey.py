"""System-wide screenshot shortcut through the Carbon hot-key API.

``RegisterEventHotKey`` works from a menu-bar app without Accessibility or
Input Monitoring permission, unlike an ``NSEvent`` global monitor. The Carbon
framework has no PyObjC bindings, so the few calls needed are made through
``ctypes``. The handler runs on the main thread inside the AppKit run loop.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)
KEY_CODE_S = 1
SHIFT_MODIFIER = 0x200
OPTION_MODIFIER = 0x800
DEFAULT_KEY_CODE = KEY_CODE_S
DEFAULT_MODIFIERS = SHIFT_MODIFIER | OPTION_MODIFIER
SHORTCUT_LABEL = "⌥⇧S"
KEYBOARD_EVENT_CLASS = int.from_bytes(b"keyb", "big")
HOT_KEY_PRESSED = 5
HOTKEY_SIGNATURE = int.from_bytes(b"MMSS", "big")
HOTKEY_ID = 1
NO_ERR = 0

HANDLER_TYPE = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


def load_carbon() -> Any:
    path = ctypes.util.find_library("Carbon")
    if path is None:
        raise OSError("Carbon framework not found")
    return ctypes.cdll.LoadLibrary(path)


class GlobalHotkey:
    """Register one system-wide key combination and dispatch it on the main thread."""

    def __init__(
        self,
        callback: Callable[[], None],
        *,
        key_code: int = DEFAULT_KEY_CODE,
        modifiers: int = DEFAULT_MODIFIERS,
        library_loader: Callable[[], Any] = load_carbon,
        logger: logging.Logger = LOGGER,
    ) -> None:
        self.callback = callback
        self.key_code = key_code
        self.modifiers = modifiers
        self.library_loader = library_loader
        self.logger = logger
        self.installed = False
        self._carbon: Any | None = None
        self._handler = HANDLER_TYPE(self._dispatch)
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_ref = ctypes.c_void_p()

    def install(self) -> bool:
        try:
            carbon = self.library_loader()
            _declare_signatures(carbon)
            target = carbon.GetApplicationEventTarget()
            spec = EventTypeSpec(KEYBOARD_EVENT_CLASS, HOT_KEY_PRESSED)
            status = carbon.InstallEventHandler(
                target, self._handler, 1, ctypes.byref(spec), None, ctypes.byref(self._handler_ref)
            )
            if status != NO_ERR:
                raise OSError(f"InstallEventHandler failed with status {status}")
            status = carbon.RegisterEventHotKey(
                self.key_code,
                self.modifiers,
                EventHotKeyID(HOTKEY_SIGNATURE, HOTKEY_ID),
                target,
                0,
                ctypes.byref(self._hotkey_ref),
            )
            if status != NO_ERR:
                raise OSError(f"RegisterEventHotKey failed with status {status}")
        except Exception:
            self.logger.warning("Global screenshot hotkey %s unavailable", SHORTCUT_LABEL)
            self.logger.debug("Hotkey installation failed", exc_info=True)
            return False
        self._carbon = carbon
        self.installed = True
        self.logger.info("Global screenshot hotkey installed: %s", SHORTCUT_LABEL)
        return True

    def uninstall(self) -> None:
        if not self.installed or self._carbon is None:
            return
        try:
            self._carbon.UnregisterEventHotKey(self._hotkey_ref)
            self._carbon.RemoveEventHandler(self._handler_ref)
        except Exception:
            self.logger.debug("Hotkey removal failed", exc_info=True)
        self.installed = False

    def _dispatch(self, _call_ref: Any, _event: Any, _user_data: Any) -> int:
        try:
            self.callback()
        except Exception:
            self.logger.exception("Screenshot hotkey callback failed")
        return NO_ERR


def _declare_signatures(carbon: Any) -> None:
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.GetApplicationEventTarget.argtypes = []
    carbon.InstallEventHandler.restype = ctypes.c_int32
    carbon.InstallEventHandler.argtypes = [
        ctypes.c_void_p,
        HANDLER_TYPE,
        ctypes.c_uint32,
        ctypes.POINTER(EventTypeSpec),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    carbon.RegisterEventHotKey.restype = ctypes.c_int32
    carbon.RegisterEventHotKey.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        EventHotKeyID,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    carbon.UnregisterEventHotKey.restype = ctypes.c_int32
    carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
    carbon.RemoveEventHandler.restype = ctypes.c_int32
    carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
