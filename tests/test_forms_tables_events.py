"""Portable form, table, event, and partial-ownership contracts."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest

from play_jab import sync_api
from play_jab._native.backend import TableInfo
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    JavaVmExitedError,
    LocatorTimeoutError,
    NativeCallError,
    StrictModeViolation,
    TableIndexError,
)
from play_jab.sync_api import JavaWindow, PlayJab

PID = 4242
HWND = 0xCAFE
EVENT_TIMEOUT = 2.0
SELECTION_OVERFLOW = 65
EXPECTED_TOGGLE_ACTIONS = 2
TABLE_SIZE = 2


class _Windows:
    def enum_windows(self) -> list[int]:
        return [HWND]

    def get_window_title(self, hwnd: int) -> str:
        assert hwnd == HWND
        return "Fixture"

    def get_window_pid(self, hwnd: int) -> int:
        assert hwnd == HWND
        return PID


class _ContractBackend(FakeBackend):
    """Model row selection separately from the flattened cell index surface."""

    def add_accessible_selection(self, vm_id: int, context: int, index: int) -> None:
        node = self._resolve(vm_id, context)
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
    table = _table_node()
    root = FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us=_states("enabled", "visible", "showing"),
        children=[text, password, checkbox, selection, table],
    )
    return root, {
        "text": text,
        "password": password,
        "checkbox": checkbox,
        "selection": selection,
        "table": table,
    }


@pytest.fixture
def form_table_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]]]:
    root, nodes = _root()
    backend = _ContractBackend({HWND: root})
    runtime = BridgeRuntime(lambda: backend, pump_interval=0.001)
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", _Windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    api = PlayJab(timeout=50)
    api.__enter__()
    try:
        window = api.attach(pid=PID).window(hwnd=HWND)
        yield api, window, backend, nodes
    finally:
        api.close()


def test_unicode_fill_clear_focus_attributes_and_reference_cleanup(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, nodes = form_table_api
    field = window.get_by_name("Username")

    field.fill("Привет, 世界 👋")
    assert field.text_content() == "Привет, 世界 👋"
    field.focus()
    assert nodes["text"].focused
    field.clear()
    assert field.text_content() == ""

    assert field.get_attribute("name") == "Username"
    assert field.get_attribute("description") == "Account name"
    assert field.get_attribute("role") == "text"
    assert field.get_attribute("bounds") == (10, 20, 30, 40)
    assert field.get_attribute("visible") is True
    assert field.get_attribute("enabled") is True
    assert field.get_attribute("checked") is False
    assert field.get_attribute("selected") is False
    assert "focused" in field.get_attribute("states")
    with pytest.raises(ValueError, match="unsupported attribute"):
        field.get_attribute("secret")

    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


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


def test_checkbox_is_idempotent_and_options_are_strict_and_zero_based(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, backend, nodes = form_table_api
    checkbox = window.get_by_name("Remember")

    checkbox.check()
    checkbox.check()
    assert checkbox.is_checked()
    checkbox.uncheck()
    checkbox.uncheck()
    assert not checkbox.is_checked()
    assert len(backend.performed_actions) == EXPECTED_TOGGLE_ACTIONS

    options = window.get_by_name("Role")
    assert window.get_by_name("Viewer").is_selected()
    options.select_option("Editor")
    assert nodes["selection"].selected_children == {1}
    options.select_option(2)
    assert nodes["selection"].selected_children == {2}
    with pytest.raises(StrictModeViolation, match="0 direct children"):
        options.select_option("Missing")
    with pytest.raises(StrictModeViolation, match="2 direct children"):
        nodes["selection"].children[0].name = "Admin"
        options.select_option("Admin")
    with pytest.raises(TypeError, match="option"):
        options.select_option(True)

    assert api.live_ref_count == 0
    assert backend.acquired == backend.released


def test_table_snapshot_headers_indices_and_selection_reads(
    form_table_api: tuple[PlayJab, JavaWindow, FakeBackend, dict[str, FakeNode]],
) -> None:
    api, window, _backend, _ = form_table_api
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
    table.unselect_row(1)
    assert table.selected_rows() == ()
    table.select_row(0)
    assert table.selected_rows() == (0,)

    for row, column in ((-1, 0), (0, -1)):
        with pytest.raises(TableIndexError):
            table.cell(row, column)
    with pytest.raises(TableIndexError):
        table.cell(2, 0).text_content()
    with pytest.raises(TableIndexError):
        table.cell(0, 2).text_content()
    with pytest.raises(TableIndexError):
        table.row_header(2).text_content()
    with pytest.raises(TableIndexError):
        table.column_header(2).text_content()
    with pytest.raises(TableIndexError):
        table.select_row(2)

    assert api.live_ref_count == 0


def test_cell_selection_and_callback_assisted_wait(
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

    with pytest.raises(LocatorTimeoutError, match="last='Done'"):
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
    runtime = BridgeRuntime(lambda: backend, pump_interval=0.001)
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", _Windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
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
