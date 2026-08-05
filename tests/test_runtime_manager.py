"""Process-wide runtime leases and client-local lifecycle contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    BridgeClosedError,
    BridgeInitializationError,
    LocatorTimeoutError,
)
from play_jab.sync_api import PlayJab

PID = 4242
HWND = 0xCAFE
GENERATION_COUNT = 2


class _Windows:
    def enum_windows(self) -> list[int]:
        return [HWND]

    def get_window_title(self, hwnd: int) -> str:
        assert hwnd == HWND
        return "Fixture"

    def get_window_pid(self, hwnd: int) -> int:
        assert hwnd == HWND
        return PID


def _tree() -> dict[int, FakeNode]:
    return {
        HWND: FakeNode(
            name="Fixture",
            role_en_us="frame",
            states_en_us="enabled,visible,showing",
            children=[
                FakeNode(
                    name="Submit",
                    role_en_us="push button",
                    states_en_us="enabled,visible,showing",
                )
            ],
        )
    }


def _fake_dll(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _install_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[BridgeRuntime], list[FakeBackend], list[Path | None]]:
    runtimes: list[BridgeRuntime] = []
    backends: list[FakeBackend] = []
    paths: list[Path | None] = []

    def create_runtime(
        dll_path: str | Path | None,
        _timeout: int,
    ) -> BridgeRuntime:
        backend = FakeBackend(_tree())
        runtime = BridgeRuntime(lambda: backend, pump_interval=0.001)
        paths.append(None if dll_path is None else Path(dll_path))
        backends.append(backend)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(sync_api, "_create_runtime", create_runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", _Windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    return runtimes, backends, paths


def test_two_clients_share_one_runtime_and_close_only_its_own_handles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtimes, backends, _ = _install_backends(monkeypatch)
    dll_path = _fake_dll(tmp_path / "WindowsAccessBridge-64.dll")
    first = PlayJab(timeout=0, dll_path=dll_path)
    second = PlayJab(timeout=0, dll_path=dll_path)
    try:
        first.__enter__()
        second.__enter__()
        first_application = first.attach(hwnd=HWND, timeout=0)
        first_window = first_application.window(hwnd=HWND, timeout=0)
        first_locator = first_window.get_by_name("Submit")
        second_window = second.attach(hwnd=HWND, timeout=0).window(
            hwnd=HWND,
            timeout=0,
        )

        assert len(runtimes) == 1
        assert backends[0].windows_run_calls == 1

        first.close()

        with pytest.raises(BridgeClosedError):
            first_application.window(hwnd=HWND, timeout=0)
        with pytest.raises(BridgeClosedError):
            first_window.accessibility_tree()
        with pytest.raises(BridgeClosedError):
            first_locator.count()

        assert second_window.get_by_name("Submit").count() == 1
        assert not runtimes[0].closed
        assert backends[0].shutdown_calls == 0
    finally:
        first.close()
        second.close()

    assert runtimes[0].closed
    assert backends[0].shutdown_calls == 1


def test_active_generation_rejects_a_different_canonical_dll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtimes, backends, paths = _install_backends(monkeypatch)
    first_path = _fake_dll(tmp_path / "first" / "WindowsAccessBridge-64.dll")
    other_path = _fake_dll(tmp_path / "other" / "WindowsAccessBridge-64.dll")
    first = PlayJab(timeout=0, dll_path=first_path)
    try:
        first.__enter__()
        with (
            pytest.raises(BridgeInitializationError, match=r"DLL|dll|path"),
            PlayJab(timeout=0, dll_path=other_path),
        ):
            pass

        assert len(runtimes) == 1
        assert paths == [first_path]
        assert backends[0].shutdown_calls == 0
    finally:
        first.close()

    assert backends[0].shutdown_calls == 1


def test_equivalent_dll_spellings_share_the_active_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtimes, backends, _ = _install_backends(monkeypatch)
    dll_path = _fake_dll(tmp_path / "WindowsAccessBridge-64.dll")
    alias_directory = tmp_path / "alias"
    alias_directory.mkdir()
    equivalent_path = alias_directory / ".." / dll_path.name
    first = PlayJab(timeout=0, dll_path=dll_path)
    second = PlayJab(timeout=0, dll_path=equivalent_path)
    try:
        first.__enter__()
        second.__enter__()
        assert len(runtimes) == 1
        assert backends[0].windows_run_calls == 1
    finally:
        first.close()
        second.close()

    assert backends[0].shutdown_calls == 1


def test_new_generation_uses_a_new_runtime_and_old_handles_stay_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtimes, backends, _ = _install_backends(monkeypatch)
    dll_path = _fake_dll(tmp_path / "WindowsAccessBridge-64.dll")
    first = PlayJab(timeout=0, dll_path=dll_path)
    first.__enter__()
    old_application = first.attach(hwnd=HWND, timeout=0)
    old_window = old_application.window(hwnd=HWND, timeout=0)
    old_locator = old_window.get_by_name("Submit")
    first.close()

    second = PlayJab(timeout=0, dll_path=dll_path)
    try:
        second.__enter__()
        new_window = second.attach(hwnd=HWND, timeout=0).window(
            hwnd=HWND,
            timeout=0,
        )

        assert len(runtimes) == GENERATION_COUNT
        assert runtimes[0] is not runtimes[1]
        assert backends[0].shutdown_calls == 1
        assert new_window.get_by_name("Submit").count() == 1

        with pytest.raises(BridgeClosedError):
            old_application.window(hwnd=HWND, timeout=0)
        with pytest.raises(BridgeClosedError):
            old_window.accessibility_tree()
        with pytest.raises(BridgeClosedError):
            old_locator.count()
    finally:
        second.close()

    assert [backend.shutdown_calls for backend in backends] == [1, 1]


def test_locator_timeout_precedence_is_call_then_window_then_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_backends(monkeypatch)
    api = PlayJab(timeout=30)
    try:
        api.__enter__()
        application = api.attach(hwnd=HWND, timeout=0)
        api_default = application.window(hwnd=HWND)
        window_default = application.window(hwnd=HWND, timeout=7)

        with pytest.raises(LocatorTimeoutError, match="30 ms") as api_timeout:
            api_default.get_by_name("Missing").wait_for()
        with pytest.raises(LocatorTimeoutError, match="7 ms") as window_timeout:
            window_default.get_by_name("Missing").wait_for()
        with pytest.raises(LocatorTimeoutError, match="0 ms") as call_timeout:
            window_default.get_by_name("Missing").wait_for(timeout=0)

        assert type(api_timeout.value) is type(window_timeout.value)
        assert type(window_timeout.value) is type(call_timeout.value)
    finally:
        api.close()
