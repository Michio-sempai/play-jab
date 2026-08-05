# flake8: noqa
"""Synchronous Java Access Bridge automation API."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from types import TracebackType
from typing import Literal, Protocol, TypeAlias

from play_jab._native.backend import ContextInfo, dll_backend_factory
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.refs import JavaRef
from play_jab.exceptions import (
    BridgeClosedError,
    JavaProcessExitedError,
    JavaWindowAmbiguousError,
    JavaWindowNotFoundError,
    JavaWindowNotAccessibleError,
    LocatorError,
    LocatorTimeoutError,
    NativeCallError,
    StrictModeViolation,
    UnsupportedActionError,
)
from play_jab.registry import AccessibilityRegistry

if sys.platform == "win32":
    from ctypes import wintypes

__all__ = [
    "AccessibilityNode",
    "ElementSnapshot",
    "JavaApplication",
    "JavaWindow",
    "Locator",
    "PlayJab",
    "WindowExpectation",
    "contains",
]

_POLL_INTERVAL = 0.1
_MAX_TREE_DEPTH = 100
_MAX_TREE_NODES = 10_000
_DIAGNOSTIC_DEPTH = 3
_DIAGNOSTIC_NODES = 50
_PASSWORD_ROLE = "password text"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
_INPUT_MOUSE = 0
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_SYNTHETIC_INPUT_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class _Contains:
    text: str


def contains(text: str) -> _Contains:
    """Build an explicit substring matcher for locator text fields."""
    if not isinstance(text, str):
        raise TypeError("contains() expects a string")
    return _Contains(text)


TextMatcher: TypeAlias = str | Pattern[str] | _Contains


@dataclass(frozen=True, slots=True)
class ElementSnapshot:
    """Immutable accessibility metadata carrying no native reference."""

    name: str
    description: str
    role: str
    states: frozenset[str]
    index_in_parent: int
    x: int
    y: int
    width: int
    height: int
    accessible_component: bool
    accessible_action: bool
    accessible_selection: bool
    accessible_text: bool
    accessible_interfaces: int

    @property
    def visible(self) -> bool:
        return "visible" in self.states

    @property
    def enabled(self) -> bool:
        return "enabled" in self.states


@dataclass(frozen=True, slots=True)
class AccessibilityNode:
    """One immutable node in a diagnostic accessibility tree."""

    snapshot: ElementSnapshot
    children: tuple[AccessibilityNode, ...] = ()

    @property
    def name(self) -> str:
        return self.snapshot.name

    @property
    def description(self) -> str:
        return self.snapshot.description

    @property
    def role(self) -> str:
        return self.snapshot.role

    @property
    def states(self) -> frozenset[str]:
        return self.snapshot.states


class WindowBackend(Protocol):
    def enum_windows(self) -> list[int]: ...

    def get_window_title(self, hwnd: int) -> str: ...

    def get_window_pid(self, hwnd: int) -> int: ...

    def set_foreground_window(self, hwnd: int) -> None: ...

    def get_cursor_position(self) -> tuple[int, int]: ...

    def set_cursor_position(self, x: int, y: int) -> None: ...

    def set_thread_dpi_awareness_context(self, context: int) -> int: ...

    def send_left_click(self) -> None: ...


class ProcessHandle(Protocol):
    pid: int


Command: TypeAlias = str | os.PathLike[str] | Sequence[str | os.PathLike[str]]


class ProcessBackend(Protocol):
    def launch(
        self,
        command: Command,
        *,
        cwd: str | os.PathLike[str] | None,
        env: Mapping[str, str] | None,
    ) -> ProcessHandle: ...

    def is_alive(self, pid: int) -> bool: ...


class _Win32WindowBackend:
    """Small Win32 seam kept separate from portable locator logic."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("window discovery is available only on Windows")
        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.EnumWindows.restype = wintypes.BOOL
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self._user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self._configure_input()

    def _configure_input(self) -> None:
        ulong_ptr = (
            ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
        )

        class MouseInput(ctypes.Structure):
            _fields_ = (
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            )

        class InputUnion(ctypes.Union):
            _fields_ = (("mi", MouseInput),)

        class Input(ctypes.Structure):
            _anonymous_ = ("value",)
            _fields_ = (("type", wintypes.DWORD), ("value", InputUnion))

        self._mouse_input = MouseInput
        self._input = Input
        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(Input),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT

    def enum_windows(self) -> list[int]:
        windows: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(
            self._wintypes.BOOL,
            self._wintypes.HWND,
            self._wintypes.LPARAM,
        )

        @callback_type  # type: ignore[untyped-decorator]
        def callback(hwnd: int, _parameter: int) -> bool:
            windows.append(int(hwnd))
            return True

        if not self._user32.EnumWindows(callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return windows

    def get_window_title(self, hwnd: int) -> str:
        length = int(self._user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def get_window_pid(self, hwnd: int) -> int:
        pid = self._wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def set_foreground_window(self, hwnd: int) -> None:
        if not self._user32.SetForegroundWindow(hwnd):
            raise ctypes.WinError(ctypes.get_last_error())

    def get_cursor_position(self) -> tuple[int, int]:
        point = self._wintypes.POINT()
        if not self._user32.GetCursorPos(ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(point.x), int(point.y)

    def set_cursor_position(self, x: int, y: int) -> None:
        if not self._user32.SetCursorPos(x, y):
            raise ctypes.WinError(ctypes.get_last_error())

    def set_thread_dpi_awareness_context(self, context: int) -> int:
        previous = self._user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(context))
        if not previous:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(previous)

    def send_left_click(self) -> None:
        inputs = (self._input * 2)()
        inputs[0].type = _INPUT_MOUSE
        inputs[0].mi = self._mouse_input(dwFlags=_MOUSEEVENTF_LEFTDOWN)
        inputs[1].type = _INPUT_MOUSE
        inputs[1].mi = self._mouse_input(dwFlags=_MOUSEEVENTF_LEFTUP)
        sent = self._user32.SendInput(2, inputs, ctypes.sizeof(self._input))
        if sent != 2:
            raise ctypes.WinError(ctypes.get_last_error())


class _SubprocessBackend:
    def launch(
        self,
        command: Command,
        *,
        cwd: str | os.PathLike[str] | None,
        env: Mapping[str, str] | None,
    ) -> subprocess.Popen[bytes]:
        return subprocess.Popen(command, cwd=cwd, env=env)

    def is_alive(self, pid: int) -> bool:
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_uint32,
            ]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.GetExitCodeProcess.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            process = kernel32.OpenProcess(
                _PROCESS_QUERY_LIMITED_INFORMATION,
                False,
                pid,
            )
            if not process:
                return False
            exit_code = ctypes.c_uint32()
            try:
                return bool(
                    kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code))
                ) and (exit_code.value == _STILL_ACTIVE)
            finally:
                kernel32.CloseHandle(process)
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def _create_runtime(
    dll_path: str | Path | None,
    timeout_ms: int,
) -> BridgeRuntime:
    return BridgeRuntime(
        dll_backend_factory(dll_path),
        ready_timeout=timeout_ms / 1_000,
    )


