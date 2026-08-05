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
from typing import Any, cast

import pytest

from play_jab._native.backend import DllBackend
from play_jab._native.types import AccessibleContext, AccessibleContextInfo

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


def out_parameter(reference: object, ctype: type) -> Any:
    """Reach through a ``byref`` argument the way the DLL writes through it."""
    return ctypes.cast(reference, ctypes.POINTER(ctype)).contents


class StubDll:
    """Answers the eight exports; every response is set by the test."""

    def __init__(self) -> None:
        self._handle = 0
        self.released: list[tuple[int, int]] = []
        self.context_from_hwnd_result = TRUE
        self.context_from_hwnd_cookie = CONTEXT
        self.context_info_result = TRUE
        self.child_cookie = CHILD_COOKIE
        self.parent_cookie = PARENT_COOKIE
        self.hwnd_result = WINDOW_HWND
        self.probe_error: Exception | None = None

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
