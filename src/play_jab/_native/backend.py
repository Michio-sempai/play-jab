# flake8: noqa
"""The seam between play-jab and the native Access Bridge.

:class:`NativeBackend` is the entire native surface this slice depends on: the
eight Access Bridge calls of the minimal vertical slice, plus the two operations
that are native concerns but have no single export behind them (draining the
thread message queue, and probing readiness).

Backends stay thin. They mirror the C API's own failure signalling - ``FALSE``,
a null cookie, a null HWND - as ``None``/``0``/``False`` and do not raise
``play_jab`` errors; turning those into diagnosable exceptions is
:class:`~play_jab._native.bridge.BridgeRuntime`'s job.

Backends are also not thread-safe by themselves: every method must be called
from the single thread that created the backend.
"""

from __future__ import annotations

import ctypes
import queue
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from play_jab._native.dll import load_access_bridge, verify_exports
from play_jab._native.functions import (
    JAVA_SHUTDOWN_CALLBACK,
    PROPERTY_CALLBACK,
    PROPERTY_CHANGE_CALLBACK,
    PROPERTY_SIMPLE_CALLBACK,
    REQUIRED_EXPORTS,
    configure_functions,
)
from play_jab._native.types import (
    MAX_ACTIONS_TO_DO,
    MAX_STRING_SIZE,
    MAX_TABLE_SELECTIONS,
    AccessibleActions,
    AccessibleActionsToDo,
    AccessibleContext,
    AccessibleContextInfo,
    AccessibleTableCellInfo,
    AccessibleTableInfo,
    AccessibleTextInfo,
    VisibleChildrenInfo,
    jint,
)

if sys.platform == "win32":
    from ctypes import wintypes as win_types

__all__ = [
    "ContextInfo",
    "DllBackend",
    "NativeBackend",
    "TableCellInfo",
    "TableInfo",
    "dll_backend_factory",
]

_PM_REMOVE = 0x0001
# Upper bound on messages dispatched per pump call, so that a message storm
# cannot starve the runtime's command queue.
_MAX_MESSAGES_PER_PUMP = 64


def _free_library(dll: ctypes.CDLL) -> None:
    """Release one loader reference without letting cleanup errors escape."""
    with suppress(BaseException):  # cleanup must preserve the original error
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.FreeLibrary.argtypes = [win_types.HMODULE]
        kernel32.FreeLibrary.restype = win_types.BOOL
        kernel32.FreeLibrary(dll._handle)


@dataclass(frozen=True, slots=True)
class ContextInfo:
    """Decoded ``AccessibleContextInfo`` with no live Java reference attached.

    ``role``/``states`` are localized by the JVM; ``role_en_us``/``states_en_us``
    are the stable ``en_US`` spellings and are the only ones logic may use. Both
    are carried verbatim - mapping them onto a validated role/state registry is
    a later layer's responsibility.
    """

    name: str
    description: str
    role: str
    role_en_us: str
    states: str
    states_en_us: str
    index_in_parent: int
    children_count: int
    x: int
    y: int
    width: int
    height: int
    accessible_component: bool
    accessible_action: bool
    accessible_selection: bool
    accessible_text: bool
    accessible_interfaces: int


@dataclass(frozen=True, slots=True)
class TableInfo:
    """Copied table metadata; non-zero handles are newly owned cookies."""

    caption: int
    summary: int
    row_count: int
    column_count: int
    context: int
    table: int


@dataclass(frozen=True, slots=True)
class TableCellInfo:
    """Copied table cell metadata; ``context`` is a newly owned cookie."""

    context: int
    index: int
    row: int
    column: int
    row_extent: int
    column_extent: int
    selected: bool


