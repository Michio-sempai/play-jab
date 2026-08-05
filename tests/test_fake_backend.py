"""The fake backend as a backend in its own right.

Everything above the native layer is tested against this fake, so a wrong fake
would quietly validate wrong code. Two things matter most: it must present the
same call surface as :class:`DllBackend`, and it must reproduce the cookie
semantics of the real bridge - a fresh reference per call, and a loud failure on
any release that does not correspond to exactly one outstanding reference.
"""

from __future__ import annotations

import inspect

import pytest

from play_jab._native.backend import ContextInfo, DllBackend, NativeBackend
from play_jab._native.fake import (
    FakeBackend,
    FakeBackendError,
    FakeNode,
    fake_backend_factory,
)

WINDOW_HWND = 0x3333
OTHER_HWND = 0x4444
MISSING_HWND = 0xDEAD
WRONG_VM_ID = 77
UNKNOWN_COOKIE = 0xBEEF
REPEATS = 3
FAULTS_BEFORE_READY = 4
ROOT_INDEX_IN_PARENT = -1
SHUTDOWN_CALLS = 2

PROTOCOL_METHODS = tuple(
    name
    for name, member in vars(NativeBackend).items()
    if callable(member) and not name.startswith("_")
)


def tree() -> FakeNode:
    return FakeNode(
        name="Dialog",
        role_en_us="dialog",
        states_en_us="visible,showing",
        children=[
            FakeNode(
                name="OK",
                role_en_us="push button",
                role="Schaltflache",
                states="sichtbar",
                x=10,
                y=20,
                width=80,
                height=24,
                accessible_component=True,
                accessible_action=True,
                actions=("click", "toggle"),
                accessible_interfaces=3,
            )
        ],
    )


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend({WINDOW_HWND: tree(), OTHER_HWND: FakeNode(name="Other")})


def context_of(backend: FakeBackend, hwnd: int) -> int:
    found = backend.get_accessible_context_from_hwnd(hwnd)
    assert found is not None
    _, context = found
    return context


# -- the shape both backends must share ------------------------------------


def test_the_protocol_has_the_methods_the_slice_needs() -> None:
    assert len(PROTOCOL_METHODS) == len(set(PROTOCOL_METHODS))
    assert "release_java_object" in PROTOCOL_METHODS


@pytest.mark.parametrize("implementation", [FakeBackend, DllBackend])
def test_both_backends_implement_the_whole_protocol(
    implementation: type[object],
) -> None:
    for method in PROTOCOL_METHODS:
        assert callable(getattr(implementation, method, None)), method


@pytest.mark.parametrize("implementation", [FakeBackend, DllBackend])
def test_both_backends_keep_the_protocol_signatures(
    implementation: type[object],
) -> None:
    """A drifted signature would only surface as a TypeError at runtime."""
    for method in PROTOCOL_METHODS:
        expected = inspect.signature(getattr(NativeBackend, method))
        assert inspect.signature(getattr(implementation, method)) == expected, method


# -- cookie semantics ------------------------------------------------------


def test_every_call_mints_a_distinct_cookie(backend: FakeBackend) -> None:
    cookies = {context_of(backend, WINDOW_HWND) for _ in range(REPEATS)}
    assert len(cookies) == REPEATS
    assert backend.live_cookies == cookies
    assert backend.acquired == REPEATS


def test_releasing_a_cookie_twice_is_reported(backend: FakeBackend) -> None:
    context = context_of(backend, WINDOW_HWND)
    backend.release_java_object(backend.vm_id, context)
    with pytest.raises(FakeBackendError, match="double release"):
        backend.release_java_object(backend.vm_id, context)


def test_releasing_an_unowned_cookie_is_reported(backend: FakeBackend) -> None:
    with pytest.raises(FakeBackendError, match="never owned"):
        backend.release_java_object(backend.vm_id, UNKNOWN_COOKIE)


def test_using_a_released_cookie_is_reported(backend: FakeBackend) -> None:
    context = context_of(backend, WINDOW_HWND)
    backend.release_java_object(backend.vm_id, context)
    with pytest.raises(FakeBackendError, match="already released"):
        backend.get_accessible_context_info(backend.vm_id, context)


def test_a_foreign_vm_id_is_reported(backend: FakeBackend) -> None:
    context = context_of(backend, WINDOW_HWND)
    with pytest.raises(FakeBackendError, match="unknown vmID"):
        backend.get_accessible_context_info(WRONG_VM_ID, context)
    with pytest.raises(FakeBackendError, match="unknown vmID"):
        backend.release_java_object(WRONG_VM_ID, context)


