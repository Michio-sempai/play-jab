"""``_Win32WindowBackend``/``_is_process_alive`` driven by stub user32/kernel32.

Both are pure ctypes-marshalling logic layered over Win32 - the DLLs
themselves are never exercised by the portable unit suite because every other
test replaces the whole window backend with a fake (see
``tests/conftest.py::FakeWindowBackend``). ``_Win32WindowBackend`` itself,
and in particular the foreground-window retry loop implicated in the
``opens_window=True`` failures the integration review observed
(``OSError: could not make window ... foreground``), was previously
untested. Stubs here are plain functions (not bound methods), because ctypes
function pointers support ``.argtypes``/``.restype`` assignment and
``_Win32WindowBackend.__init__`` assigns both on every export it uses.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

import pytest

from play_jab import sync_api

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the Win32 seam only exists on Windows"
)

TRUE = 1
FALSE = 0
TARGET_HWND = 0x4242
PID = 4242
SUCCESS_AFTER_TWO_ATTEMPTS = 2
REPEATED_KEYS = 3
SINGLE_KEY_EVENTS = 2
REPEATED_KEY_EVENTS = 6
UNICODE_EVENTS = 6


class StubUser32:
    """Every export `_Win32WindowBackend.__init__` configures, as closures."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.foreground_hwnd = 0
        self.send_counts: list[int] = []
        # Number of `SetForegroundWindow` calls after which `GetForegroundWindow`
        # starts reporting the target hwnd; `None` means it never does.
        self.succeed_after_attempts: int | None = 1

        def enum_windows(_callback: Any, _param: int) -> int:
            return TRUE

        def get_window_text_length_w(_hwnd: int) -> int:
            return 0

        def get_window_text_w(_hwnd: int, _buffer: Any, _size: int) -> int:
            return 0

        def get_window_thread_process_id(_hwnd: int, _pid_ref: Any) -> int:
            return 0

        def bring_window_to_top(hwnd: int) -> int:
            self.calls.append(("BringWindowToTop", (hwnd,)))
            return TRUE

        def set_foreground_window(hwnd: int) -> int:
            self.calls.append(("SetForegroundWindow", (hwnd,)))
            attempts = sum(1 for name, _ in self.calls if name == "SetForegroundWindow")
            if (
                self.succeed_after_attempts is not None
                and attempts >= self.succeed_after_attempts
            ):
                self.foreground_hwnd = hwnd
            return TRUE

        def get_foreground_window() -> int:
            return self.foreground_hwnd

        def get_cursor_pos(_point_ref: Any) -> int:
            return TRUE

        def set_cursor_pos(_x: int, _y: int) -> int:
            return TRUE

        def set_thread_dpi_awareness_context(_context: Any) -> int:
            return 1

        def logical_to_physical_point_for_per_monitor_dpi(
            _hwnd: int, _point_ref: Any
        ) -> int:
            return TRUE

        def send_input(count: int, _inputs: Any, _size: int) -> int:
            self.send_counts.append(count)
            return count

        self.EnumWindows = enum_windows
        self.GetWindowTextLengthW = get_window_text_length_w
        self.GetWindowTextW = get_window_text_w
        self.GetWindowThreadProcessId = get_window_thread_process_id
        self.SetForegroundWindow = set_foreground_window
        self.GetForegroundWindow = get_foreground_window
        self.BringWindowToTop = bring_window_to_top
        self.GetCursorPos = get_cursor_pos
        self.SetCursorPos = set_cursor_pos
        self.SetThreadDpiAwarenessContext = set_thread_dpi_awareness_context
        self.LogicalToPhysicalPointForPerMonitorDPI = (
            logical_to_physical_point_for_per_monitor_dpi
        )
        self.SendInput = send_input


@pytest.fixture
def stub_user32(monkeypatch: pytest.MonkeyPatch) -> StubUser32:
    stub = StubUser32()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_a, **_k: stub, raising=False)
    return stub


def test_set_foreground_window_succeeds_once_the_transition_is_observed(
    stub_user32: StubUser32,
) -> None:
    stub_user32.succeed_after_attempts = SUCCESS_AFTER_TWO_ATTEMPTS
    backend = sync_api._Win32WindowBackend()

    backend.set_foreground_window(TARGET_HWND)

    attempts = [call for call in stub_user32.calls if call[0] == "SetForegroundWindow"]
    assert len(attempts) == SUCCESS_AFTER_TWO_ATTEMPTS


def test_set_foreground_window_raises_after_all_failed_attempts(
    stub_user32: StubUser32,
) -> None:
    stub_user32.succeed_after_attempts = None
    ctypes.set_last_error(0)  # isolate from any earlier real WinAPI call in this thread
    backend = sync_api._Win32WindowBackend()

    with pytest.raises(
        OSError, match=f"could not make window {TARGET_HWND:#x} foreground"
    ):
        backend.set_foreground_window(TARGET_HWND)

    attempts = [call for call in stub_user32.calls if call[0] == "SetForegroundWindow"]
    max_attempts = sync_api._FOREGROUND_ATTEMPTS
    assert len(attempts) == max_attempts


def test_keyboard_input_batches_keys_repetition_and_utf16_units(
    stub_user32: StubUser32,
) -> None:
    backend = sync_api._Win32WindowBackend()

    backend.send_key(sync_api._VK_F2)
    backend.send_repeated_key(sync_api._VK_DELETE, REPEATED_KEYS)
    backend.send_text("A😀")
    backend.send_text("")

    assert stub_user32.send_counts == [
        SINGLE_KEY_EVENTS,
        REPEATED_KEY_EVENTS,
        UNICODE_EVENTS,
    ]


class StubKernel32:
    """Every export `_is_process_alive` calls, as closures."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.open_process_result = 0
        self.exit_code_value = 0

        def open_process(_desired_access: int, _inherit: int, pid: int) -> int:
            self.calls.append(("OpenProcess", pid))
            return self.open_process_result

        def close_handle(handle: int) -> int:
            self.calls.append(("CloseHandle", handle))
            return TRUE

        def get_exit_code_process(_handle: int, exit_code_ref: Any) -> int:
            pointer = ctypes.cast(exit_code_ref, ctypes.POINTER(ctypes.c_uint32))
            pointer.contents.value = self.exit_code_value
            return TRUE

        self.OpenProcess = open_process
        self.CloseHandle = close_handle
        self.GetExitCodeProcess = get_exit_code_process


@pytest.fixture
def stub_kernel32(monkeypatch: pytest.MonkeyPatch) -> StubKernel32:
    stub = StubKernel32()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_a, **_k: stub, raising=False)
    return stub


def test_is_process_alive_is_true_for_a_running_process(
    stub_kernel32: StubKernel32,
) -> None:
    stub_kernel32.open_process_result = 0xABCD
    stub_kernel32.exit_code_value = sync_api._STILL_ACTIVE

    assert sync_api._is_process_alive(PID) is True
    assert ("CloseHandle", 0xABCD) in stub_kernel32.calls


def test_is_process_alive_is_false_when_open_process_fails(
    stub_kernel32: StubKernel32,
) -> None:
    stub_kernel32.open_process_result = 0

    assert sync_api._is_process_alive(PID) is False
    assert not any(name == "CloseHandle" for name, _ in stub_kernel32.calls)


def test_is_process_alive_is_false_for_an_exited_process(
    stub_kernel32: StubKernel32,
) -> None:
    stub_kernel32.open_process_result = 0xABCD
    stub_kernel32.exit_code_value = 0

    assert sync_api._is_process_alive(PID) is False
