"""Exact ownership: every owned cookie is released exactly once, and only once.

An ``AccessibleContext`` is a live JVM reference the bridge pins on our behalf,
so a missed ``releaseJavaObject`` leaks a Java object for the lifetime of the VM
and a duplicate one gives back a reference we no longer hold. The fake backend
turns both into an immediate :class:`FakeBackendError`, so these tests try to
provoke them: repeated traversal of the same node, out-of-order closing, an
exception thrown mid-scope, closing twice, and dropping a reference on the floor.
"""

from __future__ import annotations

import contextlib
import gc
from collections.abc import Iterator

import pytest

from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode, fake_backend_factory
from play_jab.exceptions import JavaReferenceClosedError, NativeCallError

WINDOW_HWND = 0x2222
REPEATS = 3
DEPTH = 3
ROOT_CHILDREN = 2


def released_after_collect(backend: FakeBackend, cookie: int) -> bool:
    """Whether one collection is enough for the finalizer to give ``cookie`` back.

    It has to be. ``_submit`` clears ``_Call.result`` before returning, so the
    worker's frame no longer pins the last returned :class:`JavaRef` until its
    next loop turn - without that, collection would free the reference an
    unpredictable pump interval later and this safety net would be untestable.
    """
    gc.collect()
    return cookie not in backend.live_cookies


def nested_tree() -> FakeNode:
    """A frame > panel > list > list item chain, each level with one sibling."""
    return FakeNode(
        name="Frame",
        role_en_us="frame",
        children=[
            FakeNode(
                name="Panel",
                role_en_us="panel",
                children=[
                    FakeNode(
                        name="List",
                        role_en_us="list",
                        children=[FakeNode(name="Item", role_en_us="list item")],
                    )
                ],
            ),
            FakeNode(name="Status", role_en_us="label"),
        ],
    )


@pytest.fixture
def runtime() -> Iterator[tuple[BridgeRuntime, FakeBackend]]:
    backend, factory = fake_backend_factory({WINDOW_HWND: nested_tree()})
    bridge = BridgeRuntime(factory, pump_interval=0.001)
    with bridge:
        yield bridge, backend
    assert backend.acquired == backend.released, "a cookie outlived the test"


