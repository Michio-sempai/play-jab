"""The Access Bridge runtime: one thread, one message pump, one DLL."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import TypeVar, cast

from play_jab._native.backend import ContextInfo, NativeBackend, dll_backend_factory
from play_jab._native.dll import jab_enabled_for_current_user
from play_jab._native.refs import JavaRef
from play_jab.exceptions import (
    BridgeClosedError,
    BridgeInitializationError,
    BridgeNotEnabledError,
    JavaWindowNotAccessibleError,
    JavaWindowNotFoundError,
    NativeCallError,
)

__all__ = ["DEFAULT_PUMP_INTERVAL", "DEFAULT_READY_TIMEOUT", "BridgeRuntime"]

_T = TypeVar("_T")

DEFAULT_READY_TIMEOUT = 5.0
"""Seconds to wait for the bridge to become callable after ``Windows_run``."""

DEFAULT_PUMP_INTERVAL = 0.01
"""Longest the worker may block on the command queue before pumping again."""

_INITIAL_PROBE_DELAY = 0.005
_MAX_PROBE_DELAY = 0.2
_SHUTDOWN_JOIN_TIMEOUT = 5.0
_CLOSED_MESSAGE = "bridge runtime is closed"
_NULL_HWND = 0


class _Call:
    """One unit of work for the worker thread; ``fn is None`` means stop."""

    __slots__ = ("done", "error", "fn", "result")

    def __init__(self, fn: Callable[[], object] | None) -> None:
        self.fn = fn
        self.done = threading.Event()
        self.result: object = None
        self.error: BaseException | None = None


class BridgeRuntime:
    """Owns the Access Bridge DLL and serializes every call onto one thread.

    The Access Bridge is bound to the thread that loads the DLL and calls
    ``Windows_run``: that thread owns the bridge's message window, and the
    window's messages must keep being dispatched for the bridge's lifecycle to
    work at all. So the runtime starts a dedicated worker thread which loads the
    library, pumps messages continuously, and executes every public call. This
    is a correctness requirement, not a performance choice - calling the bridge
    from arbitrary Python threads is undefined behaviour.

    A running message pump is necessary, not sufficient: it does not, for
    example, prevent ``doAccessibleActions`` from blocking when a Java handler
    synchronously opens a modal dialog.
    """

    def __init__(
        self,
        backend_factory: Callable[[], NativeBackend] | None = None,
        *,
        ready_timeout: float = DEFAULT_READY_TIMEOUT,
        pump_interval: float = DEFAULT_PUMP_INTERVAL,
    ) -> None:
        self._backend_factory = backend_factory or dll_backend_factory()
        self._ready_timeout = ready_timeout
        self._pump_interval = pump_interval
        self._queue: queue.Queue[_Call] = queue.Queue()
        # Reentrant: worker-side operations take this lock while the runtime is
        # mid-call, and a plain Lock would turn any future nesting into a hang.
        self._lock = threading.RLock()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._backend: NativeBackend | None = None
        self._startup_error: BaseException | None = None
        self._in_flight: _Call | None = None
        self._closed = False
        self._live_refs = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the worker thread and wait until the bridge is usable."""
        with self._lock:
            if self._closed:
                raise BridgeClosedError(_CLOSED_MESSAGE)
            if self._thread is not None:
                raise BridgeInitializationError("bridge runtime is already started")
            self._thread = threading.Thread(
                target=self._worker, name="play-jab-bridge", daemon=True
            )
            thread = self._thread
        thread.start()
        self._started.wait()
        if self._startup_error is not None:
            thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT)
            raise self._startup_error

    def close(self) -> None:
        """Shut the bridge down. Safe to call any number of times."""
        with self._lock:
            thread = self._thread
            was_closed = self._closed
            self._closed = True
            if thread is None or was_closed:
                return
            self._queue.put(_Call(None))
        if thread is not threading.current_thread():
            thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def live_ref_count(self) -> int:
        """Owned Java references handed out and not yet given back to the JVM.

        Deliberately *not* reset on shutdown. Unloading the DLL is not a release:
        cookies still outstanding at that point are abandoned rather than
        returned, and the JVM may keep pinning those objects until its own exit.
        Zeroing the counter would report a clean teardown that did not happen, so
        a non-zero value after :meth:`close` is a real leak worth seeing.
        """
        return self._live_refs

    def __enter__(self) -> BridgeRuntime:
        if self._thread is None:
            self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- worker thread -----------------------------------------------------

    def _worker(self) -> None:
        backend: NativeBackend | None = None
        try:
            backend = self._backend_factory()
            backend.windows_run()
            self._await_ready(backend)
        except BaseException as exc:
            self._startup_error = exc
            self._mark_closed()
            # Cleanup must never be able to strand start(). A backend whose
            # shutdown raises is already violating the protocol, but it must
            # still not turn a diagnosable startup failure into a hang: the
            # waiter is released either way, and the original cause is what
            # start() reports.
            try:
                if backend is not None:
                    backend.shutdown()
            finally:
                self._started.set()
                self._reject_pending()
            return

        self._backend = backend
        self._started.set()
        try:
            self._serve(backend)
        finally:
            self._mark_closed()
            self._backend = None
            try:
                backend.shutdown()
            finally:
                # Same reasoning: whatever happens to the DLL, callers waiting
                # on this worker have to be woken.
                self._fail_in_flight()
                self._reject_pending()

    def _mark_closed(self) -> None:
        with self._lock:
            self._closed = True

    def _await_ready(self, backend: NativeBackend) -> None:
        """Turn the pump once, then confirm the DLL answers a call.

        What actually protects against the native access violation another
        wrapper hit here is the ``pump_messages()`` call below, before anything
        else touches the bridge. That is the whole mitigation, and it is why a
        fixed pause is not used: turning the pump is the event being waited for,
        so waiting on a clock instead would be a race dressed up as a delay.

        The probe that follows cannot fail against today's DLL, and this is
        measured rather than assumed. Disassembling the shipped 32-bit build
        shows every export opening with ``mov ecx,[init_flag]; test ecx,ecx;
        jz`` to a stub that does ``xor eax,eax; ret`` - so before initialization
        each one returns FALSE cleanly instead of faulting. Calling
        ``isJavaWindow(NULL)`` immediately after ``Windows_run`` with zero pump
        turns returns 0 either way.

        The retry loop is therefore defensive, not load-bearing: it costs one
        call on the happy path and would absorb a fault on a JDK whose exports
        are not guarded this way. It must not be read as evidence that a
        not-yet-ready bridge is detectable here - it is not.

        Consequently :class:`BridgeNotEnabledError` is unreachable through this
        path today: a bridge that is merely disabled answers the probe exactly
        like a working one. Detecting that needs a probe requiring a live JVM,
        which this eight-call slice has no way to express. The error stays
        because the condition is real and the hierarchy is mandated; only its
        detection is missing.
        """
        deadline = time.monotonic() + self._ready_timeout
        delay = _INITIAL_PROBE_DELAY
        while True:
            backend.pump_messages()
            try:
                backend.is_java_window(_NULL_HWND)
            except OSError:
                pass
            else:
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(delay)
            delay = min(delay * 2, _MAX_PROBE_DELAY)

        if not jab_enabled_for_current_user():
            raise BridgeNotEnabledError(
                "Java Access Bridge did not become ready and is not enabled for "
                "the current user. Enable it with `%JAVA_HOME%\\bin\\jabswitch "
                "-enable` and restart the Java application."
            )
        raise BridgeInitializationError(
            f"Java Access Bridge did not become ready within "
            f"{self._ready_timeout:g}s of Windows_run()"
        )

    def _serve(self, backend: NativeBackend) -> None:
        while True:
            try:
                call = self._queue.get(timeout=self._pump_interval)
            except queue.Empty:
                call = None
            if call is not None and call.fn is None:
                return
            # Publish before pumping. If pump_messages() raises, this call has
            # been taken off the queue and _reject_pending() will never see it,
            # so the shutdown path needs a way to complete it - otherwise its
            # submitter waits forever.
            self._in_flight = call
            # Pump on every turn, idle or not: the bridge's message window has
            # to keep being serviced, not only while calls are in flight.
            backend.pump_messages()
            if call is not None and call.fn is not None:
                self._execute(call, call.fn)
            self._in_flight = None

    @staticmethod
    def _execute(call: _Call, function: Callable[[], object]) -> None:
        try:
            call.result = function()
        except BaseException as exc:
            call.error = exc
        finally:
            call.done.set()

    def _fail_in_flight(self) -> None:
        """Complete a call the worker dequeued but could not finish."""
        call = self._in_flight
        if call is not None and not call.done.is_set():
            call.error = BridgeClosedError(_CLOSED_MESSAGE)
            call.done.set()

    def _reject_pending(self) -> None:
        while True:
            try:
                call = self._queue.get_nowait()
            except queue.Empty:
                return
            if call.fn is not None:
                call.error = BridgeClosedError(_CLOSED_MESSAGE)
                call.done.set()

    # -- dispatch ----------------------------------------------------------

    def _submit(self, fn: Callable[[], _T]) -> _T:
        if threading.current_thread() is self._thread:
            # Load-bearing, though nothing calls back into the runtime yet: a
            # JavaRef's weakref.finalize can fire during a GC pass on the worker
            # thread itself, mid-operation. That finalizer releases through this
            # method, and queueing it would make the worker wait on work only
            # the worker can perform. Run it inline instead.
            return fn()
        call = _Call(cast("Callable[[], object]", fn))
        with self._lock:
            if self._closed or self._thread is None:
                raise BridgeClosedError(_CLOSED_MESSAGE)
            self._queue.put(call)
        # Deliberately unbounded. A deadline here would invent failures on calls
        # that are legitimately slow - a Java handler opening a modal dialog is
        # the known case - and it could not repair anything either way, since an
        # in-flight ctypes call cannot be safely cancelled (CONCEPT section 7,
        # which leaves a watchdog to post-MVP). The specific hole this could have
        # hidden is closed instead: _in_flight tracking guarantees that a call
        # taken off the queue is completed even if the worker dies mid-turn.
        call.done.wait()
        if call.error is not None:
            raise call.error
        result = cast("_T", call.result)
        # Hand the result over completely. The worker's frame keeps the last
        # _Call in a local until its next loop turn, and a JavaRef still pinned
        # there would outlive the caller's own reference - which would make the
        # finalizer safety net fire late and non-deterministically.
        call.result = None
        return result

    def _call(self, fn: Callable[[NativeBackend], _T]) -> _T:
        return self._submit(lambda: fn(self._require_backend()))

    def _require_backend(self) -> NativeBackend:
        backend = self._backend
        if backend is None:
            raise BridgeClosedError(_CLOSED_MESSAGE)
        return backend

    def _own(self, vm_id: int, value: int) -> JavaRef:
        """Wrap a freshly returned cookie as the single owner of that reference.

        Called on the worker thread, in the same step as the native call that
        produced the cookie, so the cookie is never left unowned across a thread
        hand-off where an error could strand it.

        ``_live_refs`` is worker-owned: every increment and decrement runs on
        that one thread, so it needs no lock of its own. Readers on other
        threads see a plain int load.
        """
        self._live_refs += 1
        return JavaRef(self, vm_id, value)

    # -- native operations -------------------------------------------------
    #
    # Each operation reads ref.vm_id/ref.value *inside* the worker closure, not
    # on the calling thread. Reads and native calls are then ordered by the same
    # queue as releases, so a concurrent close() either happens entirely before
    # the operation (and the read raises) or entirely after it.

    def is_java_window(self, hwnd: int) -> bool:
        """Whether ``hwnd`` belongs to a Java application exposing JAB."""
        return self._call(lambda backend: backend.is_java_window(hwnd))

    def context_from_hwnd(self, hwnd: int) -> JavaRef:
        """Attach to a top-level window; returns a newly owned reference."""

        def operation(backend: NativeBackend) -> JavaRef:
            if not backend.is_java_window(hwnd):
                raise JavaWindowNotFoundError(
                    f"window {hwnd:#x} is not a Java window, or no longer exists"
                )
            found = backend.get_accessible_context_from_hwnd(hwnd)
            if found is None:
                raise JavaWindowNotAccessibleError(
                    f"window {hwnd:#x} is a Java window but exposes no "
                    f"accessible context"
                )
            vm_id, value = found
            return self._own(vm_id, value)

        return self._call(operation)

    def context_info(self, ref: JavaRef) -> ContextInfo:
        """Read a node's attributes. The result owns no reference."""

        def operation(backend: NativeBackend) -> ContextInfo:
            vm_id, value = ref.vm_id, ref.value
            info = backend.get_accessible_context_info(vm_id, value)
            if info is None:
                raise NativeCallError("getAccessibleContextInfo", vmID=vm_id, ac=value)
            return info

        return self._call(operation)

    def child(self, ref: JavaRef, index: int) -> JavaRef | None:
        """The child at ``index`` as a newly owned reference, or ``None``."""

        def operation(backend: NativeBackend) -> JavaRef | None:
            vm_id, value = ref.vm_id, ref.value
            child = backend.get_accessible_child_from_context(vm_id, value, index)
            if not child:
                return None
            return self._own(vm_id, child)

        return self._call(operation)

    def parent(self, ref: JavaRef) -> JavaRef | None:
        """The parent as a newly owned reference, or ``None`` at the root."""

        def operation(backend: NativeBackend) -> JavaRef | None:
            vm_id, value = ref.vm_id, ref.value
            parent = backend.get_accessible_parent_from_context(vm_id, value)
            if not parent:
                return None
            return self._own(vm_id, parent)

        return self._call(operation)

    def hwnd_from_context(self, ref: JavaRef) -> int | None:
        """The top-level window owning this context, or ``None``.

        ``None`` is the ordinary answer for any context that is not itself a
        top-level window, not a failure.
        """
        hwnd = self._call(
            lambda backend: backend.get_hwnd_from_accessible_context(
                ref.vm_id, ref.value
            )
        )
        return hwnd or None

    def _release_java_object(self, vm_id: int, value: int) -> None:
        """Give one owned reference back to the JVM. Called by :class:`JavaRef`.

        The accounting happens on the worker thread, in the same step as the
        native call, and in a ``finally``. A :class:`JavaRef` gets exactly one
        chance to release - ``weakref.finalize`` unregisters itself before
        invoking - so if the release reached the backend and then failed, the
        reference is spent either way and must stop being counted, or
        :attr:`live_ref_count` drifts permanently and stops being usable as the
        "every owned cookie released exactly once" check.
        """

        def operation(backend: NativeBackend) -> None:
            try:
                backend.release_java_object(vm_id, value)
            finally:
                self._live_refs -= 1

        self._call(operation)
