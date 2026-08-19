"""Public synchronous API checks against the real JDK 17 Swing fixture."""

from __future__ import annotations

import re

import pytest

from play_jab.exceptions import (
    JavaProcessExitedError,
    JavaVmExitedError,
    JavaWindowAmbiguousError,
    JavaWindowNotFoundError,
    StrictModeViolation,
    UnsupportedActionError,
)
from play_jab.sync_api import PlayJab, contains

from .conftest import DialogFixture, SwingFixture

pytestmark = pytest.mark.integration_jab

_TITLE = "JAB swing fixture"
_SECONDARY_TITLE = "JAB swing fixture secondary"
_API_TIMEOUT_MS = 5_000
_DYNAMIC_TIMEOUT_MS = 4_000
_TRAVERSAL_REPETITIONS = 5
_DUPLICATE_COUNT = 2
_TABLE_ROWS = 100
_TABLE_COLUMNS = 5


def test_graceful_jvm_exit_wakes_locator_wait(
    lifecycle_fixture: DialogFixture,
) -> None:
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(pid=lifecycle_fixture.process.pid).window(
            hwnd=lifecycle_fixture.hwnd
        )
        status = window.get_by_name("fixture.shutdown_status")
        assert status.text_content() == "running"

        # The click's own ActionListener only starts a short Timer before
        # returning; System.exit(0) runs later, off this call, so the click
        # itself completes normally.
        window.get_by_name("fixture.shutdown_button").click(timeout=_API_TIMEOUT_MS)
        assert status.text_content(timeout=_API_TIMEOUT_MS) == "shutting-down"

        # Which of these three fires is a genuine, benign race between the OS
        # process dying and the bridge's own VM-death bookkeeping catching up
        # (`bridge.py:context_from_hwnd`): if `_dead_vms` is updated first,
        # `JavaVmExitedError`; if the OS process table updates first,
        # `JavaProcessExitedError`; if neither has caught up yet but the HWND
        # itself is already gone, `JavaWindowNotFoundError`. All three mean
        # the same observable fact here - the window's owning process exited -
        # so the wait correctly failed instead of hanging. Narrowing this
        # further would require hardening `context_from_hwnd`'s exit
        # detection, which is a library change out of this plan's scope.
        with pytest.raises(
            (JavaVmExitedError, JavaProcessExitedError, JavaWindowNotFoundError)
        ):
            window.get_by_name("never-attached").wait_for(
                "attached", timeout=_API_TIMEOUT_MS
            )


def test_attach_by_hwnd_pid_and_exact_title(swing_fixture: SwingFixture) -> None:
    """All public attach selectors resolve the same process and top-level window."""
    selectors = (
        {"hwnd": swing_fixture.hwnd},
        {"pid": swing_fixture.process.pid},
        {"title": _TITLE},
    )
    for selector in selectors:
        with PlayJab(timeout=_API_TIMEOUT_MS) as api:
            application = api.attach(**selector)
            assert application.pid == swing_fixture.process.pid
            window = application.window(title=_TITLE)
            assert window.hwnd == swing_fixture.hwnd
            assert window.get_by_name("fixture.main").snapshot().role == "frame"
            assert api.live_ref_count == 0


def test_api_close_leaves_attached_process_alive(
    swing_fixture: SwingFixture,
) -> None:
    """The API attaches to a fixture-owned JVM and never owns its lifetime."""
    assert swing_fixture.process.poll() is None
    api = PlayJab(timeout=_API_TIMEOUT_MS)
    try:
        application = api.attach(pid=swing_fixture.process.pid)
        window = application.window(title=_TITLE)
        assert window.get_by_name("fixture.main").snapshot().name == "fixture.main"
        api.close()
        assert swing_fixture.process.poll() is None
    finally:
        api.close()


def test_window_discovery_is_strict_with_two_top_level_windows(
    swing_fixture_with_second_window: SwingFixture,
) -> None:
    """An unqualified process window is ambiguous; exact titles disambiguate it."""
    fixture = swing_fixture_with_second_window
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        application = api.attach(pid=fixture.process.pid)
        with pytest.raises(JavaWindowAmbiguousError):
            application.window()
        assert application.window(title=_TITLE).hwnd == fixture.hwnd
        secondary = application.window(title=_SECONDARY_TITLE)
        assert secondary.get_by_name("fixture.secondary").snapshot().role == "frame"


