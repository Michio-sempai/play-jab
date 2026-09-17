"""Opt-in synthetic click semantics through the replaceable Win32 seam."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import LocatorError
from play_jab.sync_api import JavaWindow, PlayJab

from .conftest import FakeWindowBackend

PID = 4242
HWND = 0xCAFE
CLICK_COUNT = 2


@pytest.fixture
def mouse_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, FakeBackend, FakeNode, FakeWindowBackend]]:
    target = FakeNode(
        name="Open",
        role_en_us="push button",
        states_en_us="enabled,visible,showing",
        x=10,
        y=20,
        width=31,
        height=41,
    )
    backend = FakeBackend(
        {
            HWND: FakeNode(
                name="Fixture",
                role_en_us="frame",
                states_en_us="enabled,visible,showing",
                children=[target],
            )
        }
    )
    runtime = BridgeRuntime(lambda: backend)
    windows = FakeWindowBackend(
        {HWND: "Fixture"}, pid=PID, cursor=(700, 800), dpi_context=123
    )
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    api = PlayJab(timeout=0)
    api.__enter__()
    try:
        yield api, api.attach(pid=PID).window(), backend, target, windows
    finally:
        api.close()


def test_opens_window_click_uses_fresh_center_and_restores_cursor_and_dpi(
    mouse_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeNode, FakeWindowBackend],
) -> None:
    api, window, backend, target, windows = mouse_api
    locator = window.get_by_name("Open")
    target.x = 100
    target.y = 200

    locator.click(opens_window=True)

    assert windows.calls == [
        ("logical_to_physical", HWND, 115, 220, (115, 220)),
        ("dpi", -4),
        ("get_cursor",),
        ("foreground", HWND),
        ("set_cursor", 115, 220),
        ("click",),
        ("set_cursor", 700, 800),
        ("dpi", 123),
    ]
    assert backend.performed_actions == []
    assert api.live_ref_count == 0


def test_click_maps_jab_coordinates_through_logical_to_physical_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The click point must go through `logical_to_physical_point`, unmodified.

    Regression for a real miss against a Swing app on a 3-monitor,
    mixed-DPI, mixed-scale desktop: JAB reports `AccessibleComponent` bounds
    in the *target window's* own logical space (a non-DPI-aware JVM, which
    a typical Swing UI is, never sees the real per-monitor scale or
    position), but `SetCursorPos` -- called under `PER_MONITOR_AWARE_V2` --
    takes physical screen pixels. A plain DPI-ratio scale was tried and
    rejected first: it still landed on the wrong monitor's geometry and
    missed by roughly a menu item's height, enough to land outside an
    already-open popup menu and silently dismiss it instead of clicking the
    item inside it -- confirmed live, no exception raised anywhere in the
    chain (the click still "succeeds", just on the wrong pixel).
    `LogicalToPhysicalPointForPerMonitorDPI` (exercised here through the fake
    as an arbitrary offset+scale, matching what a real mixed-monitor desktop
    produces) is the fix that was confirmed correct against the real desktop.
    """
    target = FakeNode(
        name="Open",
        role_en_us="push button",
        states_en_us="enabled,visible,showing",
        x=100,
        y=200,
        width=31,
        height=41,
    )
    backend = FakeBackend(
        {
            HWND: FakeNode(
                name="Fixture",
                role_en_us="frame",
                states_en_us="enabled,visible,showing",
                children=[target],
            )
        }
    )
    runtime = BridgeRuntime(lambda: backend)
    # An arbitrary offset+scale, standing in for what
    # LogicalToPhysicalPointForPerMonitorDPI does on a real mixed-monitor
    # desktop -- not a pure scale (a pure DPI ratio was the bug).
    windows = FakeWindowBackend(
        {HWND: "Fixture"},
        pid=PID,
        point_translation=lambda _hwnd, x, y: (x + 163, y + 48),
    )
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)

    with PlayJab(timeout=0) as api:
        window = api.attach(pid=PID).window()
        window.get_by_name("Open").click(opens_window=True)

    # Logical center is (115, 220); the fake's translation maps that to
    # (278, 268) -- not the raw logical point.
    assert ("logical_to_physical", HWND, 115, 220, (278, 268)) in windows.calls
    assert ("set_cursor", 278, 268) in windows.calls


def test_mouse_click_restores_cursor_and_dpi_when_input_raises(
    mouse_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeNode, FakeWindowBackend],
) -> None:
    api, window, _, _, windows = mouse_api
    windows.send_error = OSError("SendInput failed")

    with pytest.raises(OSError, match="SendInput failed"):
        window.get_by_name("Open").click(opens_window=True)

    assert windows.calls[-2:] == [("set_cursor", 700, 800), ("dpi", 123)]
    assert api.live_ref_count == 0


def test_mouse_click_rejects_empty_bounds_before_touching_win32(
    mouse_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeNode, FakeWindowBackend],
) -> None:
    _, window, _, target, windows = mouse_api
    target.width = 0
    with pytest.raises(LocatorError, match="empty bounds"):
        window.get_by_name("Open").click(opens_window=True)
    assert windows.calls == []


def test_click_requires_a_real_boolean_mode(
    mouse_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeNode, FakeWindowBackend],
) -> None:
    _, window, _, _, _ = mouse_api
    with pytest.raises(ValueError, match="opens_window"):
        window.get_by_name("Open").click(opens_window=1)  # type: ignore[arg-type]


def test_synthetic_input_is_serialized_across_callers(
    mouse_api: tuple[PlayJab, JavaWindow, FakeBackend, FakeNode, FakeWindowBackend],
) -> None:
    _, window, _, _, windows = mouse_api
    first_inside = threading.Event()
    release_first = threading.Event()
    completed: list[BaseException | None] = []
    call_count = 0

    def blocking_send() -> None:
        nonlocal call_count
        call_count += 1
        first_inside.set()
        if call_count == 1 and not release_first.wait(timeout=2):
            raise TimeoutError("test did not release first click")

    windows.send_left_click = blocking_send  # type: ignore[method-assign]

    def click() -> None:
        try:
            window.get_by_name("Open").click(opens_window=True)
        except BaseException as error:
            completed.append(error)
        else:
            completed.append(None)

    first = threading.Thread(target=click)
    second = threading.Thread(target=click)
    first.start()
    assert first_inside.wait(timeout=2)
    second.start()
    assert call_count == 1
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert not first.is_alive()
    assert not second.is_alive()
    assert completed == [None, None]
    assert call_count == CLICK_COUNT