def test_repeated_traversal_of_one_node_owns_a_cookie_per_call(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    with bridge.context_from_hwnd(WINDOW_HWND) as root:
        children = [bridge.child(root, 0) for _ in range(REPEATS)]
        assert all(child is not None for child in children)
        cookies = {child.value for child in children if child is not None}
        assert len(cookies) == REPEATS
        assert bridge.live_ref_count == REPEATS + 1
        for child in children:
            assert child is not None
            child.close()
        assert bridge.live_ref_count == 1
    assert backend.live_cookies == frozenset()


def test_closing_out_of_order_releases_each_exactly_once(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    root = bridge.context_from_hwnd(WINDOW_HWND)
    first = bridge.child(root, 0)
    second = bridge.child(root, 1)
    assert first is not None
    assert second is not None
    root.close()
    second.close()
    first.close()
    assert backend.released == backend.acquired
    assert bridge.live_ref_count == 0


def test_a_scope_left_by_an_exception_still_releases(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    with (
        pytest.raises(RuntimeError, match="boom"),
        bridge.context_from_hwnd(WINDOW_HWND) as root,
    ):
        assert bridge.context_info(root).name == "Frame"
        raise RuntimeError("boom")
    assert backend.live_cookies == frozenset()
    assert bridge.live_ref_count == 0


def test_nested_descent_releases_every_level(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    with contextlib.ExitStack() as scope:
        node = scope.enter_context(bridge.context_from_hwnd(WINDOW_HWND))
        for _ in range(DEPTH):
            child = bridge.child(node, 0)
            assert child is not None
            node = scope.enter_context(child)
        assert bridge.context_info(node).name == "Item"
        assert bridge.live_ref_count == DEPTH + 1
    assert bridge.live_ref_count == 0
    assert backend.live_cookies == frozenset()


def test_a_closed_reference_cannot_be_used_again(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, _ = runtime
    root = bridge.context_from_hwnd(WINDOW_HWND)
    root.close()

    with pytest.raises(JavaReferenceClosedError):
        bridge.context_info(root)
    with pytest.raises(JavaReferenceClosedError):
        bridge.child(root, 0)
    with pytest.raises(JavaReferenceClosedError):
        bridge.parent(root)
    with pytest.raises(JavaReferenceClosedError):
        bridge.hwnd_from_context(root)


def test_a_dropped_reference_is_released_by_the_finalizer(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    """The safety net, not the contract: correctness must not need this."""
    bridge, backend = runtime
    root = bridge.context_from_hwnd(WINDOW_HWND)
    cookie = root.value
    del root
    assert released_after_collect(backend, cookie)
    assert bridge.live_ref_count == 0


def test_the_finalizer_does_not_release_again_after_close(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    root = bridge.context_from_hwnd(WINDOW_HWND)
    root.close()
    del root
    gc.collect()
    assert backend.released == 1


def test_a_missing_child_mints_no_reference(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    with bridge.context_from_hwnd(WINDOW_HWND) as root:
        before = backend.acquired
        assert bridge.child(root, 99) is None
        assert bridge.child(root, -1) is None
        assert backend.acquired == before
        assert bridge.live_ref_count == 1


def test_the_root_has_no_parent_and_mints_no_reference(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    with bridge.context_from_hwnd(WINDOW_HWND) as root:
        before = backend.acquired
        assert bridge.parent(root) is None
        assert backend.acquired == before


def test_reading_attributes_owns_nothing(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    """``ContextInfo`` is copied data; re-reading must not accumulate cookies."""
    bridge, backend = runtime
    with bridge.context_from_hwnd(WINDOW_HWND) as root:
        before = backend.acquired
        for _ in range(REPEATS):
            assert bridge.context_info(root).children_count == ROOT_CHILDREN
            assert bridge.hwnd_from_context(root) == WINDOW_HWND
        assert backend.acquired == before
        assert bridge.live_ref_count == 1


def test_the_repr_reports_whether_the_reference_is_still_held(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, _ = runtime
    root = bridge.context_from_hwnd(WINDOW_HWND)
    assert "open" in repr(root)
    root.close()
    assert "closed" in repr(root)


def test_a_stale_reference_still_has_to_be_released(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    """A Swing rebuild invalidates the context but does not give the cookie back.

    This is the leak that matters: reads start failing, so it is tempting to
    treat the reference as gone - but the JVM is still pinning the object and
    only ``releaseJavaObject`` ends that.
    """
    bridge, backend = runtime
    with bridge.context_from_hwnd(WINDOW_HWND):
        backend.make_all_stale()
        assert bridge.live_ref_count == 1
        assert backend.released == 0
    assert backend.released == 1
    assert backend.live_cookies == frozenset()


def test_a_stale_reference_reads_as_a_diagnosable_failure(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    """Not as a crash, and not as an empty node that looks like real data."""
    bridge, backend = runtime
    with bridge.context_from_hwnd(WINDOW_HWND) as root:
        backend.make_all_stale()
        with pytest.raises(NativeCallError, match="getAccessibleContextInfo"):
            bridge.context_info(root)
        assert bridge.child(root, 0) is None
        assert bridge.parent(root) is None
        assert bridge.hwnd_from_context(root) is None


def test_shutting_the_runtime_down_does_not_release_outstanding_references() -> None:
    """Shutdown is not a release, which is why the counter must not be zeroed.

    Unloading the DLL abandons every cookie the JVM is still pinning for us; the
    objects stay alive until their VM exits. ``live_ref_count`` therefore keeps
    reporting them after :meth:`close`, so a leak stays visible instead of being
    papered over by a teardown that never actually gave anything back.
    """
    backend, factory = fake_backend_factory({WINDOW_HWND: nested_tree()})
    bridge = BridgeRuntime(factory, pump_interval=0.001)
    bridge.start()
    leaked = bridge.context_from_hwnd(WINDOW_HWND)
    cookie = leaked.value
    bridge.close()

    assert backend.released == 0
    assert backend.live_cookies == frozenset({cookie})
    leaked.close()
    assert leaked.closed
    assert backend.released == 0
    assert bridge.live_ref_count == 1
