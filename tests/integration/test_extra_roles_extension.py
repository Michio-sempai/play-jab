"""Positive and negative coverage for `PlayJab(extra_roles=...)` against a real
unrecognized accessible role, and a real reproduction of the defect that made
`SwingFixtureApp` drop `JSpinner` in an earlier version of the fixture:

An unrecognized role anywhere in a scanned subtree aborts the *entire* traversal
with `UnsupportedAccessibleRoleError`, not just resolution of the unrecognized
node - because `JTabbedPane` keeps every tab's content in the accessible tree
regardless of which tab is selected. `extra_roles` had zero integration coverage
before this file (test-app-review.md finding K-1); it otherwise only appears in
`tests/test_accessibility_registry.py` against `FakeBackend`.

Uses the opt-in `swing_fixture_custom_role` fixture (`-Dfixture.customRole=true`)
rather than the shared session-scoped `swing_fixture`, since the whole point of
the node under test is that it breaks default `PlayJab()` traversal for every
other locator too.
"""

from __future__ import annotations

import pytest

from play_jab.exceptions import UnsupportedAccessibleRoleError
from play_jab.sync_api import PlayJab

from .conftest import SwingFixture

pytestmark = pytest.mark.integration_jab

_TIMEOUT_MS = 5_000


def test_unrecognized_role_anywhere_in_scope_aborts_the_whole_scan(
    swing_fixture_custom_role: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture_custom_role.hwnd).window()
        # An ordinary sibling button, not the unrecognized-role node itself -
        # proves the *presence* of the node breaks an unrelated lookup, matching
        # what buildValuePanel's original JSpinner comment described. `count()`
        # rather than `exists()`: a match-limited scan can find this unique
        # button and stop (Verdict.STOP) before ever visiting its sibling with
        # the bad role, silently missing the defect this test exists to catch;
        # `count()` never sets a match limit, so it cannot skip that sibling.
        with pytest.raises(UnsupportedAccessibleRoleError):
            window.get_by_name("fixture.custom_role_control_button").count()
        assert api.live_ref_count == 0


def test_extra_roles_registers_the_custom_role_for_reads(
    swing_fixture_custom_role: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS, extra_roles=("fixture custom role",)) as api:
        window = api.attach(hwnd=swing_fixture_custom_role.hwnd).window()

        widget = window.get_by_name("fixture.custom_role_widget")
        assert widget.snapshot().role == "fixture custom role"

        # The scan is no longer aborted, so an unrelated sibling resolves too.
        control = window.get_by_name("fixture.custom_role_control_button")
        assert control.is_visible()
        assert api.live_ref_count == 0