def test_a_node_shared_between_two_windows_is_rejected() -> None:
    """Node identity keys the fake's parent/index tables, so sharing is ambiguous."""
    shared = FakeNode(name="Shared")
    with pytest.raises(FakeBackendError, match="twice"):
        FakeBackend({WINDOW_HWND: shared, OTHER_HWND: shared})


# -- stale contexts --------------------------------------------------------
#
# A Swing tree rebuild invalidates contexts the client still holds. The bridge
# reports that the way C reports everything - FALSE, a null cookie - never as an
# exception, and the reference stays owned: it must still be released exactly
# once. Confusing "stale" with "released" is what makes stale-node handling leak.


def test_a_stale_context_reads_as_failure_not_as_an_exception(
    backend: FakeBackend,
) -> None:
    context = context_of(backend, WINDOW_HWND)
    backend.make_stale(context)
    assert backend.get_accessible_context_info(backend.vm_id, context) is None
    assert backend.get_accessible_child_from_context(backend.vm_id, context, 0) == 0
    assert backend.get_accessible_parent_from_context(backend.vm_id, context) == 0
    assert backend.get_hwnd_from_accessible_context(backend.vm_id, context) == 0


def test_a_stale_context_is_still_owned_and_must_still_be_released(
    backend: FakeBackend,
) -> None:
    context = context_of(backend, WINDOW_HWND)
    backend.make_stale(context)
    assert context in backend.live_cookies
    backend.release_java_object(backend.vm_id, context)
    assert backend.live_cookies == frozenset()
    with pytest.raises(FakeBackendError, match="double release"):
        backend.release_java_object(backend.vm_id, context)


def test_going_stale_does_not_disturb_a_sibling_cookie(backend: FakeBackend) -> None:
    doomed = context_of(backend, WINDOW_HWND)
    survivor = context_of(backend, WINDOW_HWND)
    backend.make_stale(doomed)
    assert backend.get_accessible_context_info(backend.vm_id, doomed) is None
    assert backend.get_accessible_context_info(backend.vm_id, survivor) is not None


def test_a_tree_rebuild_invalidates_every_outstanding_context(
    backend: FakeBackend,
) -> None:
    contexts = [context_of(backend, WINDOW_HWND) for _ in range(REPEATS)]
    backend.make_all_stale()
    for context in contexts:
        assert backend.get_accessible_context_info(backend.vm_id, context) is None


def test_a_context_minted_after_the_rebuild_is_fresh(backend: FakeBackend) -> None:
    backend.make_all_stale()
    assert (
        backend.get_accessible_context_info(
            backend.vm_id, context_of(backend, WINDOW_HWND)
        )
        is not None
    )


def test_only_an_outstanding_cookie_can_be_made_stale(backend: FakeBackend) -> None:
    """Staleness is a property of a live reference; anything else is a test bug."""
    with pytest.raises(FakeBackendError, match="not an outstanding cookie"):
        backend.make_stale(UNKNOWN_COOKIE)

    released = context_of(backend, WINDOW_HWND)
    backend.release_java_object(backend.vm_id, released)
    with pytest.raises(FakeBackendError, match="not an outstanding cookie"):
        backend.make_stale(released)


# -- tree navigation -------------------------------------------------------


def test_an_unknown_window_has_neither_context_nor_java_flag(
    backend: FakeBackend,
) -> None:
    assert backend.is_java_window(WINDOW_HWND)
    assert not backend.is_java_window(MISSING_HWND)
    assert backend.get_accessible_context_from_hwnd(MISSING_HWND) is None


def test_an_out_of_range_child_index_returns_zero(backend: FakeBackend) -> None:
    context = context_of(backend, WINDOW_HWND)
    assert backend.get_accessible_child_from_context(backend.vm_id, context, 1) == 0
    assert backend.get_accessible_child_from_context(backend.vm_id, context, -1) == 0


def test_the_root_has_no_parent(backend: FakeBackend) -> None:
    context = context_of(backend, WINDOW_HWND)
    assert backend.get_accessible_parent_from_context(backend.vm_id, context) == 0


def test_a_child_reports_a_parent_under_a_fresh_cookie(backend: FakeBackend) -> None:
    root = context_of(backend, WINDOW_HWND)
    child = backend.get_accessible_child_from_context(backend.vm_id, root, 0)
    assert child != 0
    parent = backend.get_accessible_parent_from_context(backend.vm_id, child)
    assert parent not in {0, root}


