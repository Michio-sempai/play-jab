"""Read-only locator semantics against the real runtime and fake JAB tree."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest

from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    LocatorError,
    LocatorTimeoutError,
    StrictModeViolation,
    UnsupportedActionError,
)
from play_jab.sync_api import JavaWindow, PlayJab, contains

from .conftest import FakeWindowBackend, install_fake_runtime

PID = 4242
HWND = 0xCAFE
SECRET = "hunter2-secret"
DUPLICATE_COUNT = 2
BUTTON_COUNT = 3
FIRST_EXISTS_ACQUISITIONS = 3
SCAN_THEN_ACTION_ROOT_COUNT = 2
FIRST_SNAPSHOT_ACQUISITIONS = 3
SECOND_SNAPSHOT_ACQUISITIONS = 6
HEAVY_SIBLING_LEVELS = 50
BOUNDED_ACQUISITIONS_WITH_MAX_DEPTH = 3


def _tree() -> FakeNode:
    return FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us="enabled,visible,showing",
        children=[
            FakeNode(
                name="Left",
                role_en_us="panel",
                states_en_us="enabled,visible,showing",
                children=[
                    FakeNode(
                        name="Duplicate",
                        description="Левая кнопка",
                        role_en_us="push button",
                        states_en_us="enabled,visible,showing",
                        x=10,
                        y=20,
                        width=30,
                        height=40,
                        accessible_action=True,
                        actions=("ClIcK", "toggle"),
                    ),
                    FakeNode(
                        name="Disabled",
                        role_en_us="push button",
                        states_en_us="visible,showing",
                    ),
                ],
            ),
            FakeNode(
                name="Right",
                role_en_us="panel",
                states_en_us="enabled,visible,showing",
                children=[
                    FakeNode(
                        name="Duplicate",
                        description="Right button",
                        role_en_us="push button",
                        states_en_us="enabled",
                    ),
                    FakeNode(
                        name=SECRET,
                        description=SECRET,
                        role_en_us="password text",
                        states_en_us="enabled,visible,showing",
                    ),
                ],
            ),
            FakeNode(
                name="Hidden parent",
                role_en_us="panel",
                states_en_us="enabled,visible",
                children=[
                    FakeNode(
                        name="Inconsistent showing child",
                        role_en_us="label",
                        states_en_us="enabled,visible,showing",
                    )
                ],
            ),
        ],
    )


@pytest.fixture
def locator_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend]]:
    backend = FakeBackend({HWND: _tree()})
    runtime = install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    api = PlayJab(timeout=0)
    api.__enter__()
    window = api.attach(pid=PID).window()
    yield api, window, runtime, backend
    api.close()


def test_exact_regex_and_explicit_substring_matchers(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    assert window.get_by_name("Duplicate").count() == DUPLICATE_COUNT
    assert window.get_by_name("Duplic").count() == 0
    assert window.get_by_name(contains("plic")).count() == DUPLICATE_COUNT
    assert window.get_by_name(re.compile(r"^Dup.*te$")).count() == DUPLICATE_COUNT


def test_role_state_visibility_and_index_filters_compose(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    assert window.locator(role="push button").count() == BUTTON_COUNT
    assert (
        window.locator(role="push button", states=("enabled",)).count()
        == DUPLICATE_COUNT
    )
    assert (
        window.locator(role="push button", visible_only=True).count() == DUPLICATE_COUNT
    )
    assert window.locator(role="push button", index_in_parent=1).count() == 1


def test_max_depth_bounds_which_descendants_are_considered(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    assert window.locator(role="push button", max_depth=1).count() == 0
    assert window.locator(role="push button", max_depth=2).count() == BUTTON_COUNT
    assert window.locator(role="frame", max_depth=0).count() == 1
    assert window.locator(role="push button", max_depth=0).count() == 0


def test_max_depth_is_relative_to_a_chained_locators_own_parent(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    left = window.get_by_role("panel", name="Left")
    assert left.get_by_name("Duplicate", max_depth=1).count() == 1


def test_max_depth_is_validated_before_traversal(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, backend = locator_api
    acquired = backend.acquired
    with pytest.raises(ValueError, match="max_depth must be a non-negative integer"):
        window.locator(max_depth=-1)
    with pytest.raises(ValueError, match="max_depth must be a non-negative integer"):
        window.locator(max_depth=True)
    assert backend.acquired == acquired


def test_showing_only_prunes_non_showing_subtrees_without_changing_visible_only(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    name = "Inconsistent showing child"
    assert window.get_by_name(name).count() == 1
    assert window.locator(name=name, visible_only=True).count() == 1
    assert window.locator(name=name, showing_only=True).count() == 0


def test_window_snapshot_reads_only_the_root_context(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    acquired = backend.acquired
    snapshot = window.snapshot()
    assert (snapshot.name, snapshot.role) == ("Fixture", "frame")
    assert backend.acquired - acquired == 1
    assert runtime.live_ref_count == 0
    assert backend.live_cookies == frozenset()


def test_exists_is_non_strict_and_stops_at_the_first_match(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    acquired = backend.acquired
    assert window.get_by_name("Duplicate").exists()
    assert backend.acquired - acquired == FIRST_EXISTS_ACQUISITIONS
    assert not window.get_by_name("Missing").exists()
    assert runtime.live_ref_count == 0
    assert backend.live_cookies == frozenset()


def test_first_and_nth_stop_after_the_requested_match(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, backend = locator_api
    duplicates = window.get_by_name("Duplicate")
    acquired = backend.acquired
    assert duplicates.first().snapshot().description == "Левая кнопка"
    assert backend.acquired - acquired == FIRST_SNAPSHOT_ACQUISITIONS
    acquired = backend.acquired
    assert duplicates.nth(1).snapshot().description == "Right button"
    assert backend.acquired - acquired == SECOND_SNAPSHOT_ACQUISITIONS


def test_nested_locator_resolves_parent_strictly_and_only_searches_descendants(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    left = window.get_by_role("panel", name="Left")
    assert left.get_by_name("Duplicate").count() == 1
    with pytest.raises(StrictModeViolation):
        window.get_by_role("panel").get_by_name("Duplicate").count()


def test_positional_parent_stays_part_of_a_nested_locator_chain(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    button = window.get_by_role("panel").first().get_by_name("Disabled")
    assert button.count() == 1


def test_positional_locators_are_lazy_and_keep_depth_first_child_order(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    duplicates = window.get_by_name("Duplicate")
    lazy = duplicates.all()
    assert len(lazy) == DUPLICATE_COUNT
    assert [item.snapshot().description for item in lazy] == [
        "Левая кнопка",
        "Right button",
    ]
    assert duplicates.first().snapshot().description == "Левая кнопка"
    assert duplicates.last().snapshot().description == "Right button"
    assert duplicates.nth(1).snapshot().description == "Right button"


def test_all_snapshots_matches_all_plus_individual_snapshots(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    duplicates = window.get_by_name("Duplicate")
    assert [snapshot.description for snapshot in duplicates.all_snapshots()] == [
        item.snapshot().description for item in duplicates.all()
    ]


def test_all_snapshots_costs_one_traversal_not_one_per_match(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    duplicates = window.get_by_name("Duplicate")

    acquired = backend.acquired
    count = duplicates.count()
    count_acquisitions = backend.acquired - acquired

    acquired = backend.acquired
    snapshots = duplicates.all_snapshots()
    all_snapshots_acquisitions = backend.acquired - acquired

    assert len(snapshots) == count == DUPLICATE_COUNT
    # A single traversal, matching count()'s cost regardless of how many
    # matches it finds - unlike all() + reading each .snapshot(), whose cost
    # grows with every additional match (see FIRST_/SECOND_SNAPSHOT_ACQUISITIONS
    # above: the second independent re-resolve already costs twice the first).
    assert all_snapshots_acquisitions == count_acquisitions
    assert runtime.live_ref_count == 0
    assert backend.live_cookies == frozenset()
    assert backend.acquired == backend.released


def test_all_text_contents_costs_one_traversal_not_one_per_match(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    duplicates = window.get_by_name("Duplicate")

    acquired = backend.acquired
    count = duplicates.count()
    count_acquisitions = backend.acquired - acquired

    acquired = backend.acquired
    contents = duplicates.all_text_contents()
    all_text_contents_acquisitions = backend.acquired - acquired

    assert len(contents) == count == DUPLICATE_COUNT
    # Same shape as test_all_snapshots_costs_one_traversal_not_one_per_match:
    # a single traversal regardless of match count, unlike all() followed by
    # .text_content() on each result (one full chain re-resolve per match).
    assert all_text_contents_acquisitions == count_acquisitions
    assert runtime.live_ref_count == 0
    assert backend.live_cookies == frozenset()
    assert backend.acquired == backend.released


def test_all_snapshots_with_text_matches_the_two_separate_calls_zipped(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    duplicates = window.get_by_name("Duplicate")
    assert duplicates.all_snapshots_with_text() == list(
        zip(duplicates.all_snapshots(), duplicates.all_text_contents(), strict=True)
    )


def test_all_snapshots_with_text_costs_one_traversal_not_two(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    duplicates = window.get_by_name("Duplicate")

    acquired = backend.acquired
    count = duplicates.count()
    count_acquisitions = backend.acquired - acquired

    acquired = backend.acquired
    combined = duplicates.all_snapshots_with_text()
    combined_acquisitions = backend.acquired - acquired

    assert len(combined) == count == DUPLICATE_COUNT
    # One traversal for both pieces of data, not one for snapshots plus a
    # second, independent one for text (which all_snapshots() then
    # all_text_contents() back to back would cost).
    assert combined_acquisitions == count_acquisitions
    assert runtime.live_ref_count == 0
    assert backend.live_cookies == frozenset()
    assert backend.acquired == backend.released


def test_all_text_contents_prefers_accessible_text_then_description_then_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us="enabled,visible,showing",
        children=[
            FakeNode(
                name="app.form.field.0.label",
                description="",
                role_en_us="label",
                states_en_us="enabled,visible,showing",
                accessible_text=True,
                text="Live AccessibleText",
            ),
            FakeNode(
                name="app.form.field.1.label",
                description="From description",
                role_en_us="label",
                states_en_us="enabled,visible,showing",
            ),
            FakeNode(
                name="app.form.field.2.label",
                description="",
                role_en_us="label",
                states_en_us="enabled,visible,showing",
            ),
        ],
    )
    backend = FakeBackend({HWND: tree})
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    with PlayJab(timeout=0) as api:
        window = api.attach(pid=PID).window()
        fields = window.locator(name=contains("app.form"), role="label")
        # AccessibleText wins over description when the interface is present
        # (matches text_content()'s own precedence), otherwise description,
        # otherwise name (field 2's name doubles as its own fallback here) -
        # read for all three in one traversal.
        assert fields.all_text_contents() == [
            "Live AccessibleText",
            "From description",
            "app.form.field.2.label",
        ]


def test_all_text_contents_redacts_password_role_unlike_text_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us="enabled,visible,showing",
        children=[
            FakeNode(
                name=SECRET,
                description=SECRET,
                role_en_us="password text",
                states_en_us="enabled,visible,showing",
                accessible_text=True,
                text=SECRET,
            ),
        ],
    )
    backend = FakeBackend({HWND: tree})
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    with PlayJab(timeout=0) as api:
        window = api.attach(pid=PID).window()
        password = window.get_by_role("password text")
        # Explicit single-field read on a known password field still returns
        # the real value (documented text_content() contract); the bulk dump
        # does not, since it may sweep up a password incidentally among
        # unrelated matches rather than being a deliberate, targeted read.
        assert password.text_content() == SECRET
        assert password.all_text_contents() == ["<redacted>"]


def test_snapshot_requires_exactly_one_match(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    with pytest.raises(StrictModeViolation):
        window.get_by_name("Duplicate").snapshot()
    with pytest.raises(LocatorTimeoutError):
        window.get_by_name("Missing").snapshot()


def test_snapshot_is_reference_free_and_reads_expected_metadata(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    snapshot = window.get_by_name("Disabled").snapshot()
    assert snapshot.name == "Disabled"
    assert snapshot.role == "push button"
    assert "enabled" not in snapshot.states
    assert "visible" in snapshot.states
    assert runtime.live_ref_count == 0
    assert backend.live_cookies == frozenset()


def test_every_operation_re_resolves_and_releases_all_jab_references(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    locator = window.get_by_name("Disabled")
    for _ in range(5):
        assert locator.count() == 1
        assert runtime.live_ref_count == 0
        assert backend.live_cookies == frozenset()
    assert backend.acquired == backend.released


def test_click_uses_case_insensitive_accessible_action_and_releases_refs(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    window.get_by_name("Duplicate").first().click()
    assert [action for _, action in backend.performed_actions] == ["ClIcK"]
    assert runtime.live_ref_count == 0
    assert backend.acquired == backend.released


def test_click_accepts_the_only_accessible_action_as_default(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, backend = locator_api
    target = backend._windows[HWND].children[0].children[0]
    target.actions = ("press",)
    window.get_by_name("Duplicate").first().click()
    assert [action for _, action in backend.performed_actions] == ["press"]


def test_click_rejects_ambiguous_missing_and_non_actionable_targets(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, backend = locator_api
    with pytest.raises(StrictModeViolation):
        window.get_by_name("Duplicate").click()
    with pytest.raises(LocatorTimeoutError):
        window.get_by_name("Missing").click()
    with pytest.raises(LocatorError, match="enabled"):
        window.get_by_name("Disabled").click()

    target = backend._windows[HWND].children[0].children[0]
    target.actions = ("toggle", "expand")
    with pytest.raises(UnsupportedActionError, match="no click action"):
        window.get_by_name("Duplicate").first().click()
    target.accessible_action = False
    with pytest.raises(UnsupportedActionError, match="AccessibleAction"):
        window.get_by_name("Duplicate").first().click()


class _LateChildBackend(FakeBackend):
    """Attach a node only on the Nth resolution pass, without any sleeping.

    Mirrors ``_InitiallyStaleBackend``'s counted-pass style below: auto-wait
    is proven by making the node's very existence depend on how many times
    the tree has been scanned, not by racing a background thread against a
    fixed sleep.
    """

    def __init__(self, root: FakeNode, child: FakeNode, *, appear_on_pass: int) -> None:
        super().__init__({HWND: root})
        self._root = root
        self._child = child
        self._appear_on_pass = appear_on_pass
        self.passes = 0

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        self.passes += 1
        if self.passes == self._appear_on_pass:
            self.add_child(self._root, self._child)
        return super().get_accessible_context_from_hwnd(hwnd)


CHECKBOX_APPEARS_ON_PASS = 2


def _late_checkbox(*, initially_checked: bool) -> FakeNode:
    states = "enabled,visible,showing"
    if initially_checked:
        states += ",checked"
    return FakeNode(
        name="Agree",
        role_en_us="check box",
        states_en_us=states,
        accessible_action=True,
        accessible_component=True,
        actions=("click",),
    )


def test_check_waits_for_a_checkbox_that_appears_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = FakeNode(
        name="Fixture", role_en_us="frame", states_en_us="enabled,visible,showing"
    )
    checkbox = _late_checkbox(initially_checked=False)
    backend = _LateChildBackend(root, checkbox, appear_on_pass=CHECKBOX_APPEARS_ON_PASS)
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        window.get_by_name("Agree").check(timeout=2_000)
        assert "checked" in window.get_by_name("Agree").snapshot().states
        assert backend.passes >= CHECKBOX_APPEARS_ON_PASS
        assert runtime.live_ref_count == 0
        assert backend.acquired == backend.released
    finally:
        api.close()


def test_uncheck_waits_for_a_checked_checkbox_that_appears_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = FakeNode(
        name="Fixture", role_en_us="frame", states_en_us="enabled,visible,showing"
    )
    checkbox = _late_checkbox(initially_checked=True)
    backend = _LateChildBackend(root, checkbox, appear_on_pass=CHECKBOX_APPEARS_ON_PASS)
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        window.get_by_name("Agree").uncheck(timeout=2_000)
        assert "checked" not in window.get_by_name("Agree").snapshot().states
        assert backend.passes >= CHECKBOX_APPEARS_ON_PASS
        assert runtime.live_ref_count == 0
        assert backend.acquired == backend.released
    finally:
        api.close()


def test_check_on_a_permanently_missing_target_still_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix must not turn check() into an unbounded wait: a target that
    never appears still fails once the deadline is exhausted."""
    root = FakeNode(
        name="Fixture", role_en_us="frame", states_en_us="enabled,visible,showing"
    )
    backend = FakeBackend({HWND: root})
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        with pytest.raises(LocatorTimeoutError):
            window.get_by_name("Never").check(timeout=100)
        assert runtime.live_ref_count == 0
    finally:
        api.close()


