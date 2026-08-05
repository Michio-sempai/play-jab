"""Process-scoped raw-window expectations and their public result contract."""

from __future__ import annotations

import pytest

import play_jab
from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    JavaProcessExitedError,
    JavaWindowAmbiguousError,
    JavaWindowNotAccessibleError,
    JavaWindowNotFoundError,
)
from play_jab.sync_api import JavaApplication, PlayJab, WindowExpectation

PID = 4242
OWNER = 0x100
DIALOG = 0x200
OTHER_DIALOG = 0x300


class _Processes:
    def __init__(self) -> None:
        self.alive = True

    def is_alive(self, pid: int) -> bool:
        return pid == PID and self.alive


class _Windows:
    def __init__(self) -> None:
        self.visible = [OWNER]
        self.titles = {
            OWNER: "Owner",
            DIALOG: "Expected",
            OTHER_DIALOG: "Other",
        }

    def enum_windows(self) -> list[int]:
        return list(self.visible)

    def get_window_title(self, hwnd: int) -> str:
        return self.titles[hwnd]

    def get_window_pid(self, hwnd: int) -> int:
        return PID

    def set_foreground_window(self, hwnd: int) -> None:
        raise AssertionError("input is outside these tests")

    def get_cursor_position(self) -> tuple[int, int]:
        raise AssertionError("input is outside these tests")

    def set_cursor_position(self, x: int, y: int) -> None:
        raise AssertionError("input is outside these tests")

    def set_thread_dpi_awareness_context(self, context: int) -> int:
        raise AssertionError("input is outside these tests")

    def send_left_click(self) -> None:
        raise AssertionError("input is outside these tests")


def _application(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accessible: tuple[int, ...] = (OWNER, DIALOG, OTHER_DIALOG),
) -> tuple[PlayJab, JavaApplication, _Windows, _Processes]:
    nodes = {
        hwnd: FakeNode(
            name=f"window-{hwnd}",
            role_en_us="dialog",
            states_en_us="enabled,visible,showing",
        )
        for hwnd in accessible
    }
    runtime = BridgeRuntime(lambda: FakeBackend(nodes))
    windows = _Windows()
    processes = _Processes()
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", processes.is_alive)
    api = PlayJab(timeout=0)
    api.__enter__()
    return api, api.attach(pid=PID), windows, processes


def test_public_window_expectation_resolves_one_new_exact_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, application, windows, _ = _application(monkeypatch)
    try:
        pending = application.expect_window(title="Expected", timeout=0)
        with pytest.raises(RuntimeError, match="not completed"):
            _ = pending.value
        with pending:
            windows.visible.extend([OTHER_DIALOG, DIALOG])
        assert pending.value.hwnd == DIALOG
        assert pending.value.application is application
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_existing_matching_hwnd_is_not_mistaken_for_a_new_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, application, windows, _ = _application(monkeypatch)
    windows.visible.append(DIALOG)
    try:
        with (
            pytest.raises(JavaWindowNotFoundError),
            application.expect_window(title="Expected", timeout=0),
        ):
            pass
    finally:
        api.close()


def test_expect_window_reports_zero_multiple_and_inaccessible_raw_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, application, windows, _ = _application(monkeypatch, accessible=(OWNER,))
    try:
        with (
            pytest.raises(JavaWindowNotFoundError),
            application.expect_window(timeout=0),
        ):
            pass
        with (
            pytest.raises(JavaWindowAmbiguousError),
            application.expect_window(timeout=0),
        ):
            windows.visible.extend([DIALOG, OTHER_DIALOG])
        windows.visible[:] = [OWNER]
        with (
            pytest.raises(JavaWindowNotAccessibleError, match="did not become"),
            application.expect_window(title="Expected", timeout=0),
        ):
            windows.visible.append(DIALOG)
    finally:
        api.close()


def test_expect_window_reports_process_exit_and_preserves_body_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, application, windows, processes = _application(monkeypatch)
    try:
        with (
            pytest.raises(JavaProcessExitedError),
            application.expect_window(timeout=0),
        ):
            processes.alive = False

        processes.alive = True
        original = RuntimeError("body failed")
        with (
            pytest.raises(RuntimeError) as caught,
            application.expect_window(timeout=0),
        ):
            windows.visible.append(DIALOG)
            raise original
        assert caught.value is original
    finally:
        api.close()


def test_window_expectation_and_error_are_exported_from_package_root() -> None:
    assert play_jab.WindowExpectation is WindowExpectation
    assert play_jab.UnsupportedActionError is sync_api.UnsupportedActionError
