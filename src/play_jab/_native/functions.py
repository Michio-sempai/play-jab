# flake8: noqa
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
    AccessibleActions,
    AccessibleActionsToDo,
    AccessibleContext,
    AccessibleContextInfo,
    AccessibleTableCellInfo,
    AccessibleTableInfo,
    AccessibleTextInfo,
    JavaObject,
    VisibleChildrenInfo,
    jint,
)

__all__ = [
    "JAVA_SHUTDOWN_CALLBACK",
    "PROPERTY_CALLBACK",
    "PROPERTY_CHANGE_CALLBACK",
    "PROPERTY_SIMPLE_CALLBACK",
    "REQUIRED_EXPORTS",
    "configure_functions",
]

_CALLBACK = ctypes.CFUNCTYPE
JAVA_SHUTDOWN_CALLBACK = _CALLBACK(None, ctypes.c_long)
PROPERTY_CALLBACK = _CALLBACK(
    None,
    ctypes.c_long,
    JavaObject,
    JavaObject,
    ctypes.c_void_p,
    ctypes.c_void_p,
)
PROPERTY_CHANGE_CALLBACK = _CALLBACK(
    None,
    ctypes.c_long,
    JavaObject,
    JavaObject,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
)
PROPERTY_SIMPLE_CALLBACK = _CALLBACK(
    None,
    ctypes.c_long,
    JavaObject,
    JavaObject,
)

REQUIRED_EXPORTS: Final = (
    "Windows_run",
    "isJavaWindow",
    "getAccessibleContextFromHWND",
    "getAccessibleContextInfo",
    "getAccessibleChildFromContext",
    "getAccessibleParentFromContext",
    "releaseJavaObject",
    "getHWNDFromAccessibleContext",
    "getAccessibleActions",
    "doAccessibleActions",
    "getAccessibleTextInfo",
    "getAccessibleTextRange",
    "getCurrentAccessibleValueFromContext",
    "getMinimumAccessibleValueFromContext",
    "getMaximumAccessibleValueFromContext",
    "setTextContents",
    "requestFocus",
    "addAccessibleSelectionFromContext",
    "clearAccessibleSelectionFromContext",
    "getAccessibleSelectionFromContext",
    "getAccessibleSelectionCountFromContext",
    "isAccessibleChildSelectedFromContext",
    "removeAccessibleSelectionFromContext",
    "getAccessibleTableInfo",
    "getAccessibleTableCellInfo",
    "getAccessibleTableRowHeader",
    "getAccessibleTableColumnHeader",
    "getAccessibleTableRowSelectionCount",
    "getAccessibleTableRowSelections",
    "getAccessibleTableColumnSelectionCount",
    "getAccessibleTableColumnSelections",
    "getVisibleChildrenCount",
    "getVisibleChildren",
    "setJavaShutdownFP",
    "setPropertyChangeFP",
    "setPropertyStateChangeFP",
    "setPropertyTextChangeFP",
    "setPropertyValueChangeFP",
    "setPropertySelectionChangeFP",
    "setPropertyVisibleDataChangeFP",
    "setPropertyTableModelChangeFP",
)


