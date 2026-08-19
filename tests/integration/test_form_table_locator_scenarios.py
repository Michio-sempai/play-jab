"""Fixture scenarios `test_forms_and_table_api_round_trip_through_real_jab` never
touches: table selection modes, the synthetic non-actionable cell, scrollbar
materialization, the Dynamics tab, hidden/disabled action-path rejection, and
combo/list/submit end to end.

Source: integration-tests-review.md section 3 ("СВОДКА: предоставлено фикстурой,
но не покрыто ни одним интеграционным тестом") and its recommendation 5-10 - the
fixture already implements every one of these; only the Python side was missing.
"""

from __future__ import annotations

import time

import pytest

from play_jab.exceptions import (
    LocatorError,
    NativeCallError,
    UnsupportedActionError,
)
from play_jab.sync_api import Locator, PlayJab

from .conftest import SwingFixture, can_change_foreground_window

pytestmark = pytest.mark.integration_jab

_TIMEOUT_MS = 5_000
_TABLE_ROWS = 100
_MUTABLE_ROW = 7
_STATUS_COLUMN = 3
_TABLE_COLUMNS = 5
_FEW_SELECTED_ROWS = (1, 3, 5)
# Overshoots the scrollbar's documented 0..1440 range so the exact per-notch
# increment does not matter: JScrollBar clamps to its max on its own.
_LARGE_SCROLL_STEPS = 200


