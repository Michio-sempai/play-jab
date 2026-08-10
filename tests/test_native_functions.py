"""``argtypes``/``restype`` of every export the vertical slice calls.

Without an explicit ``argtypes`` ctypes falls back to its default conversions:
a Python ``int`` becomes a C ``int``, so a 64-bit ``AccessibleContext`` cookie
would be truncated and a pointer-sized ``HWND`` mangled, silently, on the call
that happens to be misconfigured. Every export therefore gets its own named
assertion, driven by :data:`EXPECTED_SIGNATURES`, rather than a "the symbol
exists" or "it has *some* explicit type" check.
"""

from __future__ import annotations

import ctypes
import sys
from typing import cast

import pytest

from play_jab._native.functions import (
    JAVA_SHUTDOWN_CALLBACK,
    PROPERTY_CALLBACK,
    PROPERTY_CHANGE_CALLBACK,
    PROPERTY_SIMPLE_CALLBACK,
    REQUIRED_EXPORTS,
    configure_functions,
)
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

_VM_ID = ctypes.c_long
_WINDOWS_LONG_SIZE = 4

_SELECTION_ARGS: list[type] = [_VM_ID, AccessibleContext, ctypes.c_int]
_TABLE_INFO_ARGS: list[type] = [
    _VM_ID,
    AccessibleContext,
    ctypes.POINTER(AccessibleTableInfo),
]
_TABLE_VALUE_ARGS: list[type] = [_VM_ID, JavaObject, jint, ctypes.POINTER(jint)]

# Mirrors `configure_functions` in `src/play_jab/_native/functions.py`
# one-to-one: every entry here is the ABI contract that module promises for
# one export. `test_every_export_matches_its_declared_signature` fails loudly
# if the two ever drift apart.
EXPECTED_SIGNATURES: dict[str, tuple[list[type], type | None]] = {
    "Windows_run": ([], None),
    "isJavaWindow": ([HWND], BOOL),
    "getAccessibleContextFromHWND": (
        [HWND, ctypes.POINTER(_VM_ID), ctypes.POINTER(AccessibleContext)],
        BOOL,
    ),
    "getAccessibleContextInfo": (
        [_VM_ID, AccessibleContext, ctypes.POINTER(AccessibleContextInfo)],
        BOOL,
    ),
    "getAccessibleChildFromContext": (
        [_VM_ID, AccessibleContext, jint],
        AccessibleContext,
    ),
    "getAccessibleParentFromContext": ([_VM_ID, AccessibleContext], AccessibleContext),
    "releaseJavaObject": ([_VM_ID, JavaObject], None),
    "getHWNDFromAccessibleContext": ([_VM_ID, AccessibleContext], HWND),
    "getAccessibleActions": (
        [_VM_ID, AccessibleContext, ctypes.POINTER(AccessibleActions)],
        BOOL,
    ),
    "doAccessibleActions": (
        [
            _VM_ID,
            AccessibleContext,
            ctypes.POINTER(AccessibleActionsToDo),
            ctypes.POINTER(jint),
        ],
        BOOL,
    ),
    "getAccessibleTextInfo": (
        [_VM_ID, AccessibleContext, ctypes.POINTER(AccessibleTextInfo), jint, jint],
        BOOL,
    ),
    "getAccessibleTextRange": (
        [
            _VM_ID,
            AccessibleContext,
            jint,
            jint,
            ctypes.POINTER(ctypes.c_wchar),
            ctypes.c_short,
        ],
        BOOL,
    ),
    "getCurrentAccessibleValueFromContext": (
        [_VM_ID, AccessibleContext, ctypes.POINTER(ctypes.c_wchar), ctypes.c_short],
        BOOL,
    ),
    "getMinimumAccessibleValueFromContext": (
        [_VM_ID, AccessibleContext, ctypes.POINTER(ctypes.c_wchar), ctypes.c_short],
        BOOL,
    ),
    "getMaximumAccessibleValueFromContext": (
        [_VM_ID, AccessibleContext, ctypes.POINTER(ctypes.c_wchar), ctypes.c_short],
        BOOL,
    ),
    "setTextContents": ([_VM_ID, AccessibleContext, ctypes.c_wchar_p], BOOL),
    "requestFocus": ([_VM_ID, AccessibleContext], BOOL),
    "addAccessibleSelectionFromContext": (_SELECTION_ARGS, None),
    "clearAccessibleSelectionFromContext": ([_VM_ID, AccessibleContext], None),
    "getAccessibleSelectionFromContext": (_SELECTION_ARGS, JavaObject),
    "getAccessibleSelectionCountFromContext": (
        [_VM_ID, AccessibleContext],
        ctypes.c_int,
    ),
    "isAccessibleChildSelectedFromContext": (_SELECTION_ARGS, BOOL),
    "removeAccessibleSelectionFromContext": (_SELECTION_ARGS, None),
    "getAccessibleTableInfo": (_TABLE_INFO_ARGS, BOOL),
    "getAccessibleTableRowHeader": (_TABLE_INFO_ARGS, BOOL),
    "getAccessibleTableColumnHeader": (_TABLE_INFO_ARGS, BOOL),
    "getAccessibleTableCellInfo": (
        [_VM_ID, JavaObject, jint, jint, ctypes.POINTER(AccessibleTableCellInfo)],
        BOOL,
    ),
    "getAccessibleTableRowSelectionCount": ([_VM_ID, JavaObject], jint),
    "getAccessibleTableColumnSelectionCount": ([_VM_ID, JavaObject], jint),
    "getAccessibleTableRowSelections": (_TABLE_VALUE_ARGS, BOOL),
    "getAccessibleTableColumnSelections": (_TABLE_VALUE_ARGS, BOOL),
    "getVisibleChildrenCount": ([_VM_ID, AccessibleContext], ctypes.c_int),
    "getVisibleChildren": (
        [_VM_ID, AccessibleContext, ctypes.c_int, ctypes.POINTER(VisibleChildrenInfo)],
        BOOL,
    ),
    "setJavaShutdownFP": ([JAVA_SHUTDOWN_CALLBACK], None),
    "setPropertyChangeFP": ([PROPERTY_CHANGE_CALLBACK], None),
    "setPropertyStateChangeFP": ([PROPERTY_CALLBACK], None),
    "setPropertyValueChangeFP": ([PROPERTY_CALLBACK], None),
    "setPropertyTableModelChangeFP": ([PROPERTY_CALLBACK], None),
    "setPropertyTextChangeFP": ([PROPERTY_SIMPLE_CALLBACK], None),
    "setPropertySelectionChangeFP": ([PROPERTY_SIMPLE_CALLBACK], None),
    "setPropertyVisibleDataChangeFP": ([PROPERTY_SIMPLE_CALLBACK], None),
}


