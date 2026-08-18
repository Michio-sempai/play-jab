"""Batched tree traversal and the locator path cache built on top of it.

Both exist for one reason: resolving a locator used to cost three worker
round-trips per node of the application's tree, and a real Swing client has
tens of thousands of them. These tests pin the two properties that make the
optimisation safe rather than merely fast -- every cookie is still released,
and a remembered path that no longer holds is discarded rather than trusted.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from play_jab import sync_api
from play_jab._native.backend import ContextInfo
from play_jab._native.bridge import BridgeRuntime, TextReader, Verdict, Visitor
from play_jab._native.fake import FakeBackend, FakeNode, fake_backend_factory
from play_jab.exceptions import (
    LocatorError,
    LocatorTimeoutError,
    NativeCallError,
    StrictModeViolation,
)
from play_jab.sync_api import JavaWindow, PlayJab

from .conftest import FakeWindowBackend, install_fake_runtime

HWND = 0xCAFE
PID = 4242
LEAF_COUNT = 3
BRANCH_COUNT = 2
ALL_NODES = 1 + BRANCH_COUNT + BRANCH_COUNT * LEAF_COUNT
TARGET_PATH = (1, 2)
PATH_READ_CALLS = 3
DUPLICATE_MATCHES = 2


def _tree() -> FakeNode:
    return FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us="enabled,visible,showing",
        children=[
            FakeNode(
                name=f"Branch {branch}",
                role_en_us="panel",
                states_en_us="enabled,visible,showing",
                children=[
                    FakeNode(
                        name=f"Leaf {branch}.{leaf}",
                        role_en_us="push button",
                        states_en_us="enabled,visible,showing",
                        accessible_text=True,
                        text=f"text {branch}.{leaf}",
                    )
                    for leaf in range(LEAF_COUNT)
                ],
            )
            for branch in range(BRANCH_COUNT)
        ],
    )


@pytest.fixture
def runtime() -> Iterator[tuple[BridgeRuntime, FakeBackend]]:
    backend, factory = fake_backend_factory({HWND: _tree()})
    bridge = BridgeRuntime(factory, pump_interval=0.001)
    with bridge:
        yield bridge, backend


def _collect(
    visited: list[tuple[tuple[int, ...], int, str]],
    verdicts: dict[str, Verdict] | None = None,
) -> Visitor:
    def visit(
        path: tuple[int, ...],
        depth: int,
        info: ContextInfo,
        read: TextReader,
    ) -> Verdict:
        visited.append((path, depth, info.name))
        if verdicts is None:
            return Verdict.DESCEND
        return verdicts.get(info.name, Verdict.DESCEND)

    return visit


# -- BridgeRuntime.traverse -------------------------------------------------


def test_traverse_visits_the_whole_subtree_in_depth_first_order(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    visited: list[tuple[tuple[int, ...], int, str]] = []

    bridge.traverse(HWND, (), _collect(visited))

    assert len(visited) == ALL_NODES
    assert visited[0] == ((), 0, "Fixture")
    assert visited[1] == ((0,), 1, "Branch 0")
    assert visited[2] == ((0, 0), 2, "Leaf 0.0")
    assert bridge.live_ref_count == 0
    assert backend.live_cookies == frozenset()


def test_traverse_starts_at_a_path_and_reports_absolute_paths(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, _ = runtime
    visited: list[tuple[tuple[int, ...], int, str]] = []

    bridge.traverse(HWND, (1,), _collect(visited))

    assert [entry[0] for entry in visited] == [
        (1,),
        (1, 0),
        (1, 1),
        (1, 2),
    ]
    # Depth is relative to the start node, so a nested step's own max_depth
    # keeps meaning "below my parent", not "below the window".
    assert [entry[1] for entry in visited] == [0, 1, 1, 1]


def test_skip_children_prunes_a_subtree_without_stopping_the_walk(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, _ = runtime
    visited: list[tuple[tuple[int, ...], int, str]] = []

    bridge.traverse(
        HWND,
        (),
        _collect(visited, {"Branch 0": Verdict.SKIP_CHILDREN}),
    )

    names = [entry[2] for entry in visited]
    assert "Branch 0" in names
    assert "Leaf 0.0" not in names
    assert "Leaf 1.0" in names


def test_stop_ends_the_walk_immediately(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    visited: list[tuple[tuple[int, ...], int, str]] = []

    bridge.traverse(HWND, (), _collect(visited, {"Leaf 0.1": Verdict.STOP}))

    assert [entry[2] for entry in visited][-1] == "Leaf 0.1"
    assert bridge.live_ref_count == 0
    assert backend.live_cookies == frozenset()


def test_a_visitor_that_raises_leaves_no_cookie_behind(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime

    def explode(
        path: tuple[int, ...],
        depth: int,
        info: ContextInfo,
        read: TextReader,
    ) -> Verdict:
        if info.name == "Leaf 1.1":
            raise LocatorError("visitor gave up")
        return Verdict.DESCEND

    with pytest.raises(LocatorError):
        bridge.traverse(HWND, (), explode)

    assert bridge.live_ref_count == 0
    assert backend.live_cookies == frozenset()


def test_the_visitor_can_read_text_for_the_node_it_is_given(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, _ = runtime
    texts: dict[str, str | None] = {}

    def visit(
        path: tuple[int, ...],
        depth: int,
        info: ContextInfo,
        read: TextReader,
    ) -> Verdict:
        if info.accessible_text:
            texts[info.name] = read()
        return Verdict.DESCEND

    bridge.traverse(HWND, (), visit)

    assert texts["Leaf 1.2"] == "text 1.2"


def test_traverse_pumps_messages_while_it_runs(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime
    turns = backend.pump_turns

    bridge.traverse(HWND, (), _collect([]))

    # Not an equality: the idle worker keeps pumping between calls too. What
    # matters is that a long batch does not stop servicing the pump entirely.
    assert backend.pump_turns > turns


# -- BridgeRuntime.read_path ------------------------------------------------


def test_read_path_returns_the_root_and_every_node_on_the_path(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime

    infos, text = bridge.read_path(HWND, TARGET_PATH)

    assert [info.name for info in infos] == ["Fixture", "Branch 1", "Leaf 1.2"]
    assert text is None
    assert bridge.live_ref_count == 0
    assert backend.live_cookies == frozenset()


def test_read_path_reads_text_on_request(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, _ = runtime

    _infos, text = bridge.read_path(HWND, TARGET_PATH, read_text=True)

    assert text == "text 1.2"


def test_read_path_reports_a_path_that_no_longer_exists(
    runtime: tuple[BridgeRuntime, FakeBackend],
) -> None:
    bridge, backend = runtime

    with pytest.raises(NativeCallError) as failure:
        bridge.read_path(HWND, (0, 99))

    assert failure.value.function == "getAccessibleChildFromContext"
    assert bridge.live_ref_count == 0
    assert backend.live_cookies == frozenset()


# -- the locator path cache -------------------------------------------------


@pytest.fixture
def locator_api(
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
    yield api, api.attach(pid=PID).window(), backend
    api.close()


@pytest.fixture
def uncached_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, FakeBackend]]:
    backend = FakeBackend({HWND: _tree()})
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    api = PlayJab(timeout=0, path_cache=False)
    api.__enter__()
    yield api, api.attach(pid=PID).window(), backend
    api.close()


def test_a_second_resolution_reads_the_remembered_path_instead_of_scanning(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, backend = locator_api
    locator = window.get_by_name("Leaf 1.2").first()

    assert locator.exists()
    acquired = backend.acquired
    assert locator.snapshot().name == "Leaf 1.2"

    # Window context plus one child per path element - not one per tree node.
    assert backend.acquired - acquired == PATH_READ_CALLS


def test_the_cache_is_off_when_the_client_asks_for_exhaustive_resolution(
    uncached_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    api, window, backend = uncached_api
    locator = window.get_by_name("Leaf 1.2").first()

    assert locator.exists()
    acquired = backend.acquired
    assert locator.snapshot().name == "Leaf 1.2"

    assert backend.acquired - acquired > PATH_READ_CALLS
    assert not api._path_cache


def test_a_remembered_path_that_stopped_matching_is_rescanned(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, backend = locator_api
    locator = window.get_by_name("Leaf 1.2")

    assert locator.snapshot().name == "Leaf 1.2"

    # Reorder the branch so the remembered path now points at a different node.
    root = backend._windows[HWND]
    root.children[1].children.reverse()
    for index, node in enumerate(root.children[1].children):
        backend._indexes[id(node)] = index

    assert locator.snapshot().name == "Leaf 1.2"
    assert window._api._path_cache[(HWND, locator._chain)][-1] == (1, 0)


def test_a_remembered_path_that_disappeared_is_not_reused(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, backend = locator_api
    locator = window.get_by_name("Leaf 1.2")

    assert locator.snapshot().name == "Leaf 1.2"

    # Popping the last child keeps every remaining index valid, so the only
    # thing that changed is that the remembered path leads nowhere.
    backend._windows[HWND].children[1].children.pop()

    with pytest.raises(LocatorTimeoutError):
        locator.snapshot()


def test_a_nested_chain_revalidates_every_step_not_only_the_target(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, backend = locator_api
    locator = window.get_by_name("Branch 1").get_by_role("push button").first()

    assert locator.snapshot().name == "Leaf 1.0"

    # The target keeps matching at (1, 0); its parent no longer does, so the
    # remembered path has to be rejected rather than reused.
    backend._windows[HWND].children[1].name = "Renamed"

    with pytest.raises(LocatorError):
        locator.snapshot()


def test_ambiguity_is_still_reported_when_the_chain_is_scanned(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, _backend = locator_api

    with pytest.raises(StrictModeViolation):
        window.get_by_role("panel").snapshot()


def test_exists_does_not_hide_preexisting_ambiguity_from_a_strict_call(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    api, window, _backend = locator_api
    locator = window.get_by_role("panel")

    assert locator.exists()
    assert (HWND, locator._chain) not in api._path_cache

    with pytest.raises(StrictModeViolation):
        locator.snapshot()


def test_clearing_the_cache_forces_the_next_resolution_to_scan(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    api, window, backend = locator_api
    locator = window.get_by_name("Leaf 1.2").first()
    assert locator.exists()

    api.clear_path_cache()

    acquired = backend.acquired
    assert locator.snapshot().name == "Leaf 1.2"
    assert backend.acquired - acquired > PATH_READ_CALLS


def test_warm_cache_intentionally_does_not_scan_for_a_new_duplicate(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, backend = locator_api
    locator = window.get_by_name("Leaf 1.2")
    assert locator.snapshot().name == "Leaf 1.2"

    duplicate = FakeNode(
        name="Leaf 1.2",
        role_en_us="push button",
        states_en_us="enabled,visible,showing",
    )
    root = backend._windows[HWND]
    root.children.append(duplicate)
    backend._indexes[id(duplicate)] = len(root.children) - 1

    assert locator.snapshot().name == "Leaf 1.2"
    assert locator.count() == DUPLICATE_MATCHES


def test_disabling_cache_preserves_exhaustive_strict_resolution(
    uncached_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, backend = uncached_api
    locator = window.get_by_name("Leaf 1.2")
    assert locator.snapshot().name == "Leaf 1.2"

    duplicate = FakeNode(
        name="Leaf 1.2",
        role_en_us="push button",
        states_en_us="enabled,visible,showing",
    )
    root = backend._windows[HWND]
    root.children.append(duplicate)
    backend._indexes[id(duplicate)] = len(root.children) - 1

    with pytest.raises(StrictModeViolation):
        locator.snapshot()


def test_path_cache_is_bounded_and_evicts_the_oldest_entry(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    api, window, _backend = locator_api
    oldest = window.get_by_name("Fixture", max_depth=0)
    assert oldest.snapshot().name == "Fixture"
    oldest_key = (HWND, oldest._chain)

    for depth in range(1, sync_api._PATH_CACHE_MAX_ENTRIES + 1):
        assert window.get_by_name("Fixture", max_depth=depth).snapshot().name == (
            "Fixture"
        )

    assert len(api._path_cache) == sync_api._PATH_CACHE_MAX_ENTRIES
    assert oldest_key not in api._path_cache


def test_path_cache_supports_parallel_lookup_and_clear(
    locator_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    api, window, _backend = locator_api
    locator = window.get_by_name("Leaf 1.2")

    def resolve_or_clear(index: int) -> str:
        if index % 5 == 0:
            api.clear_path_cache()
        return locator.snapshot().name

    with ThreadPoolExecutor(max_workers=8) as pool:
        names = list(pool.map(resolve_or_clear, range(80)))

    assert names == ["Leaf 1.2"] * 80
    assert api.live_ref_count == 0


# -- collapsed subtrees -----------------------------------------------------


COLLAPSED_CHILDREN = 5


def _collapsed_tree() -> FakeNode:
    return FakeNode(
        name="Fixture",
        role_en_us="frame",
        states_en_us="enabled,visible,showing",
        children=[
            FakeNode(
                name="Branch",
                role_en_us="label",
                states_en_us="enabled,visible,showing,expandable,collapsed",
                children=[
                    FakeNode(
                        name=f"Buried {index}",
                        role_en_us="label",
                        states_en_us="enabled,visible,showing",
                    )
                    for index in range(COLLAPSED_CHILDREN)
                ],
            ),
            FakeNode(
                name="Target",
                role_en_us="push button",
                states_en_us="enabled,visible,showing",
            ),
        ],
    )


@pytest.fixture
def collapsed_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PlayJab, JavaWindow, FakeBackend]]:
    backend = FakeBackend({HWND: _collapsed_tree()})
    install_fake_runtime(
        monkeypatch,
        backend,
        windows=FakeWindowBackend({HWND: "Fixture"}, pid=PID),
        is_process_alive=lambda pid: pid == PID,
    )
    api = PlayJab(timeout=0)
    api.__enter__()
    yield api, api.attach(pid=PID).window(), backend
    api.close()


def test_showing_only_does_not_descend_into_a_collapsed_subtree(
    collapsed_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, _backend = collapsed_api

    # The fake marks the buried nodes as showing, which a real Swing tree never
    # does for a collapsed branch. The rule is deliberate all the same: reading
    # every descendant of a collapsed control just to reject it is exactly what
    # made an unrelated search pay for a thousand-row tree.
    assert not window.locator(name="Buried 0", showing_only=True).exists()
    assert window.locator(name="Buried 0").exists()


def test_a_collapsed_node_still_matches_itself(
    collapsed_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, _backend = collapsed_api

    assert window.locator(name="Branch", showing_only=True).exists()


def test_a_collapsed_subtree_does_not_cost_a_read_per_node(
    collapsed_api: tuple[PlayJab, JavaWindow, FakeBackend],
) -> None:
    _api, window, backend = collapsed_api
    acquired = backend.acquired

    assert window.locator(name="Target", showing_only=True).exists()

    # Window context, the collapsed branch, and the target itself.
    assert backend.acquired - acquired == PATH_READ_CALLS