def test_select_row_button_selects_one_row_and_every_column(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        table = window.get_by_name("fixture.table").as_table()
        try:
            window.get_by_name("fixture.select_row_button").click()
            assert table.selected_rows() == (_MUTABLE_ROW,)
            assert table.selected_columns() == tuple(range(_TABLE_COLUMNS))
            assert api.live_ref_count == 0
        finally:
            window.get_by_name("fixture.clear_selection_button").click()
            tabs.select_option(0)


def test_select_column_button_exceeds_the_row_selection_limit(
    swing_fixture: SwingFixture,
) -> None:
    """100 selected rows exceed MAX_TABLE_SELECTIONS=64; reading them must fail
    loudly rather than truncate silently - the same contract
    test_selection_overflow_reports_the_native_count_without_leaking proves
    against the fake backend, now against the real DLL."""
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        table = window.get_by_name("fixture.table").as_table()
        try:
            window.get_by_name("fixture.select_column_button").click()
            assert table.selected_columns() == (_STATUS_COLUMN,)
            with pytest.raises(NativeCallError) as caught:
                table.selected_rows()
            assert caught.value.function == "getAccessibleTableRowSelections"
            assert caught.value.arguments["native_count"] == _TABLE_ROWS
        finally:
            window.get_by_name("fixture.clear_selection_button").click()
            tabs.select_option(0)


def test_select_few_button_selects_exactly_three_rows_and_no_columns(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        table = window.get_by_name("fixture.table").as_table()
        try:
            window.get_by_name("fixture.select_few_button").click()
            assert table.selected_rows() == _FEW_SELECTED_ROWS
            assert table.selected_columns() == ()
            assert api.live_ref_count == 0
        finally:
            window.get_by_name("fixture.clear_selection_button").click()
            tabs.select_option(0)


def test_clear_selection_button_empties_selection_without_changing_mode(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        table = window.get_by_name("fixture.table").as_table()
        try:
            window.get_by_name("fixture.select_row_button").click()
            window.get_by_name("fixture.clear_selection_button").click()
            assert table.selected_rows() == ()
            assert table.selected_columns() == ()
        finally:
            tabs.select_option(0)


def test_synthetic_table_cell_has_no_bounds_or_action(
    swing_fixture: SwingFixture,
) -> None:
    """Debt marker for unit-tests-review.md finding A1, empirically corrected.

    The diagnostic cell is a synthetic `Accessible` reachable only through
    `AccessibleTable.getAccessibleAt`, never as a real child component - the
    ordinary accessible tree `get_by_name` walks never sees it. The original
    hypothesis was that reading it through `TableLocator.cell()` would
    succeed and only *acting* on it (there is no `TableCellLocator.click()`)
    would fail. Verified against the real DLL, the read itself fails first:
    the JDK's `getAccessibleTableCellInfo` bridge implementation cannot
    materialize cell info for an `Accessible` with no `AccessibleComponent`
    (no bounds), so `table.cell(0, 0)` raises `NativeCallError` before the
    "no bounds or action" distinction is ever reached. Fixing that would mean
    changing how the fixture's cell exposes itself to JAB (or the library's
    handling of a failed cell-info call) - both out of this plan's scope, so
    this test documents the current, real failure mode instead of an assumed
    one.
    """
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        try:
            assert window.get_by_name("fixture.synthetic_cell_0_0").count() == 0
            table = window.get_by_name("fixture.synthetic_table").as_table()
            with pytest.raises(NativeCallError) as caught:
                table.cell(0, 0).text_content()
            assert caught.value.function == "getAccessibleTableCellInfo"
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_synthetic_table_row_header_is_unreachable_through_real_jab(
    swing_fixture: SwingFixture,
) -> None:
    """Debt marker for unit-tests-review.md finding A1, empirically corrected.

    `SyntheticAccessibleTable.getAccessibleRowHeader()` returns a nested 1x1
    `AccessibleTable` (`RowHeaderTable`) so `Table.row_header()` has a
    positive Java-side target to read. In-process JUnit coverage
    (`SwingFixtureContractTest`) exercises the Java object graph directly and
    passes. Through the real JAB bridge it does not: `RowHeaderTable` is a
    bare `AccessibleTable`, not an `Accessible`/`AccessibleContext` in its
    own right, and the bridge cannot hand back context/table handles for it -
    exactly the path `sync_api.py` already converts to
    `UnsupportedActionError`. This documents that real, already-handled
    failure rather than a successful read.
    """
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        try:
            table = window.get_by_name("fixture.synthetic_table").as_table()
            with pytest.raises(UnsupportedActionError, match="table header"):
                table.row_header(0).text_content()
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_column_and_row_header_are_unreachable_on_a_standard_swing_table_too(
    swing_fixture: SwingFixture,
) -> None:
    """test-app-review.md finding K-2 assumed `column_header()` works through
    the real bridge because `AccessibleJTable.getAccessibleColumnHeader()`
    works in-process
    (`SwingFixtureContractTest.realisticTableDimensionsMutationAndSelectionAreStable`)
    - untested against real JAB until this test, which found it does **not**:
    same root cause as `row_header()` on the synthetic table above.
    `JTable.AccessibleJTable`'s private `AccessibleTableHeader` (backing both
    `getAccessibleColumnHeader()` and the row-header path) is a bare
    `AccessibleTable`, not an `Accessible`/`AccessibleContext` in its own
    right, so the bridge cannot hand back a context/table handle for it -
    a JDK/Swing-level limitation, not a synthetic-fixture artifact. Verified on
    the real `fixture.table` (not `fixture.synthetic_table`), with the Table
    tab actively selected, ruling out tab-visibility as the cause.
    """
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        try:
            table = window.get_by_name("fixture.table").as_table()
            with pytest.raises(UnsupportedActionError, match="table header"):
                table.column_header(0).text_content()
            with pytest.raises(UnsupportedActionError, match="table header"):
                table.row_header(0).text_content()
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_table_row_count_status_reflects_table_model_add_and_remove(
    swing_fixture: SwingFixture,
) -> None:
    """`fixture.table_row_count_status` publishes `"rows=<N>"` from a real
    `TableModelListener` (`SwingFixtureApp.java:930-932`), the only fixture
    signal proven to be driven by a genuine model event rather than
    polling-friendly coincidence - never exercised until now
    (test-app-review.md finding, Приоритет 2 п.6).
    """
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        try:
            status = window.get_by_name("fixture.table_row_count_status")
            assert status.snapshot().description == f"rows={_TABLE_ROWS}"
            window.get_by_name("fixture.table_add_row_button").click()
            assert status.snapshot().description == f"rows={_TABLE_ROWS + 1}"
            window.get_by_name("fixture.table_remove_row_button").click()
            assert status.snapshot().description == f"rows={_TABLE_ROWS}"
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def _wait_for_accessible_value(
    locator: Locator, expected: str, *, timeout_s: float = 5.0
) -> None:
    """`Locator.scroll()` only sends async Win32 wheel input; it does not wait
    for the target to process it (unlike `fill`/`check`/`select_option`,
    which do have a built-in postcondition wait). Reading the value
    immediately afterwards races the Swing EDT - usually winning under light
    load, but not guaranteed, so this polls instead of asserting once."""
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


def test_scroll_moves_the_table_scrollbars_accessible_value_to_its_maximum(
    swing_fixture: SwingFixture,
) -> None:
    """`TableCellLocator` addresses cells purely through the AccessibleTable
    interface and exposes no per-cell states, so "did scrolling actually move
    the viewport" is only observable through the scrollbar's own
    AccessibleValue - this closes the previously-untested
    `Locator.accessible_value()` path against the real DLL.

    `Locator.scroll()` calls `set_foreground_window` internally (it must move
    real synthetic wheel input over the target), so it is subject to the same
    Windows foreground-lock environment limitation as `click(opens_window=True)`
    in `test_modal_dialogs.py` - see `can_change_foreground_window`'s docstring.
    """
    if not can_change_foreground_window(swing_fixture.hwnd):
        pytest.skip(
            "this session cannot change the Windows foreground window; "
            "scroll() cannot be exercised here"
        )
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        scrollbar = window.get_by_name("fixture.table_scrollbar_vertical")
        try:
            value = scrollbar.accessible_value()
            assert (value.minimum, value.maximum) == ("0", "1440")

            scrollbar.scroll(_LARGE_SCROLL_STEPS)
            _wait_for_accessible_value(scrollbar, value.maximum)

            scrollbar.scroll(-_LARGE_SCROLL_STEPS)
            _wait_for_accessible_value(scrollbar, value.minimum)
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_dynamic_tab_add_and_remove_never_reuse_item_numbers(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(2)
        count_label = window.get_by_name("fixture.dynamic_count_label")
        add_button = window.get_by_name("fixture.add_item_button")
        remove_button = window.get_by_name("fixture.remove_item_button")
        try:
            assert count_label.snapshot().description == "items: 0"

            add_button.click()
            first_item = window.get_by_name("fixture.dynamic_item_1")
            first_item.wait_for("attached")
            add_button.click()
            second_item = window.get_by_name("fixture.dynamic_item_2")
            second_item.wait_for("attached")
            assert count_label.snapshot().description == "items: 2"

            remove_button.click()
            second_item.wait_for("detached")
            assert count_label.snapshot().description == "items: 1"

            # Re-adding gets item 3, not a reused item 2 - the removed number
            # stays permanently retired for this process's lifetime.
            add_button.click()
            window.get_by_name("fixture.dynamic_item_3").wait_for("attached")
            assert window.get_by_name("fixture.dynamic_item_2").count() == 0
            assert api.live_ref_count == 0
        finally:
            while count_label.snapshot().description != "items: 0":
                remove_button.click()
            tabs.select_option(0)


def test_hidden_and_disabled_buttons_are_readable_but_reject_actions(
    swing_fixture: SwingFixture,
) -> None:
    """CONCEPT.MD's model: the read-path resolves hidden/disabled nodes; the
    action-path refuses to act on them."""
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        try:
            hidden = window.get_by_name("fixture.hidden_button")
            assert hidden.snapshot().description == "hidden but attached"
            assert not hidden.is_visible()
            with pytest.raises(LocatorError):
                hidden.click()

            disabled = window.get_by_name("fixture.locator_disabled_button")
            assert disabled.snapshot().description == "visible but disabled"
            assert not disabled.is_enabled()
            with pytest.raises(LocatorError):
                disabled.click()
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_list_select_option_by_name_and_by_index(swing_fixture: SwingFixture) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        environment_list = window.get_by_name("fixture.environment_list")
        try:
            environment_list.select_option("staging")
            assert window.get_by_name("staging").is_selected()
            environment_list.select_option(2)
            assert window.get_by_name("prod").is_selected()
            assert api.live_ref_count == 0
        finally:
            environment_list.select_option(0)


def test_combo_box_select_option_reaches_items_behind_the_popup(
    swing_fixture: SwingFixture,
) -> None:
    """JComboBox options live inside its popup's nested JList in JAB."""
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        combo = window.get_by_name("fixture.role_combo")
        try:
            combo.select_option("Editor")
            assert window.get_by_name("Editor").is_selected()
            combo.select_option(2)
            assert window.get_by_name("Admin").is_selected()
            assert api.live_ref_count == 0
        finally:
            combo.select_option(0)


def test_submit_button_reports_the_filled_form_via_status_label(
    swing_fixture: SwingFixture,
) -> None:
    """End-to-end form flow, including a nested JComboBox option."""
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        username = window.get_by_name("fixture.username_field")
        role = window.get_by_name("fixture.role_combo")
        environment_list = window.get_by_name("fixture.environment_list")
        remember = window.get_by_name("fixture.remember_checkbox")
        status = window.get_by_name("fixture.status_label")
        try:
            username.fill("qa-bot")
            role.select_option("Editor")
            environment_list.select_option("prod")
            if not remember.is_checked():
                remember.check()

            window.get_by_name("fixture.submit_button").click()

            description = status.snapshot().description
            assert "user=qa-bot" in description
            assert "role=Editor" in description
            assert "env=prod" in description
            assert "remember=true" in description
            assert api.live_ref_count == 0
        finally:
            username.clear()
            role.select_option(0)
            environment_list.select_option(0)
            if remember.is_checked():
                remember.uncheck()