def configure_functions(dll: ctypes.CDLL) -> None:  # noqa: PLR0915
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

    # BOOL GetAccessibleActions(long, AccessibleContext, AccessibleActions *)
    dll.getAccessibleActions.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        ctypes.POINTER(AccessibleActions),
    ]
    dll.getAccessibleActions.restype = BOOL

    # BOOL DoAccessibleActions(long, AccessibleContext,
    #                          AccessibleActionsToDo *, jint *failure)
    dll.doAccessibleActions.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        ctypes.POINTER(AccessibleActionsToDo),
        ctypes.POINTER(jint),
    ]
    dll.doAccessibleActions.restype = BOOL

    dll.getAccessibleTextInfo.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        ctypes.POINTER(AccessibleTextInfo),
        jint,
        jint,
    ]
    dll.getAccessibleTextInfo.restype = BOOL
    dll.getAccessibleTextRange.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        jint,
        jint,
        ctypes.POINTER(ctypes.c_wchar),
        ctypes.c_short,
    ]
    dll.getAccessibleTextRange.restype = BOOL
    dll.getCurrentAccessibleValueFromContext.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        ctypes.POINTER(ctypes.c_wchar),
        ctypes.c_short,
    ]
    dll.getCurrentAccessibleValueFromContext.restype = BOOL
    for function_name in (
        "getMinimumAccessibleValueFromContext",
        "getMaximumAccessibleValueFromContext",
    ):
        function = getattr(dll, function_name)
        function.argtypes = [
            ctypes.c_long,
            AccessibleContext,
            ctypes.POINTER(ctypes.c_wchar),
            ctypes.c_short,
        ]
        function.restype = BOOL
    dll.setTextContents.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        ctypes.c_wchar_p,
    ]
    dll.setTextContents.restype = BOOL
    dll.requestFocus.argtypes = [ctypes.c_long, AccessibleContext]
    dll.requestFocus.restype = BOOL

    selection_args = [ctypes.c_long, AccessibleContext, ctypes.c_int]
    dll.addAccessibleSelectionFromContext.argtypes = selection_args
    dll.addAccessibleSelectionFromContext.restype = None
    dll.clearAccessibleSelectionFromContext.argtypes = [
        ctypes.c_long,
        AccessibleContext,
    ]
    dll.clearAccessibleSelectionFromContext.restype = None
    dll.getAccessibleSelectionFromContext.argtypes = selection_args
    dll.getAccessibleSelectionFromContext.restype = JavaObject
    dll.getAccessibleSelectionCountFromContext.argtypes = [
        ctypes.c_long,
        AccessibleContext,
    ]
    dll.getAccessibleSelectionCountFromContext.restype = ctypes.c_int
    dll.isAccessibleChildSelectedFromContext.argtypes = selection_args
    dll.isAccessibleChildSelectedFromContext.restype = BOOL
    dll.removeAccessibleSelectionFromContext.argtypes = selection_args
    dll.removeAccessibleSelectionFromContext.restype = None

    table_info_args = [
        ctypes.c_long,
        AccessibleContext,
        ctypes.POINTER(AccessibleTableInfo),
    ]
    dll.getAccessibleTableInfo.argtypes = table_info_args  # type: ignore[assignment]
    dll.getAccessibleTableInfo.restype = BOOL
    dll.getAccessibleTableRowHeader.argtypes = table_info_args  # type: ignore[assignment]
    dll.getAccessibleTableRowHeader.restype = BOOL
    dll.getAccessibleTableColumnHeader.argtypes = table_info_args  # type: ignore[assignment]
    dll.getAccessibleTableColumnHeader.restype = BOOL
    dll.getAccessibleTableCellInfo.argtypes = [
        ctypes.c_long,
        JavaObject,
        jint,
        jint,
        ctypes.POINTER(AccessibleTableCellInfo),
    ]
    dll.getAccessibleTableCellInfo.restype = BOOL
    for name in (
        "getAccessibleTableRowSelectionCount",
        "getAccessibleTableColumnSelectionCount",
    ):
        function = getattr(dll, name)
        function.argtypes = [ctypes.c_long, JavaObject]
        function.restype = jint
    for name in (
        "getAccessibleTableRowSelections",
        "getAccessibleTableColumnSelections",
    ):
        function = getattr(dll, name)
        function.argtypes = [
            ctypes.c_long,
            JavaObject,
            jint,
            ctypes.POINTER(jint),
        ]
        function.restype = BOOL

    dll.getVisibleChildrenCount.argtypes = [ctypes.c_long, AccessibleContext]
    dll.getVisibleChildrenCount.restype = ctypes.c_int
    dll.getVisibleChildren.argtypes = [
        ctypes.c_long,
        AccessibleContext,
        ctypes.c_int,
        ctypes.POINTER(VisibleChildrenInfo),
    ]
    dll.getVisibleChildren.restype = BOOL

    dll.setJavaShutdownFP.argtypes = [JAVA_SHUTDOWN_CALLBACK]
    dll.setJavaShutdownFP.restype = None
    dll.setPropertyChangeFP.argtypes = [PROPERTY_CHANGE_CALLBACK]
    dll.setPropertyChangeFP.restype = None
    for name in (
        "setPropertyStateChangeFP",
        "setPropertyValueChangeFP",
        "setPropertyTableModelChangeFP",
    ):
        function = getattr(dll, name)
        function.argtypes = [PROPERTY_CALLBACK]
        function.restype = None
    for name in (
        "setPropertyTextChangeFP",
        "setPropertySelectionChangeFP",
        "setPropertyVisibleDataChangeFP",
    ):
        function = getattr(dll, name)
        function.argtypes = [PROPERTY_SIMPLE_CALLBACK]
        function.restype = None
