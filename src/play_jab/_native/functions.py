"""``argtypes``/``restype`` configuration for the Access Bridge exports used.

Handwritten for the same reason as :mod:`play_jab._native.types`: generating
this file from AccessBridgeCalls.h plus the ``LOAD_FP`` table in
AccessBridgeCalls.c is the intended long-term approach, but is out of scope here.

The DLL exports are lowerCamelCase and differ from the wrapper function names
declared in AccessBridgeCalls.h. For example the header declares
``BOOL GetAccessibleContextInfo(...)``, but that is a client-side wrapper; the
name actually exported by WindowsAccessBridge is ``getAccessibleContextInfo``.
The bindings below use the export names, verified against the export table of
the shipped 32-bit and 64-bit DLLs.

``initializeAccessBridge`` and ``shutdownAccessBridge`` are *not* exports either;
they are wrappers that load and unload the library. ``Windows_run`` is the real
initialization entry point, and unloading is handled in
:mod:`play_jab._native.backend`.
"""

from __future__ import annotations

import ctypes
from typing import Final

from play_jab._native.types import (
    BOOL,
    HWND,
    AccessibleContext,
    AccessibleContextInfo,
    JavaObject,
    jint,
)

__all__ = ["REQUIRED_EXPORTS", "configure_functions"]

REQUIRED_EXPORTS: Final = (
    "Windows_run",
    "isJavaWindow",
    "getAccessibleContextFromHWND",
    "getAccessibleContextInfo",
    "getAccessibleChildFromContext",
    "getAccessibleParentFromContext",
    "releaseJavaObject",
    "getHWNDFromAccessibleContext",
)


def configure_functions(dll: ctypes.CDLL) -> None:
    """Apply argument and return types to every export this slice calls.

    Signatures follow the function-pointer typedefs in AccessBridgeCalls.h.
    ``long vmID`` is ``ctypes.c_long``: Windows is LLP64, so C ``long`` stays
    32-bit in a 64-bit process and must not be widened to ``c_int64``.
    """
    # void Windows_run()
    dll.Windows_run.argtypes = []
    dll.Windows_run.restype = None

    # BOOL IsJavaWindow(HWND window)
    dll.isJavaWindow.argtypes = [HWND]
    dll.isJavaWindow.restype = BOOL

    # BOOL GetAccessibleContextFromHWND(HWND, long *vmID, AccessibleContext *ac)
    dll.getAccessibleContextFromHWND.argtypes = [
        HWND,
        ctypes.POINTER(ctypes.c_long),
        ctypes.POINTER(AccessibleContext),
    ]
    dll.getAccessibleContextFromHWND.restype = BOOL

    # BOOL GetAccessibleContextInfo(long, AccessibleContext, AccessibleContextInfo *)
    dll.getAccessibleContextInfo.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        ctypes.POINTER(AccessibleContextInfo),
    ]
    dll.getAccessibleContextInfo.restype = BOOL

    # AccessibleContext GetAccessibleChildFromContext(long, AccessibleContext, jint)
    dll.getAccessibleChildFromContext.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        jint,
    ]
    dll.getAccessibleChildFromContext.restype = AccessibleContext

    # AccessibleContext GetAccessibleParentFromContext(long, AccessibleContext)
    dll.getAccessibleParentFromContext.argtypes = [ctypes.c_long, AccessibleContext]
    dll.getAccessibleParentFromContext.restype = AccessibleContext

    # void ReleaseJavaObject(long vmID, Java_Object object)
    dll.releaseJavaObject.argtypes = [ctypes.c_long, JavaObject]
    dll.releaseJavaObject.restype = None

    # HWND getHWNDFromAccessibleContext(long vmID, AccessibleContext ac)
    dll.getHWNDFromAccessibleContext.argtypes = [ctypes.c_long, AccessibleContext]
    dll.getHWNDFromAccessibleContext.restype = HWND
