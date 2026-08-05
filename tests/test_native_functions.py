"""``argtypes``/``restype`` of every export the vertical slice calls.

Without an explicit ``argtypes`` ctypes falls back to its default conversions:
a Python ``int`` becomes a C ``int``, so a 64-bit ``AccessibleContext`` cookie
would be truncated and a pointer-sized ``HWND`` mangled, silently, on the call
that happens to be misconfigured. Every export therefore gets its own assertion
rather than a "the symbol exists" check.
"""

from __future__ import annotations

import ctypes
import sys
from typing import cast

import pytest

from play_jab._native.functions import REQUIRED_EXPORTS, configure_functions
from play_jab._native.types import (
    BOOL,
    HWND,
    AccessibleContext,
    AccessibleContextInfo,
    JavaObject,
    jint,
)

_VM_ID = ctypes.c_long
_WINDOWS_LONG_SIZE = 4


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


def signature_of(stub: _StubDll, name: str) -> tuple[list[type] | None, type | None]:
    export = stub.exports[name]
    return export.argtypes, export.restype


def test_windows_run(configured: _StubDll) -> None:
    assert signature_of(configured, "Windows_run") == ([], None)


def test_is_java_window(configured: _StubDll) -> None:
    assert signature_of(configured, "isJavaWindow") == ([HWND], BOOL)


def test_get_accessible_context_from_hwnd(configured: _StubDll) -> None:
    expected = [HWND, ctypes.POINTER(_VM_ID), ctypes.POINTER(AccessibleContext)]
    assert signature_of(configured, "getAccessibleContextFromHWND") == (expected, BOOL)


def test_get_accessible_context_info(configured: _StubDll) -> None:
    expected = [_VM_ID, AccessibleContext, ctypes.POINTER(AccessibleContextInfo)]
    assert signature_of(configured, "getAccessibleContextInfo") == (expected, BOOL)


def test_get_accessible_child_from_context(configured: _StubDll) -> None:
    expected = [_VM_ID, AccessibleContext, jint]
    assert signature_of(configured, "getAccessibleChildFromContext") == (
        expected,
        AccessibleContext,
    )


def test_get_accessible_parent_from_context(configured: _StubDll) -> None:
    assert signature_of(configured, "getAccessibleParentFromContext") == (
        [_VM_ID, AccessibleContext],
        AccessibleContext,
    )


def test_release_java_object(configured: _StubDll) -> None:
    assert signature_of(configured, "releaseJavaObject") == ([_VM_ID, JavaObject], None)


def test_get_hwnd_from_accessible_context(configured: _StubDll) -> None:
    assert signature_of(configured, "getHWNDFromAccessibleContext") == (
        [_VM_ID, AccessibleContext],
        HWND,
    )


def test_every_required_export_is_configured(configured: _StubDll) -> None:
    """A required export left unconfigured would use ctypes' default marshalling."""
    assert set(configured.exports) == set(REQUIRED_EXPORTS)
    assert len(REQUIRED_EXPORTS) == len(set(REQUIRED_EXPORTS))


def test_no_export_keeps_the_default_int_restype(configured: _StubDll) -> None:
    for name, export in configured.exports.items():
        assert export.restype is not object, f"{name} has no explicit restype"
        assert export.argtypes is not None, f"{name} has no explicit argtypes"


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
