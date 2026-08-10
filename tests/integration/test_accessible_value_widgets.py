"""`JScrollBar` (exercised elsewhere via `fixture.table_scrollbar_vertical`) was
the only real-DLL-tested carrier of `AccessibleValue`. `JProgressBar` and
`JSlider` implement the same interface through their own default
`AccessibleContext`, added to the fixture in task C4 specifically to close
that gap (unit-tests-review.md finding B5 / the plan's Поток C4).

`JSpinner` was deliberately left out of the fixture - see
`SwingFixtureApp.buildValuePanel`'s javadoc for why its "spinbox" role would
have broken locator resolution for the *entire* suite, not just itself.
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
