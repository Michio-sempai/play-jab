"""Portable form, table, event, and partial-ownership contracts."""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable, Iterator
from typing import cast

import pytest

from play_jab._native.backend import ContextInfo, TableInfo
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    JavaVmExitedError,
    LocatorError,
    LocatorTimeoutError,
    NativeCallError,
    StrictModeViolation,
    TableIndexError,
)
from play_jab.sync_api import JavaWindow, PlayJab

from .conftest import FakeWindowBackend, install_fake_runtime

PID = 4242
HWND = 0xCAFE
EVENT_TIMEOUT = 2.0
SELECTION_OVERFLOW = 65
EXPECTED_TOGGLE_ACTIONS = 2
TABLE_SIZE = 2


class _ContractBackend(FakeBackend):
    """Model row selection separately from the flattened cell index surface."""

    def add_accessible_selection(self, vm_id: int, context: int, index: int) -> None:
        node = self._resolve(vm_id, context)
        if node is not None and node.name == "Nested Role":
            node.selected_children.add(index)
            return
        if (
            node is not None
            and node.table_cells is not None
            and index < len(node.table_cells)
        ):
            node.selected_rows.add(index)
            return
        super().add_accessible_selection(vm_id, context, index)

    def remove_accessible_selection(
        self,
        vm_id: int,
        context: int,
        index: int,
    ) -> None:
        node = self._resolve(vm_id, context)
        if (
            node is not None
            and node.table_cells is not None
            and index < len(node.table_cells)
        ):
            node.selected_rows.discard(index)
            return
        super().remove_accessible_selection(vm_id, context, index)


def _states(*values: str) -> str:
    return ",".join(values)


def _table_node() -> FakeNode:
    cells = [
        [
            FakeNode(name="r0c0", role_en_us="label"),
            FakeNode(
                name="r0c1",
                role_en_us="label",
                accessible_text=True,
                text="text-01",
            ),
        ],
        [
            FakeNode(name="r1c0", role_en_us="label"),
            FakeNode(name="Processing", role_en_us="label"),
        ],
    ]
    row_header = FakeNode(
        role_en_us="row header",
        table_cells=[
            [FakeNode(name="row-0", role_en_us="label")],
            [FakeNode(name="row-1", role_en_us="label")],
        ],
    )
    column_header = FakeNode(
        role_en_us="header",
        table_cells=[
            [
                FakeNode(name="column-0", role_en_us="label"),
                FakeNode(name="column-1", role_en_us="label"),
            ]
        ],
    )
    return FakeNode(
        name="Orders",
        role_en_us="table",
        states_en_us=_states("enabled", "visible", "showing"),
        accessible_selection=True,
        table_cells=cells,
        selected_rows={1},
        selected_columns={0},
        row_header=row_header,
        column_header=column_header,
    )


def _root() -> tuple[FakeNode, dict[str, FakeNode]]:
    text = FakeNode(
        name="Username",
        description="Account name",
        role_en_us="text",
        states_en_us=_states("enabled", "visible", "showing", "editable"),
        accessible_component=True,
        accessible_text=True,
        text="initial",
        x=10,
        y=20,
        width=30,
        height=40,
    )
    password = FakeNode(
        name="top-secret-name",
        description="top-secret-description",
        role_en_us="password text",
        states_en_us=_states("enabled", "visible", "showing", "editable"),
        accessible_component=True,
        accessible_text=True,
        text="top-secret-text",
    )
    checkbox = FakeNode(
        name="Remember",
        role_en_us="check box",
        states_en_us=_states("enabled", "visible", "showing"),
        accessible_action=True,
        actions=("toggle",),
    )
    options = [
        FakeNode(
            name=name,
            role_en_us="list item",
            states_en_us="selected" if name == "Viewer" else "",
        )
        for name in ("Viewer", "Editor", "Admin")
    ]
    selection = FakeNode(
        name="Role",
        role_en_us="combo box",
        states_en_us=_states("enabled", "visible", "showing"),
        accessible_selection=True,
        children=options,
    )
    nested_options = [
        FakeNode(
            name=name,
            role_en_us="label",
            states_en_us="selected" if name == "Viewer" else "",
        )
        for name in ("Viewer", "Editor", "Admin")
    ]
    nested_list = FakeNode(
        role_en_us="list",
        accessible_selection=True,
        children=nested_options,
    )
    nested_selection = FakeNode(
        name="Nested Role",
        role_en_us="combo box",
        states_en_us=_states("enabled", "visible", "showing"),
        accessible_selection=True,
        children=[
            FakeNode(
                role_en_us="popup menu",
                children=[
                    FakeNode(
                        role_en_us="scroll pane",
                        children=[
                            FakeNode(role_en_us="viewport", children=[nested_list])
                        ],
                    )
                ],
            )
        ],
    )
    table = _table_node()
    root = FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us=_states("enabled", "visible", "showing"),
        children=[text, password, checkbox, selection, nested_selection, table],
    )
    return root, {
        "text": text,
        "password": password,
        "checkbox": checkbox,
        "selection": selection,
        "nested_selection": nested_selection,
        "nested_list": nested_list,
        "table": table,
    }


