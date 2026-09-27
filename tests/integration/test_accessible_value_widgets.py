"""`JScrollBar` (exercised elsewhere via `fixture.table_scrollbar_vertical`) was
the only real-DLL-tested carrier of `AccessibleValue`. `JProgressBar` and
`JSlider` implement the same interface through their own default
`AccessibleContext`, added to the fixture in task C4 specifically to close
that gap (unit-tests-review.md finding B5 / the plan's Поток C4).

`JSpinner` was deliberately left out of an earlier version of the fixture
because its "spinbox" role was not yet registered and would have broken locator
resolution for the *entire* suite, not just itself. Role "spinbox" is now
standard (`registry.py`), so `fixture.value_spinner` is back
(test-app-review.md finding K-1).
"""

from __future__ import annotations

import pytest

from play_jab.sync_api import PlayJab

from .conftest import SwingFixture

pytestmark = pytest.mark.integration_jab

_TIMEOUT_MS = 5_000


def test_progress_bar_and_slider_publish_accessible_value(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        try:
            progress = window.get_by_name("fixture.progress_bar").accessible_value()
            assert (progress.minimum, progress.current, progress.maximum) == (
                "0",
                "42",
                "100",
            )

            slider = window.get_by_name("fixture.slider").accessible_value()
            assert (slider.minimum, slider.current, slider.maximum) == (
                "0",
                "3",
                "10",
            )
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_spinner_is_reachable_with_the_now_standard_spinbox_role(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        try:
            spinner = window.get_by_name("fixture.value_spinner")
            assert spinner.snapshot().role == "spinbox"
            assert spinner.is_visible()
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_set_value_increments_and_decrements_a_real_slider(
    swing_fixture: SwingFixture,
) -> None:
    """Confirms against the real DLL that a batch of N "increment"/"decrement"
    AccessibleActions in one native call applies N steps, not one - the key
    empirical fact set_value()'s batching relies on (feature request:
    play-jab-feature-request-set-value.md)."""
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        try:
            slider = window.get_by_name("fixture.slider")
            assert slider.accessible_value().current == "3"

            slider.set_value(8)
            assert slider.accessible_value().current == "8"

            slider.set_value(1)
            assert slider.accessible_value().current == "1"

            slider.set_value(1)  # delta=0, must be a no-op
            assert slider.accessible_value().current == "1"

            with pytest.raises(ValueError, match=r"outside \[0, 10\]"):
                slider.set_value(11)
            assert api.live_ref_count == 0
        finally:
            slider.set_value(3)  # restore for any test that runs after this one
            tabs.select_option(0)


def test_set_value_works_the_same_way_on_a_real_spinner(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        try:
            spinner = window.get_by_name("fixture.value_spinner")
            assert spinner.accessible_value().current == "5"

            spinner.set_value(9)
            assert spinner.accessible_value().current == "9"
            assert api.live_ref_count == 0
        finally:
            spinner.set_value(5)
            tabs.select_option(0)
