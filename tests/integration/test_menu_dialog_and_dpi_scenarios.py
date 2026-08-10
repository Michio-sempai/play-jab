"""Integration coverage for the fixture scenes added in task C1: a real
`JMenuBar`/`JMenu`/`JMenuItem` menu (including `click(opens_window=True)`
launched from a menu item rather than a button), Swing's own `JOptionPane`
dialogs, and a fixture JVM scaled to 125% for the DPI-aware synthetic input
coordinate path.

Source: unit-tests-review.md findings A2-A4 and the plan's Поток B5.
"""

from __future__ import annotations

import time

import pytest

from play_jab.exceptions import LocatorError
from play_jab.sync_api import Locator, PlayJab

from .conftest import SwingFixture, can_change_foreground_window

pytestmark = pytest.mark.integration_jab

_TIMEOUT_MS = 5_000
# Overshoots the scrollbar's 0..1440 range so the exact per-notch increment
# does not matter: JScrollBar clamps to its max/min on its own.
_LARGE_SCROLL_STEPS = 200


def _wait_for_accessible_value(
    locator: Locator, expected: str, *, timeout_s: float = 5.0
) -> None:
    """`Locator.scroll()` only sends async Win32 wheel input and does not wait
    for the target to process it, so reading the value immediately afterwards
    races the Swing EDT - poll instead of asserting once."""
    deadline = time.monotonic() + timeout_s
    last = "<never read>"
    while time.monotonic() < deadline:
        last = locator.accessible_value().current
        if last == expected:
            return
        time.sleep(0.05)
    raise AssertionError(
        f"scrollbar value never reached {expected!r}; last observed {last!r}"
    )


def test_menu_item_runs_a_plain_action(swing_fixture: SwingFixture) -> None:
    """`fixture.menu_item_status` is a real child of `fixture.menu_file` at all
    times (a `JMenu` keeps its declared children in the tree even while
    closed), but lacks the "showing" state - and so is not clickable - until
    the dropdown is raised. Once raised, an *unscoped* `get_by_name` for the
    item resolves to two matches (JAB additionally exposes it through the
    freshly materialized popup layer, confirmed empirically against the real
    bridge), so every menu-item lookup below is scoped under the menu that
    was opened.
    """
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        menu_file = window.get_by_name("fixture.menu_file")
        item = menu_file.get_by_name("fixture.menu_item_status")
        with pytest.raises(LocatorError):
            item.click()

        menu_file.click()
        item.click()
        assert (
            window.get_by_name("fixture.status_label").snapshot().description
            == "menu action invoked"
        )
        assert api.live_ref_count == 0


def test_menu_item_opens_a_modal_dialog_via_physical_click(
    swing_fixture: SwingFixture,
) -> None:
    """`opens_window=True` launched from a menu item rather than a button -
    the dialog is a hand-rolled, application-modal `JDialog`
    (`fixture.menu_dialog`), so a *semantic* click here would block the
    native call for as long as the dialog stays open, exactly like
    `JabDialogRepro` Scenario B."""
    if not can_change_foreground_window(swing_fixture.hwnd):
        pytest.skip(
            "this session cannot change the Windows foreground window; "
            "opens_window=True cannot be exercised here"
        )
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = api.attach(hwnd=swing_fixture.hwnd)
        window = application.window()
        menu_file = window.get_by_name("fixture.menu_file")
        menu_file.click()

        with application.expect_window(title="Fixture Menu Dialog") as pending:
            menu_file.get_by_name("fixture.menu_item_open_dialog").click(
                opens_window=True
            )

        dialog = pending.value
        assert (
            dialog.get_by_name("fixture.menu_dialog_label").snapshot().name
            == "fixture.menu_dialog_label"
        )
        dialog.get_by_name("fixture.menu_dialog_close_button").click()
        assert window.get_by_name("fixture.main").snapshot().name == "fixture.main"
        assert api.live_ref_count == 0


