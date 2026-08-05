"""Portable contracts for deadlines, read/action split, value and wheel input."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import LocatorError, LocatorTimeoutError
from play_jab.sync_api import AccessibleInterface, JavaWindow, PlayJab

HWND = 0xCAFE
PID = 4242
ORIGINAL_DPI = 17


class _Windows:
    def __init__(self) -> None:
        self.cursor = (90, 80)
        self.dpi = ORIGINAL_DPI
        self.wheels: list[int] = []

    def enum_windows(self) -> list[int]:
        return [HWND]

    def get_window_title(self, hwnd: int) -> str:
        return "Fixture"

    def get_window_pid(self, hwnd: int) -> int:
        return PID

    def set_foreground_window(self, hwnd: int) -> None:
        assert hwnd == HWND

    def get_cursor_position(self) -> tuple[int, int]:
        return self.cursor

    def set_cursor_position(self, x: int, y: int) -> None:
        self.cursor = (x, y)

    def set_thread_dpi_awareness_context(self, context: int) -> int:
        previous, self.dpi = self.dpi, context
        return previous

    def send_left_click(self) -> None:
        raise AssertionError("semantic-free wheel test must not click")

    def send_mouse_wheel(self, delta: int) -> None:
        self.wheels.append(delta)


@pytest.fixture
def mvp_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, FakeBackend, _Windows]]:
    hidden = FakeNode(
        name="hidden",
        description="readable",
        role_en_us="label",
        states_en_us="",
    )
    scrollbar = FakeNode(
        name="scrollbar",
        role_en_us="scroll bar",
        states_en_us="visible,showing,enabled",
        accessible_interfaces=int(AccessibleInterface.VALUE),
        value="40",
        minimum_value="0",
        maximum_value="100",
        x=10,
        y=20,
        width=30,
        height=40,
    )
    root = FakeNode(
        name="root",
        role_en_us="frame",
        states_en_us="visible,showing,enabled",
        children=[hidden, scrollbar],
    )
    backend = FakeBackend({HWND: root})
    runtime = BridgeRuntime(lambda: backend, pump_interval=0.001)
    windows = _Windows()
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    api = PlayJab(timeout=20)
    api.__enter__()
    try:
        yield api, api.attach(pid=PID).window(hwnd=HWND), backend, windows
    finally:
        api.close()


def test_hidden_read_value_and_explicit_wheel_restore_state(
    mvp_api: tuple[PlayJab, JavaWindow, FakeBackend, _Windows],
) -> None:
    api, window, backend, windows = mvp_api
    hidden = window.get_by_name("hidden")
    assert hidden.text_content(timeout=0) == "readable"
    with pytest.raises(LocatorError, match="not actionable"):
        hidden.scroll(1, timeout=0)

    scrollbar = window.get_by_name("scrollbar")
    value = scrollbar.accessible_value(timeout=0)
    assert (value.current, value.minimum, value.maximum) == ("40", "0", "100")
    scrollbar.scroll(2, timeout=0)
    scrollbar.scroll(-1, timeout=0)
    scrollbar.scroll(0, timeout=0)
    assert windows.wheels == [-240, 120]
    assert windows.cursor == (90, 80)
    assert windows.dpi == ORIGINAL_DPI
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_timeout_diagnostic_is_structured_and_bounded(
    mvp_api: tuple[PlayJab, JavaWindow, FakeBackend, _Windows],
) -> None:
    _api, window, _backend, _windows = mvp_api
    with pytest.raises(LocatorTimeoutError) as caught:
        window.get_by_name("missing").snapshot(timeout=0)
    error = caught.value
    assert error.expected == "attached"
    assert error.elapsed_ms is not None
    assert error.tree is not None
    assert error.hwnd == HWND
    assert error.pid == PID
    assert error.generation is not None


def test_managed_descendants_use_visible_children_and_model_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hidden = FakeNode(name="hidden", role_en_us="label", states_en_us="")
    visible = FakeNode(
        name="visible", role_en_us="label", states_en_us="visible,showing,enabled"
    )
    managed = FakeNode(
        name="managed",
        role_en_us="list",
        states_en_us="visible,showing,enabled,manages descendants",
        children=[hidden, visible],
    )
    root = FakeNode(
        role_en_us="frame",
        states_en_us="visible,showing,enabled",
        children=[managed],
    )
    backend = FakeBackend({HWND: root})
    runtime = BridgeRuntime(lambda: backend, pump_interval=0.001)
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", _Windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    with PlayJab(timeout=0) as api:
        window = api.attach(pid=PID).window(hwnd=HWND)
        assert window.get_by_name("visible").snapshot(timeout=0).index_in_parent == 1
        assert window.get_by_name("hidden").count() == 0
        assert api.live_ref_count == 0
    assert backend.acquired == backend.released
