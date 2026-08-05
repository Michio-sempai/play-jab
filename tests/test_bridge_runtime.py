"""Bridge runtime behaviour over the fake backend, plus a real-DLL smoke test."""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest

from play_jab._native.backend import dll_backend_factory
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.dll import find_access_bridge_dll
from play_jab._native.fake import FakeBackend, FakeNode, fake_backend_factory
from play_jab.exceptions import (
    BridgeClosedError,
    BridgeInitializationError,
    JavaReferenceClosedError,
    JavaWindowNotFoundError,
    NativeCallError,
)

WINDOW_HWND = 0x1234
MISSING_HWND = 0x9999
BUTTON_COUNT = 2
FAULTS_BEFORE_READY = 3


def build_tree() -> FakeNode:
    return FakeNode(
        name="Example",
        role_en_us="frame",
        states_en_us="visible,showing",
        children=[
            FakeNode(name="Sign in", role_en_us="push button"),
            FakeNode(name="Cancel", role_en_us="push button"),
        ],
    )


@pytest.fixture
def runtime() -> Iterator[tuple[BridgeRuntime, FakeBackend]]:
    backend, factory = fake_backend_factory({WINDOW_HWND: build_tree()})
    bridge = BridgeRuntime(factory, pump_interval=0.001)
    with bridge:
        yield bridge, backend


def test_startup_runs_windows_run_and_pumps(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    _, backend = runtime
    assert backend.windows_run_calls == 1
    assert backend.pump_turns >= 1


def test_readiness_retries_past_native_faults() -> None:
    backend, factory = fake_backend_factory(
        {WINDOW_HWND: build_tree()}, faults_before_ready=FAULTS_BEFORE_READY
    )
    bridge = BridgeRuntime(factory, pump_interval=0.001)
    bridge.start(probe_hwnd=WINDOW_HWND)
    with bridge:
        # The probe faulted three times and startup rode it out, so the retry
        # loop is load-bearing rather than decorative.
        assert backend.faults_before_ready == 0
        # One pump turn per attempt: the pump must turn before every probe.
        assert backend.pump_turns > FAULTS_BEFORE_READY
        assert bridge.is_java_window(WINDOW_HWND)


def test_readiness_timeout_fails_startup() -> None:
    _, factory = fake_backend_factory(faults_before_ready=10**6)
    bridge = BridgeRuntime(factory, ready_timeout=0.05, pump_interval=0.001)
    with pytest.raises(BridgeInitializationError):
        bridge.start(probe_hwnd=WINDOW_HWND)
    assert bridge.closed


def test_traversal_hands_out_one_owned_reference_per_call(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    with bridge.context_from_hwnd(WINDOW_HWND) as root:
        info = bridge.context_info(root)
        assert info.name == "Example"
        assert info.children_count == BUTTON_COUNT

        first = bridge.child(root, 0)
        assert first is not None
        with first:
            assert bridge.context_info(first).name == "Sign in"
            assert bridge.hwnd_from_context(root) == WINDOW_HWND
            # A button is not a top-level window: no HWND is the normal answer,
            # not a failure.
            assert bridge.hwnd_from_context(first) is None
            parent = bridge.parent(first)
            assert parent is not None
            # A second reference to the same node is a distinct cookie.
            assert parent.value != root.value
            parent.close()

        assert bridge.child(root, BUTTON_COUNT) is None

    assert bridge.live_ref_count == 0
    assert backend.live_cookies == frozenset()
    assert backend.acquired == backend.released


def test_closing_a_reference_twice_releases_once(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    root = bridge.context_from_hwnd(WINDOW_HWND)
    root.close()
    root.close()
    assert backend.released == 1
    assert root.closed
    # A released reference is not a closed runtime; the two are distinct errors.
    with pytest.raises(JavaReferenceClosedError):
        _ = root.value


def test_unknown_window_is_not_a_java_window(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, _ = runtime
    assert bridge.is_java_window(WINDOW_HWND)
    assert not bridge.is_java_window(MISSING_HWND)
    with pytest.raises(JavaWindowNotFoundError):
        bridge.context_from_hwnd(MISSING_HWND)


def test_calls_after_close_are_rejected() -> None:
    backend, factory = fake_backend_factory({WINDOW_HWND: build_tree()})
    bridge = BridgeRuntime(factory, pump_interval=0.001)
    bridge.start()
    root = bridge.context_from_hwnd(WINDOW_HWND)
    bridge.close()
    bridge.close()

    assert backend.shutdown_calls == 1
    # Still counted: shutdown abandoned this reference rather than releasing it.
    assert bridge.live_ref_count == 1
    with pytest.raises(BridgeClosedError):
        bridge.is_java_window(WINDOW_HWND)
    with pytest.raises(BridgeClosedError):
        bridge.context_info(root)
    # Releasing a reference whose runtime is gone is a no-op, not an error: the
    # DLL is unloaded and every cookie for that vmID is already invalid.
    root.close()
    assert backend.released == 0


def test_a_stale_context_is_a_normal_outcome_not_a_crash() -> None:
    """A Swing tree rebuild invalidates live handles; that is expected, per §3."""
    backend, factory = fake_backend_factory({WINDOW_HWND: build_tree()})
    with BridgeRuntime(factory, pump_interval=0.001) as bridge:
        root = bridge.context_from_hwnd(WINDOW_HWND)
        backend.make_all_stale()

        # Reads fail the way the DLL fails - a translated error, not an assertion.
        with pytest.raises(NativeCallError):
            bridge.context_info(root)
        assert bridge.child(root, 0) is None
        assert bridge.parent(root) is None
        assert bridge.hwnd_from_context(root) is None

        # The reference is still owned, and still has to be handed back once.
        root.close()
        assert backend.released == 1
        assert bridge.live_ref_count == 0


def test_the_two_closed_errors_cannot_be_conflated() -> None:
    """Siblings on purpose: neither may be caught by handling the other."""
    assert not issubclass(JavaReferenceClosedError, BridgeClosedError)
    assert not issubclass(BridgeClosedError, JavaReferenceClosedError)


def test_a_failed_release_still_stops_counting_the_reference() -> None:
    """A JavaRef gets one shot at releasing, so the count must not drift."""

    class ReleaseFailsBackend(FakeBackend):
        def release_java_object(self, vm_id: int, value: int) -> None:
            raise OSError("releaseJavaObject blew up")

    backend = ReleaseFailsBackend({WINDOW_HWND: build_tree()})
    with BridgeRuntime(lambda: backend, pump_interval=0.001) as bridge:
        root = bridge.context_from_hwnd(WINDOW_HWND)
        assert bridge.live_ref_count == 1
        with pytest.raises(OSError, match="blew up"):
            root.close()
        assert root.closed
        assert bridge.live_ref_count == 0


@pytest.mark.skipif(
    sys.platform != "win32", reason="Java Access Bridge is Windows-only"
)
def test_real_bridge_starts_and_shuts_down() -> None:
    try:
        find_access_bridge_dll()
    except BridgeInitializationError as exc:
        pytest.skip(str(exc))
    with BridgeRuntime(dll_backend_factory()) as bridge:
        assert bridge.is_java_window(0) is False
