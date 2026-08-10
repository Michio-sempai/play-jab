"""FakeBackend's event-callback surface: cookie ownership and wake semantics.

Mirrors what a real property/table/selection event actually costs:
`DllBackend.setup_event_callbacks`/`_drain_callback_events` carry two owned
JAB references per event, not just a wakeup, and a caller that reads the
event without draining and releasing them leaks. `FakeBackend.emit_event`
reproduces exactly that shape so tests built on the fake catch the same
mistake a real leak would cause.
"""

from __future__ import annotations

from play_jab._native.fake import FakeBackend, FakeNode


def _backend() -> FakeBackend:
    return FakeBackend({1: FakeNode(name="root", role_en_us="frame")})


def test_emit_event_mints_two_owned_refs_that_pump_messages_releases() -> None:
    backend = _backend()
    backend.setup_event_callbacks(lambda: None, lambda _vm_id: None)
    baseline_acquired = backend.acquired

    backend.emit_event()

    assert backend.acquired == baseline_acquired + 2
    assert backend.released == 0  # not drained until the runtime pumps

    backend.pump_messages()
    assert backend.released == backend.acquired


def test_a_caller_that_never_pumps_leaks_the_event_refs() -> None:
    """The whole point of minting refs: a missed drain must be visible."""
    backend = _backend()
    backend.setup_event_callbacks(lambda: None, lambda _vm_id: None)

    for _ in range(3):
        backend.emit_event()

    assert backend.acquired != backend.released


def test_shutdown_drains_any_refs_still_queued_by_emit_event() -> None:
    backend = _backend()
    backend.setup_event_callbacks(lambda: None, lambda _vm_id: None)
    backend.emit_event()
    backend.emit_event()

    backend.shutdown()

    assert backend.acquired == backend.released


def test_emit_vm_shutdown_wakes_without_minting_any_refs() -> None:
    """A shutdown notification carries no owned references (event=source=0)."""
    backend = _backend()
    woken: list[None] = []
    backend.setup_event_callbacks(lambda: woken.append(None), lambda _vm_id: None)
    baseline_acquired = backend.acquired

    backend.emit_vm_shutdown()

    assert woken == [None]
    assert backend.acquired == baseline_acquired
