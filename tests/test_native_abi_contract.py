"""``AccessibleContextInfo`` against the JDK 17 header and against real UTF-16 bytes.

:mod:`tests.test_native_abi` derives its expectations from the same two size
constants that ``types.py`` itself uses, so it catches a typo but not a
misreading of the header. Here the byte offsets are pinned as absolute literals
transcribed from ``AccessBridgePackages.h``, and - when those headers happen to
be present in the working tree - recomputed straight from the C declarations.

The pinned layout is the *Windows* ABI, in which ``wchar_t`` is two bytes.
CPython's ``ctypes.c_wchar`` follows the host's ``wchar_t``, which is four bytes
on Linux, so ``AccessibleContextInfo`` does not have the bridge's layout there
at all and the layout assertions are skipped rather than made meaningless.
"""

from __future__ import annotations

import ctypes
import re
from pathlib import Path

import pytest

from play_jab._native.types import (
    MAX_STRING_SIZE,
    SHORT_STRING_SIZE,
    AccessibleContextInfo,
)

_HEADER = (
    Path(__file__).resolve().parents[1] / ".todo" / "jab_api" / "AccessBridgePackages.h"
)
_STRUCT_TAG = "AccessibleContextInfoTag"

# MSVC on x86/x64: every member is naturally aligned to its own width, and the
# widest member here is four bytes, so the default ``#pragma pack(8)`` never
# takes effect.
_C_SIZES = {"wchar_t": 2, "jint": 4, "BOOL": 4}

_WINDOWS_WCHAR_SIZE = 2
_HOST_WCHAR_SIZE = ctypes.sizeof(ctypes.c_wchar)

# Transcribed from AccessBridgePackages.h with MAX_STRING_SIZE == 1024 and
# SHORT_STRING_SIZE == 256: two 2048-byte names, four 512-byte role/state
# buffers, six jint, then five BOOL.
_EXPECTED_OFFSETS = {
    "name": 0,
    "description": 2048,
    "role": 4096,
    "role_en_US": 4608,
    "states": 5120,
    "states_en_US": 5632,
    "indexInParent": 6144,
    "childrenCount": 6148,
    "x": 6152,
    "y": 6156,
    "width": 6160,
    "height": 6164,
    "accessibleComponent": 6168,
    "accessibleAction": 6172,
    "accessibleSelection": 6176,
    "accessibleText": 6180,
    "accessibleInterfaces": 6184,
}
_EXPECTED_SIZE = 6188

_HEADER_MAX_STRING_SIZE = 1024
_HEADER_SHORT_STRING_SIZE = 256

requires_windows_wchar = pytest.mark.skipif(
    _HOST_WCHAR_SIZE != _WINDOWS_WCHAR_SIZE,
    reason=(
        f"host wchar_t is {_HOST_WCHAR_SIZE} bytes; the Access Bridge ABI is "
        f"defined for the {_WINDOWS_WCHAR_SIZE}-byte Windows wchar_t"
    ),
)


def read_header() -> str:
    """The JDK 17 header text, or skip: ``.todo`` is not part of the package."""
    if not _HEADER.is_file():
        pytest.skip(f"JDK 17 headers not available at {_HEADER}")
    return _HEADER.read_text(encoding="utf-8", errors="replace")


def header_defines(text: str) -> dict[str, int]:
    return {
        name: int(literal)
        for name, literal in re.findall(r"#define\s+(\w+)\s+(\d+)", text)
    }


def header_members(text: str) -> list[tuple[str, str, str | None]]:
    """Return ``(c_type, member_name, array_length_token)`` for each member."""
    body = re.search(
        rf"typedef\s+struct\s+{_STRUCT_TAG}\s*\{{(.*?)\}}\s*\w+\s*;", text, re.DOTALL
    )
    if body is None:
        pytest.fail(f"{_STRUCT_TAG} not found in {_HEADER}")
    declarations = re.sub(r"//[^\n]*", "", body.group(1))
    members = []
    for chunk in declarations.split(";"):
        matched = re.fullmatch(r"\s*(\w+)\s+(\w+)\s*(?:\[\s*(\w+)\s*\])?\s*", chunk)
        if matched is not None:
            members.append(matched.groups())
    return members


def header_layout(text: str) -> tuple[dict[str, int], int]:
    """Compute member offsets and the struct size from the C declarations."""
    defines = header_defines(text)
    offsets: dict[str, int] = {}
    cursor = 0
    alignment = 1
    for c_type, member, length_token in header_members(text):
        width = _C_SIZES[c_type]
        count = 1 if length_token is None else defines[length_token]
        cursor += -cursor % width
        offsets[member] = cursor
        cursor += width * count
        alignment = max(alignment, width)
    return offsets, cursor + -cursor % alignment


@requires_windows_wchar
def test_member_offsets_match_the_transcribed_header() -> None:
    actual = {
        member: getattr(AccessibleContextInfo, member).offset
        for member in _EXPECTED_OFFSETS
    }
    assert actual == _EXPECTED_OFFSETS


@requires_windows_wchar
def test_struct_size_matches_the_transcribed_header() -> None:
    assert ctypes.sizeof(AccessibleContextInfo) == _EXPECTED_SIZE


@requires_windows_wchar
def test_no_member_is_missing_from_the_ctypes_declaration() -> None:
    declared = [member for member, _ in AccessibleContextInfo._fields_]
    assert declared == list(_EXPECTED_OFFSETS)


def test_transcription_agrees_with_the_jdk_header() -> None:
    """The literals above are only trustworthy while the header still says so."""
    offsets, size = header_layout(read_header())
    assert offsets == _EXPECTED_OFFSETS
    assert size == _EXPECTED_SIZE


def test_string_size_constants_come_from_the_header() -> None:
    defines = header_defines(read_header())
    assert defines["MAX_STRING_SIZE"] == _HEADER_MAX_STRING_SIZE
    assert defines["SHORT_STRING_SIZE"] == _HEADER_SHORT_STRING_SIZE
    assert defines["MAX_STRING_SIZE"] == MAX_STRING_SIZE
    assert defines["SHORT_STRING_SIZE"] == SHORT_STRING_SIZE


def test_jobject64_is_jlong_outside_the_legacy_build() -> None:
    """``types.py`` picks the non-legacy arm of the header's ``#ifdef``."""
    text = read_header()
    switch = re.search(
        r"#ifdef\s+ACCESSBRIDGE_ARCH_LEGACY(.*?)#else(.*?)#endif", text, re.DOTALL
    )
    assert switch is not None
    assert "typedef jobject JOBJECT64;" in switch.group(1)
    assert "typedef jlong JOBJECT64;" in switch.group(2)
