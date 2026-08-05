"""Handwritten ctypes description of the Java Access Bridge ABI.

Handwritten on purpose. A ctypesgen-based generator over the JDK headers is the
intended long-term source of these definitions (see ``.todo/ctypec_research.md``
sections 7-10), but that pipeline is unproven research and is out of scope for
this slice, so only the types required by the minimal vertical slice are
declared here, by hand, from ``.todo/jab_api/AccessBridgePackages.h``.

Nothing in this module performs lookups, waits or error translation.
"""

from __future__ import annotations

import ctypes
import sys

__all__ = [
    "BOOL",
    "HWND",
    "JOBJECT64",
    "MAX_ACTIONS_TO_DO",
    "MAX_ACTION_INFO",
    "MAX_STRING_SIZE",
    "MAX_TABLE_SELECTIONS",
    "MAX_VISIBLE_CHILDREN",
    "SHORT_STRING_SIZE",
    "AccessibleActionInfo",
    "AccessibleActions",
    "AccessibleActionsToDo",
    "AccessibleContext",
    "AccessibleContextInfo",
    "AccessibleTableCellInfo",
    "AccessibleTableInfo",
    "AccessibleTextInfo",
    "JavaObject",
    "VisibleChildrenInfo",
    "jint",
    "jlong",
]

# AccessBridgePackages.h
MAX_STRING_SIZE = 1024
SHORT_STRING_SIZE = 256
MAX_ACTION_INFO = 256
MAX_ACTIONS_TO_DO = 32
MAX_TABLE_SELECTIONS = 64
MAX_VISIBLE_CHILDREN = 256

# jni_md.h (Windows): `typedef long jint` and `typedef __int64 jlong`. Windows is
# LLP64, so C `long` is 32-bit even in a 64-bit process; jint is therefore 32-bit
# and jlong is 64-bit. Both are spelled with explicit widths to keep that
# independent of the host platform's C `long`.
jint = ctypes.c_int32
jlong = ctypes.c_int64

# windows.h: `typedef int BOOL` - a 32-bit signed int, not a C99 bool.
BOOL = ctypes.c_int

# AccessBridgePackages.h selects JOBJECT64 with a preprocessor switch:
#
#     #ifdef ACCESSBRIDGE_ARCH_LEGACY
#     typedef jobject JOBJECT64;      // a pointer, legacy 32-bit bridge only
#     #else
#     typedef jlong JOBJECT64;        // 64-bit value
#     #endif
#
# The shipped WindowsAccessBridge DLLs are built without ACCESSBRIDGE_ARCH_LEGACY
# (that macro exists for the obsolete in-process bridge), so JOBJECT64 is jlong:
# a 64-bit signed value in *both* the 32-bit and 64-bit DLL. It is deliberately
# not modelled as c_void_p (which would be 32-bit wide in a 32-bit process and
# would silently truncate the cookie) and not as c_long (32-bit on Windows).
JOBJECT64 = jlong

# All Java handle typedefs in the header are aliases of JOBJECT64. Only the two
# used by this slice are declared.
AccessibleContext = JOBJECT64
JavaObject = JOBJECT64

if sys.platform == "win32":
    from ctypes import wintypes as win_types

    # wintypes.HWND is ctypes.c_void_p, i.e. pointer-sized, which is what an
    # HWND actually is. Modelling it as c_long would truncate in a 64-bit
    # process.
    HWND = win_types.HWND
else:  # pragma: no cover - import shim so fake-backend tests run off-Windows
    # ctypes.wintypes does not import on non-Windows platforms. The real DLL is
    # unreachable there anyway; this keeps the module importable for unit tests
    # that only exercise the fake backend.
    HWND = ctypes.c_void_p


class AccessibleContextInfo(ctypes.Structure):
    """``AccessibleContextInfo`` from AccessBridgePackages.h.

    The ``wchar_t name[N]`` members are fixed-size inline arrays, so they are
    declared as ``c_wchar * N`` and never as ``c_wchar_p``: the struct owns the
    storage, there is no pointer to follow.
    """

    _fields_ = (
        ("name", ctypes.c_wchar * MAX_STRING_SIZE),
        ("description", ctypes.c_wchar * MAX_STRING_SIZE),
        ("role", ctypes.c_wchar * SHORT_STRING_SIZE),
        ("role_en_US", ctypes.c_wchar * SHORT_STRING_SIZE),
        ("states", ctypes.c_wchar * SHORT_STRING_SIZE),
        ("states_en_US", ctypes.c_wchar * SHORT_STRING_SIZE),
        ("indexInParent", jint),
        ("childrenCount", jint),
        ("x", jint),
        ("y", jint),
        ("width", jint),
        ("height", jint),
        ("accessibleComponent", BOOL),
        ("accessibleAction", BOOL),
        ("accessibleSelection", BOOL),
        ("accessibleText", BOOL),
        ("accessibleInterfaces", BOOL),
    )


class AccessibleActionInfo(ctypes.Structure):
    """One named action from ``AccessBridgePackages.h``."""

    _fields_ = (("name", ctypes.c_wchar * SHORT_STRING_SIZE),)


class AccessibleActions(ctypes.Structure):
    """Actions supported by an accessible context."""

    _fields_ = (
        ("actionsCount", jint),
        ("actionInfo", AccessibleActionInfo * MAX_ACTION_INFO),
    )


class AccessibleActionsToDo(ctypes.Structure):
    """Bounded action list passed to ``doAccessibleActions``."""

    _fields_ = (
        ("actionsCount", jint),
        ("actions", AccessibleActionInfo * MAX_ACTIONS_TO_DO),
    )


class AccessibleTextInfo(ctypes.Structure):
    """Character count and caret metadata from ``AccessibleTextInfo``."""

    _fields_ = (
        ("charCount", jint),
        ("caretIndex", jint),
        ("indexAtPoint", jint),
    )


class AccessibleTableInfo(ctypes.Structure):
    """Table-level contexts and dimensions from JDK 17 JAB."""

    _fields_ = (
        ("caption", JOBJECT64),
        ("summary", JOBJECT64),
        ("rowCount", jint),
        ("columnCount", jint),
        ("accessibleContext", JOBJECT64),
        ("accessibleTable", JOBJECT64),
    )


class AccessibleTableCellInfo(ctypes.Structure):
    """One cell returned by ``getAccessibleTableCellInfo``."""

    _fields_ = (
        ("accessibleContext", JOBJECT64),
        ("index", jint),
        ("row", jint),
        ("column", jint),
        ("rowExtent", jint),
        ("columnExtent", jint),
        ("isSelected", ctypes.c_ubyte),
    )


class VisibleChildrenInfo(ctypes.Structure):
    """One bounded page returned by ``getVisibleChildren``."""

    _fields_ = (
        ("returnedChildrenCount", ctypes.c_int),
        ("children", AccessibleContext * MAX_VISIBLE_CHILDREN),
    )