def test_message_dialog_via_joptionpane(swing_fixture: SwingFixture) -> None:
    """The message dialog's own "OK" button is assembled by the current
    Look&Feel (BasicOptionPaneUI in English locale), not by the fixture -
    unlike everything else in this suite, its accessible name is not a
    fixture-chosen constant."""
    if not can_change_foreground_window(swing_fixture.hwnd):
        pytest.skip(
            "this session cannot change the Windows foreground window; "
            "opens_window=True cannot be exercised here"
        )
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = api.attach(hwnd=swing_fixture.hwnd)
        window = application.window()
        menu_dialogs = window.get_by_name("fixture.menu_dialogs")
        menu_dialogs.click()

        with application.expect_window(title="Fixture Message") as pending:
            menu_dialogs.get_by_name("fixture.menu_item_message_dialog").click(
                opens_window=True
            )

        dialog = pending.value
        dialog.get_by_name("OK").click()
        window.get_by_name("fixture.status_label").wait_for("attached")
        assert (
            window.get_by_name("fixture.status_label").snapshot().description
            == "message dialog closed"
        )
        assert api.live_ref_count == 0


def test_confirm_dialog_via_joptionpane_reports_the_chosen_option(
    swing_fixture: SwingFixture,
) -> None:
    """`showOptionDialog` was given explicit `{"Yes", "No"}` options, so - unlike
    the message dialog's "OK" - these two accessible names are deterministic
    regardless of Look&Feel."""
    if not can_change_foreground_window(swing_fixture.hwnd):
        pytest.skip(
            "this session cannot change the Windows foreground window; "
            "opens_window=True cannot be exercised here"
        )
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = api.attach(hwnd=swing_fixture.hwnd)
        window = application.window()
        menu_dialogs = window.get_by_name("fixture.menu_dialogs")
        menu_dialogs.click()

        with application.expect_window(title="Fixture Confirm") as pending:
            menu_dialogs.get_by_name("fixture.menu_item_confirm_dialog").click(
                opens_window=True
            )

        dialog = pending.value
        dialog.get_by_name("Yes").click()
        window.get_by_name("fixture.status_label").wait_for("attached")
        assert (
            window.get_by_name("fixture.status_label").snapshot().description
            == "confirm result=true"
        )
        assert api.live_ref_count == 0


def test_input_dialog_via_joptionpane_reports_the_entered_value(
    swing_fixture: SwingFixture,
) -> None:
    if not can_change_foreground_window(swing_fixture.hwnd):
        pytest.skip(
            "this session cannot change the Windows foreground window; "
            "opens_window=True cannot be exercised here"
        )
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        application = api.attach(hwnd=swing_fixture.hwnd)
        window = application.window()
        menu_dialogs = window.get_by_name("fixture.menu_dialogs")
        menu_dialogs.click()

        with application.expect_window(title="Fixture Input") as pending:
            menu_dialogs.get_by_name("fixture.menu_item_input_dialog").click(
                opens_window=True
            )

        dialog = pending.value
        dialog.get_by_name("OK").click()
        window.get_by_name("fixture.status_label").wait_for("attached")
        assert (
            window.get_by_name("fixture.status_label").snapshot().description
            == "input result="
        )
        assert api.live_ref_count == 0


def test_click_and_scroll_survive_125_percent_dpi_scaling(
    swing_fixture_dpi_125: SwingFixture,
) -> None:
    """`click(opens_window=True)`/`scroll()` send synthetic Win32 input at
    physical coordinates under `SetThreadDpiAwarenessContext(
    PER_MONITOR_AWARE_V2)` - previously implemented but never exercised
    against a JVM actually scaled away from 100% (unit-tests-review.md
    finding A4). A wrong click here would either silently hit nothing (empty
    bounds check catches that) or land on the wrong control - `remember`'s
    checked state and the table scrollbar's `AccessibleValue` are both
    directly observable proof the coordinates landed correctly.
    """
    if not can_change_foreground_window(swing_fixture_dpi_125.hwnd):
        pytest.skip(
            "this session cannot change the Windows foreground window; "
            "opens_window=True cannot be exercised here"
        )
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture_dpi_125.hwnd).window()
        remember = window.get_by_name("fixture.remember_checkbox")
        tabs = window.get_by_name("fixture.tabs")
        try:
            assert not remember.is_checked()
            remember.click(opens_window=True)
            assert remember.is_checked()

            tabs.select_option(1)
            scrollbar = window.get_by_name("fixture.table_scrollbar_vertical")
            minimum = scrollbar.accessible_value().minimum
            maximum = scrollbar.accessible_value().maximum
            scrollbar.scroll(_LARGE_SCROLL_STEPS)
            _wait_for_accessible_value(scrollbar, maximum)
            scrollbar.scroll(-_LARGE_SCROLL_STEPS)
            _wait_for_accessible_value(scrollbar, minimum)
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)
            if remember.is_checked():
                remember.click(opens_window=True)