class NativeBackend(Protocol):
    """The native operations the bridge runtime needs.

    Passing a context that was never handed out, or one already released, is a
    programming error whose behaviour in the real bridge is undefined - it may
    return garbage or fault the process. Nothing here promises to detect it; the
    fake backend deliberately does, as a test-only tripwire.
    """

    def windows_run(self) -> None:
        """Start the bridge (``Windows_run``). Called once, on the pump thread."""

    def pump_messages(self) -> None:
        """Dispatch pending window messages for the calling thread."""

    def is_java_window(self, hwnd: int) -> bool:
        """``isJavaWindow``.

        Also serves as the runtime's readiness call, so it must reach the DLL
        rather than answer from a cache.
        """

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        """``getAccessibleContextFromHWND``: ``(vm_id, context)`` or ``None``.

        The returned context is a new owned reference.
        """

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        """``getAccessibleContextInfo``; ``None`` when the call returns FALSE.

        The result is copied data and owns no reference.
        """

    def get_accessible_child_from_context(
        self, vm_id: int, context: int, index: int
    ) -> int:
        """``getAccessibleChildFromContext``; ``0`` when there is no such child.

        A non-zero result is a new owned reference.
        """

    def get_accessible_parent_from_context(self, vm_id: int, context: int) -> int:
        """``getAccessibleParentFromContext``; ``0`` at the root.

        A non-zero result is a new owned reference.
        """

    def release_java_object(self, vm_id: int, value: int) -> None:
        """``releaseJavaObject``: give exactly one owned reference back to the JVM."""

    def get_hwnd_from_accessible_context(self, vm_id: int, context: int) -> int:
        """``getHWNDFromAccessibleContext``; ``0`` when the context has no window."""

    def get_accessible_actions(
        self, vm_id: int, context: int
    ) -> tuple[str, ...] | None:
        """Return supported action names, or ``None`` when the call fails."""

    def do_accessible_actions(
        self, vm_id: int, context: int, actions: tuple[str, ...]
    ) -> tuple[bool, int]:
        """Perform actions and return ``(success, failure_index)``."""

    def get_accessible_text(self, vm_id: int, context: int) -> str | None: ...

    def get_current_accessible_value(self, vm_id: int, context: int) -> str | None: ...

    def get_minimum_accessible_value(self, vm_id: int, context: int) -> str | None: ...

    def get_maximum_accessible_value(self, vm_id: int, context: int) -> str | None: ...

    def set_text_contents(self, vm_id: int, context: int, text: str) -> bool: ...

    def request_focus(self, vm_id: int, context: int) -> bool: ...

    def get_accessible_selection_count(self, vm_id: int, context: int) -> int: ...

    def get_accessible_selection(self, vm_id: int, context: int, index: int) -> int: ...

    def is_accessible_child_selected(
        self, vm_id: int, context: int, index: int
    ) -> bool: ...

    def add_accessible_selection(
        self, vm_id: int, context: int, index: int
    ) -> None: ...

    def remove_accessible_selection(
        self, vm_id: int, context: int, index: int
    ) -> None: ...

    def clear_accessible_selection(self, vm_id: int, context: int) -> None: ...

    def get_accessible_table_info(
        self, vm_id: int, context: int
    ) -> TableInfo | None: ...

    def get_accessible_table_cell_info(
        self, vm_id: int, table: int, row: int, column: int
    ) -> TableCellInfo | None: ...

    def get_accessible_table_header(
        self, vm_id: int, context: int, *, column: bool
    ) -> TableInfo | None: ...

    def get_accessible_table_selections(
        self, vm_id: int, table: int, *, column: bool
    ) -> tuple[int, tuple[int, ...] | None]: ...

    def set_accessible_table_row_selected(
        self, vm_id: int, context: int, row: int, selected: bool
    ) -> None: ...

    def get_visible_children(
        self, vm_id: int, context: int
    ) -> tuple[int, ...] | None: ...

    def setup_event_callbacks(
        self, wake: Callable[[], None], vm_exit: Callable[[int], None]
    ) -> None: ...

    def shutdown(self) -> None:
        """Release the bridge. Must be idempotent and must not raise."""


