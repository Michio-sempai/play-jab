"""Minimal contract for callback-assisted waiting."""

from __future__ import annotations

from play_jab._native.backend import NativeBackend


def test_the_native_backend_registers_process_lifecycle_callbacks() -> None:
    assert callable(NativeBackend.setup_event_callbacks)
