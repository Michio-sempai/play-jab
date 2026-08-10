"""Startup failure, cleanup after it, and the errors a bad environment produces.

A half-started bridge is the dangerous state: the worker thread exists, the DLL
may be loaded, and the message pump may already be turning. Every failure mode
below therefore asserts the same three things - the caller gets a diagnosable
:class:`PlayJabError`, the backend was shut down exactly once, and no worker
thread is left behind.
"""

from __future__ import annotations

import threading
import time

import pytest

from play_jab._native.backend import NativeBackend, dll_backend_factory
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode, fake_backend_factory
from play_jab.exceptions import (
    BridgeClosedError,
    BridgeInitializationError,
    BridgeNotEnabledError,
)

WINDOW_HWND = 0x5555
WORKER_THREAD_NAME = "play-jab-bridge"
UNREACHABLE_FAULT_COUNT = 10**6
SHORT_TIMEOUT = 0.05
PUMP_INTERVAL = 0.001
READY_AFTER_PUMP_TURNS = 3
HANG_TIMEOUT = 2.0
UNBLOCK_TIMEOUT = 5.0


class RunFailsBackend(FakeBackend):
    """``Windows_run`` fails, as it would against an incompatible DLL."""

    def windows_run(self) -> None:
        super().windows_run()
        raise BridgeInitializationError("Windows_run refused to start the bridge")


class ShutdownFailsBackend(RunFailsBackend):
    """Also violates the protocol's "shutdown must not raise" requirement."""

    def shutdown(self) -> None:
        raise RuntimeError("FreeLibrary blew up during cleanup")


class PumpDiesMidCall(FakeBackend):
    """The message pump fails on a turn that has already dequeued a call.

    Reads ``BridgeRuntime._in_flight`` deliberately. The behaviour under test is
    the private bookkeeping that lets a dequeued call be completed after the
    worker dies, and there is no public signal for "a call is in flight right
    now" - waiting on a wall-clock guess instead would make the test a race.
    """

    def __init__(self) -> None:
        super().__init__({WINDOW_HWND: FakeNode(name="Frame")})
        self.bridge: BridgeRuntime | None = None
        self.reached_a_call = threading.Event()
        self.may_die = threading.Event()

    def pump_messages(self) -> None:
        super().pump_messages()
        if self.bridge is None or self.bridge._in_flight is None:
            return
        self.reached_a_call.set()
        self.may_die.wait(UNBLOCK_TIMEOUT)
        raise OSError("the message pump died")


def queued_calls(bridge: BridgeRuntime) -> int:
    return bridge._queue.qsize()


def worker_threads() -> list[str]:
    return [
        thread.name
        for thread in threading.enumerate()
        if thread.name == WORKER_THREAD_NAME
    ]


def drained_worker_threads() -> list[str]:
    """``worker_threads()``, once a worker nobody joined has had time to exit.

    ``close()`` joins the worker, so everywhere else the check is immediate. A
    worker that dies of its own accord is only observed through the errors it
    hands back, and may still be unwinding when the last of those arrives.
    """
    deadline = time.monotonic() + UNBLOCK_TIMEOUT
    while worker_threads() and time.monotonic() < deadline:
        time.sleep(0.005)
    return worker_threads()


def timing_out_runtime() -> tuple[FakeBackend, BridgeRuntime]:
    backend, factory = fake_backend_factory(
        faults_before_ready=UNREACHABLE_FAULT_COUNT,
    )
    return backend, BridgeRuntime(
        factory, ready_timeout=SHORT_TIMEOUT, pump_interval=PUMP_INTERVAL
    )


# -- the backend never comes into existence --------------------------------


def test_a_factory_that_raises_leaves_no_thread_behind() -> None:
    def factory() -> NativeBackend:
        raise BridgeInitializationError("DLL is missing")

    bridge = BridgeRuntime(factory, pump_interval=PUMP_INTERVAL)
    with pytest.raises(BridgeInitializationError, match="DLL is missing"):
        bridge.start()
    assert bridge.closed
    assert worker_threads() == []


def test_a_missing_dll_fails_the_same_way_through_the_real_factory() -> None:
    """The expected-error smoke path: no bridge anywhere, no crash, a clear error."""
    bridge = BridgeRuntime(dll_backend_factory("no-such-WindowsAccessBridge.dll"))
    with pytest.raises(BridgeInitializationError):
        bridge.start()
    assert bridge.closed
    assert worker_threads() == []


# -- the backend exists but startup fails ----------------------------------


def test_a_failing_windows_run_shuts_the_backend_down_once() -> None:
    backend = RunFailsBackend()
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    with pytest.raises(BridgeInitializationError, match="Windows_run"):
        bridge.start()
    assert backend.shutdown_calls == 1
    assert bridge.closed
    assert worker_threads() == []