class _StaleFirstActionBackend(FakeBackend):
    def __init__(self, root: FakeNode) -> None:
        super().__init__({HWND: root})
        self.staled_action_once = False

    def get_accessible_actions(
        self, vm_id: int, context: int
    ) -> tuple[str, ...] | None:
        if not self.staled_action_once:
            self.make_stale(context)
            self.staled_action_once = True
        return super().get_accessible_actions(vm_id, context)


def test_click_re_resolves_once_when_the_action_context_goes_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _StaleFirstActionBackend(_tree())
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        window.get_by_name("Duplicate").first().click()
        assert backend.staled_action_once
        assert [action for _, action in backend.performed_actions] == ["ClIcK"]
        assert runtime.live_ref_count == 0
        assert backend.acquired == backend.released
    finally:
        api.close()


class _StaleSecondRootBackend(FakeBackend):
    """Stale the root the action path opens, not the one the scan opened.

    A resolution pass and the following ``Locator._operate`` each call
    ``getAccessibleContextFromHWND`` once, in that order: the scan's own
    retry already covers a stale first root, so only staling the *second*
    root reaches ``_operate``'s own recovery branch.
    """

    def __init__(self, root: FakeNode) -> None:
        super().__init__({HWND: root})
        self.roots_handed_out = 0

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        found = super().get_accessible_context_from_hwnd(hwnd)
        self.roots_handed_out += 1
        if found is not None and self.roots_handed_out == SCAN_THEN_ACTION_ROOT_COUNT:
            self.make_stale(found[1])
        return found


