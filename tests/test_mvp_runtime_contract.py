"""Portable contracts for deadlines, read/action split, value and wheel input."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import LocatorError, LocatorTimeoutError
from play_jab.sync_api import AccessibleInterface, JavaWindow, PlayJab

from .conftest import FakeWindowBackend

HWND = 0xCAFE
PID = 4242
ORIGINAL_DPI = 17
TIMEOUT_ZERO_SLACK_MS = 1_000


@pytest.fixture
def mvp_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, FakeBackend, FakeWindowBackend]]:
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
    windows = FakeWindowBackend(
        {HWND: "Fixture"},
        pid=PID,
        cursor=(90, 80),
        dpi_context=ORIGINAL_DPI,
    )
    windows.send_error = AssertionError("semantic-free wheel test must not click")
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    api = PlayJab(timeout=20)
    api.__enter__()
    try:
        yield api, api.attach(pid=PID).window(hwnd=HWND), backend, windows
    finally:
        api.close()


def test_reading_a_hidden_node_still_returns_its_text(
    mvp_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeWindowBackend],
) -> None:
    api, window, backend, _windows = mvp_api
    hidden = window.get_by_name("hidden")

    assert hidden.text_content(timeout=0) == "readable"

    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_scroll_on_a_hidden_node_is_rejected_as_not_actionable(
    mvp_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeWindowBackend],
) -> None:
    _api, window, _backend, _windows = mvp_api
    hidden = window.get_by_name("hidden")

    with pytest.raises(LocatorError, match="not actionable"):
        hidden.scroll(1, timeout=0)


def test_accessible_value_reads_current_minimum_and_maximum(
    mvp_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeWindowBackend],
) -> None:
    api, window, backend, _windows = mvp_api
    scrollbar = window.get_by_name("scrollbar")

    value = scrollbar.accessible_value(timeout=0)

    assert (value.current, value.minimum, value.maximum) == ("40", "0", "100")
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_scroll_sends_wheel_deltas_and_restores_cursor_and_dpi(
    mvp_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeWindowBackend],
) -> None:
    api, window, backend, windows = mvp_api
    scrollbar = window.get_by_name("scrollbar")

    scrollbar.scroll(2, timeout=0)
    scrollbar.scroll(-1, timeout=0)
    scrollbar.scroll(0, timeout=0)

    assert windows.wheels == [-240, 120]
    assert windows.cursor == (90, 80)
    assert windows.dpi_context == ORIGINAL_DPI
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_timeout_diagnostic_is_structured_and_bounded(
    mvp_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeWindowBackend],
) -> None:
    _api, window, _backend, _windows = mvp_api
    with pytest.raises(LocatorTimeoutError) as caught:
        window.get_by_name("missing").snapshot(timeout=0)
    error = caught.value
    assert error.expected == "attached"
    # `timeout=0` means the wait resolves immediately; a slack of well under a
    # second still catches a diagnostic that silently blocks or misreports.
    assert error.elapsed_ms is not None
    assert 0 <= error.elapsed_ms < TIMEOUT_ZERO_SLACK_MS
    assert error.hwnd == HWND
    assert error.pid == PID
    # `_RUNTIME_MANAGER` is a session-wide singleton whose generation counter
    # only grows, so an exact value here would depend on test execution order;
    # a positive int is the actual, order-independent contract.
    assert error.generation is not None and error.generation >= 1
    assert error.tree is not None
    tree_lines = error.tree.splitlines()
    assert 0 < len(tree_lines) <= sync_api._DIAGNOSTIC_NODES
    assert "role='frame'" in tree_lines[0]


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
    monkeypatch.setattr(
        sync_api,
        "_create_window_backend",
        lambda: FakeWindowBackend({HWND: "Fixture"}, pid=PID),
    )
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    with PlayJab(timeout=0) as api:
        window = api.attach(pid=PID).window(hwnd=HWND)
        assert window.get_by_name("visible").snapshot(timeout=0).index_in_parent == 1
        assert window.get_by_name("hidden").count() == 0
        assert api.live_ref_count == 0
    assert backend.acquired == backend.released