def test_a_readiness_timeout_shuts_the_backend_down_once() -> None:
    backend, bridge = timing_out_runtime()
    with pytest.raises(BridgeInitializationError):
        bridge.start(probe_hwnd=WINDOW_HWND)
    assert backend.windows_run_calls == 1
    assert backend.pump_turns >= 1
    assert backend.faults_before_ready < UNREACHABLE_FAULT_COUNT
    assert backend.shutdown_calls == 1
    assert bridge.closed
    assert worker_threads() == []


def test_a_readiness_timeout_names_the_disabled_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "play_jab._native.bridge.jab_enabled_for_current_user", lambda: False
    )
    _, bridge = timing_out_runtime()
    with pytest.raises(BridgeNotEnabledError, match="jabswitch"):
        bridge.start(probe_hwnd=WINDOW_HWND)


def test_a_readiness_timeout_with_jab_enabled_blames_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "play_jab._native.bridge.jab_enabled_for_current_user", lambda: True
    )
    _, bridge = timing_out_runtime()
    with pytest.raises(
        BridgeInitializationError, match="did not become accessible"
    ) as info:
        bridge.start(probe_hwnd=WINDOW_HWND)
    assert not isinstance(info.value, BridgeNotEnabledError)


def test_start_without_a_probe_only_requires_the_first_pump_turn() -> None:
    backend, factory = fake_backend_factory(
        faults_before_ready=UNREACHABLE_FAULT_COUNT,
    )
    bridge = BridgeRuntime(factory, ready_timeout=SHORT_TIMEOUT)
    bridge.start()
    try:
        assert backend.pump_turns >= 1
        assert backend.faults_before_ready == UNREACHABLE_FAULT_COUNT
    finally:
        bridge.close()


def test_start_with_a_probe_waits_until_the_hwnd_is_recognised() -> None:
    backend, factory = fake_backend_factory(
        {WINDOW_HWND: FakeNode(name="Frame")}, faults_before_ready=2
    )
    bridge = BridgeRuntime(
        factory, ready_timeout=SHORT_TIMEOUT, pump_interval=PUMP_INTERVAL
    )
    bridge.start(probe_hwnd=WINDOW_HWND)
    try:
        assert backend.faults_before_ready == 0
        assert backend.pump_turns >= READY_AFTER_PUMP_TURNS
    finally:
        bridge.close()


# -- what remains usable afterwards ----------------------------------------


def test_a_failed_start_cannot_be_retried() -> None:
    backend = RunFailsBackend()
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    with pytest.raises(BridgeInitializationError):
        bridge.start()
    with pytest.raises(BridgeClosedError):
        bridge.start()
    assert backend.windows_run_calls == 1


def test_closing_after_a_failed_start_shuts_nothing_down_twice() -> None:
    backend = RunFailsBackend()
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    with pytest.raises(BridgeInitializationError):
        bridge.start()
    bridge.close()
    bridge.close()
    assert backend.shutdown_calls == 1


def test_every_operation_after_a_failed_start_is_rejected() -> None:
    backend = RunFailsBackend()
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    with pytest.raises(BridgeInitializationError):
        bridge.start()
    with pytest.raises(BridgeClosedError):
        bridge.is_java_window(WINDOW_HWND)
    with pytest.raises(BridgeClosedError):
        bridge.context_from_hwnd(WINDOW_HWND)


def test_a_failed_context_manager_entry_leaves_nothing_dangling() -> None:
    backend = RunFailsBackend()
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    with pytest.raises(BridgeInitializationError), bridge:
        pytest.fail("the body must not run when __enter__ fails")
    assert bridge.closed
    assert backend.shutdown_calls == 1
    assert worker_threads() == []


# -- the healthy lifecycle -------------------------------------------------


def test_starting_an_already_started_runtime_is_refused() -> None:
    _, factory = fake_backend_factory({WINDOW_HWND: FakeNode(name="Frame")})
    bridge = BridgeRuntime(factory, pump_interval=PUMP_INTERVAL)
    with bridge, pytest.raises(BridgeInitializationError, match="already started"):
        bridge.start()


def test_starting_a_closed_runtime_is_refused() -> None:
    _, factory = fake_backend_factory({WINDOW_HWND: FakeNode(name="Frame")})
    bridge = BridgeRuntime(factory, pump_interval=PUMP_INTERVAL)
    bridge.start()
    bridge.close()
    with pytest.raises(BridgeClosedError):
        bridge.start()


