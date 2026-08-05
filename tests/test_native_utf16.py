"""Decoding the fixed-size UTF-16 buffers of ``AccessibleContextInfo``.

The bridge writes ``wchar_t name[1024]`` inline into the struct. Nothing hands
back a length, so every string is whatever precedes the first NUL - or the whole
buffer when the JVM fills it completely. These are the cases that a
``c_wchar_p``, a wrong array length or a byte-oriented decode would get wrong,
so they are exercised on bytes laid into the struct's own storage rather than on
values Python round-trips through its own encoder.
"""

from __future__ import annotations

import ctypes

import pytest

from play_jab._native.types import (
    MAX_STRING_SIZE,
    SHORT_STRING_SIZE,
    AccessibleContextInfo,
)

_WINDOWS_WCHAR_SIZE = 2
_HOST_WCHAR_SIZE = ctypes.sizeof(ctypes.c_wchar)

_GRINNING_FACE = "\U0001f600"
_SURROGATE_PAIR_UNITS = 2

requires_utf16_wchar = pytest.mark.skipif(
    _HOST_WCHAR_SIZE != _WINDOWS_WCHAR_SIZE,
    reason=(
        f"host wchar_t is {_HOST_WCHAR_SIZE} bytes, so c_wchar is not UTF-16 "
        f"and raw UTF-16 bytes are not what this platform would decode"
    ),
)


def fill(member: str, text: str) -> AccessibleContextInfo:
    """Lay ``text`` into ``member``'s storage as raw UTF-16LE, as the DLL does.

    No NUL is appended: a caller that wants one spells it out, so that the
    "buffer completely full" case stays distinguishable.
    """
    struct = AccessibleContextInfo()
    payload = text.encode("utf-16-le")
    ctypes.memmove(
        ctypes.byref(struct, getattr(AccessibleContextInfo, member).offset),
        payload,
        len(payload),
    )
    return struct


@requires_utf16_wchar
def test_non_ascii_bmp_text_decodes() -> None:
    struct = fill("name", "Пользователь\x00")
    assert struct.name == "Пользователь"


@requires_utf16_wchar
def test_a_surrogate_pair_decodes_to_one_character() -> None:
    struct = fill("name", f"OK {_GRINNING_FACE}\x00")
    assert struct.name == f"OK {_GRINNING_FACE}"
    assert len(struct.name) == len("OK ") + 1


@requires_utf16_wchar
def test_text_stops_at_the_first_nul() -> None:
    """Bytes past the terminator are stale buffer contents, not part of the name."""
    struct = fill("name", "Save\x00Cancel\x00")
    assert struct.name == "Save"


@requires_utf16_wchar
def test_a_completely_full_buffer_has_no_terminator_to_find() -> None:
    struct = fill("role", "y" * SHORT_STRING_SIZE)
    assert struct.role == "y" * SHORT_STRING_SIZE


@requires_utf16_wchar
def test_a_surrogate_pair_may_occupy_the_last_two_units() -> None:
    filler = "y" * (SHORT_STRING_SIZE - _SURROGATE_PAIR_UNITS)
    struct = fill("role", filler + _GRINNING_FACE)
    assert struct.role == filler + _GRINNING_FACE
    assert len(struct.role) == SHORT_STRING_SIZE - 1


@requires_utf16_wchar
def test_a_full_buffer_does_not_bleed_into_the_next_member() -> None:
    """``role`` and ``role_en_US`` are adjacent; an off-by-one would show here."""
    struct = fill("role", "y" * SHORT_STRING_SIZE)
    struct.role_en_US = "push button"
    assert struct.role == "y" * SHORT_STRING_SIZE
    assert struct.role_en_US == "push button"


@requires_utf16_wchar
def test_the_long_and_short_buffers_have_different_capacities() -> None:
    struct = fill("description", "d" * MAX_STRING_SIZE)
    assert len(struct.description) == MAX_STRING_SIZE
    assert len(fill("states", "s" * SHORT_STRING_SIZE).states) == SHORT_STRING_SIZE


@requires_utf16_wchar
def test_an_astral_character_costs_two_of_the_buffer_units() -> None:
    struct = AccessibleContextInfo()
    with pytest.raises(ValueError, match="too long"):
        struct.role = "y" * (SHORT_STRING_SIZE - 1) + _GRINNING_FACE


def test_assignment_cannot_overrun_a_fixed_buffer() -> None:
    struct = AccessibleContextInfo()
    with pytest.raises(ValueError, match="too long"):
        struct.name = "z" * (MAX_STRING_SIZE + 1)


def test_an_exactly_full_assignment_is_accepted() -> None:
    struct = AccessibleContextInfo()
    struct.name = "z" * MAX_STRING_SIZE
    assert len(struct.name) == MAX_STRING_SIZE
