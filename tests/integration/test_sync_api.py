"""Public synchronous API checks against the real JDK 17 Swing fixture."""

from __future__ import annotations

import re

import pytest

from play_jab.exceptions import JavaWindowAmbiguousError, StrictModeViolation
from play_jab.sync_api import PlayJab, contains

from .conftest import SwingFixture

pytestmark = pytest.mark.integration_jab

_TITLE = "JAB swing fixture"
_SECONDARY_TITLE = "JAB swing fixture secondary"
_API_TIMEOUT_MS = 5_000
_DYNAMIC_TIMEOUT_MS = 4_000
_TRAVERSAL_REPETITIONS = 5
_DUPLICATE_COUNT = 2
_TABLE_ROWS = 100
_TABLE_COLUMNS = 5


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


def test_polling_observes_automatic_attachment_cycle(
    swing_fixture: SwingFixture,
) -> None:
    """A lazy locator re-resolves the tree while its Swing node comes and goes."""
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(pid=swing_fixture.process.pid).window(title=_TITLE)
        node = window.get_by_name("fixture.auto_node")
        node.wait_for("attached", timeout=_DYNAMIC_TIMEOUT_MS)
        node.wait_for("detached", timeout=_DYNAMIC_TIMEOUT_MS)
        assert node.count() == 0
        assert api.live_ref_count == 0


def test_repeated_public_traversals_do_not_leak_native_references(
    swing_fixture: SwingFixture,
) -> None:
    """Snapshots, locator trees and dumps leave the bridge reference count flat."""
    with PlayJab(timeout=_API_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        baseline = api.live_ref_count
        for _ in range(_TRAVERSAL_REPETITIONS):
            assert window.get_by_name("fixture.scope_alpha").snapshot().name
            assert window.get_by_name("fixture.scope_alpha").accessibility_tree()
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

        try:
            username.fill("Привет, 世界 👋")
            assert username.text_content() == "Привет, 世界 👋"
            password.fill("секрет")
            assert len(password.text_content()) == len("секрет")
            remember.check()
            assert remember.is_checked()

            tabs.select_option(1)
            table = window.get_by_name("fixture.table").as_table()
            assert table.row_count() == _TABLE_ROWS
            assert table.column_count() == _TABLE_COLUMNS
            assert table.cell(7, 1).text_content() == "job-7"
            assert table.cell(99, 1).text_content() == "job-99"
            assert table.cell(7, 3).text_content() == "Processing"
            window.get_by_name("fixture.mark_done_button").click()
            table.cell(7, 3).wait_for_text("Done")
            window.get_by_name("fixture.reset_table_button").click()
            table.cell(7, 3).wait_for_text("Processing")
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)
            username.clear()
            password.clear()
            remember.uncheck()