def test_click_recovers_when_the_action_path_context_goes_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scan resolves the target, then the action path re-walks the same
    path and finds the root context it just opened already stale - a Swing
    tree rebuild landing between resolution and action, not during either
    individually. This must heal like every other stale pass, not surface
    the native call failure."""
    backend = _StaleSecondRootBackend(_tree())
    runtime = install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    api = PlayJab(timeout=2_000, path_cache=False)
    api.__enter__()
    try:
        window = api.attach(pid=PID).window()
        window.get_by_name("Duplicate").first().click()
        assert [action for _, action in backend.performed_actions] == ["ClIcK"]
        assert runtime.live_ref_count == 0
        assert backend.acquired == backend.released
    finally:
        api.close()


class _AlwaysStaleActionRootBackend(FakeBackend):
    """Every scan succeeds; every action-path root the caller opens is stale.

    Roots alternate: odd handouts (the scan's own ``traverse``) stay live,
    even handouts (``_operate``'s own ``context_from_hwnd``) go stale
    immediately - so ``_operate`` keeps finding its target and keeps failing
    to act on it, and its own timeout branch (not the scan's) has to fire.
    """

    def __init__(self, root: FakeNode) -> None:
        super().__init__({HWND: root})
        self.roots_handed_out = 0

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        found = super().get_accessible_context_from_hwnd(hwnd)
        self.roots_handed_out += 1
        if found is not None and self.roots_handed_out % 2 == 0:
            self.make_stale(found[1])
        return found


class _ActionPathChildVanishesBackend(FakeBackend):
    """The action path's first child lookup finds nothing, once.

    Distinct from a dead context: the parent the action path re-opens is
    perfectly live, but the index it walks toward no longer has a child at
    all - a sibling was removed, not the target's own context invalidated.
    ``getAccessibleChildFromContext`` returns ``0`` for this, not FALSE, so
    this must raise ``_StaleLocatorError`` rather than route through
    ``_context_info``.
    """

    def __init__(self, root: FakeNode) -> None:
        super().__init__({HWND: root})
        self.roots_handed_out = 0
        self._triggered = False

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        found = super().get_accessible_context_from_hwnd(hwnd)
        self.roots_handed_out += 1
        return found

    def get_accessible_child_from_context(
        self, vm_id: int, context: int, index: int
    ) -> int:
        if self.roots_handed_out >= SCAN_THEN_ACTION_ROOT_COUNT and not self._triggered:
            self._triggered = True
            return 0
        return super().get_accessible_child_from_context(vm_id, context, index)


def test_click_recovers_when_a_child_vanishes_mid_walk_on_the_action_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _ActionPathChildVanishesBackend(_tree())
    runtime = install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    api = PlayJab(timeout=2_000, path_cache=False)
    api.__enter__()
    try:
        window = api.attach(pid=PID).window()
        window.get_by_name("Duplicate").first().click()
        assert backend._triggered
        assert [action for _, action in backend.performed_actions] == ["ClIcK"]
        assert runtime.live_ref_count == 0
        assert backend.acquired == backend.released
    finally:
        api.close()


def test_click_times_out_cleanly_when_the_action_path_never_stops_staling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _AlwaysStaleActionRootBackend(_tree())
    runtime = install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    api = PlayJab(timeout=100, path_cache=False)
    api.__enter__()
    try:
        window = api.attach(pid=PID).window()
        with pytest.raises(LocatorTimeoutError):
            window.get_by_name("Duplicate").first().click()
        assert runtime.live_ref_count == 0
        assert backend.acquired == backend.released
    finally:
        api.close()


@pytest.mark.parametrize("index", [-2, -1])
def test_invalid_positional_indices_fail_before_traversal(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
    index: int,
) -> None:
    _, window, _, backend = locator_api
    acquired = backend.acquired
    with pytest.raises(
        ValueError,
        match="locator index must be a non-negative integer",
    ):
        window.get_by_name("Duplicate").nth(index)
    assert backend.acquired == acquired


def test_role_and_state_validation_happens_before_traversal(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, backend = locator_api
    acquired = backend.acquired
    with pytest.raises(ValueError, match="unsupported accessible role"):
        window.locator(role="application-specific")
    with pytest.raises(ValueError, match="unsupported accessible state"):
        window.locator(states=("application-specific",))
    assert backend.acquired == acquired


def test_password_metadata_is_redacted_from_snapshot_dump_and_diagnostics(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    snapshot = window.get_by_role("password text").snapshot()
    assert SECRET not in repr(snapshot)
    assert SECRET not in window.dump()
    with pytest.raises(LocatorError) as caught:
        window.get_by_name("never-present").snapshot()
    assert SECRET not in str(caught.value)


def test_accessibility_tree_honours_diagnostic_limits(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, runtime, backend = locator_api
    tree = window.accessibility_tree(max_depth=1, max_nodes=2)
    # max_nodes=2 covers the root itself plus exactly one child - a bound of
    # `<= 1` would also pass for a broken traversal that returned no children.
    assert len(tree.children) == 1
    assert runtime.live_ref_count == 0
    assert backend.live_cookies == frozenset()
    with pytest.raises(ValueError, match="max_depth must be a non-negative integer"):
        window.accessibility_tree(max_depth=-1)
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="max_nodes must be a positive integer"):
            window.accessibility_tree(max_nodes=invalid)


def test_visibility_and_enabled_queries_are_strict(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    assert window.get_by_name("Disabled").is_visible()
    assert not window.get_by_name("Disabled").is_enabled()
    assert not window.get_by_name("Missing").is_visible()
    with pytest.raises(StrictModeViolation):
        window.get_by_name("Duplicate").is_visible()


def test_wait_for_polls_at_one_hundred_milliseconds_until_attached(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, window, runtime, backend = locator_api
    window._timeout = 1_000
    root = backend._windows[HWND]
    target = root.children[0].children[1]
    root.children[0].children.remove(target)
    delays: list[float] = []

    def reveal(delay: float) -> None:
        delays.append(delay)
        root.children[0].children.append(target)

    monkeypatch.setattr(runtime, "wait_for_event", reveal)
    window.get_by_name("Disabled").wait_for(state="attached")
    assert delays == [pytest.approx(0.1)]


def test_wait_for_detached_re_resolves_instead_of_holding_a_cookie(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, window, runtime, backend = locator_api
    root = backend._windows[HWND]
    target = root.children[0].children[1]

    def remove(_delay: float) -> None:
        root.children[0].children.remove(target)

    monkeypatch.setattr(runtime, "wait_for_event", remove)
    window.get_by_name("Disabled").wait_for(state="detached", timeout=1_000)
    assert runtime.live_ref_count == 0
    assert backend.live_cookies == frozenset()


@pytest.mark.parametrize("state", ["attached", "visible"])
def test_wait_for_one_node_states_enforces_strictness(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
    state: str,
) -> None:
    _, window, _, _ = locator_api
    with pytest.raises(StrictModeViolation):
        window.get_by_name("Duplicate").wait_for(state=state, timeout=0)


def test_hidden_succeeds_for_zero_or_one_invisible_node(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    window.get_by_name("Missing").wait_for(state="hidden", timeout=0)
    window.get_by_name("Duplicate").last().wait_for(state="hidden", timeout=0)


def test_wait_timeout_and_state_are_validated(
    locator_api: tuple[PlayJab, JavaWindow, BridgeRuntime, FakeBackend],
) -> None:
    _, window, _, _ = locator_api
    locator = window.get_by_name("Missing")
    with pytest.raises(LocatorTimeoutError, match="0 ms"):
        locator.wait_for(state="attached", timeout=0)
    with pytest.raises(ValueError, match="state"):
        locator.wait_for(state="enabled")
    with pytest.raises(ValueError, match="timeout"):
        locator.wait_for(timeout=-1)


class _StalingRootBackend(FakeBackend):
    def __init__(self, root: FakeNode, *, every_time: bool) -> None:
        super().__init__({HWND: root})
        self._every_time = every_time
        self._staled_once = False

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        found = super().get_accessible_context_from_hwnd(hwnd)
        if found is not None and (self._every_time or not self._staled_once):
            self.make_stale(found[1])
            self._staled_once = True
        return found


class _InitiallyStaleBackend(FakeBackend):
    def __init__(self, root: FakeNode, stale_passes: int) -> None:
        super().__init__({HWND: root})
        self._stale_passes = stale_passes

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        found = super().get_accessible_context_from_hwnd(hwnd)
        if found is not None and self._stale_passes:
            self.make_stale(found[1])
            self._stale_passes -= 1
        return found


def _window_for_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: FakeBackend,
) -> tuple[PlayJab, JavaWindow, BridgeRuntime]:
    runtime = install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    api = PlayJab(timeout=0)
    api.__enter__()
    return api, api.attach(pid=PID).window(), runtime


def test_immediate_operation_retries_one_stale_pass_and_releases_both_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _StalingRootBackend(_tree(), every_time=False)
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        assert window.get_by_name("Disabled").count() == 1
        assert backend.acquired == backend.released
        assert runtime.live_ref_count == 0
    finally:
        api.close()


def test_repeated_stale_context_becomes_locator_error_without_a_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _StalingRootBackend(_tree(), every_time=True)
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        with pytest.raises(LocatorError, match="stale"):
            window.get_by_name("Disabled").count()
        assert backend.acquired == backend.released
        assert runtime.live_ref_count == 0
    finally:
        api.close()


def test_waiting_operation_starts_new_passes_after_repeated_stale_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _InitiallyStaleBackend(_tree(), stale_passes=3)
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        window.get_by_name("Disabled").wait_for(state="attached", timeout=1_000)
        assert backend.acquired == backend.released
        assert runtime.live_ref_count == 0
    finally:
        api.close()


def test_depth_limit_fails_deterministically_without_leaking_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = FakeNode(name="root", role_en_us="panel")
    current = root
    for level in range(102):
        child = FakeNode(name=f"level-{level}", role_en_us="panel")
        current.children.append(child)
        current = child
    backend = FakeBackend({HWND: root})
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        with pytest.raises(LocatorError, match="limit"):
            window.get_by_role("panel").count()
        assert backend.acquired == backend.released
        assert runtime.live_ref_count == 0
    finally:
        api.close()


def test_max_depth_skips_a_heavy_showing_sibling_before_a_shallow_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for depth-first-first-shallow-target: a deep, "showing"
    subtree that sorts before a shallow target must not be fully walked when
    the caller knows the target is shallow."""
    heavy = FakeNode(
        name="Heavy", role_en_us="panel", states_en_us="enabled,visible,showing"
    )
    current = heavy
    for level in range(HEAVY_SIBLING_LEVELS):
        child = FakeNode(
            name=f"heavy-{level}",
            role_en_us="panel",
            states_en_us="enabled,visible,showing",
        )
        current.children.append(child)
        current = child
    root = FakeNode(
        name="root",
        role_en_us="frame",
        states_en_us="enabled,visible,showing",
        children=[
            heavy,
            FakeNode(
                name="Target",
                role_en_us="toggle button",
                states_en_us="enabled,visible,showing",
            ),
        ],
    )
    backend = FakeBackend({HWND: root})
    api, window, runtime = _window_for_backend(monkeypatch, backend)
    try:
        acquired = backend.acquired
        assert window.locator(role="toggle button", max_depth=1).count() == 1
        # Bounded: only root's two direct children are opened - the 50-level
        # chain under the showing "Heavy" sibling is never descended into.
        assert backend.acquired - acquired == BOUNDED_ACQUISITIONS_WITH_MAX_DEPTH
        assert runtime.live_ref_count == 0
    finally:
        api.close()


def _wide_tree_with_duplicates(sibling_count: int) -> FakeNode:
    """A root panel with two identically-named "dupe" leaves among many."""
    children = [
        FakeNode(
            name="dupe",
            role_en_us="push button",
            states_en_us="enabled,visible,showing",
        )
        for _ in range(2)
    ]
    children += [
        FakeNode(
            name=f"leaf-{index}",
            role_en_us="push button",
            states_en_us="enabled,visible,showing",
        )
        for index in range(sibling_count)
    ]
    return FakeNode(
        name="root",
        role_en_us="panel",
        states_en_us="enabled,visible,showing",
        children=children,
    )


def test_ambiguous_leaf_locator_scan_cost_does_not_grow_with_tree_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: `_strict()` only distinguishes 0/1/"more than one" match, so
    an ambiguous locator must stop scanning shortly after the second match --
    not pay for every remaining sibling, however many there are."""
    costs = []
    for sibling_count in (48, 2_000):
        backend = FakeBackend({HWND: _wide_tree_with_duplicates(sibling_count)})
        api, window, _ = _window_for_backend(monkeypatch, backend)
        try:
            acquired = backend.acquired
            with pytest.raises(StrictModeViolation):
                window.get_by_name("dupe").is_visible()
            costs.append(backend.acquired - acquired)
        finally:
            api.close()
    assert costs[0] == costs[1]


def test_ambiguous_parent_step_scan_cost_does_not_grow_with_tree_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same regression as above, but for a parent-narrowing (non-final) step:
    `window.get_by_name("group").get_by_name(...)` must confirm "group" is
    ambiguous without scanning every one of the other root-level siblings."""
    costs = []
    for sibling_count in (48, 2_000):
        groups = [
            FakeNode(
                name="group", role_en_us="panel", states_en_us="enabled,visible,showing"
            )
            for _ in range(2)
        ]
        groups += [
            FakeNode(
                name=f"other-{index}",
                role_en_us="panel",
                states_en_us="enabled,visible,showing",
            )
            for index in range(sibling_count)
        ]
        root = FakeNode(
            name="root",
            role_en_us="frame",
            states_en_us="enabled,visible,showing",
            children=groups,
        )
        backend = FakeBackend({HWND: root})
        api, window, _ = _window_for_backend(monkeypatch, backend)
        try:
            acquired = backend.acquired
            with pytest.raises(StrictModeViolation):
                window.get_by_name("group").get_by_name("whatever").count()
            costs.append(backend.acquired - acquired)
        finally:
            api.close()
    assert costs[0] == costs[1]


def test_last_still_returns_the_true_last_match_among_many_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: capping ambiguity-detection scans at a couple of
    matches (above) must never apply to `.last()` -- it needs the true total
    to know which match is actually last, not just the second one found."""
    children = [
        FakeNode(
            name="dupe",
            description=f"copy-{index}",
            role_en_us="push button",
            states_en_us="enabled,visible,showing",
        )
        for index in range(5)
    ]
    root = FakeNode(
        name="root",
        role_en_us="panel",
        states_en_us="enabled,visible,showing",
        children=children,
    )
    backend = FakeBackend({HWND: root})
    api, window, _ = _window_for_backend(monkeypatch, backend)
    try:
        assert window.get_by_name("dupe").last().snapshot().description == "copy-4"
    finally:
        api.close()