def test_locator_chaining_strictness_states_and_unicode(
    swing_fixture: SwingFixture,
) -> None:
    """Scoped descendants, strict locators, matchers and metadata work end to end."""
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        duplicates = window.get_by_name("fixture.duplicate")
        assert duplicates.count() == _DUPLICATE_COUNT
        with pytest.raises(StrictModeViolation):
            duplicates.snapshot()

        alpha = window.get_by_name("fixture.scope_alpha")
        alpha_duplicate = alpha.get_by_role("push button", name="fixture.duplicate")
        assert alpha_duplicate.snapshot().description == "duplicate in alpha"
        assert duplicates.first().snapshot().description == "duplicate in alpha"
        assert duplicates.last().snapshot().description == "duplicate in beta"
        assert [item.snapshot().name for item in duplicates.all()] == [
            "fixture.duplicate",
            "fixture.duplicate",
        ]

        visible = window.locator(
            role="push button",
            name=re.compile(r"^fixture\.visible_button$"),
            description=contains("enabled"),
            states={"visible", "enabled"},
            visible_only=True,
        )
        assert visible.is_visible()
        assert visible.is_enabled()
        assert not window.get_by_name("fixture.locator_disabled_button").is_enabled()

        unicode_node = window.get_by_name("fixture.auto_node").snapshot()
        assert "Автоматический узел" in unicode_node.description
        assert "日本語" in unicode_node.description
        assert "🚀" in unicode_node.description
        assert api.live_ref_count == 0


def test_select_option_selects_tab_page_by_exact_accessible_name(
    swing_fixture: SwingFixture,
) -> None:
    """`select_option()` already accepts an exact accessible name, not just an
    index, but no test had ever exercised it against `fixture.tabs`' named
    pages (test-app-review.md finding, Приоритет 2 п.6)."""
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        try:
            tabs.select_option("fixture.tab_table_page")
            assert window.get_by_name("fixture.table").exists()
            tabs.select_option("fixture.tab_form_page")
            assert window.get_by_name("fixture.submit_button").exists()
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_disabled_button_reports_not_enabled(swing_fixture: SwingFixture) -> None:
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        assert window.get_by_name("fixture.disabled_button").is_enabled() is False
        assert api.live_ref_count == 0


def test_polling_observes_automatic_attachment_cycle(
    swing_fixture: SwingFixture,
) -> None:
    """A lazy locator re-resolves a deterministically attached Swing node."""
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(pid=swing_fixture.process.pid).window(title=_TITLE)
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(4)
        try:
            node = window.get_by_name("fixture.workload_dynamic_node")
            window.get_by_name("fixture.workload_detach_button").click()
            node.wait_for("detached", timeout=_DYNAMIC_TIMEOUT_MS)
            assert node.count() == 0
            window.get_by_name("fixture.workload_attach_button").click()
            node.wait_for("attached", timeout=_DYNAMIC_TIMEOUT_MS)
            assert api.live_ref_count == 0
        finally:
            # A failure between detach and attach would otherwise leave the
            # session-scoped fixture's node detached for every later test.
            if window.get_by_name("fixture.workload_dynamic_node").count() == 0:
                window.get_by_name("fixture.workload_attach_button").click()
            tabs.select_option(0)


def test_repeated_public_traversals_do_not_leak_native_references(
    swing_fixture: SwingFixture,
) -> None:
    """Snapshots, locator trees and dumps leave the bridge reference count flat."""
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        baseline = api.live_ref_count
        for _ in range(_TRAVERSAL_REPETITIONS):
            assert window.get_by_name("fixture.scope_alpha").snapshot().name
            assert window.get_by_name("fixture.scope_alpha").accessibility_tree().role
            assert "fixture.scope_alpha" in window.dump(max_depth=10)
            assert api.live_ref_count == baseline
        assert baseline == 0


def test_forms_and_table_api_round_trip_through_real_jab(
    swing_fixture: SwingFixture,
) -> None:
    """Editable text, selection and table calls use the JDK 17 ABI end to end."""
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        username = window.get_by_name("fixture.username_field")
        password = window.get_by_name("fixture.password_field")
        remember = window.get_by_name("fixture.remember_checkbox")
        tabs = window.get_by_name("fixture.tabs")
        # Constructed early (locators do not resolve anything on their own) so
        # the `finally` block below can rely on it regardless of where the try
        # body fails.
        table = window.get_by_name("fixture.table").as_table()

        try:
            username.fill("Привет, 世界 👋")
            assert username.text_content() == "Привет, 世界 👋"
            password.fill("секрет")
            assert len(password.text_content()) == len("секрет")
            remember.check()
            assert remember.is_checked()

            tabs.select_option(1)
            assert table.row_count() == _TABLE_ROWS
            assert table.column_count() == _TABLE_COLUMNS
            assert table.cell(7, 1).text_content() == "job-7"
            assert table.cell(99, 1).text_content() == "job-99"
            assert table.cell(7, 3).text_content() == "Processing"
            window.get_by_name("fixture.mark_done_button").click()
            table.cell(7, 3).wait_for_text("Done")
            window.get_by_name("fixture.reset_table_button").click()
            table.cell(7, 3).wait_for_text("Processing")
            window.get_by_name("fixture.table_add_row_button").click()
            assert table.row_count() == _TABLE_ROWS + 1
            assert table.cell(_TABLE_ROWS, 1).text_content() == "job-100"
            window.get_by_name("fixture.table_remove_row_button").click()
            assert table.row_count() == _TABLE_ROWS
            assert api.live_ref_count == 0
        finally:
            # A failure between the add-row and remove-row clicks above would
            # otherwise leave 101 rows for every later use of this
            # session-scoped fixture, including a re-run of this same test.
            if table.row_count() > _TABLE_ROWS:
                window.get_by_name("fixture.table_remove_row_button").click()
            tabs.select_option(0)
            username.clear()
            password.clear()
            remember.uncheck()


