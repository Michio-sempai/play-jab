"""Two more C4 fixture additions exercised against the real DLL:

- `fixture.focus_status`: an explicit, deliberately non-declaration-order
  `FocusTraversalPolicy` (C -> A -> B) plus a label reporting which button
  currently owns focus - a way to prove which component is focused without
  relying on OS-level "active window" state.
- `fixture.synthetic_merged_cell`: a row-spanning ("merged") cell in
  `SyntheticAccessibleTable` (`getAccessibleRowExtentAt == 2`).
"""

from __future__ import annotations

import pytest

from play_jab.exceptions import NativeCallError
from play_jab.sync_api import PlayJab

from .conftest import SwingFixture, can_change_foreground_window

pytestmark = pytest.mark.integration_jab

_TIMEOUT_MS = 5_000
_SYNTHETIC_TABLE_ROWS = 3


def test_physically_clicking_each_focus_button_updates_the_focus_status_label(
    swing_fixture: SwingFixture,
) -> None:
    """A *semantic* `click()` invokes the button's `ActionListener` directly
    through JAB's `doAccessibleActions`, bypassing AWT's normal focus-transfer
    machinery entirely - confirmed empirically: it fires the action but never
    moves keyboard focus, leaving `fixture.focus_status` at "none". Only a
    real Win32 mouse click (`opens_window=True`) grants focus the way an
    actual user interaction would, so that is what this test needs.
    """
    if not can_change_foreground_window(swing_fixture.hwnd):
        pytest.skip(
            "this session cannot change the Windows foreground window; "
            "opens_window=True cannot be exercised here"
        )
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        status = window.get_by_name("fixture.focus_status")
        try:
            for button_name in (
                "fixture.focus_button_a",
                "fixture.focus_button_b",
                "fixture.focus_button_c",
            ):
                window.get_by_name(button_name).click(opens_window=True)
                assert status.snapshot().description == button_name
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_merged_cell_read_hits_the_same_real_dll_limitation_as_the_diagnostic_cell(
    swing_fixture: SwingFixture,
) -> None:
    """Debt marker, not a fixture defect.

    The hypothesis behind adding `AccessibleComponent`/bounds to this cell
    (unlike `fixture.synthetic_cell_0_0`, which deliberately has none) was
    that bounds were *why* `getAccessibleTableCellInfo` fails for a custom,
    non-`JTable`-derived `AccessibleTable` (see
    `test_form_table_locator_scenarios.py::
    test_synthetic_table_cell_has_no_bounds_or_action`). Confirmed
    empirically, that hypothesis is wrong: the merged cell has real bounds
    and still fails the identical native call. The real cause is broader -
    the JDK's `getAccessibleTableCellInfo` bridge implementation does not
    work for `AccessibleTable` implementations outside `AccessibleJTable` at
    all, regardless of bounds - which also means `getAccessibleRowExtentAt`
    can never be observed through this library's public API for a table like
    this one, since that information only reaches Python through the same
    failing call. Fixing this is out of this testing-only plan's scope. Basic
    table metadata (`row_count`/`column_count`, obtained through
    `getAccessibleTableInfo`, a different native call) is unaffected.
    """
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(1)
        try:
            table = window.get_by_name("fixture.synthetic_table").as_table()
            assert table.row_count() == _SYNTHETIC_TABLE_ROWS
            assert table.column_count() == 1
            with pytest.raises(NativeCallError) as caught:
                table.cell(1, 0).text_content()
            assert caught.value.function == "getAccessibleTableCellInfo"
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)
