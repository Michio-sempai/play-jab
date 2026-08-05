"""Lifecycle and Win32/process discovery contracts for the sync API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    JavaProcessExitedError,
    JavaWindowAmbiguousError,
    JavaWindowNotFoundError,
)
from play_jab.sync_api import PlayJab

PID = 4321
OTHER_PID = 9876
HWND = 0x1234
SECOND_HWND = 0x5678
OTHER_HWND = 0x9999


@dataclass(frozen=True)
class FakeProcessHandle:
    pid: int


class FakeWindows:
    def __init__(self) -> None:
        self.windows: list[int] = [HWND, OTHER_HWND]
        self.titles = {HWND: "Main", SECOND_HWND: "Second", OTHER_HWND: "Main"}
        self.pids = {HWND: PID, SECOND_HWND: PID, OTHER_HWND: OTHER_PID}
        self.calls = 0

    def enum_windows(self) -> list[int]:
        self.calls += 1
        return list(self.windows)

    def get_window_title(self, hwnd: int) -> str:
        return self.titles[hwnd]

    def get_window_pid(self, hwnd: int) -> int:
        return self.pids[hwnd]


class FakeProcesses:
    def __init__(self) -> None:
        self.alive: set[int] = {PID, OTHER_PID}
        self.launches: list[
            tuple[str | Sequence[str], str | Path | None, Mapping[str, str] | None]
        ] = []

    def launch(
        self,
        command: str | Sequence[str],
        *,
        cwd: str | Path | None,
        env: Mapping[str, str] | None,
    ) -> FakeProcessHandle:
        self.launches.append((command, cwd, env))
        return FakeProcessHandle(PID)

    def is_alive(self, pid: int) -> bool:
        return pid in self.alive


@pytest.fixture
def api_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses]:
    roots = {
        HWND: FakeNode(name="Main", role_en_us="frame", states_en_us="visible"),
        SECOND_HWND: FakeNode(
            name="Second", role_en_us="frame", states_en_us="visible"
        ),
        OTHER_HWND: FakeNode(name="Other", role_en_us="frame", states_en_us="visible"),
    }
    backend = FakeBackend(roots)
    runtime = BridgeRuntime(lambda: backend)
    windows = FakeWindows()
    processes = FakeProcesses()
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    monkeypatch.setattr(sync_api, "_create_process_backend", lambda: processes)
    return PlayJab(), runtime, backend, windows, processes


def test_context_manager_owns_one_runtime_and_close_is_idempotent(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
) -> None:
    api, runtime, backend, _, _ = api_backends
    with api as entered:
        assert entered is api
        with api as nested:
            assert nested is api
    api.close()
    api.close()
    assert runtime.closed
    assert backend.windows_run_calls == 1
    assert backend.shutdown_calls == 1


def test_attach_requires_exactly_one_selector_before_discovery(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
) -> None:
    api, _, _, windows, _ = api_backends
    with api:
        for arguments in (
            {},
            {"pid": PID, "hwnd": HWND},
            {"pid": PID, "title": "Main"},
        ):
            with pytest.raises(ValueError):
                api.attach(**arguments)  # type: ignore[arg-type]
    assert windows.calls == 0


@pytest.mark.parametrize(
    ("arguments", "invalid"),
    [
        ({"hwnd": 0}, "hwnd"),
        ({"hwnd": -1}, "hwnd"),
        ({"pid": 0}, "pid"),
        ({"pid": -1}, "pid"),
        ({"title": ""}, "title"),
        ({"pid": PID, "timeout": -1}, "timeout"),
    ],
)
def test_attach_rejects_invalid_values_before_native_calls(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
    arguments: dict[str, object],
    invalid: str,
) -> None:
    api, _, _, windows, _ = api_backends
    with api, pytest.raises(ValueError, match=invalid):
        api.attach(**arguments)  # type: ignore[arg-type]
    assert windows.calls == 0


def test_attach_and_window_discovery_are_pid_scoped_and_title_exact(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
) -> None:
    api, _, _, windows, _ = api_backends
    with api:
        application = api.attach(pid=PID)
        assert application.pid == PID
        assert application.window(title="Main").hwnd == HWND
        with pytest.raises(JavaWindowNotFoundError):
            application.window(title="main", timeout=0)

        windows.windows.append(SECOND_HWND)
        with pytest.raises(JavaWindowAmbiguousError):
            application.window(timeout=0)


def test_attach_by_title_is_globally_strict(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
) -> None:
    api, _, _, _, _ = api_backends
    with api, pytest.raises(JavaWindowAmbiguousError):
        api.attach(title="Main", timeout=0)


def test_window_hwnd_must_belong_to_the_application_pid(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
) -> None:
    api, _, _, _, _ = api_backends
    with api:
        application = api.attach(pid=PID)
        with pytest.raises(JavaWindowNotFoundError):
            application.window(hwnd=OTHER_HWND, timeout=0)


def test_launch_returns_immediately_and_never_terminates_the_process(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
) -> None:
    api, _, _, _, processes = api_backends
    environment = {"LANG": "ru_RU.UTF-8"}
    with api:
        application = api.launch(
            ["java", "-jar", "fixture.jar"], cwd=Path("fixture"), env=environment
        )
        assert application.pid == PID
    assert processes.launches == [
        (["java", "-jar", "fixture.jar"], Path("fixture"), environment)
    ]
    assert PID in processes.alive


def test_dead_process_is_reported_before_window_lookup(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
) -> None:
    api, _, _, windows, processes = api_backends
    with api:
        application = api.attach(pid=PID)
        processes.alive.remove(PID)
        before = windows.calls
        with pytest.raises(JavaProcessExitedError):
            application.window(timeout=0)
        assert windows.calls == before


@pytest.mark.parametrize("timeout", [-1, 1.5, True])
def test_constructor_validates_timeout_before_creating_native_backends(
    monkeypatch: pytest.MonkeyPatch,
    timeout: object,
) -> None:
    def unexpected(*_arguments: object) -> object:
        raise AssertionError("a backend was created before validation")

    monkeypatch.setattr(sync_api, "_create_runtime", unexpected)
    monkeypatch.setattr(sync_api, "_create_window_backend", unexpected)
    monkeypatch.setattr(sync_api, "_create_process_backend", unexpected)
    with pytest.raises(ValueError, match="timeout"):
        PlayJab(timeout=timeout)  # type: ignore[arg-type]


def test_window_selector_validation_precedes_window_enumeration(
    api_backends: tuple[
        PlayJab, BridgeRuntime, FakeBackend, FakeWindows, FakeProcesses
    ],
) -> None:
    api, _, _, windows, _ = api_backends
    with api:
        application = api.attach(pid=PID)
        for arguments in (
            {"hwnd": HWND, "title": "Main"},
            {"hwnd": 0},
            {"title": ""},
            {"timeout": -1},
        ):
            before = windows.calls
            with pytest.raises(ValueError):
                application.window(**arguments)  # type: ignore[arg-type]
            assert windows.calls == before