def test_table_cell_fill_round_trips_through_standard_swing_editor(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        table = window.get_by_name("fixture.table").as_table()
        status = window.get_by_name("fixture.table_edit_status")
        editable = table.cell(7, 3)
        tabs.select_option(1)
        try:
            for iteration in range(20):
                value = f"Правка {iteration} 世界"
                editable.fill(value)
                assert editable.text_content() == value
                assert status.snapshot().description == f"cell={value}"

            editable.fill("")
            assert editable.text_content() == ""
            assert status.snapshot().description == "cell="

            with pytest.raises(
                UnsupportedActionError, match="did not accept in-place editing"
            ):
                table.cell(7, 2).fill("read-only", timeout=500)
            assert api.live_ref_count == 0
        finally:
            window.get_by_name("fixture.reset_table_button").click()
            tabs.select_option(0)


def test_virtualized_workloads_and_replacement_use_lazy_locators(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=10_000) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(4)
        try:
            item = window.get_by_name("fixture.virtual_list_item_0500")
            window.get_by_name("fixture.virtual_list_500_button").click()
            item.wait_for("attached")
            assert item.snapshot().name == "fixture.virtual_list_item_0500"

            dynamic = window.get_by_name("fixture.workload_dynamic_node")
            before = dynamic.snapshot().description
            window.get_by_name("fixture.workload_replace_button").click()
            dynamic.wait_for("attached")
            assert dynamic.snapshot().description != before

            # The root shows its immediate children (the 40 groups) by default,
            # so `fixture.virtual_tree_group_00` is already attached; a node
            # nested one level deeper genuinely requires the expand click.
            nested_item = window.get_by_name("fixture.virtual_tree_group_00_item_00")
            assert nested_item.count() == 0
            window.get_by_name("fixture.virtual_tree_expand_button").click()
            assert (
                nested_item.count() == 1
            )  # `<= 1` would also pass if expand did nothing
            assert api.live_ref_count == 0
        finally:
            window.get_by_name("fixture.virtual_list_start_button").click()
            tabs.select_option(0)


def test_showing_only_prunes_the_collapsed_tree_subtree_on_real_jab(
    swing_fixture: SwingFixture,
) -> None:
    """`docs/performance.md:189` credits `showing_only=True` pruning a
    `collapsed` subtree with "up to 50x cold" - proven so far only against
    `FakeBackend`, where `collapsed` nodes are artificially marked `showing`
    (`test_batched_traversal.py:539-542` admits as much). This is the first
    check against a real, static (non-lazy) Swing `JTree`: every one of the 40
    groups' 5 items genuinely exists in `DefaultTreeModel` regardless of
    expansion state - `showing_only=False` reaches all 241 descendants
    (measured), each collapsed item reporting `role="unknown"`, empty name and
    `bounds=(-1,-1,-1,-1)` (JAB never rendered it) but still present as a node
    `showing_only=False` counts. `showing_only=True` is asserted to exclude
    every single one of those 200 items, not just fewer of them - a total
    number of *visible* rows would be viewport/DPI/font-dependent (the same
    caveat already measured for `fixture.table` cells), but "zero
    role=unknown items in a showing_only scan while a collapsed group is
    selected" is not (test-app-review.md finding B-2).
    """
    with PlayJab(timeout=10_000) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(4)
        try:
            # Deterministic regardless of what earlier tests in this
            # session-scoped fixture left expanded/collapsed/scrolled.
            window.get_by_name("fixture.virtual_tree_collapse_button").click()
            window.get_by_name("fixture.virtual_tree_reset_button").click()
            window.get_by_name("fixture.virtual_tree_status").wait_for("attached")

            tree = window.get_by_name("fixture.virtual_tree")
            all_nodes = tree.locator(showing_only=False).all_snapshots()
            assert len(all_nodes) == 1 + 40 + 40 * 5
            hidden_items = [node for node in all_nodes if node.role == "unknown"]
            assert len(hidden_items) == 40 * 5

            showing_nodes = tree.locator(showing_only=True).all_snapshots()
            assert len(showing_nodes) < len(all_nodes)
            assert not any(node.role == "unknown" for node in showing_nodes)
            assert api.live_ref_count == 0
        finally:
            window.get_by_name("fixture.virtual_tree_expand_button").click()
            tabs.select_option(0)