def _create_window_backend() -> WindowBackend:
    return _Win32WindowBackend()


def _create_process_backend() -> ProcessBackend:
    return _SubprocessBackend()


def _timeout(value: int, name: str = "timeout") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer in milliseconds")
    return value


def _positive(value: int | None, name: str) -> int | None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
    ):
        raise ValueError(f"{name} must be a positive integer")
    return value


class PlayJab:
    """Own one bridge runtime and create Java application handles."""

    def __init__(
        self,
        timeout: int = 5_000,
        dll_path: str | Path | None = None,
        extra_roles: Iterable[str] = (),
        extra_states: Iterable[str] = (),
    ) -> None:
        self._timeout = _timeout(timeout)
        self._registry = AccessibilityRegistry(extra_roles, extra_states)
        self._runtime = _create_runtime(dll_path, self._timeout)
        self._windows = _create_window_backend()
        self._processes = _create_process_backend()
        self._started = False
        self._closed = False
        self._context_depth = 0

    @property
    def live_ref_count(self) -> int:
        return self._runtime.live_ref_count

    def _ensure_started(self) -> None:
        if self._closed:
            raise BridgeClosedError("PlayJab is closed")
        if not self._started:
            self._runtime.start()
            self._started = True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._runtime.close()

    def __enter__(self) -> PlayJab:
        self._ensure_started()
        self._context_depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._context_depth = max(0, self._context_depth - 1)
        if self._context_depth == 0:
            self.close()

    def launch(
        self,
        command: Command,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> JavaApplication:
        self._ensure_started()
        handle = self._processes.launch(command, cwd=cwd, env=env)
        return self._application(_positive(handle.pid, "pid"))

    def attach(
        self,
        *,
        hwnd: int | None = None,
        pid: int | None = None,
        title: str | None = None,
        timeout: int | None = None,
    ) -> JavaApplication:
        hwnd = _positive(hwnd, "hwnd")
        pid = _positive(pid, "pid")
        selected = sum(value is not None for value in (hwnd, pid, title))
        if selected != 1:
            raise ValueError("attach() requires exactly one of hwnd, pid, or title")
        if title is not None and (not isinstance(title, str) or not title):
            raise ValueError("title must be a non-empty string")
        wait = self._timeout if timeout is None else _timeout(timeout)
        self._ensure_started()
        if pid is not None:
            if not self._processes.is_alive(pid):
                raise JavaProcessExitedError(f"process {pid} is not running")
            return self._application(pid)
        window = self._wait_window(hwnd=hwnd, title=title, timeout=wait)
        return self._application(self._windows.get_window_pid(window))

    def _application(self, pid: int | None) -> JavaApplication:
        if pid is None:
            raise ValueError("pid must be a positive integer")
        return JavaApplication(self, pid)

    def _java_windows(self) -> list[int]:
        return [
            hwnd
            for hwnd in self._windows.enum_windows()
            if self._runtime.is_java_window(hwnd)
        ]

    def _wait_window(
        self,
        *,
        hwnd: int | None = None,
        title: str | None = None,
        pid: int | None = None,
        timeout: int,
    ) -> int:
        deadline = time.monotonic() + timeout / 1_000
        while True:
            if pid is not None and not self._processes.is_alive(pid):
                raise JavaProcessExitedError(f"process {pid} exited")
            matches = self._java_windows()
            if hwnd is not None:
                matches = [candidate for candidate in matches if candidate == hwnd]
            if title is not None:
                matches = [
                    candidate
                    for candidate in matches
                    if self._windows.get_window_title(candidate) == title
                ]
            if pid is not None:
                matches = [
                    candidate
                    for candidate in matches
                    if self._windows.get_window_pid(candidate) == pid
                ]
            if len(matches) > 1:
                raise JavaWindowAmbiguousError(
                    f"window query resolved to {len(matches)} Java windows"
                )
            if matches:
                return matches[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JavaWindowNotFoundError("Java window was not found")
            time.sleep(min(_POLL_INTERVAL, remaining))


class JavaApplication:
    """A process-scoped handle; closing it never terminates the process."""

    def __init__(self, api: PlayJab, pid: int) -> None:
        self._api = api
        self.pid = pid

    def window(
        self,
        *,
        hwnd: int | None = None,
        title: str | None = None,
        timeout: int | None = None,
    ) -> JavaWindow:
        hwnd = _positive(hwnd, "hwnd")
        if hwnd is not None and title is not None:
            raise ValueError("window() accepts at most one of hwnd or title")
        if title is not None and (not isinstance(title, str) or not title):
            raise ValueError("title must be a non-empty string")
        wait = self._api._timeout if timeout is None else _timeout(timeout)
        resolved = self._api._wait_window(
            hwnd=hwnd,
            title=title,
            pid=self.pid,
            timeout=wait,
        )
        return JavaWindow(self, resolved)

    def expect_window(
        self,
        *,
        title: str | None = None,
        timeout: int | None = None,
    ) -> WindowExpectation:
        """Expect exactly one new top-level window created by this process."""
        if title is not None and (not isinstance(title, str) or not title):
            raise ValueError("title must be a non-empty string")
        wait = self._api._timeout if timeout is None else _timeout(timeout)
        return WindowExpectation(self, title=title, timeout=wait)


class WindowExpectation:
    """Context manager resolving a newly-created Win32 window through JAB."""

    def __init__(
        self,
        application: JavaApplication,
        *,
        title: str | None,
        timeout: int,
    ) -> None:
        self._application = application
        self._title = title
        self._timeout = timeout
        self._before: frozenset[int] | None = None
        self._value: JavaWindow | None = None

    @property
    def value(self) -> JavaWindow:
        if self._value is None:
            raise RuntimeError("window expectation has not completed successfully")
        return self._value

    def __enter__(self) -> WindowExpectation:
        windows = self._application._api._windows
        self._before = frozenset(
            hwnd
            for hwnd in windows.enum_windows()
            if windows.get_window_pid(hwnd) == self._application.pid
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exc_type is not None:
            return False
        before = self._before
        if before is None:
            raise RuntimeError("window expectation was not entered")
        self._value = self._wait_for_new_window(before)
        return False

    def _raw_matches(self, before: frozenset[int]) -> list[int]:
        windows = self._application._api._windows
        return [
            hwnd
            for hwnd in windows.enum_windows()
            if hwnd not in before
            and windows.get_window_pid(hwnd) == self._application.pid
            and (self._title is None or windows.get_window_title(hwnd) == self._title)
        ]

    def _wait_for_new_window(self, before: frozenset[int]) -> JavaWindow:
        api = self._application._api
        deadline = time.monotonic() + self._timeout / 1_000
        inaccessible: int | None = None
        while True:
            if not api._processes.is_alive(self._application.pid):
                raise JavaProcessExitedError(
                    f"process {self._application.pid} exited while waiting for window"
                )
            matches = self._raw_matches(before)
            inaccessible = matches[0] if len(matches) == 1 else None
            if len(matches) > 1:
                raise JavaWindowAmbiguousError(
                    f"window expectation resolved to {len(matches)} new windows"
                )
            if matches:
                hwnd = matches[0]
                if api._runtime.is_java_window(hwnd):
                    try:
                        with api._runtime.context_from_hwnd(hwnd):
                            pass
                    except (JavaWindowNotFoundError, JavaWindowNotAccessibleError):
                        pass
                    else:
                        return JavaWindow(self._application, hwnd)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if inaccessible is not None:
                    raise JavaWindowNotAccessibleError(
                        f"new window {inaccessible:#x} exists but did not become "
                        "accessible through Java Access Bridge"
                    )
                title = "" if self._title is None else f" titled {self._title!r}"
                raise JavaWindowNotFoundError(
                    f"new window{title} was not found for process "
                    f"{self._application.pid}"
                )
            time.sleep(min(_POLL_INTERVAL, remaining))


@dataclass(frozen=True, slots=True)
class _Query:
    role: str | None = None
    name: TextMatcher | None = None
    description: TextMatcher | None = None
    states: frozenset[str] = frozenset()
    index_in_parent: int | None = None
    visible_only: bool = False

    def matches(self, snapshot: ElementSnapshot) -> bool:
        return (
            (self.role is None or snapshot.role == self.role)
            and _text_matches(self.name, snapshot.name)
            and _text_matches(self.description, snapshot.description)
            and self.states <= snapshot.states
            and (
                self.index_in_parent is None
                or snapshot.index_in_parent == self.index_in_parent
            )
            and (not self.visible_only or "visible" in snapshot.states)
        )


def _text_matches(matcher: TextMatcher | None, value: str) -> bool:
    if matcher is None:
        return True
    if isinstance(matcher, str):
        return matcher == value
    if isinstance(matcher, _Contains):
        return matcher.text in value
    return matcher.search(value) is not None


def _matcher(value: object, name: str) -> TextMatcher | None:
    if value is None or isinstance(value, (str, _Contains, re.Pattern)):
        return value
    raise ValueError(f"{name} must be a string, regex, or contains() matcher")


class JavaWindow:
    """A top-level Java window identified only by HWND, never by a JAB cookie."""

    def __init__(self, application: JavaApplication, hwnd: int) -> None:
        self.application = application
        self.hwnd = hwnd

    @property
    def _api(self) -> PlayJab:
        return self.application._api

    def locator(  # noqa: PLR0913, PLR0917
        self,
        role: str | None = None,
        name: TextMatcher | None = None,
        description: TextMatcher | None = None,
        states: str | Iterable[str] | None = None,
        index_in_parent: int | None = None,
        visible_only: bool = False,
    ) -> Locator:
        query = _make_query(
            self._api._registry,
            role,
            name,
            description,
            states,
            index_in_parent,
            visible_only,
        )
        return Locator(self, (_Step(query),))

    def get_by_role(self, role: str, *, name: TextMatcher | None = None) -> Locator:
        return self.locator(role=role, name=name)

    def get_by_name(self, name: TextMatcher) -> Locator:
        return self.locator(name=name)

    def accessibility_tree(
        self,
        max_depth: int = 10,
        max_nodes: int = 1_000,
    ) -> AccessibilityNode:
        _tree_limits(max_depth, max_nodes)
        for attempt in range(2):
            try:
                return self._read_tree(max_depth, max_nodes)
            except _StaleContext:
                if attempt:
                    raise LocatorError("accessibility tree became stale") from None
        raise AssertionError("unreachable")

    def _read_tree(self, max_depth: int, max_nodes: int) -> AccessibilityNode:
        remaining = [max_nodes]
        with self._api._runtime.context_from_hwnd(self.hwnd) as root:
            return self._read_node(root, 0, max_depth, remaining)

    def _read_node(
        self,
        ref: JavaRef,
        depth: int,
        max_depth: int,
        remaining: list[int],
    ) -> AccessibilityNode:
        info = _context_info(self._api._runtime, ref)
        snapshot = _snapshot(info, self._api._registry)
        remaining[0] -= 1
        children: list[AccessibilityNode] = []
        if depth < max_depth and remaining[0] > 0:
            for index in range(info.children_count):
                if remaining[0] <= 0:
                    break
                child = self._api._runtime.child(ref, index)
                if child is None:
                    raise _StaleContext
                with child:
                    children.append(
                        self._read_node(
                            child,
                            depth + 1,
                            max_depth,
                            remaining,
                        )
                    )
        return AccessibilityNode(snapshot, tuple(children))

    def dump(self, max_depth: int = 10, max_nodes: int = 1_000) -> str:
        return _format_tree(self.accessibility_tree(max_depth, max_nodes))


def _tree_limits(max_depth: int, max_nodes: int) -> None:
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
        raise ValueError("max_depth must be a non-negative integer")
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes <= 0:
        raise ValueError("max_nodes must be a positive integer")


def _make_query(  # noqa: PLR0913, PLR0917
    registry: AccessibilityRegistry,
    role: str | None,
    name: object,
    description: object,
    states: str | Iterable[str] | None,
    index_in_parent: int | None,
    visible_only: bool,
) -> _Query:
    if role is not None:
        if not isinstance(role, str):
            raise ValueError("role must be a string")
        registry.role(role)
    if index_in_parent is not None and (
        isinstance(index_in_parent, bool)
        or not isinstance(index_in_parent, int)
        or index_in_parent < 0
    ):
        raise ValueError("index_in_parent must be a non-negative integer")
    if not isinstance(visible_only, bool):
        raise ValueError("visible_only must be a bool")
    state_values = (
        () if states is None else ((states,) if isinstance(states, str) else states)
    )
    checked_states = frozenset(registry.state(state) for state in state_values)
    return _Query(
        role=role,
        name=_matcher(name, "name"),
        description=_matcher(description, "description"),
        states=checked_states,
        index_in_parent=index_in_parent,
        visible_only=visible_only,
    )


@dataclass(frozen=True, slots=True)
class _Match:
    path: tuple[int, ...]
    snapshot: ElementSnapshot


@dataclass(frozen=True, slots=True)
class _Step:
    query: _Query
    position: int | None = None


class _StaleContext(Exception):
    pass


class _StaleLocatorError(LocatorError):
    pass


class Locator:
    """A lazy query that re-resolves the accessibility tree on every operation."""

    def __init__(
        self,
        window: JavaWindow,
        chain: tuple[_Step, ...],
    ) -> None:
        self._window = window
        self._chain = chain

    def locator(  # noqa: PLR0913, PLR0917
        self,
        role: str | None = None,
        name: TextMatcher | None = None,
        description: TextMatcher | None = None,
        states: str | Iterable[str] | None = None,
        index_in_parent: int | None = None,
        visible_only: bool = False,
    ) -> Locator:
        query = _make_query(
            self._window._api._registry,
            role,
            name,
            description,
            states,
            index_in_parent,
            visible_only,
        )
        return Locator(self._window, (*self._chain, _Step(query)))

    def get_by_role(self, role: str, *, name: TextMatcher | None = None) -> Locator:
        return self.locator(role=role, name=name)

    def get_by_name(self, name: TextMatcher) -> Locator:
        return self.locator(name=name)

    def first(self) -> Locator:
        return self._with_position(0)

    def last(self) -> Locator:
        return self._with_position(-1)

    def nth(self, index: int) -> Locator:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("locator index must be a non-negative integer")
        return self._with_position(index)

    def _with_position(self, position: int) -> Locator:
        last = self._chain[-1]
        return Locator(
            self._window,
            (*self._chain[:-1], _Step(last.query, position)),
        )

    def count(self) -> int:
        return len(self._resolve_immediate())

    def all(self) -> list[Locator]:
        return [self.nth(index) for index in range(self.count())]

    def snapshot(self) -> ElementSnapshot:
        return self._wait_strict(self._window._api._timeout).snapshot

    def click(self, *, opens_window: bool = False) -> None:
        """Click the strict target semantically or with opt-in Win32 input."""
        if not isinstance(opens_window, bool):
            raise ValueError("opens_window must be a bool")
        if opens_window:
            self._click_with_mouse()
            return
        for attempt in range(2):
            match = self._wait_strict(self._window._api._timeout)
            self._check_actionable(match.snapshot, require_action=True)
            try:
                self._perform_semantic_click(match)
                return
            except NativeCallError as error:
                if attempt or error.function not in {
                    "getAccessibleContextInfo",
                    "getAccessibleActions",
                }:
                    raise
        raise AssertionError("unreachable")

    @staticmethod
    def _check_actionable(
        snapshot: ElementSnapshot,
        *,
        require_action: bool,
    ) -> None:
        missing = {
            state
            for state in ("visible", "showing", "enabled")
            if state not in snapshot.states
        }
        if missing:
            raise LocatorError(
                "locator is not actionable; missing states: "
                + ", ".join(sorted(missing))
            )
        if require_action and not snapshot.accessible_action:
            raise UnsupportedActionError(
                "locator does not expose the AccessibleAction interface"
            )

    def _perform_semantic_click(self, match: _Match) -> None:
        runtime = self._window._api._runtime
        with runtime.context_from_hwnd(self._window.hwnd) as root:
            current = root
            owned: JavaRef | None = None
            try:
                for index in match.path:
                    child = runtime.child(current, index)
                    if child is None:
                        raise NativeCallError(
                            "getAccessibleContextInfo",
                            reason="stale locator path",
                        )
                    if owned is not None:
                        owned.close()
                    owned = child
                    current = child
                info = runtime.context_info(current)
                self._check_actionable(
                    _snapshot(info, self._window._api._registry),
                    require_action=True,
                )
                actions = runtime.accessible_actions(current)
                action = next(
                    (
                        candidate
                        for candidate in actions
                        if candidate.casefold() == "click"
                    ),
                    None,
                )
                if action is None and len(actions) == 1:
                    action = actions[0]
                if action is None:
                    raise UnsupportedActionError(
                        f"locator has no click action; available actions: {actions!r}"
                    )
                runtime.do_accessible_actions(current, (action,))
            finally:
                if owned is not None:
                    owned.close()

    def _click_with_mouse(self) -> None:
        match = self._wait_strict(self._window._api._timeout)
        snapshot = match.snapshot
        self._check_actionable(snapshot, require_action=False)
        if snapshot.width <= 0 or snapshot.height <= 0:
            raise LocatorError("locator has empty bounds and cannot be clicked")
        x = snapshot.x + snapshot.width // 2
        y = snapshot.y + snapshot.height // 2
        windows = self._window._api._windows
        with _SYNTHETIC_INPUT_LOCK:
            previous_dpi = windows.set_thread_dpi_awareness_context(
                _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            )
            previous_cursor: tuple[int, int] | None = None
            try:
                previous_cursor = windows.get_cursor_position()
                windows.set_foreground_window(self._window.hwnd)
                windows.set_cursor_position(x, y)
                windows.send_left_click()
            finally:
                try:
                    if previous_cursor is not None:
                        windows.set_cursor_position(*previous_cursor)
                finally:
                    windows.set_thread_dpi_awareness_context(previous_dpi)

    def is_visible(self) -> bool:
        matches = self._resolve_immediate()
        if not matches:
            return False
        match = self._strict(matches)
        return "visible" in match.snapshot.states

    def is_enabled(self) -> bool:
        matches = self._resolve_immediate()
        if not matches:
            return False
        match = self._strict(matches)
        return "enabled" in match.snapshot.states

    def wait_for(self, state: str = "visible", timeout: int | None = None) -> None:
        if state not in {"attached", "detached", "visible", "hidden"}:
            raise ValueError("state must be attached, detached, visible, or hidden")
        wait = self._window._api._timeout if timeout is None else _timeout(timeout)
        deadline = time.monotonic() + wait / 1_000
        while True:
            try:
                matches = self._resolve_immediate()
            except _StaleLocatorError:
                matches = []
            if self._condition(state, matches):
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._raise_timeout(state, wait)
            time.sleep(min(_POLL_INTERVAL, remaining))

    def _condition(self, state: str, matches: list[_Match]) -> bool:
        if state == "detached":
            return not matches
        if state == "hidden":
            if not matches:
                return True
            return "visible" not in self._strict(matches).snapshot.states
        if not matches:
            return False
        match = self._strict(matches)
        return state == "attached" or "visible" in match.snapshot.states

    def _wait_strict(self, timeout: int) -> _Match:
        deadline = time.monotonic() + timeout / 1_000
        while True:
            try:
                matches = self._resolve_immediate()
            except _StaleLocatorError:
                matches = []
            if matches:
                return self._strict(matches)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._raise_timeout("attached", timeout)
            time.sleep(min(_POLL_INTERVAL, remaining))

    def _strict(self, matches: list[_Match]) -> _Match:
        if len(matches) != 1:
            self._raise_strict(len(matches))
        return matches[0]

    def _raise_strict(self, count: int) -> None:
        diagnostic = self._diagnostic()
        raise StrictModeViolation(
            f"locator resolved to {count} nodes; expected exactly one\n{diagnostic}"
        )

    def _raise_timeout(self, state: str, timeout: int) -> None:
        diagnostic = self._diagnostic()
        raise LocatorTimeoutError(
            f"timed out after {timeout} ms waiting for locator to be {state}\n"
            f"{diagnostic}"
        )

    def _diagnostic(self) -> str:
        try:
            return self._window.dump(_DIAGNOSTIC_DEPTH, _DIAGNOSTIC_NODES)
        except Exception:  # diagnostics must not replace the original failure
            return "<accessibility tree unavailable>"

    def _resolve_immediate(self) -> list[_Match]:
        for attempt in range(2):
            try:
                return self._resolve_once()
            except (_StaleContext, NativeCallError):
                if attempt:
                    raise _StaleLocatorError(
                        "accessibility context remained stale after retry"
                    ) from None
        raise AssertionError("unreachable")

    def _resolve_once(self) -> list[_Match]:
        parents: list[_Match] | None = None
        for step_index, step in enumerate(self._chain):
            if parents is None:
                matches = self._scan((), step.query, include_start=True)
            else:
                parent = self._strict(parents)
                matches = self._scan(parent.path, step.query, include_start=False)
            parents = self._select_position(matches, step.position)
            if step_index < len(self._chain) - 1:
                self._strict(parents)
        return parents or []

    def _select_position(
        self,
        matches: list[_Match],
        position: int | None,
    ) -> list[_Match]:
        if position is None:
            return matches
        index = position if position >= 0 else len(matches) - 1
        if 0 <= index < len(matches):
            return [matches[index]]
        return []

    def _scan(
        self,
        start_path: tuple[int, ...],
        query: _Query,
        *,
        include_start: bool,
    ) -> list[_Match]:
        runtime = self._window._api._runtime
        with runtime.context_from_hwnd(self._window.hwnd) as root:
            start = root
            owned: JavaRef | None = None
            try:
                for index in start_path:
                    child = runtime.child(start, index)
                    if child is None:
                        raise _StaleContext
                    if owned is not None:
                        owned.close()
                    owned = child
                    start = child
                matches: list[_Match] = []
                seen = [0]
                self._walk(
                    start,
                    start_path,
                    0,
                    query,
                    include_start,
                    matches,
                    seen,
                )
                return matches
            finally:
                if owned is not None:
                    owned.close()

    def _walk(  # noqa: PLR0913, PLR0917
        self,
        ref: JavaRef,
        path: tuple[int, ...],
        depth: int,
        query: _Query,
        consider: bool,
        matches: list[_Match],
        seen: list[int],
    ) -> None:
        if depth > _MAX_TREE_DEPTH or seen[0] >= _MAX_TREE_NODES:
            raise LocatorError("accessibility traversal limit exceeded")
        info = _context_info(self._window._api._runtime, ref)
        seen[0] += 1
        snapshot = _snapshot(info, self._window._api._registry)
        if consider and query.matches(snapshot):
            matches.append(_Match(path, snapshot))
        for index in range(info.children_count):
            child = self._window._api._runtime.child(ref, index)
            if child is None:
                raise _StaleContext
            with child:
                self._walk(
                    child,
                    (*path, index),
                    depth + 1,
                    query,
                    True,
                    matches,
                    seen,
                )

    def accessibility_tree(
        self,
        max_depth: int = 10,
        max_nodes: int = 1_000,
    ) -> AccessibilityNode:
        _tree_limits(max_depth, max_nodes)
        for attempt in range(2):
            match = self._strict(self._resolve_immediate())
            try:
                return self._tree_for_match(match, max_depth, max_nodes)
            except (_StaleContext, NativeCallError):
                if attempt:
                    raise LocatorError(
                        "locator tree remained stale after retry"
                    ) from None
        raise AssertionError("unreachable")

    def _tree_for_match(
        self,
        match: _Match,
        max_depth: int,
        max_nodes: int,
    ) -> AccessibilityNode:
        # The path is resolved afresh; no cookie from the locator pass survives.
        runtime = self._window._api._runtime
        with runtime.context_from_hwnd(self._window.hwnd) as root:
            current = root
            owned: JavaRef | None = None
            try:
                for index in match.path:
                    child = runtime.child(current, index)
                    if child is None:
                        raise _StaleContext
                    if owned is not None:
                        owned.close()
                    owned = child
                    current = child
                return self._window._read_node(
                    current,
                    0,
                    max_depth,
                    [max_nodes],
                )
            finally:
                if owned is not None:
                    owned.close()

    def dump(self, max_depth: int = 10, max_nodes: int = 1_000) -> str:
        return _format_tree(self.accessibility_tree(max_depth, max_nodes))


def _context_info(runtime: BridgeRuntime, ref: JavaRef) -> ContextInfo:
    try:
        return runtime.context_info(ref)
    except NativeCallError as error:
        if error.function == "getAccessibleContextInfo":
            raise _StaleContext from error
        raise


def _states(value: str) -> frozenset[str]:
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def _snapshot(
    info: ContextInfo,
    registry: AccessibilityRegistry,
) -> ElementSnapshot:
    role = registry.role(info.role_en_us)
    states = _states(info.states_en_us)
    for state in states:
        registry.state(state)
    password = info.role_en_us == _PASSWORD_ROLE
    return ElementSnapshot(
        name="<redacted>" if password and info.name else info.name,
        description="<redacted>" if password and info.description else info.description,
        role=role,
        states=states,
        index_in_parent=info.index_in_parent,
        x=info.x,
        y=info.y,
        width=info.width,
        height=info.height,
        accessible_component=info.accessible_component,
        accessible_action=info.accessible_action,
        accessible_selection=info.accessible_selection,
        accessible_text=info.accessible_text,
        accessible_interfaces=info.accessible_interfaces,
    )


def _format_tree(root: AccessibilityNode) -> str:
    lines: list[str] = []

    def append(node: AccessibilityNode, depth: int) -> None:
        snapshot = node.snapshot
        attributes = [f"role={snapshot.role!r}"]
        if snapshot.name:
            attributes.append(f"name={snapshot.name!r}")
        if snapshot.description:
            attributes.append(f"description={snapshot.description!r}")
        if snapshot.states:
            attributes.append(f"states={','.join(sorted(snapshot.states))!r}")
        lines.append(f"{'  ' * depth}- " + " ".join(attributes))
        for child in node.children:
            append(child, depth + 1)

    append(root, 0)
    return "\n".join(lines)
