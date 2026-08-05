"""Placeholder for the callback surface the read-only polling API omits.

The locator waiting and generated registry placeholders formerly in this module
were replaced by their full contract suites when those surfaces landed. Native
callbacks remain explicitly outside this stage, so their absence stays pinned.

Delete each test - and write the real ones - as the surface lands.
"""

from __future__ import annotations

from play_jab._native.backend import NativeBackend

_EVENT_WORDS = ("callback", "listener", "event", "subscribe", "notify")


def public_names(namespace: type) -> list[str]:
    return [name for name in vars(namespace) if not name.startswith("_")]


def test_the_native_backend_registers_no_callbacks() -> None:
    """No Python callback objects are kept alive yet, because none are registered."""
    offenders = [
        name
        for name in public_names(NativeBackend)
        if any(word in name.lower() for word in _EVENT_WORDS)
    ]
    assert offenders == [], f"callbacks landed; write the event tests for {offenders}"
