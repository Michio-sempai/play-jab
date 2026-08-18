"""Shared fixtures and fakes for the portable (non-integration) unit tests.

Consolidates the Win32 window-backend double that used to be copy-pasted
across seven test files (``_Windows``/``FakeWindows``/``_InputWindows`` in
``test_locator_contract.py``, ``test_mvp_runtime_contract.py``,
``test_forms_tables_events.py``, ``test_runtime_manager.py``,
``test_expect_window.py``, ``test_sync_api_lifecycle.py`` and
``test_win32_click.py``), plus an autouse guard against a leaked global
``_RUNTIME_MANAGER`` state cascading into unrelated tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend

DEFAULT_PID = 4242
DEFAULT_HWND = 0xCAFE


class FakeWindowBackend:
    """Configurable double for ``sync_api.WindowBackend``.

    Every hwnd in ``titles`` is enumerable; ``pids`` maps a subset of them
    to a process id, falling back to ``pid`` for the rest. All Win32-input
    methods append to ``.calls`` and are safe to invoke unless
    ``guard_input=True``, in which case any input-affecting call raises
    ``AssertionError`` -- use that for tests whose contract is "no synthetic
    input happens here" (mirrors the old ``_Windows`` guard classes in
    ``test_expect_window.py``).
    """

    def __init__(  # noqa: PLR0913 -- independent config knobs for a test double
        self,
        titles: dict[int, str] | None = None,
        *,
        pid: int = DEFAULT_PID,
        pids: dict[int, int] | None = None,
        visible: list[int] | None = None,
        cursor: tuple[int, int] = (0, 0),
        dpi_context: int = 0,
        guard_input: bool = False,
        on_key: Callable[[int], None] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> None:
        self.titles = dict(titles) if titles is not None else {DEFAULT_HWND: "Fixture"}
        self.pid = pid
        self.pids = dict(pids) if pids is not None else {}
        self.visible = list(visible) if visible is not None else list(self.titles)
        self.cursor = cursor
        self.dpi_context = dpi_context
        self.guard_input = guard_input
        self.on_key = on_key
        self.on_text = on_text
        self.calls: list[tuple[object, ...]] = []
        self.wheels: list[int] = []
        self.send_error: BaseException | None = None
        self.key_errors: dict[int, BaseException] = {}
        self.text_error: BaseException | None = None
        self.enum_calls = 0

    def enum_windows(self) -> list[int]:
        self.enum_calls += 1
        return list(self.visible)

    def get_window_title(self, hwnd: int) -> str:
        return self.titles[hwnd]

    def get_window_pid(self, hwnd: int) -> int:
        return self.pids.get(hwnd, self.pid)

    def _guard(self, name: str) -> None:
        if self.guard_input:
            raise AssertionError(f"unexpected synthetic input call: {name}")

    def set_foreground_window(self, hwnd: int) -> None:
        self._guard("set_foreground_window")
        self.calls.append(("foreground", hwnd))

    def get_cursor_position(self) -> tuple[int, int]:
        self._guard("get_cursor_position")
        self.calls.append(("get_cursor",))
        return self.cursor

    def set_cursor_position(self, x: int, y: int) -> None:
        self._guard("set_cursor_position")
        self.cursor = (x, y)
        self.calls.append(("set_cursor", x, y))

    def set_thread_dpi_awareness_context(self, context: int) -> int:
        self._guard("set_thread_dpi_awareness_context")
        previous, self.dpi_context = self.dpi_context, context
        self.calls.append(("dpi", context))
        return previous

    def send_left_click(self) -> None:
        self._guard("send_left_click")
        self.calls.append(("click",))
        if self.send_error is not None:
            raise self.send_error

    def send_mouse_wheel(self, delta: int) -> None:
        self._guard("send_mouse_wheel")
        self.calls.append(("wheel", delta))
        self.wheels.append(delta)

    def send_key(self, vk_code: int) -> None:
        self._guard("send_key")
        self.calls.append(("key", vk_code))
        error = self.key_errors.get(vk_code)
        if error is not None:
            raise error
        if self.send_error is not None:
            raise self.send_error
        if self.on_key is not None:
            self.on_key(vk_code)

    def send_repeated_key(self, vk_code: int, count: int) -> None:
        self._guard("send_repeated_key")
        self.calls.append(("repeat_key", vk_code, count))
        if self.send_error is not None:
            raise self.send_error
        if self.on_key is not None:
            for _ in range(count):
                self.on_key(vk_code)

    def send_text(self, value: str) -> None:
        self._guard("send_text")
        self.calls.append(("text", value))
        if self.text_error is not None:
            raise self.text_error
        if self.on_text is not None:
            self.on_text(value)


def install_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    backend: FakeBackend,
    *,
    windows: object | None = None,
    is_process_alive: Callable[[int], bool] | None = None,
    pump_interval: float | None = None,
) -> BridgeRuntime:
    """Wire a `FakeBackend` and optional window/process doubles into `sync_api`.

    Returns the `BridgeRuntime` so callers can still reach into it (for
    example to assert on `live_ref_count`). Pass `pump_interval` to tighten
    the worker's poll cadence for tests that wait on event-driven wakeups.
    """
    runtime_kwargs = {} if pump_interval is None else {"pump_interval": pump_interval}
    runtime = BridgeRuntime(lambda: backend, **runtime_kwargs)
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    if windows is not None:
        monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    if is_process_alive is not None:
        monkeypatch.setattr(sync_api, "_is_process_alive", is_process_alive)
    return runtime


@pytest.fixture(autouse=True)
def _runtime_manager_is_stopped_after_every_test() -> Iterator[None]:
    """Fail fast if a test leaks the process-wide runtime manager.

    Without this, a test that forgets to release its lease would not fail
    itself -- it would corrupt every *subsequent* test file with
    ``BridgeInitializationError: ...uses a different DLL path``, which is
    far harder to diagnose than a failure at the source.
    """
    yield
    state = sync_api._RUNTIME_MANAGER._state
    assert state == "stopped", (
        f"_RUNTIME_MANAGER leaked in state {state!r}; "
        "a test forgot to release/close its PlayJab instance"
    )
