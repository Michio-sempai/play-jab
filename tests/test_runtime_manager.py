"""Process-wide runtime leases and client-local lifecycle contracts."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab._native.manager import RuntimeManager, RuntimeSession
from play_jab.exceptions import (
    BridgeClosedError,
    BridgeInitializationError,
    LocatorTimeoutError,
)
from play_jab.sync_api import PlayJab

from .conftest import FakeWindowBackend

THREAD_JOIN_TIMEOUT = 2.0
BLOCKED_CHECK_WINDOW = 0.2

PID = 4242
HWND = 0xCAFE
GENERATION_COUNT = 2


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
    monkeypatch.setattr(
        sync_api,
        "_create_window_backend",
        lambda: FakeWindowBackend({HWND: "Fixture"}, pid=PID),
    )
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


def _make_runtime() -> BridgeRuntime:
    return BridgeRuntime(lambda: FakeBackend(_tree()), pump_interval=0.001)


class _BlockingWindowCheckBackend(FakeBackend):
    """A backend whose ``is_java_window`` blocks until the test releases it.

    Stands in for a slow native call that is still in flight while another
    thread tries to ``release()`` the same lease.
    """

    def __init__(
        self,
        windows: dict[int, FakeNode],
        *,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(windows)
        self._entered = entered
        self._release = release

    def is_java_window(self, hwnd: int) -> bool:
        self._entered.set()
        assert self._release.wait(timeout=THREAD_JOIN_TIMEOUT), (
            "test did not release the in-flight call"
        )
        return super().is_java_window(hwnd)


def test_second_acquire_waits_while_the_first_is_starting_and_shares_the_result() -> (
    None
):
    """Two concurrent first-time clients must not race two runtimes into being."""
    manager = RuntimeManager()
    entered_factory = threading.Event()
    release_factory = threading.Event()
    factory_calls: list[object] = []

    def factory(_dll_path: object, _timeout_ms: int) -> BridgeRuntime:
        factory_calls.append(object())
        entered_factory.set()
        assert release_factory.wait(timeout=THREAD_JOIN_TIMEOUT), (
            "test did not release the factory gate"
        )
        return _make_runtime()

    sessions: list[RuntimeSession] = []
    errors: list[BaseException] = []

    def acquire(target: list[RuntimeSession]) -> None:
        try:
            target.append(manager.acquire(None, 0, factory))
        except BaseException as error:
            errors.append(error)

    first_thread = threading.Thread(target=acquire, args=(sessions,), daemon=True)
    first_thread.start()
    assert entered_factory.wait(THREAD_JOIN_TIMEOUT), "first acquire never started"

    second_thread = threading.Thread(target=acquire, args=(sessions,), daemon=True)
    second_thread.start()
    # The second client must genuinely block on the condition, not race ahead.
    second_thread.join(BLOCKED_CHECK_WINDOW)
    assert second_thread.is_alive()

    release_factory.set()
    first_thread.join(THREAD_JOIN_TIMEOUT)
    second_thread.join(THREAD_JOIN_TIMEOUT)

    concurrent_clients = 2
    assert errors == []
    assert len(factory_calls) == 1, "the second client must not build its own runtime"
    assert len(sessions) == concurrent_clients
    assert sessions[0].generation == sessions[1].generation == 1

    for session in sessions:
        session.close()
    assert manager._state == "stopped"


def test_release_waits_for_an_in_flight_call_on_another_thread() -> None:
    manager = RuntimeManager()
    entered_call = threading.Event()
    release_call = threading.Event()

    def factory(_dll_path: object, _timeout_ms: int) -> BridgeRuntime:
        backend = _BlockingWindowCheckBackend(
            _tree(), entered=entered_call, release=release_call
        )
        return BridgeRuntime(lambda: backend, pump_interval=0.001)

    session = manager.acquire(None, 0, factory)
    call_finished = threading.Event()

    def slow_call() -> None:
        session.is_java_window(HWND)
        call_finished.set()

    call_thread = threading.Thread(target=slow_call, daemon=True)
    call_thread.start()
    assert entered_call.wait(THREAD_JOIN_TIMEOUT), "in-flight call never started"

    release_finished = threading.Event()

    def do_release() -> None:
        session.close()
        release_finished.set()

    release_thread = threading.Thread(target=do_release, daemon=True)
    release_thread.start()
    # release() must block on the in-flight call, not tear the runtime down under it.
    release_thread.join(BLOCKED_CHECK_WINDOW)
    assert not release_finished.is_set()

    release_call.set()
    call_thread.join(THREAD_JOIN_TIMEOUT)
    release_thread.join(THREAD_JOIN_TIMEOUT)

    assert call_finished.is_set()
    assert release_finished.is_set()
    assert manager._state == "stopped"


def test_a_failed_start_reverts_to_stopped_and_a_waiting_second_acquire_recovers() -> (
    None
):
    manager = RuntimeManager()
    entered_first = threading.Event()
    release_first = threading.Event()

    def failing_factory(_dll_path: object, _timeout_ms: int) -> BridgeRuntime:
        entered_first.set()
        assert release_first.wait(timeout=THREAD_JOIN_TIMEOUT), (
            "test did not release the failing factory"
        )
        raise RuntimeError("simulated bridge init failure")

    first_errors: list[BaseException] = []

    def acquire_first() -> None:
        try:
            manager.acquire(None, 0, failing_factory)
        except BaseException as error:
            first_errors.append(error)

    first_thread = threading.Thread(target=acquire_first, daemon=True)
    first_thread.start()
    assert entered_first.wait(THREAD_JOIN_TIMEOUT), "first acquire never started"

    second_sessions: list[RuntimeSession] = []

    def acquire_second() -> None:
        second_sessions.append(manager.acquire(None, 0, lambda *_a: _make_runtime()))

    second_thread = threading.Thread(target=acquire_second, daemon=True)
    second_thread.start()
    # The second client must wait behind the first's (doomed) "starting" attempt.
    second_thread.join(BLOCKED_CHECK_WINDOW)
    assert second_thread.is_alive()

    release_first.set()
    first_thread.join(THREAD_JOIN_TIMEOUT)
    second_thread.join(THREAD_JOIN_TIMEOUT)

    assert len(first_errors) == 1
    assert isinstance(first_errors[0], RuntimeError)

    assert len(second_sessions) == 1
    assert second_sessions[0].generation == 1
    assert manager._state == "running"

    second_sessions[0].close()
    assert manager._state == "stopped"


def test_a_closed_session_rejects_further_calls_and_close_is_idempotent() -> None:
    manager = RuntimeManager()
    session = manager.acquire(None, 0, lambda *_args: _make_runtime())

    session.close()
    session.close()  # idempotent: must not raise or release a second time

    with pytest.raises(BridgeClosedError):
        session.is_java_window(HWND)
    assert manager._state == "stopped"