class DllBackend:
    """:class:`NativeBackend` backed by the real WindowsAccessBridge DLL."""

    def __init__(self, dll: ctypes.CDLL) -> None:
        self._dll = dll
        self._closed = False
        self._callbacks: list[object] = []
        self._callback_events: queue.SimpleQueue[tuple[int, int, int]] = (
            queue.SimpleQueue()
        )
        self._callback_vm_exit: Callable[[int], None] | None = None
        if sys.platform != "win32":  # pragma: no cover - unit-test import shim
            self._user32 = None
            self._message = None
            return
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._message = win_types.MSG()
        self._configure_win32()

    @classmethod
    def load(cls, dll_path: str | Path | None = None) -> DllBackend:
        """Locate, load and configure the Access Bridge DLL."""
        dll = load_access_bridge(dll_path)
        try:
            verify_exports(dll, REQUIRED_EXPORTS)
            configure_functions(dll)
            return cls(dll)
        except BaseException:
            _free_library(dll)
            raise

    def _configure_win32(self) -> None:
        message_pointer = ctypes.POINTER(win_types.MSG)
        self._user32.PeekMessageW.argtypes = [
            message_pointer,
            win_types.HWND,
            win_types.UINT,
            win_types.UINT,
            win_types.UINT,
        ]
        self._user32.PeekMessageW.restype = win_types.BOOL
        self._user32.TranslateMessage.argtypes = [message_pointer]
        self._user32.TranslateMessage.restype = win_types.BOOL
        self._user32.DispatchMessageW.argtypes = [message_pointer]
        self._user32.DispatchMessageW.restype = ctypes.c_ssize_t

    def windows_run(self) -> None:
        self._dll.Windows_run()

    def pump_messages(self) -> None:
        if sys.platform != "win32":  # pragma: no cover - unit-test import shim
            return
        pointer = ctypes.byref(self._message)
        for _ in range(_MAX_MESSAGES_PER_PUMP):
            if not self._user32.PeekMessageW(pointer, None, 0, 0, _PM_REMOVE):
                break
            self._user32.TranslateMessage(pointer)
            self._user32.DispatchMessageW(pointer)
        self._drain_callback_events()

    def _drain_callback_events(self) -> None:
        while True:
            try:
                vm_id, event, source = self._callback_events.get_nowait()
            except queue.Empty:
                return
            if event:
                self.release_java_object(vm_id, event)
            if source:
                self.release_java_object(vm_id, source)
            if not event and not source and self._callback_vm_exit is not None:
                self._callback_vm_exit(vm_id)

    def is_java_window(self, hwnd: int) -> bool:
        return bool(self._dll.isJavaWindow(hwnd))

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        vm_id = ctypes.c_long()
        context = AccessibleContext()
        ok = self._dll.getAccessibleContextFromHWND(
            hwnd, ctypes.byref(vm_id), ctypes.byref(context)
        )
        if not ok or not context.value:
            return None
        return int(vm_id.value), int(context.value)

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        raw = AccessibleContextInfo()
        ok = self._dll.getAccessibleContextInfo(vm_id, context, ctypes.byref(raw))
        if not ok:
            return None
        # ctypes already decodes `c_wchar * N` fields to str and jint fields to
        # int. The BOOLs arrive as C ints and are narrowed here - except
        # accessibleInterfaces, which the header declares BOOL but uses as a
        # bitfield of interface flags, so it stays an int.
        return ContextInfo(
            name=raw.name,
            description=raw.description,
            role=raw.role,
            role_en_us=raw.role_en_US,
            states=raw.states,
            states_en_us=raw.states_en_US,
            index_in_parent=raw.indexInParent,
            children_count=raw.childrenCount,
            x=raw.x,
            y=raw.y,
            width=raw.width,
            height=raw.height,
            accessible_component=bool(raw.accessibleComponent),
            accessible_action=bool(raw.accessibleAction),
            accessible_selection=bool(raw.accessibleSelection),
            accessible_text=bool(raw.accessibleText),
            accessible_interfaces=int(raw.accessibleInterfaces),
        )

    def get_accessible_child_from_context(
        self, vm_id: int, context: int, index: int
    ) -> int:
        return int(self._dll.getAccessibleChildFromContext(vm_id, context, index))

    def get_accessible_parent_from_context(self, vm_id: int, context: int) -> int:
        return int(self._dll.getAccessibleParentFromContext(vm_id, context))

    def release_java_object(self, vm_id: int, value: int) -> None:
        self._dll.releaseJavaObject(vm_id, value)

    def get_hwnd_from_accessible_context(self, vm_id: int, context: int) -> int:
        hwnd = self._dll.getHWNDFromAccessibleContext(vm_id, context)
        return int(hwnd) if hwnd else 0

    def get_accessible_actions(
        self, vm_id: int, context: int
    ) -> tuple[str, ...] | None:
        raw = AccessibleActions()
        if not self._dll.getAccessibleActions(vm_id, context, ctypes.byref(raw)):
            return None
        count = int(raw.actionsCount)
        if count < 0 or count > len(raw.actionInfo):
            return None
        return tuple(raw.actionInfo[index].name for index in range(count))

    def do_accessible_actions(
        self, vm_id: int, context: int, actions: tuple[str, ...]
    ) -> tuple[bool, int]:
        if not actions or len(actions) > MAX_ACTIONS_TO_DO:
            return False, -1
        raw = AccessibleActionsToDo()
        raw.actionsCount = len(actions)
        for index, action in enumerate(actions):
            raw.actions[index].name = action
        failure = jint(-1)
        ok = self._dll.doAccessibleActions(
            vm_id,
            context,
            ctypes.byref(raw),
            ctypes.byref(failure),
        )
        return bool(ok), int(failure.value)

    def get_accessible_text(self, vm_id: int, context: int) -> str | None:
        info = AccessibleTextInfo()
        if not self._dll.getAccessibleTextInfo(
            vm_id, context, ctypes.byref(info), 0, 0
        ):
            return None
        count = int(info.charCount)
        if count <= 0:
            return ""
        # The native range call is bounded by a signed short and includes a
        # terminator. Reading in chunks also avoids the fixed MAX_STRING_SIZE
        # limit used by older bridge implementations.
        chunks: list[str] = []
        start = 0
        chunk_size = min(MAX_STRING_SIZE - 1, 32_766)
        while start < count:
            end = min(count - 1, start + chunk_size - 1)
            buffer = ctypes.create_unicode_buffer(end - start + 2)
            if not self._dll.getAccessibleTextRange(
                vm_id, context, start, end, buffer, len(buffer)
            ):
                return None
            chunks.append(buffer.value)
            start = end + 1
        return "".join(chunks)

    def get_current_accessible_value(self, vm_id: int, context: int) -> str | None:
        buffer = ctypes.create_unicode_buffer(MAX_STRING_SIZE)
        if not self._dll.getCurrentAccessibleValueFromContext(
            vm_id, context, buffer, len(buffer)
        ):
            return None
        return buffer.value

    def _get_accessible_value(
        self, function_name: str, vm_id: int, context: int
    ) -> str | None:
        buffer = ctypes.create_unicode_buffer(MAX_STRING_SIZE)
        function = getattr(self._dll, function_name)
        if not function(vm_id, context, buffer, MAX_STRING_SIZE):
            return None
        return buffer.value

    def get_minimum_accessible_value(self, vm_id: int, context: int) -> str | None:
        return self._get_accessible_value(
            "getMinimumAccessibleValueFromContext", vm_id, context
        )

    def get_maximum_accessible_value(self, vm_id: int, context: int) -> str | None:
        return self._get_accessible_value(
            "getMaximumAccessibleValueFromContext", vm_id, context
        )

    def set_text_contents(self, vm_id: int, context: int, text: str) -> bool:
        return bool(self._dll.setTextContents(vm_id, context, text))

    def request_focus(self, vm_id: int, context: int) -> bool:
        return bool(self._dll.requestFocus(vm_id, context))

    def get_accessible_selection_count(self, vm_id: int, context: int) -> int:
        return int(self._dll.getAccessibleSelectionCountFromContext(vm_id, context))

    def get_accessible_selection(self, vm_id: int, context: int, index: int) -> int:
        return int(self._dll.getAccessibleSelectionFromContext(vm_id, context, index))

    def is_accessible_child_selected(
        self, vm_id: int, context: int, index: int
    ) -> bool:
        return bool(
            self._dll.isAccessibleChildSelectedFromContext(vm_id, context, index)
        )

    def add_accessible_selection(self, vm_id: int, context: int, index: int) -> None:
        self._dll.addAccessibleSelectionFromContext(vm_id, context, index)

    def remove_accessible_selection(self, vm_id: int, context: int, index: int) -> None:
        self._dll.removeAccessibleSelectionFromContext(vm_id, context, index)

    def clear_accessible_selection(self, vm_id: int, context: int) -> None:
        self._dll.clearAccessibleSelectionFromContext(vm_id, context)

    @staticmethod
    def _table_info(raw: AccessibleTableInfo) -> TableInfo:
        return TableInfo(
            caption=int(raw.caption),
            summary=int(raw.summary),
            row_count=int(raw.rowCount),
            column_count=int(raw.columnCount),
            context=int(raw.accessibleContext),
            table=int(raw.accessibleTable),
        )

    def get_accessible_table_info(self, vm_id: int, context: int) -> TableInfo | None:
        raw = AccessibleTableInfo()
        if not self._dll.getAccessibleTableInfo(vm_id, context, ctypes.byref(raw)):
            self._release_table_handles(vm_id, raw)
            return None
        return self._table_info(raw)

    def _release_table_handles(self, vm_id: int, raw: AccessibleTableInfo) -> None:
        for value in (
            raw.caption,
            raw.summary,
            raw.accessibleContext,
            raw.accessibleTable,
        ):
            if value:
                self.release_java_object(vm_id, int(value))

    def get_accessible_table_cell_info(
        self, vm_id: int, table: int, row: int, column: int
    ) -> TableCellInfo | None:
        raw = AccessibleTableCellInfo()
        if not self._dll.getAccessibleTableCellInfo(
            vm_id, table, row, column, ctypes.byref(raw)
        ):
            if raw.accessibleContext:
                self.release_java_object(vm_id, int(raw.accessibleContext))
            return None
        return TableCellInfo(
            context=int(raw.accessibleContext),
            index=int(raw.index),
            row=int(raw.row),
            column=int(raw.column),
            row_extent=int(raw.rowExtent),
            column_extent=int(raw.columnExtent),
            selected=bool(raw.isSelected),
        )

    def get_accessible_table_header(
        self, vm_id: int, context: int, *, column: bool
    ) -> TableInfo | None:
        raw = AccessibleTableInfo()
        function = (
            self._dll.getAccessibleTableColumnHeader
            if column
            else self._dll.getAccessibleTableRowHeader
        )
        if not function(vm_id, context, ctypes.byref(raw)):
            self._release_table_handles(vm_id, raw)
            return None
        return self._table_info(raw)

    def get_accessible_table_selections(
        self, vm_id: int, table: int, *, column: bool
    ) -> tuple[int, tuple[int, ...] | None]:
        count_function = (
            self._dll.getAccessibleTableColumnSelectionCount
            if column
            else self._dll.getAccessibleTableRowSelectionCount
        )
        values_function = (
            self._dll.getAccessibleTableColumnSelections
            if column
            else self._dll.getAccessibleTableRowSelections
        )
        count = int(count_function(vm_id, table))
        if count < 0 or count > MAX_TABLE_SELECTIONS:
            return count, None
        if count == 0:
            return 0, ()
        values = (jint * count)()
        if not values_function(vm_id, table, count, values):
            return count, None
        return count, tuple(int(value) for value in values)

    def set_accessible_table_row_selected(
        self, vm_id: int, context: int, row: int, selected: bool
    ) -> None:
        if selected:
            self.add_accessible_selection(vm_id, context, row)
        else:
            self.remove_accessible_selection(vm_id, context, row)

    def get_visible_children(self, vm_id: int, context: int) -> tuple[int, ...] | None:
        count = int(self._dll.getVisibleChildrenCount(vm_id, context))
        if count < 0:
            return None
        children: list[int] = []
        for start in range(0, count, len(VisibleChildrenInfo().children)):
            raw = VisibleChildrenInfo()
            if not self._dll.getVisibleChildren(
                vm_id, context, start, ctypes.byref(raw)
            ):
                for child in children:
                    self.release_java_object(vm_id, child)
                return None
            returned = int(raw.returnedChildrenCount)
            if returned < 0 or returned > len(raw.children):
                for child in children:
                    self.release_java_object(vm_id, child)
                for child in raw.children:
                    if child:
                        self.release_java_object(vm_id, int(child))
                return None
            children.extend(int(raw.children[index]) for index in range(returned))
        return tuple(children)

    def setup_event_callbacks(
        self, wake: Callable[[], None], vm_exit: Callable[[int], None]
    ) -> None:
        self._callback_vm_exit = vm_exit

        def queue_event(vm_id: int, event: int, source: int) -> None:
            self._callback_events.put((int(vm_id), int(event), int(source)))
            wake()

        @JAVA_SHUTDOWN_CALLBACK  # type: ignore[untyped-decorator]
        def java_shutdown(vm_id: int) -> None:
            queue_event(int(vm_id), 0, 0)

        @PROPERTY_CHANGE_CALLBACK  # type: ignore[untyped-decorator]
        def property_change(
            vm_id: int,
            event: int,
            source: int,
            _property: int,
            _old: int,
            _new: int,
        ) -> None:
            queue_event(int(vm_id), int(event), int(source))

        @PROPERTY_CALLBACK  # type: ignore[untyped-decorator]
        def property_value(
            vm_id: int,
            event: int,
            source: int,
            _old: int,
            _new: int,
        ) -> None:
            queue_event(int(vm_id), int(event), int(source))

        @PROPERTY_SIMPLE_CALLBACK  # type: ignore[untyped-decorator]
        def property_simple(vm_id: int, event: int, source: int) -> None:
            queue_event(int(vm_id), int(event), int(source))

        self._callbacks = [
            java_shutdown,
            property_change,
            property_value,
            property_simple,
        ]
        registrations = (
            ("setJavaShutdownFP", java_shutdown),
            ("setPropertyChangeFP", property_change),
            *(
                (name, property_value)
                for name in (
                    "setPropertyStateChangeFP",
                    "setPropertyValueChangeFP",
                    "setPropertyTableModelChangeFP",
                )
            ),
            *(
                (name, property_simple)
                for name in (
                    "setPropertyTextChangeFP",
                    "setPropertySelectionChangeFP",
                    "setPropertyVisibleDataChangeFP",
                )
            ),
        )
        registered: list[str] = []
        try:
            for name, callback in registrations:
                getattr(self._dll, name)(callback)
                registered.append(name)
        except BaseException:
            for name in reversed(registered):
                getattr(self._dll, name)(None)
            self._callbacks.clear()
            self._callback_vm_exit = None
            raise

    def _clear_event_callbacks(self) -> None:
        for name in (
            "setJavaShutdownFP",
            "setPropertyChangeFP",
            "setPropertyStateChangeFP",
            "setPropertyValueChangeFP",
            "setPropertyTableModelChangeFP",
            "setPropertyTextChangeFP",
            "setPropertySelectionChangeFP",
            "setPropertyVisibleDataChangeFP",
        ):
            with suppress(BaseException):
                getattr(self._dll, name)(None)
        self._callbacks.clear()
        self._callback_vm_exit = None
        # Events already queued before unregister still carry two owned JAB
        # cookies. Release them before unloading the DLL, without delivering
        # lifecycle notifications during shutdown.
        while True:
            try:
                vm_id, event, source = self._callback_events.get_nowait()
            except queue.Empty:
                break
            if event:
                self.release_java_object(vm_id, event)
            if source:
                self.release_java_object(vm_id, source)

    def shutdown(self) -> None:
        """Unload the Access Bridge DLL.

        The DLL exports no ``shutdownAccessBridge``; that name belongs to a
        client-side wrapper in AccessBridgeCalls.c whose job is to release the
        library. Unloading is done from the same thread that called
        ``Windows_run``, so the bridge's message window is torn down by its
        owning thread. Failures are swallowed: shutdown runs on the close path
        and must not mask the caller's own errors.
        """
        if self._closed:
            return
        self._closed = True
        self._clear_event_callbacks()
        _free_library(self._dll)


def dll_backend_factory(
    dll_path: str | Path | None = None,
) -> Callable[[], NativeBackend]:
    """Build a factory that loads the real DLL on whichever thread calls it.

    The bridge runtime calls the factory on its worker thread, because the
    Access Bridge's message window belongs to the thread that loads the library
    and calls ``Windows_run``.
    """

    def factory() -> NativeBackend:
        return DllBackend.load(dll_path)

    return factory
