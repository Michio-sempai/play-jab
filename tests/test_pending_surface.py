"""Placeholders for concept requirements the native slice does not implement yet.

CONCEPT.MD asks the unit suite to cover "timeout and wake-up by events" and the
ABI suite to check a generated role/state registry. The bridge exposes no
callback registration, no waiting primitive and no registry, so there is nothing
to time out, nothing to wake and nothing to compare against. Rather than leave
those silently untested, the absences are asserted here: each test fails the
moment the surface appears, which is the moment the real tests are owed.

Delete each test - and write the real ones - as the surface lands.
"""

from __future__ import annotations

import importlib.util

from play_jab._native.backend import NativeBackend
from play_jab._native.bridge import BridgeRuntime

_EVENT_WORDS = ("callback", "listener", "event", "subscribe", "notify")
_WAITING_WORDS = ("wait", "expect", "poll", "deadline", "timeout")


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


def test_the_bridge_runtime_offers_no_waiting_primitive() -> None:
    """The one existing timeout is not auto-wait and does not satisfy the concept.

    ``ready_timeout`` bounds startup only. It does not re-evaluate a condition,
    so it is not the polling-plus-event auto-wait CONCEPT.MD asks for; there is
    still no API to test for that.
    """
    offenders = [
        name
        for name in public_names(BridgeRuntime)
        if any(word in name.lower() for word in _WAITING_WORDS + _EVENT_WORDS)
    ]
    assert offenders == [], f"waiting landed; write the timeout tests for {offenders}"


def test_no_role_or_state_registry_exists_to_validate_yet() -> None:
    """``ContextInfo`` carries ``role_en_us``/``states_en_us`` as opaque strings.

    Until a registry exists there is nothing to compare against the header's
    ``ACCESSIBLE_*`` constants, and no distinct scenarios for the standard
    ``"unknown"`` role, an unrecognised value, and a registered extension.
    """
    for module in ("play_jab._native.roles", "play_jab._native.states"):
        assert importlib.util.find_spec(module) is None, (
            f"{module} landed; write the registry contract tests"
        )