class _Export:
    """Stands in for a ctypes ``_FuncPtr``: it only carries the two attributes."""

    def __init__(self) -> None:
        self.argtypes: list[type] | None = None
        self.restype: type | None = object


class _StubDll:
    """Hands out one :class:`_Export` per attribute, remembering which."""

    def __init__(self) -> None:
        self.exports: dict[str, _Export] = {}

    def __getattr__(self, name: str) -> _Export:
        return self.exports.setdefault(name, _Export())


@pytest.fixture
def configured() -> _StubDll:
    stub = _StubDll()
    configure_functions(cast("ctypes.CDLL", stub))
    return stub


def test_expected_signatures_cover_every_required_export() -> None:
    """The table above must track `REQUIRED_EXPORTS`, not fall behind it."""
    assert set(EXPECTED_SIGNATURES) == set(REQUIRED_EXPORTS)
    assert len(REQUIRED_EXPORTS) == len(set(REQUIRED_EXPORTS))


@pytest.mark.parametrize("name", sorted(EXPECTED_SIGNATURES))
def test_every_export_matches_its_declared_signature(
    configured: _StubDll, name: str
) -> None:
    export = configured.exports[name]
    expected_argtypes, expected_restype = EXPECTED_SIGNATURES[name]
    assert export.argtypes == expected_argtypes, f"{name} argtypes mismatch"
    assert export.restype == expected_restype, f"{name} restype mismatch"


def test_cookie_carrying_types_are_64_bit() -> None:
    """Truncating a cookie to 32 bits would leak the reference and corrupt lookups."""
    assert AccessibleContext is JavaObject
    assert ctypes.sizeof(AccessibleContext) == ctypes.sizeof(ctypes.c_int64)


def test_hwnd_is_pointer_sized() -> None:
    assert ctypes.sizeof(HWND) == ctypes.sizeof(ctypes.c_void_p)


@pytest.mark.skipif(sys.platform != "win32", reason="LLP64 is a Windows property")
def test_vm_id_stays_a_32_bit_c_long() -> None:
    """``long vmID`` in the header: Windows is LLP64, so it never widens."""
    assert ctypes.sizeof(_VM_ID) == _WINDOWS_LONG_SIZE
