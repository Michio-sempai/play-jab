"""Contract tests for keyboard-driven ``TableCellLocator.fill()``."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    LocatorTimeoutError,
    UnsupportedActionError,
)
from play_jab.sync_api import JavaWindow, PlayJab

from .conftest import FakeWindowBackend

PID = 4242
HWND = 0xCAFE
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_F2 = 0x71
VK_DELETE = 0x2E
VK_HOME = 0x24
TARGET_ROW = 1
TARGET_COLUMN = 1

CellFixture = tuple[PlayJab, JavaWindow, FakeWindowBackend, FakeNode]


def _table_node(*, writable: bool, initial: str = "old") -> tuple[FakeNode, FakeNode]:
    target = FakeNode(
        name=initial,
        description=initial,
        role_en_us="label",
        states_en_us="enabled,visible,showing",
        text=initial,
    )
    cells = [
        [
            FakeNode(
                name=f"cell-{row}-{column}",
                description=f"cell-{row}-{column}",
                role_en_us="label",
                states_en_us="enabled,visible,showing",
            )
            for column in range(2)
        ]
        for row in range(2)
    ]
    cells[TARGET_ROW][TARGET_COLUMN] = target
    table = FakeNode(
        name="Editable table",
        role_en_us="table",
        states_en_us="enabled,visible,showing",
        accessible_component=True,
        accessible_selection=True,
        table_cells=cells,
    )
    target.value = "writable" if writable else "read-only"
    return table, target


def _attach(
    monkeypatch: pytest.MonkeyPatch,
    *,
    writable: bool,
    commit: bool = True,
    committed_value: str | None = None,
    initial: str = "old",
) -> CellFixture:
    table, target = _table_node(writable=writable, initial=initial)
    backend = FakeBackend(
        {
            HWND: FakeNode(
                name="Fixture",
                role_en_us="frame",
                states_en_us="enabled,visible,showing",
                children=[table],
            )
        }
    )

    def handle_key(vk_code: int) -> None:
        if vk_code == VK_F2 and target.value == "writable":
            target.accessible_text = True
            target.accessible_component = True
            target.role_en_us = "text"
            target.states_en_us = "enabled,visible,showing,focused"
            table.children[:] = [target]
            backend._indexes[id(target)] = 0
        elif vk_code == VK_RETURN and target.accessible_text:
            if commit:
                final = target.text if committed_value is None else committed_value
                target.name = final or ""
                target.description = final or ""
            target.accessible_text = False
            target.accessible_component = False
            target.role_en_us = "label"
            target.states_en_us = "enabled,visible,showing"
            table.children.clear()
        elif vk_code == VK_ESCAPE:
            target.accessible_text = False
            target.accessible_component = False
            target.role_en_us = "label"
            target.states_en_us = "enabled,visible,showing"
            table.children.clear()
        elif vk_code == VK_DELETE and target.accessible_text and target.text:
            target.text = target.text[1:]

    def handle_text(value: str) -> None:
        if target.accessible_text:
            target.text = value

    runtime = BridgeRuntime(lambda: backend)
    windows = FakeWindowBackend(
        {HWND: "Fixture"}, pid=PID, on_key=handle_key, on_text=handle_text
    )
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    api = PlayJab(timeout=0)
    api.__enter__()
    return api, api.attach(pid=PID).window(), windows, target


@pytest.fixture
def editable_cell(monkeypatch: pytest.MonkeyPatch) -> Iterator[CellFixture]:
    fixture = _attach(monkeypatch, writable=True)
    try:
        yield fixture
    finally:
        fixture[0].close()


@pytest.mark.parametrize("value", ["", "Новое значение 世界"])
def test_fill_selects_focuses_opens_editor_writes_and_commits(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    api, window, windows, target = _attach(monkeypatch, writable=True)
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        cell.fill(value, timeout=1_000)

        assert cell.text_content() == value
        assert target.accessible_text is False
        assert windows.calls == [
            ("foreground", HWND),
            ("key", VK_F2),
            ("key", VK_HOME),
            ("repeat_key", VK_DELETE, len("old")),
            ("text", value),
            ("key", VK_RETURN),
        ]
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_fill_raises_and_cancels_when_cell_never_enters_edit_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, window, windows, _target = _attach(monkeypatch, writable=False)
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        with pytest.raises(
            UnsupportedActionError, match="did not accept in-place editing"
        ):
            cell.fill("new value", timeout=100)

        assert windows.calls[-2:] == [("key", VK_RETURN), ("key", VK_ESCAPE)]
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_fill_does_not_require_cell_or_table_bounds(
    editable_cell: CellFixture,
) -> None:
    api, window, _windows, _target = editable_cell
    cell = (
        window.get_by_name("Editable table").as_table().cell(TARGET_ROW, TARGET_COLUMN)
    )

    cell.fill("without geometry", timeout=1_000)

    assert cell.text_content() == "without geometry"
    assert api.live_ref_count == 0


def test_fill_deletes_every_utf16_code_unit_from_the_original_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = "A😀B"
    api, window, windows, _target = _attach(
        monkeypatch,
        writable=True,
        initial=original,
    )
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        cell.fill("replacement", timeout=1_000)

        delete_call = next(call for call in windows.calls if call[0] == "repeat_key")
        assert delete_call == ("repeat_key", VK_DELETE, 4)
        assert cell.text_content() == "replacement"
    finally:
        api.close()


def test_fill_propagates_text_input_error_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, window, windows, _target = _attach(monkeypatch, writable=True)
    windows.text_error = OSError("text input failed")
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        with pytest.raises(OSError, match="text input failed"):
            cell.fill("new value", timeout=1_000)

        assert windows.calls[-2:] == [("text", "new value"), ("key", VK_ESCAPE)]
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_fill_preserves_keyboard_error_and_cancels_open_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, window, windows, _target = _attach(monkeypatch, writable=True)
    windows.key_errors[VK_RETURN] = OSError("Enter failed")
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        with pytest.raises(OSError, match="Enter failed"):
            cell.fill("new value", timeout=1_000)

        assert windows.calls[-2:] == [("key", VK_RETURN), ("key", VK_ESCAPE)]
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_fill_reports_unsupported_when_enter_does_not_change_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, window, windows, _target = _attach(monkeypatch, writable=True, commit=False)
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        with pytest.raises(
            UnsupportedActionError, match="did not accept in-place editing"
        ):
            cell.fill("uncommitted", timeout=100)

        assert windows.calls[-1] == ("key", VK_ESCAPE)
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_fill_times_out_when_model_commits_an_unexpected_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, window, _windows, _target = _attach(
        monkeypatch,
        writable=True,
        committed_value="normalized",
    )
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        with pytest.raises(LocatorTimeoutError, match="cell text updated"):
            cell.fill("requested", timeout=100)
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_fill_requires_a_string_value(editable_cell: CellFixture) -> None:
    _api, window, windows, _target = editable_cell
    cell = (
        window.get_by_name("Editable table").as_table().cell(TARGET_ROW, TARGET_COLUMN)
    )

    with pytest.raises(TypeError, match="fill\\(\\) value must be a string"):
        cell.fill(123)  # type: ignore[arg-type]
    assert windows.calls == []
