"""Two more C4 harness additions:

- `swing_fixture_windows_laf`: the fixture launched under the real Windows
  L&F instead of the cross-platform default - proves locator/accessible-name
  resolution does not depend on which L&F rendered the widgets.
- `swing_fixture_no_auto_node`: the fixture launched with
  `fixture.auto_node`'s attach/detach timer disabled entirely, for tests
  that want a `live_ref_count` unaffected by its own traffic.
"""

from __future__ import annotations

import time

import pytest

from play_jab.sync_api import PlayJab

from .conftest import SwingFixture

pytestmark = pytest.mark.integration_jab

_TIMEOUT_MS = 5_000
# fixture.auto_node's cycle is 3000ms; watching for longer than one full
# cycle is what makes "it never appears" a meaningful claim rather than a
# lucky snapshot.
_AUTO_NODE_WATCH_SECONDS = 3.5


def test_widgets_resolve_the_same_way_under_the_windows_look_and_feel(
    swing_fixture_windows_laf: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture_windows_laf.hwnd).window()
        remember = window.get_by_name("fixture.remember_checkbox")
        try:
            assert remember.snapshot().role == "check box"
            assert not remember.is_checked()
            remember.check()
            assert remember.is_checked()
            assert api.live_ref_count == 0
        finally:
            remember.uncheck()


def test_auto_node_never_appears_when_disabled(
    swing_fixture_no_auto_node: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture_no_auto_node.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        try:
            auto_node = window.get_by_name("fixture.auto_node")
            deadline = time.monotonic() + _AUTO_NODE_WATCH_SECONDS
            while time.monotonic() < deadline:
                assert auto_node.count() == 0
                time.sleep(0.2)
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)
