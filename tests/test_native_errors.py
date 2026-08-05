"""Turning native failure signals into diagnosable Python errors.

Backends mirror the C API: ``FALSE`` becomes ``None``, a null cookie becomes
``0``. Those are not errors yet - :class:`BridgeRuntime` is what decides which
of them is a failure and attaches enough context to debug it. The concept
document also constrains *what* may be attached: the export name and scalar
arguments, never text read out of the application, because that text can be the
contents of a password field.
"""

from __future__ import annotations

import contextlib
import gc
import threading
import time
from collections.abc import Iterator

import pytest

from play_jab._native.backend import ContextInfo
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode, fake_backend_factory
from play_jab.exceptions import (
    JavaWindowNotAccessibleError,
    JavaWindowNotFoundError,
    NativeCallError,
    PlayJabError,
)

WINDOW_HWND = 0x7777
MISSING_HWND = 0x8888
PUMP_INTERVAL = 0.001
REENTRY_TIMEOUT = 5.0
UNBLOCK_TIMEOUT = 5.0
# Long enough that a caller which was going to return already would have.
WEDGE_OBSERVATION = 0.2
HANG_TIMEOUT = 5.0
SECRET = "hunter2"


def tree() -> FakeNode:
    return FakeNode(
        name=SECRET,
        role_en_us="password text",
        children=[FakeNode(name="OK", role_en_us="push button")],
    )


class RefusesContextInfo(FakeBackend):
    """``getAccessibleContextInfo`` answers FALSE, as it does for a dead node."""

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        return None


class HasNoAccessibleContext(FakeBackend):
    """A Java window whose root context cannot be obtained."""

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        return None


class BlocksUntilReleased(FakeBackend):
    """A native call that does not return, like the known modal-dialog hang."""

    def __init__(self, windows: dict[int, FakeNode]) -> None:
        super().__init__(windows)
        self.may_return = threading.Event()

    def is_java_window(self, hwnd: int) -> bool:
        # Only the call under test blocks. The runtime's readiness probe is the
        # same export with a NULL hwnd, and wedging that would just stall startup.
        if hwnd == WINDOW_HWND:
            self.may_return.wait(UNBLOCK_TIMEOUT)
        return super().is_java_window(hwnd)


class CollectsGarbageMidCall(FakeBackend):
    """Runs a GC pass on the worker thread, from inside a native call.

    Counts releases that arrive *while* a call is still executing, which is the
    only observable proof that the finalizer re-entered the runtime rather than
    taking the ordinary queued path.
    """

    def __init__(self, windows: dict[int, FakeNode]) -> None:
        super().__init__(windows)
        self.mid_call = False
        self.released_mid_call = 0

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        self.mid_call = True
        try:
            gc.collect()
            return super().get_accessible_context_info(vm_id, context)
        finally:
            self.mid_call = False

    def release_java_object(self, vm_id: int, value: int) -> None:
        if self.mid_call:
            self.released_mid_call += 1
        super().release_java_object(vm_id, value)


def strand_in_a_cycle(ref: object) -> None:
    """Make ``ref`` reachable only from a reference cycle.

    A plain ``del`` is not the scenario: the refcount hits zero and CPython
    finalizes immediately, on the calling thread, through the ordinary queued
    path. Parking the reference in a cycle leaves it for the cyclic collector,
    so the finalizer runs on whichever thread next collects - the worker.
    """
    cycle: dict[str, object] = {"ref": ref}
    cycle["self"] = cycle


class CallsBackIntoTheBridge(FakeBackend):
    """Re-enters the runtime from inside a native call, as a callback would."""

    def __init__(self, windows: dict[int, FakeNode]) -> None:
        super().__init__(windows)
        self.bridge: BridgeRuntime | None = None
        self.answers: list[bool] = []

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        assert self.bridge is not None
        self.answers.append(self.bridge.is_java_window(WINDOW_HWND))
        return super().get_accessible_context_info(vm_id, context)


@pytest.fixture
def runtime() -> Iterator[tuple[BridgeRuntime, FakeBackend]]:
    backend, factory = fake_backend_factory({WINDOW_HWND: tree()})
    bridge = BridgeRuntime(factory, pump_interval=PUMP_INTERVAL)
    with bridge:
        yield bridge, backend


def started(backend: FakeBackend) -> BridgeRuntime:
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    bridge.start()
    return bridge


def test_a_false_context_info_names_the_export_and_its_arguments() -> None:
    backend = RefusesContextInfo({WINDOW_HWND: tree()})
    bridge = started(backend)
    with bridge, bridge.context_from_hwnd(WINDOW_HWND) as root:
        cookie = root.value
        with pytest.raises(NativeCallError) as raised:
            bridge.context_info(root)

    failure = raised.value
    assert failure.function == "getAccessibleContextInfo"
    assert failure.arguments == {"vmID": backend.vm_id, "ac": cookie}
    assert "getAccessibleContextInfo" in str(failure)
    assert isinstance(failure, PlayJabError)


def test_a_native_failure_never_carries_application_text() -> None:
    """The node's name is a password field's contents here; it must not leak."""
    backend = RefusesContextInfo({WINDOW_HWND: tree()})
    bridge = started(backend)
    with (
        bridge,
        bridge.context_from_hwnd(WINDOW_HWND) as root,
        pytest.raises(NativeCallError) as raised,
    ):
        bridge.context_info(root)

    assert SECRET not in str(raised.value)
    assert SECRET not in repr(raised.value.arguments)


