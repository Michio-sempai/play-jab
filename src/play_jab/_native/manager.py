# flake8: noqa
"""Process-wide leases for the single Java Access Bridge runtime."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

from play_jab._native.bridge import BridgeRuntime
from play_jab.exceptions import BridgeClosedError, BridgeInitializationError

__all__ = ["RuntimeManager", "RuntimeSession"]

_T = TypeVar("_T")


def _canonical(path: str | Path | None) -> str | None:
    if path is not None:
        return os.path.normcase(str(Path(path).expanduser().resolve()))
    file_name = (
        "WindowsAccessBridge-64.dll"
        if sys.maxsize > (1 << 32) - 1
        else "WindowsAccessBridge-32.dll"
    )
    roots = (
        (
            Path(java_home) / "bin"
            if (java_home := os.environ.get("JAVA_HOME"))
            else None
        ),
        (
            Path(system_root) / "System32"
            if (system_root := os.environ.get("SYSTEMROOT"))
            else None
        ),
    )
    for root in roots:
        if root is not None and (candidate := root / file_name).is_file():
            return os.path.normcase(str(candidate.resolve()))
    return None


class RuntimeSession:
    """One client-local lease delegating to the process runtime."""

    def __init__(
        self,
        manager: RuntimeManager,
        runtime: BridgeRuntime,
        lease_id: int,
        generation: int,
    ) -> None:
        self._manager = manager
        self._runtime = runtime
        self._lease_id = lease_id
        self._generation = generation
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def live_ref_count(self) -> int:
        return self._invoke(lambda: self._runtime.live_ref_count)

    def _invoke(self, function: Callable[[], _T]) -> _T:
        self._manager._enter(self._lease_id, self._generation)
        try:
            return function()
        finally:
            self._manager._leave(self._lease_id)

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._runtime, name)
        if not callable(attribute):
            return self._invoke(lambda: attribute)

        def guarded(*args: object, **kwargs: object) -> object:
            return self._invoke(lambda: attribute(*args, **kwargs))

        return guarded

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._manager.release(self._lease_id, self._generation)


class RuntimeManager:
    """Coordinate one runtime, its canonical DLL and process-wide generations."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._state = "stopped"
        self._runtime: BridgeRuntime | None = None
        self._canonical_path: str | None = None
        self._generation = 0
        self._next_lease = 1
        self._leases: dict[int, int] = {}
        self._active_calls: dict[int, int] = {}

    def acquire(
        self,
        dll_path: str | Path | None,
        timeout_ms: int,
        factory: Callable[[str | Path | None, int], BridgeRuntime],
    ) -> RuntimeSession:
        canonical = _canonical(dll_path)
        with self._condition:
            while self._state in {"starting", "stopping"}:
                self._condition.wait()
            if self._state == "running":
                if canonical != self._canonical_path:
                    raise BridgeInitializationError(
                        "active Java Access Bridge runtime uses a different DLL path"
                    )
                return self._new_session(cast("BridgeRuntime", self._runtime))
            self._state = "starting"

        try:
            runtime = factory(dll_path, timeout_ms)
            runtime.start()
        except BaseException:
            with self._condition:
                self._state = "stopped"
                self._condition.notify_all()
            raise

        with self._condition:
            self._runtime = runtime
            self._canonical_path = canonical
            self._generation += 1
            self._state = "running"
            session = self._new_session(runtime)
            self._condition.notify_all()
            return session

    def _new_session(self, runtime: BridgeRuntime) -> RuntimeSession:
        lease_id = self._next_lease
        self._next_lease += 1
        self._leases[lease_id] = self._generation
        self._active_calls[lease_id] = 0
        return RuntimeSession(self, runtime, lease_id, self._generation)

    def _enter(self, lease_id: int, generation: int) -> None:
        with self._condition:
            if self._leases.get(lease_id) != generation or self._state != "running":
                raise BridgeClosedError(
                    f"runtime session from generation {generation} is closed"
                )
            self._active_calls[lease_id] += 1

    def _leave(self, lease_id: int) -> None:
        with self._condition:
            active = self._active_calls.get(lease_id)
            if active is None:
                return
            self._active_calls[lease_id] = active - 1
            self._condition.notify_all()

    def release(self, lease_id: int, generation: int) -> None:
        with self._condition:
            if self._leases.get(lease_id) != generation:
                return
            del self._leases[lease_id]
            while self._active_calls.get(lease_id, 0):
                self._condition.wait()
            self._active_calls.pop(lease_id, None)
            if self._leases:
                return
            runtime = self._runtime
            self._state = "stopping"

        try:
            if runtime is not None:
                runtime.close()
        finally:
            with self._condition:
                self._runtime = None
                self._canonical_path = None
                self._state = "stopped"
                self._condition.notify_all()
