# flake8: noqa
"""Process-wide leases for the single Java Access Bridge runtime."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar, cast

from play_jab._native.backend import ContextInfo, TableCellInfo
from play_jab._native.bridge import BridgeRuntime, Visitor
from play_jab._native.refs import JavaRef
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

    @property
    def generation(self) -> int:
        return self._generation

    def _invoke(self, function: Callable[[], _T]) -> _T:
        self._manager._enter(self._lease_id, self._generation)
        try:
            return function()
        finally:
            self._manager._leave(self._lease_id)

    def wait_for_event(self, timeout: float) -> None:
        self._invoke(lambda: self._runtime.wait_for_event(timeout))

    def is_java_window(self, hwnd: int) -> bool:
        return self._invoke(lambda: self._runtime.is_java_window(hwnd))

    def is_vm_exited_window(self, hwnd: int) -> bool:
        return self._invoke(lambda: self._runtime.is_vm_exited_window(hwnd))

    def context_from_hwnd(self, hwnd: int) -> JavaRef:
        return self._invoke(lambda: self._runtime.context_from_hwnd(hwnd))

    def context_info(self, ref: JavaRef) -> ContextInfo:
        return self._invoke(lambda: self._runtime.context_info(ref))

    def child(self, ref: JavaRef, index: int) -> JavaRef | None:
        return self._invoke(lambda: self._runtime.child(ref, index))

    def accessible_actions(self, ref: JavaRef) -> tuple[str, ...]:
        return self._invoke(lambda: self._runtime.accessible_actions(ref))

    def do_accessible_actions(self, ref: JavaRef, actions: tuple[str, ...]) -> None:
        self._invoke(lambda: self._runtime.do_accessible_actions(ref, actions))

    def accessible_text(self, ref: JavaRef) -> str | None:
        return self._invoke(lambda: self._runtime.accessible_text(ref))

    def accessible_value_range(
        self, ref: JavaRef
    ) -> tuple[str | None, str | None, str | None]:
        return self._invoke(lambda: self._runtime.accessible_value_range(ref))

    def set_text_contents(self, ref: JavaRef, text: str) -> None:
        self._invoke(lambda: self._runtime.set_text_contents(ref, text))

    def request_focus(self, ref: JavaRef) -> None:
        self._invoke(lambda: self._runtime.request_focus(ref))

    def clear_selection(self, ref: JavaRef) -> None:
        self._invoke(lambda: self._runtime.clear_selection(ref))

    def set_child_selected(self, ref: JavaRef, index: int, selected: bool) -> None:
        self._invoke(lambda: self._runtime.set_child_selected(ref, index, selected))

    def is_child_selected(self, ref: JavaRef, index: int) -> bool:
        return self._invoke(lambda: self._runtime.is_child_selected(ref, index))

    def table_info(self, ref: JavaRef) -> tuple[int, int, tuple[JavaRef | None, ...]]:
        return self._invoke(lambda: self._runtime.table_info(ref))

    def table_cell(
        self, table_ref: JavaRef, row: int, column: int
    ) -> tuple[JavaRef, TableCellInfo]:
        return self._invoke(lambda: self._runtime.table_cell(table_ref, row, column))

    def table_header(
        self, ref: JavaRef, *, column: bool
    ) -> tuple[int, int, tuple[JavaRef | None, ...]] | None:
        return self._invoke(lambda: self._runtime.table_header(ref, column=column))

    def table_selections(self, ref: JavaRef, *, column: bool) -> tuple[int, ...]:
        return self._invoke(lambda: self._runtime.table_selections(ref, column=column))

    def set_table_row_selected(self, ref: JavaRef, row: int, selected: bool) -> None:
        self._invoke(lambda: self._runtime.set_table_row_selected(ref, row, selected))

    def visible_children(self, ref: JavaRef) -> tuple[JavaRef, ...] | None:
        return self._invoke(lambda: self._runtime.visible_children(ref))

    def traverse(self, hwnd: int, start_path: Sequence[int], visit: Visitor) -> None:
        self._invoke(lambda: self._runtime.traverse(hwnd, start_path, visit))

    def read_path(
        self, hwnd: int, path: Sequence[int], *, read_text: bool = False
    ) -> tuple[tuple[ContextInfo, ...], str | None]:
        return self._invoke(
            lambda: self._runtime.read_path(hwnd, path, read_text=read_text)
        )

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
