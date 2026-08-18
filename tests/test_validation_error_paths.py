"""Argument validation and small diagnostic surfaces `sync_api.py` never exercises.

CLAUDE.md asks for focused unit tests on "normal, error, and cleanup paths".
The error paths gathered here are cheap to prove wrong (most raise before any
native call happens at all) but were previously invisible in coverage - see
unit-tests-review.md section 4.1 for the full list this file closes.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator

import pytest

from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import JavaVmExitedError, LocatorError, TableIndexError
from play_jab.sync_api import JavaWindow, PlayJab, contains

from .conftest import FakeWindowBackend, install_fake_runtime

PID = 4242
HWND = 0xCAFE
EVENT_TIMEOUT = 2.0


def _tree() -> FakeNode:
    combo = FakeNode(
        name="Role",
        role_en_us="combo box",
        states_en_us="enabled,visible,showing",
        accessible_selection=True,
        children=[
            FakeNode(name="Viewer", role_en_us="list item"),
            FakeNode(name="Editor", role_en_us="list item"),
        ],
    )
    zero_bounds = FakeNode(
        name="ZeroBounds",
        role_en_us="push button",
        states_en_us="enabled,visible,showing",
        accessible_action=True,
        actions=("click",),
    )
    child = FakeNode(
        name="Child",
        role_en_us="label",
        states_en_us="enabled,visible,showing",
    )
    return FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us="enabled,visible,showing",
        children=[combo, zero_bounds, child],
    )


@pytest.fixture
def window(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, FakeBackend]]:
    backend = FakeBackend({HWND: _tree()})
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    api = PlayJab(timeout=0)
    api.__enter__()
    try:
        yield api, api.attach(pid=PID).window(hwnd=HWND), backend
    finally:
        api.close()


# -- contains() / _matcher --------------------------------------------------
def test_contains_rejects_a_non_string() -> None:
    with pytest.raises(TypeError, match="contains"):
        contains(123)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_matcher", [123, 1.5, ["a"], {"a"}])
def test_get_by_name_rejects_an_unsupported_matcher_type(
    window: tuple[PlayJab, JavaWindow, FakeBackend], bad_matcher: object
) -> None:
    _api, win, _backend = window
    with pytest.raises(ValueError, match="name must be"):
        win.get_by_name(bad_matcher)  # type: ignore[arg-type]


def test_get_by_name_accepts_a_compiled_regex(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    assert win.get_by_name(re.compile("Fix.*")).count() == 1
    assert win.get_by_name(contains("ixtur")).count() == 1


# -- JavaWindow.locator() ----------------------------------------------------
def test_locator_rejects_a_non_string_role(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    with pytest.raises(ValueError, match="role must be a string"):
        win.locator(role=123)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_index", [-1, 1.5, True, "0"])
def test_locator_rejects_an_invalid_index_in_parent(
    window: tuple[PlayJab, JavaWindow, FakeBackend], bad_index: object
) -> None:
    _api, win, _backend = window
    with pytest.raises(ValueError, match="index_in_parent"):
        win.locator(index_in_parent=bad_index)  # type: ignore[arg-type]


def test_locator_rejects_a_non_bool_visible_only(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    with pytest.raises(ValueError, match="visible_only must be a bool"):
        win.locator(visible_only="yes")  # type: ignore[arg-type]


def test_locator_rejects_a_non_bool_showing_only(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _, win, _ = window
    with pytest.raises(ValueError, match="showing_only must be a bool"):
        win.locator(showing_only="yes")  # type: ignore[arg-type]


# -- Locator.fill() / .scroll() / .select_option() ---------------------------
def test_fill_rejects_a_non_string_value(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    with pytest.raises(TypeError, match=r"fill\(\) value must be a string"):
        win.get_by_name("Child").fill(123)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_steps", [1.5, "1", True, None])
def test_scroll_rejects_a_non_integer_step_count(
    window: tuple[PlayJab, JavaWindow, FakeBackend], bad_steps: object
) -> None:
    _api, win, _backend = window
    with pytest.raises(TypeError, match="steps must be an integer"):
        win.get_by_name("Child").scroll(bad_steps)  # type: ignore[arg-type]


def test_scroll_rejects_a_target_with_empty_bounds(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    with pytest.raises(LocatorError, match="empty bounds"):
        win.get_by_name("ZeroBounds").scroll(1, timeout=0)


@pytest.mark.parametrize("bad_option", [1.5, None, ["a"]])
def test_select_option_rejects_a_type_that_is_neither_name_nor_index(
    window: tuple[PlayJab, JavaWindow, FakeBackend], bad_option: object
) -> None:
    _api, win, _backend = window
    with pytest.raises(TypeError, match="option must be"):
        win.get_by_name("Role").select_option(bad_option)  # type: ignore[arg-type]


def test_select_option_by_index_rejects_an_out_of_range_index(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    with pytest.raises(LocatorError, match="outside the available children"):
        win.get_by_name("Role").select_option(5)


# -- TableCellLocator.wait_for_text() / TableLocator index guards -----------
def test_wait_for_text_rejects_a_non_string(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    cell = win.get_by_name("Orders").as_table().cell(0, 0)
    with pytest.raises(TypeError, match="text must be a string"):
        cell.wait_for_text(123)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_row", [-1, 1.5, True])
def test_row_header_rejects_a_negative_or_non_integer_row(
    window: tuple[PlayJab, JavaWindow, FakeBackend], bad_row: object
) -> None:
    _api, win, _backend = window
    with pytest.raises(TableIndexError, match="row index"):
        win.get_by_name("Orders").as_table().row_header(bad_row)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_column", [-1, 1.5, True])
def test_column_header_rejects_a_negative_or_non_integer_column(
    window: tuple[PlayJab, JavaWindow, FakeBackend], bad_column: object
) -> None:
    _api, win, _backend = window
    table = win.get_by_name("Orders").as_table()
    with pytest.raises(TableIndexError, match="column index"):
        table.column_header(bad_column)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_row", [-1, 1.5, True])
def test_select_row_rejects_a_negative_or_non_integer_row(
    window: tuple[PlayJab, JavaWindow, FakeBackend], bad_row: object
) -> None:
    _api, win, _backend = window
    table = win.get_by_name("Orders").as_table()
    with pytest.raises(TableIndexError, match="row index"):
        table.select_row(bad_row)  # type: ignore[arg-type]


# -- AccessibilityNode / accessibility_tree() / dump() -----------------------
def test_accessibility_node_properties_mirror_the_snapshot(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    tree = win.accessibility_tree()
    assert tree.name == tree.snapshot.name == "Fixture"
    assert tree.description == tree.snapshot.description
    assert tree.role == tree.snapshot.role == "frame"
    assert tree.states == tree.snapshot.states


def test_locator_accessibility_tree_scopes_to_the_matched_node(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    tree = win.get_by_name("Role").accessibility_tree()
    assert tree.name == "Role"
    assert {child.name for child in tree.children} == {"Viewer", "Editor"}


def test_locator_dump_renders_the_scoped_subtree(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, win, _backend = window
    diagnostics = win.get_by_name("Role").dump()
    assert "role='combo box'" in diagnostics
    assert "Viewer" in diagnostics
    assert "Fixture" not in diagnostics


# -- JVM-exited window discovery ---------------------------------------------
def test_attach_by_hwnd_reports_jvm_exit_for_a_previously_seen_window(
    window: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    api, win, backend = window
    win.accessibility_tree()  # forces a native lookup, recording hwnd -> vmID

    backend.emit_vm_shutdown()
    deadline = time.monotonic() + EVENT_TIMEOUT
    while not api._bridge.is_vm_exited_window(HWND) and time.monotonic() < deadline:
        time.sleep(0.001)
    assert api._bridge.is_vm_exited_window(HWND)

    with pytest.raises(JavaVmExitedError):
        api.attach(hwnd=HWND, timeout=0)
