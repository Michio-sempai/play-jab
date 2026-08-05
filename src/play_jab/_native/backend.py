"""The seam between play-jab and the native Access Bridge.

:class:`NativeBackend` is the entire native surface this slice depends on: the
eight Access Bridge calls of the minimal vertical slice, plus the two operations
that are native concerns but have no single export behind them (draining the
thread message queue, and probing readiness).

Backends stay thin. They mirror the C API's own failure signalling - ``FALSE``,
a null cookie, a null HWND - as ``None``/``0``/``False`` and do not raise
``play_jab`` errors; turning those into diagnosable exceptions is
:class:`~play_jab._native.bridge.BridgeRuntime`'s job.

Backends are also not thread-safe by themselves: every method must be called
from the single thread that created the backend.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from play_jab._native.dll import load_access_bridge, verify_exports
from play_jab._native.functions import REQUIRED_EXPORTS, configure_functions
from play_jab._native.types import AccessibleContext, AccessibleContextInfo

if sys.platform == "win32":
    from ctypes import wintypes as win_types

__all__ = ["ContextInfo", "DllBackend", "NativeBackend", "dll_backend_factory"]

_PM_REMOVE = 0x0001
# Upper bound on messages dispatched per pump call, so that a message storm
# cannot starve the runtime's command queue.
_MAX_MESSAGES_PER_PUMP = 64


def _free_library(dll: ctypes.CDLL) -> None:
    """Release one loader reference without letting cleanup errors escape."""
    with suppress(BaseException):  # cleanup must preserve the original error
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.FreeLibrary.argtypes = [win_types.HMODULE]
        kernel32.FreeLibrary.restype = win_types.BOOL
        kernel32.FreeLibrary(dll._handle)


@dataclass(frozen=True, slots=True)
class ContextInfo:
    """Decoded ``AccessibleContextInfo`` with no live Java reference attached.

    ``role``/``states`` are localized by the JVM; ``role_en_us``/``states_en_us``
    are the stable ``en_US`` spellings and are the only ones logic may use. Both
    are carried verbatim - mapping them onto a validated role/state registry is
    a later layer's responsibility.
    """

    name: str
    description: str
    role: str
    role_en_us: str
    states: str
    states_en_us: str
    index_in_parent: int
    children_count: int
    x: int
    y: int
    width: int
    height: int
    accessible_component: bool
    accessible_action: bool
    accessible_selection: bool
    accessible_text: bool
    accessible_interfaces: int


class NativeBackend(Protocol):
    """The native operations the bridge runtime needs.

    Passing a context that was never handed out, or one already released, is a
    programming error whose behaviour in the real bridge is undefined - it may
    return garbage or fault the process. Nothing here promises to detect it; the
    fake backend deliberately does, as a test-only tripwire.
    """

    def windows_run(self) -> None:
        """Start the bridge (``Windows_run``). Called once, on the pump thread."""

    def pump_messages(self) -> None:
        """Dispatch pending window messages for the calling thread."""

    def is_java_window(self, hwnd: int) -> bool:
        """``isJavaWindow``.

        Also serves as the runtime's readiness call, so it must reach the DLL
        rather than answer from a cache.
        """

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        """``getAccessibleContextFromHWND``: ``(vm_id, context)`` or ``None``.

        The returned context is a new owned reference.
        """

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        """``getAccessibleContextInfo``; ``None`` when the call returns FALSE.

        The result is copied data and owns no reference.
        """

    def get_accessible_child_from_context(
        self, vm_id: int, context: int, index: int
    ) -> int:
        """``getAccessibleChildFromContext``; ``0`` when there is no such child.

        A non-zero result is a new owned reference.
        """

    def get_accessible_parent_from_context(self, vm_id: int, context: int) -> int:
        """``getAccessibleParentFromContext``; ``0`` at the root.

        A non-zero result is a new owned reference.
        """

    def release_java_object(self, vm_id: int, value: int) -> None:
        """``releaseJavaObject``: give exactly one owned reference back to the JVM."""

    def get_hwnd_from_accessible_context(self, vm_id: int, context: int) -> int:
        """``getHWNDFromAccessibleContext``; ``0`` when the context has no window."""

    def shutdown(self) -> None:
        """Release the bridge. Must be idempotent and must not raise."""


class DllBackend:
    """:class:`NativeBackend` backed by the real WindowsAccessBridge DLL."""

    def __init__(self, dll: ctypes.CDLL) -> None:
        self._dll = dll
        self._closed = False
        if sys.platform != "win32":  # pragma: no cover - unit-test import shim
            self._user32 = None
            self._message = None
            return
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._message = win_types.MSG()
        self._configure_win32()

    @classmethod
    def load(cls, dll_path: str | Path | None = None) -> DllBackend:
        """Locate, load and configure the Access Bridge DLL."""
        dll = load_access_bridge(dll_path)
        try:
            verify_exports(dll, REQUIRED_EXPORTS)
            configure_functions(dll)
            return cls(dll)
        except BaseException:
            _free_library(dll)
            raise

    def _configure_win32(self) -> None:
        message_pointer = ctypes.POINTER(win_types.MSG)
        self._user32.PeekMessageW.argtypes = [
            message_pointer,
            win_types.HWND,
            win_types.UINT,
            win_types.UINT,
            win_types.UINT,
        ]
        self._user32.PeekMessageW.restype = win_types.BOOL
        self._user32.TranslateMessage.argtypes = [message_pointer]
        self._user32.TranslateMessage.restype = win_types.BOOL
        self._user32.DispatchMessageW.argtypes = [message_pointer]
        self._user32.DispatchMessageW.restype = ctypes.c_ssize_t

    def windows_run(self) -> None:
        self._dll.Windows_run()

    def pump_messages(self) -> None:
        if sys.platform != "win32":  # pragma: no cover - unit-test import shim
            return
        pointer = ctypes.byref(self._message)
        for _ in range(_MAX_MESSAGES_PER_PUMP):
            if not self._user32.PeekMessageW(pointer, None, 0, 0, _PM_REMOVE):
                return
            self._user32.TranslateMessage(pointer)
            self._user32.DispatchMessageW(pointer)

    def is_java_window(self, hwnd: int) -> bool:
        return bool(self._dll.isJavaWindow(hwnd))

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        vm_id = ctypes.c_long()
        context = AccessibleContext()
        ok = self._dll.getAccessibleContextFromHWND(
            hwnd, ctypes.byref(vm_id), ctypes.byref(context)
        )
        if not ok or not context.value:
            return None
        return int(vm_id.value), int(context.value)

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        raw = AccessibleContextInfo()
        ok = self._dll.getAccessibleContextInfo(vm_id, context, ctypes.byref(raw))
        if not ok:
            return None
        # ctypes already decodes `c_wchar * N` fields to str and jint fields to
        # int. The BOOLs arrive as C ints and are narrowed here - except
        # accessibleInterfaces, which the header declares BOOL but uses as a
        # bitfield of interface flags, so it stays an int.
        return ContextInfo(
            name=raw.name,
            description=raw.description,
            role=raw.role,
            role_en_us=raw.role_en_US,
            states=raw.states,
            states_en_us=raw.states_en_US,
            index_in_parent=raw.indexInParent,
            children_count=raw.childrenCount,
            x=raw.x,
            y=raw.y,
            width=raw.width,
            height=raw.height,
            accessible_component=bool(raw.accessibleComponent),
            accessible_action=bool(raw.accessibleAction),
            accessible_selection=bool(raw.accessibleSelection),
            accessible_text=bool(raw.accessibleText),
            accessible_interfaces=int(raw.accessibleInterfaces),
        )

    def get_accessible_child_from_context(
        self, vm_id: int, context: int, index: int
    ) -> int:
        return int(self._dll.getAccessibleChildFromContext(vm_id, context, index))

    def get_accessible_parent_from_context(self, vm_id: int, context: int) -> int:
        return int(self._dll.getAccessibleParentFromContext(vm_id, context))

    def release_java_object(self, vm_id: int, value: int) -> None:
        self._dll.releaseJavaObject(vm_id, value)

    def get_hwnd_from_accessible_context(self, vm_id: int, context: int) -> int:
        hwnd = self._dll.getHWNDFromAccessibleContext(vm_id, context)
        return int(hwnd) if hwnd else 0

    def shutdown(self) -> None:
        """Unload the Access Bridge DLL.

        The DLL exports no ``shutdownAccessBridge``; that name belongs to a
        client-side wrapper in AccessBridgeCalls.c whose job is to release the
        library. Unloading is done from the same thread that called
        ``Windows_run``, so the bridge's message window is torn down by its
        owning thread. Failures are swallowed: shutdown runs on the close path
        and must not mask the caller's own errors.
        """
        if self._closed:
            return
        self._closed = True
        _free_library(self._dll)


def dll_backend_factory(
    dll_path: str | Path | None = None,
) -> Callable[[], NativeBackend]:
    """Build a factory that loads the real DLL on whichever thread calls it.

    The bridge runtime calls the factory on its worker thread, because the
    Access Bridge's message window belongs to the thread that loads the library
    and calls ``Windows_run``.
    """

    def factory() -> NativeBackend:
        return DllBackend.load(dll_path)

    return factory
