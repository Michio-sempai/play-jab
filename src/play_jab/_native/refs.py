"""Ownership of a single Java Access Bridge reference."""

from __future__ import annotations

import contextlib
import weakref
from types import TracebackType
from typing import Protocol

from play_jab.exceptions import BridgeClosedError, JavaReferenceClosedError

__all__ = ["JavaRef", "ReferenceReleaser"]


class ReferenceReleaser(Protocol):
    """Whatever can hand an owned reference back to the JVM."""

    def _release_java_object(self, vm_id: int, value: int) -> None: ...


def _release(releaser: ReferenceReleaser, vm_id: int, value: int) -> None:
    """Release a cookie, tolerating a runtime that is already gone.

    Must not close over the :class:`JavaRef` itself - it runs as a finalizer.
    """
    # A runtime that shut down first has already unloaded the DLL, and every
    # reference for its vmID is invalid, so there is nothing left to give back.
    # Narrow by construction: JavaReferenceClosedError is a sibling rather than a
    # subclass of BridgeClosedError, so this cannot swallow one.
    with contextlib.suppress(BridgeClosedError):
        releaser._release_java_object(vm_id, value)


class JavaRef:
    """Owns exactly one Access Bridge reference.

    An ``AccessibleContext`` is a live JVM reference, not an identifier: the JVM
    cannot collect the object until ``releaseJavaObject`` is called. Copying the
    numeric cookie does not create a second independent reference, so exactly one
    ``JavaRef`` must exist per reference returned by a native call.

    The deterministic release path is :meth:`close` or the context manager. A
    :func:`weakref.finalize` is registered purely as a safety net for references
    dropped without closing; correctness never depends on the garbage collector.
    """

    __slots__ = ("__weakref__", "_finalizer", "_value", "_vm_id")

    def __init__(self, releaser: ReferenceReleaser, vm_id: int, value: int) -> None:
        self._vm_id = vm_id
        self._value = value
        # finalize() is one-shot, which is what makes close() idempotent: calling
        # it twice releases exactly once.
        self._finalizer = weakref.finalize(self, _release, releaser, vm_id, value)

    @property
    def vm_id(self) -> int:
        """The JVM this reference belongs to."""
        return self._vm_id

    @property
    def value(self) -> int:
        """The raw cookie, for passing to a native call.

        Read this on the bridge's worker thread, not on the calling thread: the
        check and the native call have to happen in the same serialized step, or
        a concurrent :meth:`close` could slip between them and the call would run
        against a cookie the JVM has already taken back.
        """
        if self.closed:
            raise JavaReferenceClosedError(
                f"Java reference {self._value:#x} (vmID {self._vm_id}) is closed"
            )
        return self._value

    @property
    def closed(self) -> bool:
        return not self._finalizer.alive

    def close(self) -> None:
        """Release the reference. Safe to call any number of times."""
        self._finalizer()

    def __enter__(self) -> JavaRef:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self.closed else "open"
        return f"JavaRef(vm_id={self._vm_id}, value={self._value:#x}, {state})"