def test_a_java_window_without_a_context_is_its_own_error() -> None:
    """Distinct from "not a Java window": the window is there, the tree is not."""
    bridge = started(HasNoAccessibleContext({WINDOW_HWND: tree()}))
    with bridge, pytest.raises(JavaWindowNotAccessibleError, match=r"no.*accessible"):
        bridge.context_from_hwnd(WINDOW_HWND)


def test_an_absent_window_is_reported_before_any_context_is_asked_for(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    with pytest.raises(JavaWindowNotFoundError, match="not a Java window"):
        bridge.context_from_hwnd(MISSING_HWND)
    assert backend.acquired == 0


def test_a_wedged_native_call_blocks_every_caller_with_no_diagnostic() -> None:
    """Documents an accepted limitation, not a behaviour anyone wants.

    Every call is serialized onto the one worker thread, so a native call that
    does not return blocks every other caller on every thread, silently. The
    known instance is ``doAccessibleActions`` on a handler that synchronously
    opens a modal dialog.

    A call timeout was considered and rejected: an in-flight ctypes call cannot
    be safely cancelled (CONCEPT section 7, which leaves a watchdog to post-MVP),
    so a deadline could not repair anything and would instead invent failures on
    calls that are legitimately slow - the modal-dialog case being exactly one of
    those. What *is* guaranteed is narrower: a call the worker has dequeued is
    always completed rather than abandoned, even if the worker dies mid-turn.
    """
    backend = BlocksUntilReleased({WINDOW_HWND: tree()})
    bridge = BridgeRuntime(lambda: backend, pump_interval=PUMP_INTERVAL)
    bridge.start()
    returned: dict[str, threading.Event] = {
        "wedged": threading.Event(),
        "bystander": threading.Event(),
    }

    def call(tag: str, hwnd: int) -> None:
        with contextlib.suppress(BaseException):
            bridge.is_java_window(hwnd)
        returned[tag].set()

    threading.Thread(target=call, args=("wedged", WINDOW_HWND), daemon=True).start()
    # The bystander asks about a different window, which the backend answers
    # immediately - it is stuck only because the worker is, which is the point.
    threading.Thread(target=call, args=("bystander", MISSING_HWND), daemon=True).start()
    deadline = time.monotonic() + HANG_TIMEOUT
    while bridge._queue.qsize() < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert bridge._queue.qsize() == 1, "the bystander's call never reached the queue"

    try:
        assert not returned["wedged"].wait(WEDGE_OBSERVATION), (
            "the caller returned; the wedge this test documents is gone"
        )
        assert not returned["bystander"].is_set(), (
            "an unrelated call completed while the worker was wedged; "
            "calls are no longer serialized onto one thread"
        )
    finally:
        backend.may_return.set()
        assert returned["wedged"].wait(HANG_TIMEOUT), "caller never unwedged"
        assert returned["bystander"].wait(HANG_TIMEOUT), "bystander never unwedged"
        bridge.close()


def test_a_finalizer_firing_during_gc_on_the_worker_thread_does_not_deadlock() -> None:
    """The concrete reason ``_submit``'s re-entrancy fast path is load-bearing.

    Nothing calls back into the runtime yet, so the fast path can look
    speculative. It is not: a dropped :class:`JavaRef`'s ``weakref.finalize``
    fires on whichever thread happens to run the GC pass, and that can be the
    worker thread, mid-operation. The finalizer releases through ``_submit``, so
    without the fast path the worker would queue work only it can perform and
    wait on itself forever. The reentrant lock is needed for the same reason -
    the release re-takes a lock the operation already holds.
    """
    backend = CollectsGarbageMidCall({WINDOW_HWND: tree()})
    bridge = started(backend)
    finished = threading.Event()

    def drive() -> None:
        anchor = bridge.context_from_hwnd(WINDOW_HWND)
        strand_in_a_cycle(bridge.context_from_hwnd(WINDOW_HWND))
        bridge.context_info(anchor)
        anchor.close()
        finished.set()

    threading.Thread(target=drive, name="gc-reentry-probe", daemon=True).start()
    assert finished.wait(REENTRY_TIMEOUT), "a finalizer on the worker thread deadlocked"
    # Without this the test passes vacuously: a reference dropped by refcount
    # finalizes on the caller's thread and never re-enters anything.
    assert backend.released_mid_call == 1, "the finalizer never ran on the worker"
    bridge.close()

    assert backend.released == backend.acquired
    assert bridge.live_ref_count == 0


def test_re_entering_the_runtime_from_a_native_call_does_not_deadlock() -> None:
    """A callback runs on the worker thread; queueing its call would self-deadlock.

    Driven from a helper thread with a deadline so that a regression fails the
    test instead of wedging the whole suite - there is no timeout on the command
    queue, by design, so a genuine deadlock here would never return.
    """
    backend = CallsBackIntoTheBridge({WINDOW_HWND: tree()})
    bridge = started(backend)
    backend.bridge = bridge
    finished = threading.Event()
    names: list[str] = []

    def drive() -> None:
        with bridge.context_from_hwnd(WINDOW_HWND) as root:
            names.append(bridge.context_info(root).name)
        finished.set()

    threading.Thread(target=drive, name="reentry-probe", daemon=True).start()
    assert finished.wait(REENTRY_TIMEOUT), "a re-entrant call deadlocked"
    bridge.close()

    assert names == [SECRET]
    assert backend.answers == [True]
