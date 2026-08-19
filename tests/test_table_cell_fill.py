"""Contract tests for keyboard-driven ``TableCellLocator.fill()``."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    InputNotAvailableError,
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
_MIN_RETRIED_F2_PRESSES = 2

CellFixture = tuple[PlayJab, JavaWindow, FakeWindowBackend, FakeNode]


class _FocusRace:
    """Simulates whether a Java-side ``requestFocus()`` call actually grants
    real focus before a synthetic F2 is dispatched.

    Mirrors the contract confirmed on real JAB by
    ``SwingFixtureContractTest``: ``BasicTableUI``'s F2 binding
    (``"startEditing"``) checks ``table.hasFocus()`` and, if false, only
    re-requests focus instead of opening the editor. A ``requestFocus()``
    issued before the window is even the OS foreground window does not
    count; and even a correctly-ordered request may need more than one
    round to "stick" (``settle_after``), modelling EDT-scheduling lag that
    exists independently of call order.
    """

    def __init__(self, *, settle_after: int = 0) -> None:
        self.settle_after = settle_after
        self.has_real_focus = False
        self._foreground_called = False
        self._ready_requests = 0

    def note_foreground(self) -> None:
        self._foreground_called = True

    def note_focus_request(self) -> None:
        if not self._foreground_called:
            self.has_real_focus = False
            return
        self._ready_requests += 1
        self.has_real_focus = self._ready_requests > self.settle_after


class _RacyBackend(FakeBackend):
    """``FakeBackend`` that reports every ``request_focus()`` to a ``_FocusRace``."""

    def __init__(self, roots: dict[int, FakeNode], race: _FocusRace) -> None:
        super().__init__(roots)
        self._race = race

    def request_focus(self, vm_id: int, context: int) -> bool:
        result = super().request_focus(vm_id, context)
        self._race.note_focus_request()
        return result


class _RacyWindowBackend(FakeWindowBackend):
    """``FakeWindowBackend`` that reports ``set_foreground_window()`` calls
    to a ``_FocusRace``.
    """

    def __init__(
        self,
        titles: dict[int, str] | None = None,
        *,
        pid: int = PID,
        on_key: Callable[[int], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        race: _FocusRace,
    ) -> None:
        super().__init__(titles, pid=pid, on_key=on_key, on_text=on_text)
        self._race = race

    def set_foreground_window(self, hwnd: int) -> None:
        super().set_foreground_window(hwnd)
        self._race.note_foreground()


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


def _attach(  # noqa: PLR0913 -- independent config knobs for a test fixture
    monkeypatch: pytest.MonkeyPatch,
    *,
    writable: bool,
    commit: bool = True,
    committed_value: str | None = None,
    initial: str = "old",
    focus_race: _FocusRace | None = None,
) -> CellFixture:
    table, target = _table_node(writable=writable, initial=initial)
    roots = {
        HWND: FakeNode(
            name="Fixture",
            role_en_us="frame",
            states_en_us="enabled,visible,showing",
            children=[table],
        )
    }
    backend: FakeBackend = (
        FakeBackend(roots) if focus_race is None else _RacyBackend(roots, focus_race)
    )

    def handle_key(vk_code: int) -> None:
        if vk_code == VK_F2 and target.value == "writable":
            if focus_race is not None and not focus_race.has_real_focus:
                return
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
    windows: FakeWindowBackend
    if focus_race is None:
        windows = FakeWindowBackend(
            {HWND: "Fixture"}, pid=PID, on_key=handle_key, on_text=handle_text
        )
    else:
        windows = _RacyWindowBackend(
            {HWND: "Fixture"},
            pid=PID,
            on_key=handle_key,
            on_text=handle_text,
            race=focus_race,
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

        cell.fill(value, force_input=True, timeout=1_000)

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


def test_fill_requests_the_window_foreground_before_asking_for_java_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K-5 root cause: on real JAB, ``Component.requestFocus()`` only sticks
    reliably once the OS window already owns foreground - requesting Java
    focus before the window is foreground (the original call order) races a
    focus request that may never land before the synthetic keys that follow
    are dispatched, so they land on whatever actually has real OS focus
    instead of the table.
    """
    race = _FocusRace()
    api, window, windows, _target = _attach(monkeypatch, writable=True, focus_race=race)
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        cell.fill("value", force_input=True, timeout=500)

        assert cell.text_content() == "value"
        assert windows.calls[0] == ("foreground", HWND)
        assert windows.calls[1] == ("key", VK_F2)
    finally:
        api.close()


