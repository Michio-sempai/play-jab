"""Regression coverage for JAB dispatch around modal ``JDialog`` windows."""

from __future__ import annotations

import threading
import time

import pytest

from play_jab.sync_api import JavaApplication, JavaWindow, Locator, PlayJab

from .conftest import (
    DialogFixture,
    can_change_foreground_window,
    close_raw_window,
    wait_for_raw_window,
    wait_for_raw_window_closed,
)

pytestmark = pytest.mark.integration_jab

_TIMEOUT_MS = 5_000
_OWNER_TITLE = "JAB dialog repro"


def _assert_semantic_click_blocks_until_window_closes(
    locator: Locator,
    fixture: DialogFixture,
    title: str,
) -> None:
    """Confirm the synchronous modal contract without hanging pytest."""
    finished = threading.Event()
    errors: list[BaseException] = []

    def click() -> None:
        try:
            locator.click()
        except BaseException as error:  # preserve the worker-thread failure
            errors.append(error)
        finally:
            finished.set()

    thread = threading.Thread(target=click, daemon=True)
    thread.start()
    hwnd = wait_for_raw_window(fixture.process, title)
    assert not finished.wait(0.25), (
        "semantic click unexpectedly returned while the modal HWND existed"
    )
    close_raw_window(hwnd)
    wait_for_raw_window_closed(fixture.process.pid, title)
    assert finished.wait(_TIMEOUT_MS / 1_000), (
        "semantic click did not return after the modal HWND was closed"
    )
    if errors:
        raise errors[0]


def _application(api: PlayJab, fixture: DialogFixture) -> JavaApplication:
    application = api.attach(pid=fixture.process.pid)
    owner = application.window(title=_OWNER_TITLE)
    assert owner.get_by_name("repro.main").snapshot().role == "frame"
    assert api.live_ref_count == 0
    return application


def _require_foreground_capable(hwnd: int) -> None:
    """Skip synthetic-input tests when this session cannot own the foreground.

    Distinguishes an environment limitation (locked/non-interactive desktop, or
    another process holding the foreground lock) from a real regression in
    `opens_window=True`'s underlying `set_foreground_window` retry loop - see
    `can_change_foreground_window`'s docstring.
    """
    if not can_change_foreground_window(hwnd):
        pytest.skip(
            "this session cannot change the Windows foreground window; "
            "opens_window=True cannot be exercised here"
        )


def _assert_owner_recovered(
    api: PlayJab, application: JavaApplication, title: str
) -> None:
    wait_for_raw_window_closed(application.pid, title)
    owner = application.window(title=_OWNER_TITLE, timeout=_TIMEOUT_MS)
    assert owner.get_by_name("repro.main").snapshot().name == "repro.main"
    assert api.live_ref_count == 0


@pytest.mark.parametrize(
    ("button_name", "dialog_title"),
    [
        ("repro.open_modeless", "Scenario A"),
        ("repro.open_modal", "Scenario B"),
    ],
)
def test_semantic_click_blocks_for_a_and_b_then_jab_recovers(
    dialog_fixture: DialogFixture,
    button_name: str,
    dialog_title: str,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = _application(api, dialog_fixture)
        button = application.window(title=_OWNER_TITLE).get_by_name(button_name)
        assert button.is_visible() and button.is_enabled()

        _assert_semantic_click_blocks_until_window_closes(
            button,
            dialog_fixture,
            dialog_title,
        )
        _assert_owner_recovered(api, application, dialog_title)


def test_scenario_c_remains_accessible_and_closes_semantically(
    dialog_fixture: DialogFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = _application(api, dialog_fixture)
        owner = application.window(title=_OWNER_TITLE)
        owner.get_by_name("repro.open_invokeandwait").click()
        wait_for_raw_window(dialog_fixture.process, "Scenario C")

        dialog = application.window(title="Scenario C")
        assert dialog.get_by_name("repro.invokeandwait.dialog").snapshot()
        assert dialog.get_by_name("repro.invokeandwait.input").snapshot()
        assert owner.get_by_name("repro.main").snapshot()
        dialog.get_by_name("repro.invokeandwait.ok").click()
        _assert_owner_recovered(api, application, "Scenario C")


def test_modal_b_is_safe_with_window_expectation_and_physical_open_click(
    dialog_fixture: DialogFixture,
) -> None:
    _require_foreground_capable(dialog_fixture.hwnd)
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = _application(api, dialog_fixture)
        owner = application.window(title=_OWNER_TITLE)
        with application.expect_window(title="Scenario B") as pending:
            owner.get_by_name("repro.open_modal").click(opens_window=True)

        dialog = pending.value
        assert dialog.get_by_name("repro.modal.input").snapshot()
        assert owner.get_by_name("repro.main").snapshot()
        dialog.get_by_name("repro.modal.ok").click()
        _assert_owner_recovered(api, application, "Scenario B")


def _open_scenario_c(application: JavaApplication) -> tuple[JavaWindow, JavaWindow]:
    owner = application.window(title=_OWNER_TITLE)
    owner.get_by_name("repro.open_invokeandwait").click()
    return owner, application.window(title="Scenario C")


def test_nested_semantic_open_blocks_until_win32_close_then_recovers(
    dialog_fixture: DialogFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = _application(api, dialog_fixture)
        _, outer = _open_scenario_c(application)
        _assert_semantic_click_blocks_until_window_closes(
            outer.get_by_name("repro.invokeandwait.open_nested"),
            dialog_fixture,
            "Scenario Nested",
        )
        assert (
            application.window(title="Scenario C")
            .get_by_name("repro.invokeandwait.dialog")
            .snapshot()
        )
        assert api.live_ref_count == 0


def test_nested_physical_open_keeps_nested_outer_and_owner_accessible(
    dialog_fixture: DialogFixture,
) -> None:
    _require_foreground_capable(dialog_fixture.hwnd)
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = _application(api, dialog_fixture)
        owner, outer = _open_scenario_c(application)
        with application.expect_window(title="Scenario Nested") as pending:
            outer.get_by_name("repro.invokeandwait.open_nested").click(
                opens_window=True
            )

        nested = pending.value
        assert nested.get_by_name("repro.nested.input").snapshot()
        assert outer.get_by_name("repro.invokeandwait.dialog").snapshot()
        assert owner.get_by_name("repro.main").snapshot()
        nested.get_by_name("repro.nested.ok").click()
        wait_for_raw_window_closed(application.pid, "Scenario Nested")
        assert api.live_ref_count == 0


def test_dialog_first_is_a_diagnostic_not_a_causal_proof(
    dialog_first_fixture: DialogFixture,
) -> None:
    """Record dialog-first accessibility without treating it as evidence for A/B."""
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = api.attach(pid=dialog_first_fixture.process.pid)
        dialog = application.window(title="Scenario First")
        assert dialog.get_by_name("repro.first.dialog").snapshot()
        assert dialog.get_by_name("repro.first.input").snapshot()
        assert api.live_ref_count == 0

    close_raw_window(dialog_first_fixture.hwnd)
    deadline = time.monotonic() + _TIMEOUT_MS / 1_000
    while dialog_first_fixture.process.poll() is None:
        if time.monotonic() >= deadline:
            pytest.fail("dialog-first JVM did not exit after Win32 close")
        time.sleep(min(0.05, deadline - time.monotonic()))
