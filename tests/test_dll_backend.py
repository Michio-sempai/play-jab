"""``DllBackend`` driven by a stand-in for the DLL.

The real Access Bridge cannot be exercised without a JVM, but everything
:class:`DllBackend` itself does - filling out-parameters, deciding what counts
as failure, decoding the struct, and not truncating a 64-bit cookie - is
independent of who answers the calls. So the calls are answered by a stub that
writes into the very ``byref`` buffers the backend passed it.

Windows-only: the backend binds ``user32``/``kernel32`` in its constructor.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from typing import Any, cast

import pytest

from play_jab._native import backend as backend_module
from play_jab._native.backend import DllBackend
from play_jab._native.types import (
    MAX_STRING_SIZE,
    MAX_TABLE_SELECTIONS,
    MAX_VISIBLE_CHILDREN,
    AccessibleActions,
    AccessibleActionsToDo,
    AccessibleContext,
    AccessibleContextInfo,
    AccessibleTableCellInfo,
    AccessibleTableInfo,
    AccessibleTextInfo,
    VisibleChildrenInfo,
    jint,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="DllBackend binds Windows system libraries"
)

TRUE = 1
FALSE = 0
VM_ID = 42
CONTEXT = 0x1234_5678
HUGE_COOKIE = 0x7FFF_FFFF_FFFF_FFFF
WINDOW_HWND = 0x9ABC
CHILD_COOKIE = 0xFEED
PARENT_COOKIE = 0xF00D
BUTTON_BOUNDS = (10, 20, 80, 24)
INTERFACE_FLAGS = 5
INDEX_IN_PARENT = 3
# What the runtime's readiness loop passes: isJavaWindow(NULL).
PROBE_HWND = 0


def out_parameter(reference: Any, ctype: type) -> Any:
    """Reach through a ``byref`` argument the way the DLL writes through it."""
    return ctypes.cast(reference, ctypes.POINTER(ctype)).contents


def fire_callback(stub: StubDll, name: str, *args: object) -> None:
    """Invoke a registered event-callback function pointer, as the DLL would."""
    callback = cast("Callable[..., None]", stub.registered_callbacks[name])
    callback(*args)


class StubDll:
    """Answers every export `DllBackend` calls; each response is set by the test."""

    def __init__(self) -> None:
        self._handle = 0
        self.released: list[tuple[int, int]] = []
        self.context_from_hwnd_result = TRUE
        self.context_from_hwnd_cookie = CONTEXT
        self.context_info_result = TRUE
        self.child_cookie = CHILD_COOKIE
        self.parent_cookie = PARENT_COOKIE
        self.hwnd_result = WINDOW_HWND
        self.accessible_actions_result = TRUE
        self.actions = ("click", "toggle")
        self.actions_count: int | None = None
        self.do_actions_result = TRUE
        self.failure_index = -1
        self.actions_done: tuple[str, ...] | None = None
        self.probe_error: Exception | None = None

        # -- text -----------------------------------------------------
        self.text_info_result = TRUE
        self.text_char_count = 0
        self.text_source = ""
        self.text_range_calls: list[tuple[int, int, int]] = []
        self.text_range_fail_at: int | None = None

        # -- value ------------------------------------------------------
        self.value_current: str | None = "1"
        self.value_minimum: str | None = "0"
        self.value_maximum: str | None = "10"

        # -- text entry / focus ------------------------------------------
        self.set_text_result = TRUE
        self.set_text_calls: list[tuple[int, int, str]] = []
        self.focus_result = TRUE
        self.focus_calls: list[tuple[int, int]] = []

        # -- selection --------------------------------------------------
        self.selection_count = 0
        self.selection_values: dict[int, int] = {}
        self.child_selected: dict[int, bool] = {}
        self.add_selection_calls: list[tuple[int, int, int]] = []
        self.remove_selection_calls: list[tuple[int, int, int]] = []
        self.clear_selection_calls: list[tuple[int, int]] = []

        # -- table --------------------------------------------------------
        self.table_info_result = TRUE
        self.table_info_values = {
            "caption": 0,
            "summary": 0,
            "rowCount": 0,
            "columnCount": 0,
            "accessibleContext": 0,
            "accessibleTable": 0,
        }
        self.table_cell_result = TRUE
        self.table_cell_values = {
            "accessibleContext": 0,
            "index": 0,
            "row": 0,
            "column": 0,
            "rowExtent": 1,
            "columnExtent": 1,
            "isSelected": FALSE,
        }
        self.table_header_result = {"row": TRUE, "column": TRUE}
        self.table_header_values = {
            "row": dict(self.table_info_values),
            "column": dict(self.table_info_values),
        }
        self.table_selection_count = {"row": 0, "column": 0}
        self.table_selection_values: dict[str, tuple[int, ...]] = {
            "row": (),
            "column": (),
        }
        self.table_selection_values_calls: list[str] = []

        # -- visible children ---------------------------------------------
        self.visible_children_count = 0
        # One list of cookies per page; a page of `None` simulates the DLL
        # call itself returning FALSE for that page.
        self.visible_children_pages: list[list[int] | None] = []
        # Maps page index -> forced `returnedChildrenCount`, for simulating an
        # invalid (negative or over-capacity) count on a specific page.
        self.visible_children_overrun_at_page: dict[int, int] = {}

        # -- event callbacks ------------------------------------------------
        self.registered_callbacks: dict[str, object | None] = {}
        self.raise_on_register: str | None = None

    def Windows_run(self) -> None:
        """No-op: startup sequencing is the runtime's concern, not the backend's."""

    def isJavaWindow(self, hwnd: object) -> int:
        if self.probe_error is not None:
            raise self.probe_error
        return TRUE if hwnd == WINDOW_HWND else FALSE

    def getAccessibleContextFromHWND(
        self, hwnd: int, vm_reference: object, context_reference: object
    ) -> int:
        assert hwnd == WINDOW_HWND
        out_parameter(vm_reference, ctypes.c_long).value = VM_ID
        out_parameter(
            context_reference, AccessibleContext
        ).value = self.context_from_hwnd_cookie
        return self.context_from_hwnd_result

    def getAccessibleContextInfo(
        self, vm_id: int, context: int, info_reference: object
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        if not self.context_info_result:
            return FALSE
        self.fill(out_parameter(info_reference, AccessibleContextInfo))
        return TRUE

    @staticmethod
    def fill(info: AccessibleContextInfo) -> None:
        info.name = "Сохранить \U0001f600"
        info.description = "toolbar button"
        info.role = "Schaltflache"
        info.role_en_US = "push button"
        info.states = "sichtbar,aktiviert"
        info.states_en_US = "visible,enabled"
        info.indexInParent = INDEX_IN_PARENT
        info.childrenCount = 0
        info.x, info.y, info.width, info.height = BUTTON_BOUNDS
        info.accessibleComponent = TRUE
        info.accessibleAction = TRUE
        info.accessibleSelection = FALSE
        info.accessibleText = FALSE
        info.accessibleInterfaces = INTERFACE_FLAGS

    def getAccessibleChildFromContext(
        self, vm_id: int, context: int, index: int
    ) -> int:
        assert (vm_id, context, index) == (VM_ID, CONTEXT, 0)
        return self.child_cookie

    def getAccessibleParentFromContext(self, vm_id: int, context: int) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        return self.parent_cookie

    def releaseJavaObject(self, vm_id: int, value: int) -> None:
        self.released.append((vm_id, value))

    def getHWNDFromAccessibleContext(self, vm_id: int, context: int) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        return self.hwnd_result

    def getAccessibleActions(
        self, vm_id: int, context: int, actions_reference: object
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        if not self.accessible_actions_result:
            return FALSE
        actions = out_parameter(actions_reference, AccessibleActions)
        actions.actionsCount = (
            len(self.actions) if self.actions_count is None else self.actions_count
        )
        for index, name in enumerate(self.actions):
            actions.actionInfo[index].name = name
        return TRUE

    def doAccessibleActions(
        self,
        vm_id: int,
        context: int,
        actions_reference: object,
        failure_reference: object,
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        actions = out_parameter(actions_reference, AccessibleActionsToDo)
        self.actions_done = tuple(
            actions.actions[index].name for index in range(actions.actionsCount)
        )
        out_parameter(failure_reference, jint).value = self.failure_index
        return self.do_actions_result

    # -- text -----------------------------------------------------------
    def getAccessibleTextInfo(
        self,
        vm_id: int,
        context: int,
        info_reference: object,
        _x: int,
        _y: int,
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        if not self.text_info_result:
            return FALSE
        out_parameter(
            info_reference, AccessibleTextInfo
        ).charCount = self.text_char_count
        return TRUE

    def getAccessibleTextRange(  # noqa: PLR0913, PLR0917 -- mirrors the DLL export
        self,
        vm_id: int,
        context: int,
        start: int,
        end: int,
        buffer: Any,
        buffer_len: int,
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        call_index = len(self.text_range_calls)
        self.text_range_calls.append((start, end, buffer_len))
        if self.text_range_fail_at == call_index:
            return FALSE
        buffer.value = self.text_source[start : end + 1]
        return TRUE

    # -- value ------------------------------------------------------------
    def getCurrentAccessibleValueFromContext(
        self, vm_id: int, context: int, buffer: Any, _size: int
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        if self.value_current is None:
            return FALSE
        buffer.value = self.value_current
        return TRUE

    def getMinimumAccessibleValueFromContext(
        self, vm_id: int, context: int, buffer: Any, _size: int
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        if self.value_minimum is None:
            return FALSE
        buffer.value = self.value_minimum
        return TRUE

    def getMaximumAccessibleValueFromContext(
        self, vm_id: int, context: int, buffer: Any, _size: int
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        if self.value_maximum is None:
            return FALSE
        buffer.value = self.value_maximum
        return TRUE

    # -- text entry / focus -------------------------------------------------
    def setTextContents(self, vm_id: int, context: int, text: str) -> int:
        self.set_text_calls.append((vm_id, context, text))
        return self.set_text_result

    def requestFocus(self, vm_id: int, context: int) -> int:
        self.focus_calls.append((vm_id, context))
        return self.focus_result

    # -- selection ----------------------------------------------------------
    def getAccessibleSelectionCountFromContext(self, vm_id: int, context: int) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        return self.selection_count

    def getAccessibleSelectionFromContext(
        self, vm_id: int, context: int, index: int
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        return self.selection_values.get(index, 0)

    def isAccessibleChildSelectedFromContext(
        self, vm_id: int, context: int, index: int
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        return TRUE if self.child_selected.get(index, False) else FALSE

    def addAccessibleSelectionFromContext(
        self, vm_id: int, context: int, index: int
    ) -> None:
        self.add_selection_calls.append((vm_id, context, index))

    def removeAccessibleSelectionFromContext(
        self, vm_id: int, context: int, index: int
    ) -> None:
        self.remove_selection_calls.append((vm_id, context, index))

    def clearAccessibleSelectionFromContext(self, vm_id: int, context: int) -> None:
        self.clear_selection_calls.append((vm_id, context))

    # -- table ----------------------------------------------------------
    @staticmethod
    def _fill_table_info(raw: AccessibleTableInfo, values: dict[str, int]) -> None:
        raw.caption = values["caption"]
        raw.summary = values["summary"]
        raw.rowCount = values["rowCount"]
        raw.columnCount = values["columnCount"]
        raw.accessibleContext = values["accessibleContext"]
        raw.accessibleTable = values["accessibleTable"]

    def getAccessibleTableInfo(
        self, vm_id: int, context: int, info_reference: object
    ) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        self._fill_table_info(
            out_parameter(info_reference, AccessibleTableInfo),
            self.table_info_values,
        )
        return self.table_info_result

    def getAccessibleTableCellInfo(
        self,
        vm_id: int,
        table: int,
        row: int,
        column: int,
        info_reference: object,
    ) -> int:
        cell = out_parameter(info_reference, AccessibleTableCellInfo)
        cell.accessibleContext = self.table_cell_values["accessibleContext"]
        cell.index = self.table_cell_values["index"]
        cell.row = self.table_cell_values["row"]
        cell.column = self.table_cell_values["column"]
        cell.rowExtent = self.table_cell_values["rowExtent"]
        cell.columnExtent = self.table_cell_values["columnExtent"]
        cell.isSelected = self.table_cell_values["isSelected"]
        return self.table_cell_result

    def getAccessibleTableRowHeader(
        self, vm_id: int, context: int, info_reference: object
    ) -> int:
        self._fill_table_info(
            out_parameter(info_reference, AccessibleTableInfo),
            self.table_header_values["row"],
        )
        return self.table_header_result["row"]

    def getAccessibleTableColumnHeader(
        self, vm_id: int, context: int, info_reference: object
    ) -> int:
        self._fill_table_info(
            out_parameter(info_reference, AccessibleTableInfo),
            self.table_header_values["column"],
        )
        return self.table_header_result["column"]

    def getAccessibleTableRowSelectionCount(self, vm_id: int, table: int) -> int:
        return self.table_selection_count["row"]

    def getAccessibleTableColumnSelectionCount(self, vm_id: int, table: int) -> int:
        return self.table_selection_count["column"]

    def getAccessibleTableRowSelections(
        self, vm_id: int, table: int, count: int, values: Any
    ) -> int:
        self.table_selection_values_calls.append("row")
        for index, value in enumerate(self.table_selection_values["row"][:count]):
            values[index] = value
        return TRUE

    def getAccessibleTableColumnSelections(
        self, vm_id: int, table: int, count: int, values: Any
    ) -> int:
        self.table_selection_values_calls.append("column")
        for index, value in enumerate(self.table_selection_values["column"][:count]):
            values[index] = value
        return TRUE

    # -- visible children -------------------------------------------------
    def getVisibleChildrenCount(self, vm_id: int, context: int) -> int:
        assert (vm_id, context) == (VM_ID, CONTEXT)
        return self.visible_children_count

    def getVisibleChildren(
        self, vm_id: int, context: int, start: int, info_reference: object
    ) -> int:
        page_index = start // MAX_VISIBLE_CHILDREN
        pages = self.visible_children_pages
        page = pages[page_index] if page_index < len(pages) else None
        if page is None:
            return FALSE
        raw = out_parameter(info_reference, VisibleChildrenInfo)
        raw.returnedChildrenCount = self.visible_children_overrun_at_page.get(
            page_index, len(page)
        )
        for index, cookie in enumerate(page):
            raw.children[index] = cookie
        return TRUE

    # -- event callbacks --------------------------------------------------
    def _register(self, name: str, callback: object | None) -> None:
        if callback is not None and name == self.raise_on_register:
            raise RuntimeError(f"{name} rejected the callback")
        self.registered_callbacks[name] = callback

    def setJavaShutdownFP(self, callback: object | None) -> None:
        self._register("setJavaShutdownFP", callback)

    def setPropertyChangeFP(self, callback: object | None) -> None:
        self._register("setPropertyChangeFP", callback)

    def setPropertyStateChangeFP(self, callback: object | None) -> None:
        self._register("setPropertyStateChangeFP", callback)

    def setPropertyValueChangeFP(self, callback: object | None) -> None:
        self._register("setPropertyValueChangeFP", callback)

    def setPropertyTableModelChangeFP(self, callback: object | None) -> None:
        self._register("setPropertyTableModelChangeFP", callback)

    def setPropertyTextChangeFP(self, callback: object | None) -> None:
        self._register("setPropertyTextChangeFP", callback)

    def setPropertySelectionChangeFP(self, callback: object | None) -> None:
        self._register("setPropertySelectionChangeFP", callback)

    def setPropertyVisibleDataChangeFP(self, callback: object | None) -> None:
        self._register("setPropertyVisibleDataChangeFP", callback)


@pytest.fixture
def stub() -> StubDll:
    return StubDll()


@pytest.fixture
def backend(stub: StubDll) -> DllBackend:
    return DllBackend(cast("ctypes.CDLL", stub))


def test_context_info_decodes_every_member(backend: DllBackend) -> None:
    info = backend.get_accessible_context_info(VM_ID, CONTEXT)
    assert info is not None
    assert info.name == "Сохранить \U0001f600"
    assert info.description == "toolbar button"
    assert (info.role, info.role_en_us) == ("Schaltflache", "push button")
    assert (info.states, info.states_en_us) == ("sichtbar,aktiviert", "visible,enabled")
    assert (info.x, info.y, info.width, info.height) == BUTTON_BOUNDS
    assert info.index_in_parent == INDEX_IN_PARENT
    assert info.accessible_interfaces == INTERFACE_FLAGS


def test_context_info_reports_the_flags_as_booleans(backend: DllBackend) -> None:
    """``BOOL`` is a 32-bit int; the dataclass promises ``bool``."""
    info = backend.get_accessible_context_info(VM_ID, CONTEXT)
    assert info is not None
    assert info.accessible_component is True
    assert info.accessible_action is True
    assert info.accessible_selection is False
    assert info.accessible_text is False


def test_a_false_return_means_no_context_info(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.context_info_result = FALSE
    assert backend.get_accessible_context_info(VM_ID, CONTEXT) is None


def test_attaching_to_a_window_yields_the_vm_and_the_cookie(
    backend: DllBackend,
) -> None:
    assert backend.get_accessible_context_from_hwnd(WINDOW_HWND) == (VM_ID, CONTEXT)


def test_a_full_width_cookie_is_not_truncated(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.context_from_hwnd_cookie = HUGE_COOKIE
    assert backend.get_accessible_context_from_hwnd(WINDOW_HWND) == (VM_ID, HUGE_COOKIE)


def test_a_false_return_means_no_context(backend: DllBackend, stub: StubDll) -> None:
    stub.context_from_hwnd_result = FALSE
    assert backend.get_accessible_context_from_hwnd(WINDOW_HWND) is None


def test_a_null_cookie_means_no_context_even_on_success(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.context_from_hwnd_cookie = 0
    assert backend.get_accessible_context_from_hwnd(WINDOW_HWND) is None


def test_is_java_window_answers_with_a_bool(backend: DllBackend) -> None:
    assert backend.is_java_window(WINDOW_HWND) is True
    assert backend.is_java_window(WINDOW_HWND + 1) is False


def test_navigation_returns_the_raw_cookies(backend: DllBackend) -> None:
    assert backend.get_accessible_child_from_context(VM_ID, CONTEXT, 0) == CHILD_COOKIE
    assert backend.get_accessible_parent_from_context(VM_ID, CONTEXT) == PARENT_COOKIE


def test_a_context_without_a_window_reports_zero(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.hwnd_result = 0
    assert backend.get_hwnd_from_accessible_context(VM_ID, CONTEXT) == 0


def test_release_reaches_the_dll_once_per_call(
    backend: DllBackend, stub: StubDll
) -> None:
    backend.release_java_object(VM_ID, CONTEXT)
    backend.release_java_object(VM_ID, HUGE_COOKIE)
    assert stub.released == [(VM_ID, CONTEXT), (VM_ID, HUGE_COOKIE)]


def test_accessible_actions_are_decoded_in_native_order(
    backend: DllBackend,
) -> None:
    assert backend.get_accessible_actions(VM_ID, CONTEXT) == ("click", "toggle")


def test_false_get_accessible_actions_reports_no_actions(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.accessible_actions_result = FALSE
    assert backend.get_accessible_actions(VM_ID, CONTEXT) is None


@pytest.mark.parametrize("count", [-1, 257])
def test_invalid_native_action_count_is_rejected(
    backend: DllBackend, stub: StubDll, count: int
) -> None:
    stub.actions_count = count
    assert backend.get_accessible_actions(VM_ID, CONTEXT) is None


def test_do_accessible_actions_marshals_names_and_returns_failure_index(
    backend: DllBackend, stub: StubDll
) -> None:
    assert backend.do_accessible_actions(VM_ID, CONTEXT, ("click", "toggle")) == (
        True,
        -1,
    )
    assert stub.actions_done == ("click", "toggle")


def test_do_accessible_actions_preserves_native_failure_details(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.do_actions_result = FALSE
    stub.failure_index = 1
    assert backend.do_accessible_actions(VM_ID, CONTEXT, ("click", "toggle")) == (
        False,
        1,
    )


def test_a_faulting_dll_propagates_the_error_unchanged(
    backend: DllBackend, stub: StubDll
) -> None:
    """A half-initialized bridge faults; ctypes reports that as OSError.

    The backend does not soften it - the runtime's readiness loop is what
    decides a fault is retryable.
    """
    stub.probe_error = OSError("access violation")
    with pytest.raises(OSError, match="access violation"):
        backend.is_java_window(PROBE_HWND)


def test_pumping_and_shutting_down_are_safe_to_repeat(backend: DllBackend) -> None:
    backend.pump_messages()
    backend.pump_messages()
    backend.shutdown()
    backend.shutdown()


@pytest.mark.parametrize("failure_stage", ["verify", "configure", "constructor"])
def test_load_releases_the_dll_when_backend_construction_fails(
    monkeypatch: pytest.MonkeyPatch, stub: StubDll, failure_stage: str
) -> None:
    error = RuntimeError(f"{failure_stage} failed")
    released: list[object] = []

    monkeypatch.setattr(backend_module, "load_access_bridge", lambda _path: stub)
    monkeypatch.setattr(backend_module, "_free_library", released.append)

    if failure_stage == "verify":
        monkeypatch.setattr(
            backend_module,
            "verify_exports",
            lambda *_args: (_ for _ in ()).throw(error),
        )
    elif failure_stage == "configure":
        monkeypatch.setattr(backend_module, "verify_exports", lambda *_args: None)
        monkeypatch.setattr(
            backend_module,
            "configure_functions",
            lambda *_args: (_ for _ in ()).throw(error),
        )
    else:
        monkeypatch.setattr(backend_module, "verify_exports", lambda *_args: None)
        monkeypatch.setattr(backend_module, "configure_functions", lambda *_args: None)

        def fail_init(self: DllBackend, _dll: ctypes.CDLL) -> None:
            raise error

        monkeypatch.setattr(DllBackend, "__init__", fail_init)

    with pytest.raises(RuntimeError, match=failure_stage) as caught:
        DllBackend.load("bridge.dll")

    assert caught.value is error
    assert released == [stub]


def test_load_does_not_release_the_dll_after_success(
    monkeypatch: pytest.MonkeyPatch, stub: StubDll
) -> None:
    released: list[object] = []
    monkeypatch.setattr(backend_module, "load_access_bridge", lambda _path: stub)
    monkeypatch.setattr(backend_module, "verify_exports", lambda *_args: None)
    monkeypatch.setattr(backend_module, "configure_functions", lambda *_args: None)
    monkeypatch.setattr(backend_module, "_free_library", released.append)

    loaded = DllBackend.load("bridge.dll")

    assert isinstance(loaded, DllBackend)
    assert released == []
    loaded.shutdown()
    loaded.shutdown()
    assert released == [stub]


def test_free_library_failure_does_not_mask_load_error(
    monkeypatch: pytest.MonkeyPatch, stub: StubDll
) -> None:
    original = RuntimeError("missing export")

    class RaisingFreeLibrary:
        argtypes: object = None
        restype: object = None

        def __call__(self, _handle: object) -> None:
            raise OSError("FreeLibrary failed")

    class Kernel32Stub:
        FreeLibrary = RaisingFreeLibrary()

    monkeypatch.setattr(backend_module, "load_access_bridge", lambda _path: stub)
    monkeypatch.setattr(
        backend_module, "verify_exports", lambda *_args: (_ for _ in ()).throw(original)
    )
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: Kernel32Stub(),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="missing export") as caught:
        DllBackend.load("bridge.dll")

    assert caught.value is original


# -- text ------------------------------------------------------------------
# Chunk size is bounded by MAX_STRING_SIZE-1 (1023), well below the 32_766
# short-signed-range guard, so a 1500-char text must be read in two chunks.
TEXT_LENGTH = 1500
CHUNK_SIZE = MAX_STRING_SIZE - 1


def test_get_accessible_text_reads_long_text_in_bounded_chunks(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.text_char_count = TEXT_LENGTH
    stub.text_source = "".join(str(index % 10) for index in range(TEXT_LENGTH))
    assert backend.get_accessible_text(VM_ID, CONTEXT) == stub.text_source
    assert stub.text_range_calls == [
        (0, CHUNK_SIZE - 1, CHUNK_SIZE + 1),
        (CHUNK_SIZE, TEXT_LENGTH - 1, TEXT_LENGTH - CHUNK_SIZE + 1),
    ]


def test_get_accessible_text_reports_none_when_a_chunk_read_fails(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.text_char_count = TEXT_LENGTH
    stub.text_source = "x" * TEXT_LENGTH
    stub.text_range_fail_at = 1
    assert backend.get_accessible_text(VM_ID, CONTEXT) is None


def test_get_accessible_text_of_zero_length_is_empty_without_a_range_call(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.text_char_count = 0
    assert backend.get_accessible_text(VM_ID, CONTEXT) == ""
    assert stub.text_range_calls == []


def test_get_accessible_text_reports_none_when_the_context_has_no_text(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.text_info_result = FALSE
    assert backend.get_accessible_text(VM_ID, CONTEXT) is None


# -- value -------------------------------------------------------------------
def test_current_minimum_maximum_value_round_trip(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.value_current, stub.value_minimum, stub.value_maximum = "40", "0", "100"
    assert backend.get_current_accessible_value(VM_ID, CONTEXT) == "40"
    assert backend.get_minimum_accessible_value(VM_ID, CONTEXT) == "0"
    assert backend.get_maximum_accessible_value(VM_ID, CONTEXT) == "100"


def test_value_reads_report_none_on_failure(backend: DllBackend, stub: StubDll) -> None:
    stub.value_current = stub.value_minimum = stub.value_maximum = None
    assert backend.get_current_accessible_value(VM_ID, CONTEXT) is None
    assert backend.get_minimum_accessible_value(VM_ID, CONTEXT) is None
    assert backend.get_maximum_accessible_value(VM_ID, CONTEXT) is None


# -- text entry / focus -------------------------------------------------------
def test_set_text_contents_marshals_the_string_and_reports_the_dll_result(
    backend: DllBackend, stub: StubDll
) -> None:
    assert backend.set_text_contents(VM_ID, CONTEXT, "Привет 世界") is True
    assert stub.set_text_calls == [(VM_ID, CONTEXT, "Привет 世界")]

    stub.set_text_result = FALSE
    assert backend.set_text_contents(VM_ID, CONTEXT, "again") is False


def test_request_focus_reports_the_dll_result(
    backend: DllBackend, stub: StubDll
) -> None:
    assert backend.request_focus(VM_ID, CONTEXT) is True
    assert stub.focus_calls == [(VM_ID, CONTEXT)]

    stub.focus_result = FALSE
    assert backend.request_focus(VM_ID, CONTEXT) is False


# -- selection ----------------------------------------------------------------
SELECTION_COUNT = 2
FIRST_SELECTION_COOKIE = 0xAAA1


def test_selection_reads_and_mutations_round_trip(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.selection_count = SELECTION_COUNT
    stub.selection_values = {0: FIRST_SELECTION_COOKIE, 1: 0xAAA2}
    stub.child_selected = {0: True, 1: False}

    assert backend.get_accessible_selection_count(VM_ID, CONTEXT) == SELECTION_COUNT
    assert backend.get_accessible_selection(VM_ID, CONTEXT, 0) == FIRST_SELECTION_COOKIE
    assert backend.is_accessible_child_selected(VM_ID, CONTEXT, 0) is True
    assert backend.is_accessible_child_selected(VM_ID, CONTEXT, 1) is False

    backend.add_accessible_selection(VM_ID, CONTEXT, 3)
    backend.remove_accessible_selection(VM_ID, CONTEXT, 1)
    backend.clear_accessible_selection(VM_ID, CONTEXT)

    assert stub.add_selection_calls == [(VM_ID, CONTEXT, 3)]
    assert stub.remove_selection_calls == [(VM_ID, CONTEXT, 1)]
    assert stub.clear_selection_calls == [(VM_ID, CONTEXT)]


def test_set_accessible_table_row_selected_delegates_to_add_or_remove(
    backend: DllBackend, stub: StubDll
) -> None:
    backend.set_accessible_table_row_selected(VM_ID, CONTEXT, 5, selected=True)
    backend.set_accessible_table_row_selected(VM_ID, CONTEXT, 5, selected=False)
    assert stub.add_selection_calls == [(VM_ID, CONTEXT, 5)]
    assert stub.remove_selection_calls == [(VM_ID, CONTEXT, 5)]


# -- table ---------------------------------------------------------------------
TABLE = 0x5000


def test_get_accessible_table_info_decodes_every_member(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.table_info_values = {
        "caption": 0,
        "summary": 0,
        "rowCount": 5,
        "columnCount": 3,
        "accessibleContext": 0x1000,
        "accessibleTable": 0x2000,
    }
    info = backend.get_accessible_table_info(VM_ID, CONTEXT)
    assert info is not None
    assert (info.row_count, info.column_count) == (5, 3)
    assert (info.context, info.table) == (0x1000, 0x2000)
    assert stub.released == []


def test_get_accessible_table_info_releases_partially_filled_handles_on_failure(
    backend: DllBackend, stub: StubDll
) -> None:
    """A DLL that fails mid-fill may still have allocated some handles."""
    stub.table_info_result = FALSE
    stub.table_info_values = {
        "caption": 0x1111,
        "summary": 0x2222,
        "rowCount": 0,
        "columnCount": 0,
        "accessibleContext": 0x3333,
        "accessibleTable": 0x4444,
    }
    assert backend.get_accessible_table_info(VM_ID, CONTEXT) is None
    assert stub.released == [
        (VM_ID, 0x1111),
        (VM_ID, 0x2222),
        (VM_ID, 0x3333),
        (VM_ID, 0x4444),
    ]


def test_get_accessible_table_cell_info_decodes_every_member(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.table_cell_values = {
        "accessibleContext": 0xC0DE,
        "index": 4,
        "row": 1,
        "column": 2,
        "rowExtent": 1,
        "columnExtent": 1,
        "isSelected": TRUE,
    }
    cell = backend.get_accessible_table_cell_info(VM_ID, TABLE, 1, 2)
    assert cell is not None
    assert (cell.context, cell.index, cell.row, cell.column) == (0xC0DE, 4, 1, 2)
    assert cell.selected is True


def test_get_accessible_table_cell_info_releases_the_context_on_failure(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.table_cell_result = FALSE
    stub.table_cell_values["accessibleContext"] = 0xBAD1
    assert backend.get_accessible_table_cell_info(VM_ID, TABLE, 0, 0) is None
    assert stub.released == [(VM_ID, 0xBAD1)]


@pytest.mark.parametrize("column", [False, True])
def test_get_accessible_table_header_reads_row_and_column_independently(
    backend: DllBackend, stub: StubDll, column: bool
) -> None:
    key = "column" if column else "row"
    stub.table_header_values[key]["rowCount"] = 1
    stub.table_header_values[key]["columnCount"] = 3 if column else 1
    header = backend.get_accessible_table_header(VM_ID, CONTEXT, column=column)
    assert header is not None
    assert header.column_count == (3 if column else 1)


def test_get_accessible_table_header_releases_handles_on_failure(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.table_header_result["row"] = FALSE
    stub.table_header_values["row"]["accessibleContext"] = 0x9999
    assert backend.get_accessible_table_header(VM_ID, CONTEXT, column=False) is None
    assert stub.released == [(VM_ID, 0x9999)]


def test_get_accessible_table_selections_reads_row_and_column_independently(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.table_selection_count = {"row": 3, "column": 0}
    stub.table_selection_values = {"row": (1, 3, 5), "column": ()}
    assert backend.get_accessible_table_selections(VM_ID, TABLE, column=False) == (
        3,
        (1, 3, 5),
    )
    assert backend.get_accessible_table_selections(VM_ID, TABLE, column=True) == (0, ())
    assert stub.table_selection_values_calls == ["row"]


def test_get_accessible_table_selections_does_not_read_values_past_the_limit(
    backend: DllBackend, stub: StubDll
) -> None:
    """Overflow is reported by count alone; the values call would overrun."""
    stub.table_selection_count["row"] = MAX_TABLE_SELECTIONS + 1
    count, values = backend.get_accessible_table_selections(VM_ID, TABLE, column=False)
    assert (count, values) == (MAX_TABLE_SELECTIONS + 1, None)
    assert stub.table_selection_values_calls == []


# -- visible children ------------------------------------------------------------
def test_get_visible_children_stitches_multiple_pages(
    backend: DllBackend, stub: StubDll
) -> None:
    first_page = list(range(1, MAX_VISIBLE_CHILDREN + 1))
    second_page = list(range(MAX_VISIBLE_CHILDREN + 1, MAX_VISIBLE_CHILDREN + 45))
    stub.visible_children_count = len(first_page) + len(second_page)
    stub.visible_children_pages = [first_page, second_page]
    assert backend.get_visible_children(VM_ID, CONTEXT) == tuple(
        first_page + second_page
    )
    assert stub.released == []


def test_get_visible_children_releases_earlier_pages_when_a_later_page_fails(
    backend: DllBackend, stub: StubDll
) -> None:
    first_page = list(range(1, MAX_VISIBLE_CHILDREN + 1))
    stub.visible_children_count = MAX_VISIBLE_CHILDREN + 1
    stub.visible_children_pages = [first_page, None]
    assert backend.get_visible_children(VM_ID, CONTEXT) is None
    assert stub.released == [(VM_ID, cookie) for cookie in first_page]


def test_get_visible_children_releases_the_page_when_the_returned_count_is_invalid(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.visible_children_count = 3
    stub.visible_children_pages = [[1, 2, 3]]
    stub.visible_children_overrun_at_page = {0: MAX_VISIBLE_CHILDREN + 1}
    assert backend.get_visible_children(VM_ID, CONTEXT) is None
    assert stub.released == [(VM_ID, 1), (VM_ID, 2), (VM_ID, 3)]


# -- event callbacks ---------------------------------------------------------------
def test_setup_event_callbacks_registers_all_eight_function_pointers(
    backend: DllBackend, stub: StubDll
) -> None:
    backend.setup_event_callbacks(lambda: None, lambda _vm_id: None)
    expected = {
        "setJavaShutdownFP",
        "setPropertyChangeFP",
        "setPropertyStateChangeFP",
        "setPropertyValueChangeFP",
        "setPropertyTableModelChangeFP",
        "setPropertyTextChangeFP",
        "setPropertySelectionChangeFP",
        "setPropertyVisibleDataChangeFP",
    }
    assert set(stub.registered_callbacks) == expected
    assert all(value is not None for value in stub.registered_callbacks.values())


def test_pumping_drains_a_property_event_and_releases_both_owned_cookies(
    backend: DllBackend, stub: StubDll
) -> None:
    woken: list[None] = []
    backend.setup_event_callbacks(lambda: woken.append(None), lambda _vm_id: None)
    event_cookie, source_cookie = 0x7001, 0x7002

    fire_callback(
        stub, "setPropertyChangeFP", VM_ID, event_cookie, source_cookie, 0, 0, 0
    )
    assert woken == [None]
    assert stub.released == []  # not drained until the runtime pumps

    backend.pump_messages()
    assert stub.released == [(VM_ID, event_cookie), (VM_ID, source_cookie)]


def test_pumping_drains_a_vm_shutdown_event_without_releasing_cookies(
    backend: DllBackend, stub: StubDll
) -> None:
    exited: list[int] = []
    backend.setup_event_callbacks(lambda: None, exited.append)
    fire_callback(stub, "setJavaShutdownFP", VM_ID)

    backend.pump_messages()
    assert exited == [VM_ID]
    assert stub.released == []


def test_shutdown_unregisters_every_callback_and_drains_leftover_events(
    backend: DllBackend, stub: StubDll
) -> None:
    backend.setup_event_callbacks(lambda: None, lambda _vm_id: None)
    event_cookie, source_cookie = 0x7003, 0x7004
    fire_callback(
        stub, "setPropertyChangeFP", VM_ID, event_cookie, source_cookie, 0, 0, 0
    )

    backend.shutdown()

    assert all(value is None for value in stub.registered_callbacks.values())
    assert stub.released == [(VM_ID, event_cookie), (VM_ID, source_cookie)]


def test_do_accessible_actions_rejects_empty_or_oversized_lists_before_the_dll(
    backend: DllBackend, stub: StubDll
) -> None:
    assert backend.do_accessible_actions(VM_ID, CONTEXT, ()) == (False, -1)
    oversized = tuple(f"action-{index}" for index in range(33))
    assert backend.do_accessible_actions(VM_ID, CONTEXT, oversized) == (False, -1)
    assert stub.actions_done is None


def test_get_accessible_table_selections_reports_none_when_the_values_call_fails(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.table_selection_count["row"] = 2
    stub.table_selection_values["row"] = (1, 2)

    def failing_values(*_args: object) -> int:
        return FALSE

    stub.getAccessibleTableRowSelections = failing_values  # type: ignore[assignment]
    assert backend.get_accessible_table_selections(VM_ID, TABLE, column=False) == (
        2,
        None,
    )


def test_get_visible_children_reports_none_on_a_negative_count(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.visible_children_count = -1
    assert backend.get_visible_children(VM_ID, CONTEXT) is None


def test_get_visible_children_releases_earlier_pages_on_a_later_invalid_count(
    backend: DllBackend, stub: StubDll
) -> None:
    first_page = list(range(1, MAX_VISIBLE_CHILDREN + 1))
    second_page = [MAX_VISIBLE_CHILDREN + 1, MAX_VISIBLE_CHILDREN + 2]
    stub.visible_children_count = len(first_page) + len(second_page)
    stub.visible_children_pages = [first_page, second_page]
    stub.visible_children_overrun_at_page = {1: MAX_VISIBLE_CHILDREN + 1}

    assert backend.get_visible_children(VM_ID, CONTEXT) is None
    assert stub.released == [(VM_ID, cookie) for cookie in first_page] + [
        (VM_ID, cookie) for cookie in second_page
    ]


def test_state_and_simple_property_callbacks_also_queue_events(
    backend: DllBackend, stub: StubDll
) -> None:
    """Every FP variant funnels through the same queue, not just the change one."""
    woken: list[None] = []
    backend.setup_event_callbacks(lambda: woken.append(None), lambda _vm_id: None)

    fire_callback(stub, "setPropertyStateChangeFP", VM_ID, 0x8001, 0x8002, 0, 0)
    fire_callback(stub, "setPropertyTextChangeFP", VM_ID, 0x8003, 0x8004)

    backend.pump_messages()
    assert stub.released == [
        (VM_ID, 0x8001),
        (VM_ID, 0x8002),
        (VM_ID, 0x8003),
        (VM_ID, 0x8004),
    ]
    events_dispatched = 2
    assert len(woken) == events_dispatched


def test_setup_event_callbacks_rolls_back_registrations_when_one_fails(
    backend: DllBackend, stub: StubDll
) -> None:
    stub.raise_on_register = "setPropertyTableModelChangeFP"
    with pytest.raises(RuntimeError, match="setPropertyTableModelChangeFP"):
        backend.setup_event_callbacks(lambda: None, lambda _vm_id: None)

    assert all(value is None for value in stub.registered_callbacks.values())