def test_only_a_top_level_context_maps_back_to_a_window(backend: FakeBackend) -> None:
    """``getHWNDFromAccessibleContext`` is documented for top-level windows only.

    The Java Accessibility Guide describes it as returning "the HWND from the
    AccessibleContext of a top-level window", so a descendant answers NULL and
    callers must walk to the root rather than expect a window from any node.
    """
    root = context_of(backend, WINDOW_HWND)
    child = backend.get_accessible_child_from_context(backend.vm_id, root, 0)
    assert backend.get_hwnd_from_accessible_context(backend.vm_id, root) == WINDOW_HWND
    assert backend.get_hwnd_from_accessible_context(backend.vm_id, child) == 0


def test_the_root_reports_no_index_in_its_parent(backend: FakeBackend) -> None:
    info = backend.get_accessible_context_info(
        backend.vm_id, context_of(backend, WINDOW_HWND)
    )
    assert info is not None
    assert info.index_in_parent == ROOT_INDEX_IN_PARENT
    assert info.children_count == 1


def test_a_localized_role_does_not_replace_the_en_us_spelling(
    backend: FakeBackend,
) -> None:
    root = context_of(backend, WINDOW_HWND)
    child = backend.get_accessible_child_from_context(backend.vm_id, root, 0)
    info = backend.get_accessible_context_info(backend.vm_id, child)
    assert info is not None
    assert info.role == "Schaltflache"
    assert info.role_en_us == "push button"
    assert info.states == "sichtbar"
    assert info.states_en_us == ""


def test_an_unlocalized_node_repeats_the_en_us_spelling(backend: FakeBackend) -> None:
    info = backend.get_accessible_context_info(
        backend.vm_id, context_of(backend, WINDOW_HWND)
    )
    assert info is not None
    assert info.role == info.role_en_us == "dialog"
    assert info.states == info.states_en_us == "visible,showing"


def test_geometry_and_interface_flags_survive_the_round_trip(
    backend: FakeBackend,
) -> None:
    root = context_of(backend, WINDOW_HWND)
    child = backend.get_accessible_child_from_context(backend.vm_id, root, 0)
    info = backend.get_accessible_context_info(backend.vm_id, child)
    assert info == ContextInfo(
        name="OK",
        description="",
        role="Schaltflache",
        role_en_us="push button",
        states="sichtbar",
        states_en_us="",
        index_in_parent=0,
        children_count=0,
        x=10,
        y=20,
        width=80,
        height=24,
        accessible_component=True,
        accessible_action=True,
        accessible_selection=False,
        accessible_text=False,
        accessible_interfaces=3,
    )


def test_action_calls_follow_cookie_and_stale_semantics(
    backend: FakeBackend,
) -> None:
    root = context_of(backend, WINDOW_HWND)
    child = backend.get_accessible_child_from_context(backend.vm_id, root, 0)
    assert backend.get_accessible_actions(backend.vm_id, child) == (
        "click",
        "toggle",
    )
    assert backend.do_accessible_actions(backend.vm_id, child, ("click",)) == (True, -1)

    backend.make_stale(child)
    assert backend.get_accessible_actions(backend.vm_id, child) is None
    assert backend.do_accessible_actions(backend.vm_id, child, ("click",)) == (False, 0)


# -- lifecycle bookkeeping -------------------------------------------------


def test_a_not_yet_ready_bridge_faults_the_configured_number_of_times() -> None:
    """The fake models a not-ready bridge the way ctypes reports one: ``OSError``."""
    backend = FakeBackend(
        {WINDOW_HWND: tree()}, faults_before_ready=FAULTS_BEFORE_READY
    )
    for _ in range(FAULTS_BEFORE_READY):
        with pytest.raises(OSError, match="not ready"):
            backend.is_java_window(WINDOW_HWND)
    assert backend.is_java_window(WINDOW_HWND) is True
    assert backend.faults_before_ready == 0


def test_lifecycle_calls_are_counted(backend: FakeBackend) -> None:
    backend.windows_run()
    backend.pump_messages()
    backend.shutdown()
    backend.shutdown()
    assert backend.windows_run_calls == 1
    assert backend.pump_turns == 1
    assert backend.shutdown_calls == SHUTDOWN_CALLS


def test_the_factory_hands_back_the_very_instance_it_returned() -> None:
    backend, factory = fake_backend_factory({WINDOW_HWND: tree()}, vm_id=WRONG_VM_ID)
    assert factory() is backend
    assert factory() is backend
    assert backend.vm_id == WRONG_VM_ID
