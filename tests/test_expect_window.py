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
SERVICE_FRAME = 0x400
USER_FRAME = 0x500

_TITLES = {
    OWNER: "Owner",
    DIALOG: "Expected",
    OTHER_DIALOG: "Other",
    SERVICE_FRAME: "",
    USER_FRAME: "Frame",
}

# A hidden shared-owner frame Swing may create alongside a modal JDialog: a
# real Java top-level HWND, but not the window the caller is waiting for.
SERVICE_FRAME_NODE = FakeNode(
    name="",
    role_en_us="frame",
    states_en_us="enabled,focusable,resizable",
    x=-1,
    y=-1,
    width=-1,
    height=-1,
)
DIALOG_NODE = FakeNode(
    name="Information",
    role_en_us="dialog",
    states_en_us="active,enabled,focusable,modal,showing,visible",
)
OTHER_DIALOG_NODE = FakeNode(
    name="Other",
    role_en_us="dialog",
    states_en_us="active,enabled,focusable,modal,showing,visible",
)
USER_FRAME_NODE = FakeNode(
    name="MainFrame",
    role_en_us="frame",
    states_en_us="enabled,focusable,resizable,showing,visible",
)


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
    nodes: dict[int, FakeNode] | None = None,
    make_backend: type[FakeBackend] = FakeBackend,
) -> tuple[PlayJab, JavaApplication, FakeWindowBackend, _Processes]:
    if nodes is None:
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
        dict(_TITLES),
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


def test_expect_window_waits_past_hidden_service_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared-owner service frame appearing before the real dialog must not
    be mistaken for the target window on the first raw HWND it sees -
    expect_window() keeps polling for a semantic match instead."""
    api, application, windows, _ = _application(
        monkeypatch,
        nodes={SERVICE_FRAME: SERVICE_FRAME_NODE, DIALOG: DIALOG_NODE},
    )
    try:
        original_enum = windows.enum_windows
        calls = {"count": 0}
        # 1st call: WindowExpectation.__enter__'s "before" snapshot.
        # 2nd call: the first poll, after the frame alone is visible.
        # 3rd call: the second poll, once the dialog has caught up.
        dialog_appears_on_call = 3

        def enum_with_delayed_dialog() -> list[int]:
            calls["count"] += 1
            if calls["count"] == dialog_appears_on_call:
                windows.visible.append(DIALOG)
            return original_enum()

        windows.enum_windows = enum_with_delayed_dialog  # type: ignore[method-assign]

        with application.expect_window(
            role="dialog", states={"modal", "showing"}, timeout=1_000
        ) as pending:
            windows.visible.append(SERVICE_FRAME)

        assert pending.value.hwnd == DIALOG
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_expect_window_filters_before_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two new raw Java HWNDs, only one of which is a semantic match, resolve
    to that one instead of raising ambiguity on raw HWND count."""
    api, application, windows, _ = _application(
        monkeypatch,
        nodes={SERVICE_FRAME: SERVICE_FRAME_NODE, DIALOG: DIALOG_NODE},
    )
    try:
        with application.expect_window(role="dialog", states="modal") as pending:
            windows.visible.extend([SERVICE_FRAME, DIALOG])
        assert pending.value.hwnd == DIALOG
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_expect_window_is_ambiguous_after_semantic_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two real, equally-matching dialogs are still ambiguous - the fix only
    removes false ambiguity, not genuine ambiguity."""
    api, application, windows, _ = _application(
        monkeypatch,
        nodes={DIALOG: DIALOG_NODE, OTHER_DIALOG: OTHER_DIALOG_NODE},
    )
    try:
        with (
            pytest.raises(JavaWindowAmbiguousError),
            application.expect_window(role="dialog", states="modal"),
        ):
            windows.visible.extend([DIALOG, OTHER_DIALOG])
    finally:
        api.close()


def test_expect_window_can_select_visible_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The semantic filter is not hardcoded to dialogs - a plain visible
    JFrame can be the awaited window too."""
    api, application, windows, _ = _application(
        monkeypatch,
        nodes={USER_FRAME: USER_FRAME_NODE},
    )
    try:
        with application.expect_window(role="frame", states="showing") as pending:
            windows.visible.append(USER_FRAME)
        assert pending.value.hwnd == USER_FRAME
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_expect_window_times_out_on_service_frame_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the hidden service frame ever appears - expect_window() must time
    out as not-found, never resolve to the service HWND and never raise
    ambiguous or inaccessible."""
    api, application, windows, _ = _application(
        monkeypatch,
        nodes={SERVICE_FRAME: SERVICE_FRAME_NODE},
    )
    try:
        with (
            pytest.raises(JavaWindowNotFoundError),
            application.expect_window(role="dialog", states="modal", timeout=0),
        ):
            windows.visible.append(SERVICE_FRAME)
    finally:
        api.close()


def test_window_expectation_and_error_are_exported_from_package_root() -> None:
    assert play_jab.WindowExpectation is WindowExpectation
    assert play_jab.UnsupportedActionError is UnsupportedActionError