@pytest.fixture
def form_table_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]]]:
    root, nodes = _root()
    backend = _ContractBackend({HWND: root})
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
        pump_interval=0.001,
    )
    api = PlayJab(timeout=50)
    api.__enter__()
    try:
        window = api.attach(pid=PID).window(hwnd=HWND)
        yield api, window, backend, nodes
    finally:
        api.close()


def test_fill_replaces_text_content_with_unicode(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, _nodes = form_table_api
    field = window.get_by_name("Username")

    field.fill("Привет, 世界 👋")

    assert field.text_content() == "Привет, 世界 👋"
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_clear_empties_the_text(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, _nodes = form_table_api
    field = window.get_by_name("Username")

    field.clear()

    assert field.text_content() == ""
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_focus_sets_the_native_focused_state_and_is_reflected_in_states(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, nodes = form_table_api
    field = window.get_by_name("Username")

    field.focus()

    assert nodes["text"].focused
    states = cast("frozenset[str]", field.get_attribute("states"))
    assert "focused" in states
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("name", "Username"),
        ("description", "Account name"),
        ("role", "text"),
        ("bounds", (10, 20, 30, 40)),
        ("visible", True),
        ("enabled", True),
        ("checked", False),
        ("selected", False),
    ],
)
def test_get_attribute_reads_the_matching_facet(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
    attribute: str,
    expected: object,
) -> None:
    _api, window, _backend, _nodes = form_table_api
    field = window.get_by_name("Username")

    assert field.get_attribute(attribute) == expected


def test_get_attribute_rejects_an_unsupported_name(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    _api, window, _backend, _nodes = form_table_api
    field = window.get_by_name("Username")

    with pytest.raises(ValueError, match="unsupported attribute"):
        field.get_attribute("secret")


def test_password_is_explicitly_readable_but_redacted_everywhere_diagnostic(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, _ = form_table_api
    password = window.get_by_role("password text")

    assert password.text_content() == "top-secret-text"
    snapshot = password.snapshot()
    assert snapshot.name == "<redacted>"
    assert snapshot.description == "<redacted>"
    password.fill("новый-пароль-秘密")
    assert password.text_content() == "новый-пароль-秘密"

    diagnostics = window.dump()
    for secret in (
        "top-secret-name",
        "top-secret-description",
        "top-secret-text",
        "новый-пароль-秘密",
    ):
        assert secret not in diagnostics
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_check_and_uncheck_are_idempotent(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    _api, window, backend, _nodes = form_table_api
    checkbox = window.get_by_name("Remember")

    checkbox.check()
    checkbox.check()
    assert checkbox.is_checked()
    checkbox.uncheck()
    checkbox.uncheck()
    assert not checkbox.is_checked()
    assert len(backend.performed_actions) == EXPECTED_TOGGLE_ACTIONS


def test_select_option_accepts_a_name_or_a_zero_based_index(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    _api, window, _backend, nodes = form_table_api
    options = window.get_by_name("Role")

    assert options.get_by_name("Viewer").is_selected()
    options.select_option("Editor")
    assert nodes["selection"].selected_children == {1}
    options.select_option(2)
    assert nodes["selection"].selected_children == {2}


def test_select_option_by_name_is_strict(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    _api, window, _backend, nodes = form_table_api
    options = window.get_by_name("Role")

    with pytest.raises(StrictModeViolation, match="0 direct children"):
        options.select_option("Missing")
    nodes["selection"].children[0].name = "Admin"
    with pytest.raises(StrictModeViolation, match="2 direct children"):
        options.select_option("Admin")


def test_select_option_uses_a_nested_combo_box_list(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, nodes = form_table_api
    options = window.get_by_name("Nested Role")

    options.select_option("Editor")
    assert nodes["nested_selection"].selected_children == {1}
    options.select_option(2)
    assert nodes["nested_selection"].selected_children == {2}
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_nested_combo_box_option_name_is_strict(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    _api, window, _backend, nodes = form_table_api
    options = window.get_by_name("Nested Role")

    with pytest.raises(StrictModeViolation, match="0 nested options"):
        options.select_option("Missing")
    nodes["nested_list"].children[0].name = "Admin"
    with pytest.raises(StrictModeViolation, match="2 nested options"):
        options.select_option("Admin")


def test_nested_combo_box_rejects_an_out_of_range_index(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    _api, window, _backend, _nodes = form_table_api

    with pytest.raises(LocatorError, match="outside the available children"):
        window.get_by_name("Nested Role").select_option(3)


def test_select_option_rejects_a_bool_masquerading_as_an_index(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    _api, window, _backend, _nodes = form_table_api
    options = window.get_by_name("Role")

    with pytest.raises(TypeError, match="option"):
        options.select_option(True)


def test_table_reads_cells_headers_and_selection(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, _backend, _nodes = form_table_api
    table = window.get_by_name("Orders").as_table()

    assert table.row_count() == TABLE_SIZE
    assert table.column_count() == TABLE_SIZE
    assert table.cell(0, 1).text_content() == "text-01"
    assert table.row_header(1).text_content() == "row-1"
    assert table.column_header(0).text_content() == "column-0"
    assert table.selected_rows() == (1,)
    assert table.selected_columns() == (0,)
    snapshot = table.snapshot()
    assert snapshot.cells == (("r0c0", "text-01"), ("r1c0", "Processing"))
    assert snapshot.selected_rows == (1,)
    assert snapshot.selected_columns == (0,)

    assert api.live_ref_count == 0


def test_select_row_and_unselect_row_mutate_the_row_selection(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, _backend, _nodes = form_table_api
    table = window.get_by_name("Orders").as_table()

    table.unselect_row(1)
    assert table.selected_rows() == ()
    table.select_row(0)
    assert table.selected_rows() == (0,)

    assert api.live_ref_count == 0


@pytest.mark.parametrize(
    "operate",
    [
        lambda table: table.cell(-1, 0),
        lambda table: table.cell(0, -1),
        lambda table: table.cell(2, 0).text_content(),
        lambda table: table.cell(0, 2).text_content(),
        lambda table: table.row_header(2).text_content(),
        lambda table: table.column_header(2).text_content(),
        lambda table: table.select_row(2),
    ],
    ids=[
        "negative-row",
        "negative-column",
        "row-past-end",
        "column-past-end",
        "row-header-past-end",
        "column-header-past-end",
        "select-row-past-end",
    ],
)
def test_table_index_errors_reject_negative_and_out_of_range_access(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
    operate: Callable[[object], object],
) -> None:
    _api, window, _backend, _nodes = form_table_api
    table = window.get_by_name("Orders").as_table()

    with pytest.raises(TableIndexError):
        operate(table)


def test_cell_select_and_unselect_toggle_is_selected(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, nodes = form_table_api
    nodes["table"].selected_rows.clear()
    nodes["table"].selected_columns.clear()
    cell = window.get_by_name("Orders").as_table().cell(1, 1)

    assert not cell.is_selected()
    cell.select()
    assert cell.is_selected()
    cell.unselect()
    assert not cell.is_selected()

    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_wait_for_text_wakes_on_a_native_event_from_another_thread(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, nodes = form_table_api
    cell = window.get_by_name("Orders").as_table().cell(1, 1)

    finished = threading.Event()
    failures: list[BaseException] = []

    def wait() -> None:
        try:
            cell.wait_for_text("Done", timeout=1_000)
        except BaseException as error:
            failures.append(error)
        finally:
            finished.set()

    baseline = backend.acquired
    thread = threading.Thread(target=wait, daemon=True)
    thread.start()
    deadline = time.monotonic() + EVENT_TIMEOUT
    while backend.acquired == baseline and time.monotonic() < deadline:
        time.sleep(0.001)
    nodes["table"].table_cells[1][1].name = "Done"  # type: ignore[index]
    backend.emit_event()
    assert finished.wait(EVENT_TIMEOUT)
    thread.join(EVENT_TIMEOUT)
    assert failures == []

    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_wait_for_text_times_out_when_the_value_never_matches(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, _nodes = form_table_api
    cell = window.get_by_name("Orders").as_table().cell(1, 1)

    with pytest.raises(LocatorTimeoutError, match="last='Processing'"):
        cell.wait_for_text("Never", timeout=0)

    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_selection_overflow_reports_the_native_count_without_leaking(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, nodes = form_table_api
    nodes["table"].selected_rows = set(range(SELECTION_OVERFLOW))

    with pytest.raises(NativeCallError) as caught:
        window.get_by_name("Orders").as_table().selected_rows()
    assert caught.value.function == "getAccessibleTableRowSelections"
    assert caught.value.arguments["native_count"] == SELECTION_OVERFLOW
    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_callback_wakes_waiters_and_vm_shutdown_invalidates_owned_refs() -> None:
    root, _ = _root()
    backend = FakeBackend({HWND: root})
    bridge = BridgeRuntime(lambda: backend, pump_interval=0.001)
    bridge.start()
    try:
        woke = threading.Event()

        def wait() -> None:
            bridge.wait_for_event(EVENT_TIMEOUT)
            woke.set()

        thread = threading.Thread(target=wait, daemon=True)
        thread.start()
        backend.emit_event()
        assert woke.wait(EVENT_TIMEOUT)
        thread.join(EVENT_TIMEOUT)

        ref = bridge.context_from_hwnd(HWND)
        backend.emit_vm_shutdown()
        deadline = time.monotonic() + EVENT_TIMEOUT
        while not ref.closed and time.monotonic() < deadline:
            time.sleep(0.001)
        assert ref.closed
        assert bridge.live_ref_count == 0
        with pytest.raises(JavaVmExitedError, match="has exited"):
            bridge.context_info(ref)
    finally:
        bridge.close()


class _PartialTableBackend(FakeBackend):
    def get_accessible_table_info(
        self,
        vm_id: int,
        context: int,
    ) -> TableInfo | None:
        node = self._resolve(vm_id, context)
        if node is None or node.table_cells is None:
            return None
        columns = len(node.table_cells[0]) if node.table_cells else 0
        return TableInfo(
            caption=0,
            summary=0,
            row_count=len(node.table_cells),
            column_count=columns,
            context=self._mint(node),
            table=0,
        )


def test_partial_table_info_failure_releases_every_returned_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = _root()
    backend = _PartialTableBackend({HWND: root})
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
        pump_interval=0.001,
    )
    api = PlayJab(timeout=0)
    try:
        api.__enter__()
        table = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Orders").as_table()
        with pytest.raises(NativeCallError, match="missing handles"):
            table.row_count()
        assert api.live_ref_count == 0
        assert backend.acquired == backend.released
    finally:
        api.close()


class _AsyncCheckboxBackend(FakeBackend):
    """A checkbox whose visible state lags the actual native toggle.

    `FakeBackend.do_accessible_actions` mutates state synchronously, so every
    other test's postcondition (``sync_api.py:1064-1087``) is satisfied on the
    very first read and the retry loop never actually retries - it is
    entirely unexercised by the rest of the unit suite (see
    unit-tests-review.md finding K-5). This backend masks a freshly-set
    ``checked`` state
    out of the first `delay` reads that would otherwise report it, standing
    in for a real Swing listener that applies the change on a later EDT tick.
    """

    def __init__(self, windows: dict[int, FakeNode], *, delay: int) -> None:
        super().__init__(windows)
        self.delay = delay
        self.masked_reads = 0

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        info = super().get_accessible_context_info(vm_id, context)
        if info is None or "checked" not in info.states_en_us:
            return info
        if self.masked_reads >= self.delay:
            return info
        self.masked_reads += 1
        visible_states = ",".join(
            state for state in info.states_en_us.split(",") if state != "checked"
        )
        return dataclasses.replace(info, states_en_us=visible_states)


def _checkbox_tree() -> FakeNode:
    checkbox = FakeNode(
        name="Remember",
        role_en_us="check box",
        states_en_us="enabled,visible,showing",
        accessible_action=True,
        actions=("toggle",),
    )
    return FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us="enabled,visible,showing",
        children=[checkbox],
    )


def test_check_retries_the_postcondition_until_the_state_becomes_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _AsyncCheckboxBackend({HWND: _checkbox_tree()}, delay=2)
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    with PlayJab(timeout=2_000) as api:
        checkbox = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Remember")
        checkbox.check()
        assert backend.masked_reads == backend.delay
        assert checkbox.is_checked()
        assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_check_raises_a_postcondition_timeout_when_the_state_never_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _AsyncCheckboxBackend({HWND: _checkbox_tree()}, delay=1_000_000)
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    with PlayJab(timeout=2_000) as api:
        checkbox = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Remember")
        with pytest.raises(LocatorTimeoutError, match="checked") as caught:
            checkbox.check(timeout=50)
        assert caught.value.expected == "checked"
        assert api.live_ref_count == 0
    assert backend.acquired == backend.released