def test_close_cannot_join_the_worker_before_thread_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Captured before the monkeypatch below replaces the shared `threading.Thread`
    # attribute process-wide, so the test's own driver threads stay real threads.
    real_thread = threading.Thread
    entered_start = threading.Event()
    allow_start = threading.Event()

    class DelayedStartThread(threading.Thread):
        def start(self) -> None:
            entered_start.set()
            assert allow_start.wait(UNBLOCK_TIMEOUT)
            super().start()

    monkeypatch.setattr("play_jab._native.bridge.threading.Thread", DelayedStartThread)
    _, factory = fake_backend_factory({WINDOW_HWND: FakeNode(name="Frame")})
    bridge = BridgeRuntime(factory, pump_interval=PUMP_INTERVAL)
    outcomes: list[BaseException] = []

    def start_runtime() -> None:
        try:
            bridge.start()
        except BaseException as exc:
            outcomes.append(exc)

    def close_runtime() -> None:
        try:
            bridge.close()
        except BaseException as exc:
            outcomes.append(exc)

    starter = real_thread(target=start_runtime, daemon=True)
    closer = real_thread(target=close_runtime, daemon=True)
    starter.start()
    assert entered_start.wait(UNBLOCK_TIMEOUT)
    closer.start()
    # close() must be waiting for the same lifecycle lock, not joining an
    # unstarted Thread object.
    closer.join(0.02)
    assert closer.is_alive()

    allow_start.set()
    starter.join(UNBLOCK_TIMEOUT)
    closer.join(UNBLOCK_TIMEOUT)
    assert not starter.is_alive()
    assert not closer.is_alive()
    assert outcomes == []
    assert bridge.closed
    assert worker_threads() == []


def test_the_worker_thread_does_not_outlive_the_runtime() -> None:
    _, factory = fake_backend_factory({WINDOW_HWND: FakeNode(name="Frame")})
    with BridgeRuntime(factory, pump_interval=PUMP_INTERVAL) as bridge:
        assert worker_threads() == [WORKER_THREAD_NAME]
        assert bridge.is_java_window(WINDOW_HWND)
    assert worker_threads() == []


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_worker_that_dies_completes_every_call_it_leaves_behind() -> None:
    """Nobody waits forever because the worker died holding their work.

    Two callers are stranded in different places: one call the worker had
    already dequeued, and one still sitting in the queue behind it. Both must
    come back with :class:`BridgeClosedError` - ``_submit`` waits on an event
    with only the call timeout to save it, so a call left uncompleted is a
    30-second stall per caller and then a misleading timeout diagnosis.
    """
    backend = PumpDiesMidCall()
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    bridge.start()
    backend.bridge = bridge
    outcomes: dict[str, BaseException | None] = {}

    def caller(tag: str) -> None:
        outcomes[tag] = None
        try:
            bridge.is_java_window(WINDOW_HWND)
        except BaseException as exc:  # the test is about what callers are told
            outcomes[tag] = exc

    dequeued = threading.Thread(target=caller, args=("dequeued",), daemon=True)
    dequeued.start()
    assert backend.reached_a_call.wait(UNBLOCK_TIMEOUT), "no call ever reached the pump"

    still_queued = threading.Thread(target=caller, args=("queued",), daemon=True)
    still_queued.start()
    deadline = time.monotonic() + UNBLOCK_TIMEOUT
    while queued_calls(bridge) < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert queued_calls(bridge) == 1, "the second call never reached the queue"

    backend.may_die.set()
    dequeued.join(UNBLOCK_TIMEOUT)
    still_queued.join(UNBLOCK_TIMEOUT)

    assert not dequeued.is_alive(), "the in-flight caller was never released"
    assert not still_queued.is_alive(), "the queued caller was never released"
    assert isinstance(outcomes["dequeued"], BridgeClosedError)
    assert isinstance(outcomes["queued"], BridgeClosedError)
    assert bridge.closed
    assert backend.shutdown_calls == 1
    assert drained_worker_threads() == []


# -- cleanup that itself misbehaves ----------------------------------------


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_shutdown_that_raises_does_not_wedge_start() -> None:
    """Cleanup that itself fails must not turn a diagnosable failure into a hang.

    Driven from a helper thread with a deadline: ``start()`` waits on an
    ``Event`` with no timeout, so a regression here would block forever rather
    than fail, and would take the whole suite with it.
    """
    backend = ShutdownFailsBackend()
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    returned = threading.Event()
    reported: list[BaseException] = []

    def attempt() -> None:
        try:
            bridge.start()
        except BaseException as exc:  # the point of the test is what start() raises
            reported.append(exc)
        returned.set()

    threading.Thread(target=attempt, name="failed-start-probe", daemon=True).start()
    assert returned.wait(HANG_TIMEOUT), "start() never returned"

    # The caller is told why startup failed, not how cleanup then failed: the
    # RuntimeError from shutdown() must not displace the original cause.
    assert len(reported) == 1
    assert isinstance(reported[0], BridgeInitializationError)
    assert "Windows_run" in str(reported[0])
    assert bridge.closed
