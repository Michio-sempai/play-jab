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
    UnsupportedActionError,
)
from play_jab.sync_api import JavaApplication, PlayJab, WindowExpectation

from .conftest import FakeWindowBackend

PID = 4242
OWNER = 0x100
DIALOG = 0x200
OTHER_DIALOG = 0x300


class _Processes:
    def __init__(self) -> None:
        self.alive = True

    def is_alive(self, pid: int) -> bool:
        return pid == PID and self.alive


class _InaccessibleContextBackend(FakeBackend):
    """A window that reports as Java (``is_java_window``) but whose accessible
    context can never be fetched - the race ``expect_window`` must still
    distinguish from "not a Java window at all"."""

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        return None


def _application(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accessible: tuple[int, ...] = (OWNER, DIALOG, OTHER_DIALOG),
    make_backend: type[FakeBackend] = FakeBackend,
) -> tuple[PlayJab, JavaApplication, FakeWindowBackend, _Processes]:
    nodes = {
        hwnd: FakeNode(
            name=f"window-{hwnd}",
            role_en_us="dialog",
            states_en_us="enabled,visible,showing",
        )
        for hwnd in accessible
    }
    runtime = BridgeRuntime(lambda: make_backend(nodes))
    windows = FakeWindowBackend(
        {OWNER: "Owner", DIALOG: "Expected", OTHER_DIALOG: "Other"},
        pid=PID,
        visible=[OWNER],
        guard_input=True,
    )
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


def test_expect_window_reports_zero_raw_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, application, _windows, _ = _application(monkeypatch)
    try:
        with (
            pytest.raises(JavaWindowNotFoundError),
            application.expect_window(timeout=0),
        ):
            pass
    finally:
        api.close()


def test_expect_window_ignores_non_java_hwnds_and_resolves_the_single_java_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second, non-Java HWND created by the same action must not be mistaken
    for ambiguity - only Java-accessible HWNDs are candidates."""
    api, application, windows, _ = _application(monkeypatch, accessible=(OWNER, DIALOG))
    try:
        with application.expect_window(timeout=0) as pending:
            windows.visible.extend([DIALOG, OTHER_DIALOG])
        assert pending.value.hwnd == DIALOG
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_expect_window_reports_not_found_for_only_non_java_raw_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-Java HWNDs never surface as candidates, so with none of the new raw
    windows being Java-accessible the expectation times out as not-found, not
    ambiguous or inaccessible - this is the exact bug scenario."""
    api, application, windows, _ = _application(monkeypatch, accessible=(OWNER,))
    try:
        with (
            pytest.raises(JavaWindowNotFoundError),
            application.expect_window(timeout=0),
        ):
            windows.visible.extend([DIALOG, OTHER_DIALOG])
    finally:
        api.close()


def test_expect_window_still_raises_ambiguous_for_two_java_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, application, windows, _ = _application(monkeypatch)
    try:
        with (
            pytest.raises(JavaWindowAmbiguousError),
            application.expect_window(timeout=0),
        ):
            windows.visible.extend([DIALOG, OTHER_DIALOG])
    finally:
        api.close()


def test_expect_window_reports_inaccessible_raw_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, application, windows, _ = _application(
        monkeypatch,
        accessible=(OWNER, DIALOG),
        make_backend=_InaccessibleContextBackend,
    )
    try:
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
    assert play_jab.UnsupportedActionError is UnsupportedActionError
