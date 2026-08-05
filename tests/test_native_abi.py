"""ABI shape of the handwritten ctypes definitions.

Offsets and sizes are computed here from the header's own declarations, so a
typo in types.py (a wrong array length, ``c_wchar_p`` instead of ``c_wchar * N``,
a widened ``long``) shows up as a mismatch. Cross-checking against a compiled C
reference program is a separate, later job.
"""

from __future__ import annotations

import ctypes

from play_jab._native.types import (
    BOOL,
    JOBJECT64,
    MAX_STRING_SIZE,
    SHORT_STRING_SIZE,
    AccessibleContextInfo,
    jint,
    jlong,
)

WCHAR_SIZE = 2
JOBJECT64_SIZE = 8
JINT_SIZE = 4
BOOL_SIZE = 4

_LONG_STRING_BYTES = MAX_STRING_SIZE * WCHAR_SIZE
_SHORT_STRING_BYTES = SHORT_STRING_SIZE * WCHAR_SIZE
_STRINGS_BYTES = 2 * _LONG_STRING_BYTES + 4 * _SHORT_STRING_BYTES
_CONTEXT_INFO_SIZE = _STRINGS_BYTES + 6 * JINT_SIZE + 5 * BOOL_SIZE


def test_jobject64_is_a_64_bit_value() -> None:
    # JOBJECT64 is jlong in every non-legacy build of the bridge, in both the
    # 32-bit and the 64-bit DLL - it must not follow pointer size.
    assert ctypes.sizeof(JOBJECT64) == JOBJECT64_SIZE
    assert JOBJECT64 is jlong


def test_scalar_widths_follow_the_windows_abi() -> None:
    assert ctypes.sizeof(jint) == JINT_SIZE
    assert ctypes.sizeof(BOOL) == BOOL_SIZE


def test_context_info_size() -> None:
    assert ctypes.sizeof(AccessibleContextInfo) == _CONTEXT_INFO_SIZE


def test_context_info_field_offsets() -> None:
    expected = {
        "name": 0,
        "description": _LONG_STRING_BYTES,
        "role": 2 * _LONG_STRING_BYTES,
        "role_en_US": 2 * _LONG_STRING_BYTES + _SHORT_STRING_BYTES,
        "states": 2 * _LONG_STRING_BYTES + 2 * _SHORT_STRING_BYTES,
        "states_en_US": 2 * _LONG_STRING_BYTES + 3 * _SHORT_STRING_BYTES,
        "indexInParent": _STRINGS_BYTES,
        "childrenCount": _STRINGS_BYTES + JINT_SIZE,
        "accessibleInterfaces": _STRINGS_BYTES + 6 * JINT_SIZE + 4 * BOOL_SIZE,
    }
    actual = {name: getattr(AccessibleContextInfo, name).offset for name in expected}
    assert actual == expected


def test_fixed_size_text_fields_decode_as_str() -> None:
    info = AccessibleContextInfo()
    info.name = "Пользователь \U0001f600"
    assert info.name == "Пользователь \U0001f600"