def test_fill_retries_the_whole_activation_sequence_after_a_transient_focus_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K-5 self-healing: even with the correct call order (previous test),
    a single correctly-ordered focus request may still not "stick" before F2
    fires (EDT-scheduling lag independent of order). One failed attempt must
    not burn the whole deadline reading text that will never change - the
    entire activation (select/foreground/focus/F2) must retry.
    """
    race = _FocusRace(settle_after=1)
    api, window, windows, _target = _attach(monkeypatch, writable=True, focus_race=race)
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        cell.fill("value", force_input=True, timeout=2_000)

        assert cell.text_content() == "value"
        f2_presses = windows.calls.count(("key", VK_F2))
        assert f2_presses >= _MIN_RETRIED_F2_PRESSES
        assert api.live_ref_count == 0
    finally:
        api.close()


def test_fill_raises_and_cancels_when_cell_never_enters_edit_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely non-editable cell fails cleanly once the deadline is
    exhausted. Confirmed against real JAB (see spec.md) that a standard
    JTable cell's AccessibleContext never exposes any observable "editing"
    signal, on real Swing not just this fake's model - so unlike the first
    version of this fix, fill() cannot confirm the editor opened before
    sending Home/Delete/text/Enter, and the residual risk of those landing
    on a genuinely non-editable table is inherent to the widget, not a bug
    left in this code. What the retry loop *can* and does guarantee: it
    still fails cleanly once the deadline is exhausted rather than hanging,
    and it does not send the same blind sequence forever within one call.
    """
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
            cell.fill("new value", force_input=True, timeout=100)

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

    cell.fill("without geometry", force_input=True, timeout=1_000)

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

        cell.fill("replacement", force_input=True, timeout=1_000)

        delete_call = next(call for call in windows.calls if call[0] == "repeat_key")
        assert delete_call == ("repeat_key", VK_DELETE, 4)
        assert cell.text_content() == "replacement"
    finally:
        api.close()


def test_fill_wraps_text_input_error_in_input_not_available_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Win32 failures inside fill() must stay inside the PlayJabError
    hierarchy - a plain ``except PlayJabError:`` used to miss this one.
    """
    api, window, windows, _target = _attach(monkeypatch, writable=True)
    windows.text_error = OSError("text input failed")
    try:
        cell = (
            window.get_by_name("Editable table")
            .as_table()
            .cell(TARGET_ROW, TARGET_COLUMN)
        )

        with pytest.raises(InputNotAvailableError, match="text input failed"):
            cell.fill("new value", force_input=True, timeout=1_000)

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

        with pytest.raises(InputNotAvailableError, match="Enter failed"):
            cell.fill("new value", force_input=True, timeout=1_000)

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
            cell.fill("uncommitted", force_input=True, timeout=100)

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
            cell.fill("requested", force_input=True, timeout=100)
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


def test_fill_without_force_input_raises_before_any_win32_call(
    editable_cell: CellFixture,
) -> None:
    """N-1: `TableCellLocator.fill()` sends real OS-level input (foreground
    window changes, synthetic keystrokes), unlike `Locator.fill()`. A caller
    must opt in explicitly, mirroring `click(opens_window=True)`.
    """
    _api, window, windows, _target = editable_cell
    cell = (
        window.get_by_name("Editable table").as_table().cell(TARGET_ROW, TARGET_COLUMN)
    )

    with pytest.raises(InputNotAvailableError, match="force_input"):
        cell.fill("value", timeout=1_000)
    assert windows.calls == []
