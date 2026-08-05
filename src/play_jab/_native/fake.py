"""In-memory fake of the native Access Bridge.

Implements the same call surface as the real DLL backend on top of a plain
Python node tree, so the bridge runtime and everything layered on it can be
tested without a JVM, without JAB, and on any platform.

The fake reproduces the behaviour the layers above must get right: every context
handed out is a *distinct* new reference, even for the same node, exactly as the
JVM mints a new cookie per call.

Two situations that look alike are kept firmly apart, because only one of them
is a bug:

*Stale contexts* are normal. A Swing tree rebuild invalidates handles that were
perfectly good a moment ago, and CONCEPT section 3 designs locators around
exactly that. :meth:`FakeBackend.make_stale` and
:meth:`FakeBackend.make_all_stale` reproduce it the way the DLL does - reads
answer FALSE or a null cookie, never an exception - so the layers above can be
tested against it.

*Using a cookie that was never handed out, or releasing one twice*, is a bug in
the caller. Natively that is undefined behaviour: the DLL may return garbage or
fault the process. The fake raises :class:`FakeBackendError` instead, as a
tripwire. Nothing may be written to depend on that exception, since in
production the same mistake is a crash; it derives from :class:`AssertionError`
rather than ``PlayJabError`` so it can never be mistaken for a native failure
worth handling.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from play_jab._native.backend import ContextInfo, NativeBackend

__all__ = ["FakeBackend", "FakeBackendError", "FakeNode", "fake_backend_factory"]

_FIRST_COOKIE = 0x1000


class FakeBackendError(AssertionError):
    """The code under test misused the native call surface.

    A test-only tripwire. The real bridge does not report this; see the module
    docstring.
    """


@dataclass
class FakeNode:
    """One node of a fake accessibility tree."""

    name: str = ""
    description: str = ""
    role_en_us: str = "unknown"
    states_en_us: str = ""
    role: str | None = None
    states: str | None = None
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    accessible_component: bool = False
    accessible_action: bool = False
    accessible_selection: bool = False
    accessible_text: bool = False
    accessible_interfaces: int = 0
    actions: tuple[str, ...] = ()
    children: list[FakeNode] = field(default_factory=list)

    @property
    def localized_role(self) -> str:
        """The localized role; defaults to the ``en_US`` spelling."""
        return self.role_en_us if self.role is None else self.role

    @property
    def localized_states(self) -> str:
        """The localized states; defaults to the ``en_US`` spelling."""
        return self.states_en_us if self.states is None else self.states


class FakeBackend:
    """:class:`~play_jab._native.backend.NativeBackend` over a node tree."""

    def __init__(
        self,
        windows: Mapping[int, FakeNode] | None = None,
        *,
        vm_id: int = 1,
        faults_before_ready: int = 0,
    ) -> None:
        self.vm_id = vm_id
        self.faults_before_ready = faults_before_ready
        self.windows_run_calls = 0
        self.shutdown_calls = 0
        self.pump_turns = 0
        self.acquired = 0
        self.released = 0
        self.performed_actions: list[tuple[int, str]] = []

        self._windows: dict[int, FakeNode] = dict(windows or {})
        self._live: dict[int, FakeNode] = {}
        self._stale: set[int] = set()
        self._next_cookie = _FIRST_COOKIE
        # Keyed by id(node); self._pinned keeps every node alive so the ids stay
        # unique and valid for the backend's lifetime.
        self._pinned: list[FakeNode] = []
        self._parents: dict[int, FakeNode | None] = {}
        self._indexes: dict[int, int] = {}
        # Only a top-level window's own context maps back to an HWND, matching
        # getHWNDFromAccessibleContext, which answers NULL for anything deeper.
        self._root_hwnds: dict[int, int] = {}
        for hwnd, root in self._windows.items():
            self._root_hwnds[id(root)] = hwnd
            self._index_tree(root, parent=None, index_in_parent=-1)

    @property
    def live_cookies(self) -> frozenset[int]:
        """Cookies handed out and not yet released."""
        return frozenset(self._live)

    def _index_tree(
        self, node: FakeNode, *, parent: FakeNode | None, index_in_parent: int
    ) -> None:
        key = id(node)
        if key in self._parents:
            raise FakeBackendError("the same FakeNode appears twice in the tree")
        self._pinned.append(node)
        self._parents[key] = parent
        self._indexes[key] = index_in_parent
        for index, child in enumerate(node.children):
            self._index_tree(child, parent=node, index_in_parent=index)

    def _mint(self, node: FakeNode) -> int:
        cookie = self._next_cookie
        self._next_cookie += 1
        self._live[cookie] = node
        self.acquired += 1
        return cookie

    def make_stale(self, cookie: int) -> None:
        """Make one outstanding cookie behave like a context the JVM dropped.

        Distinct from releasing it: the reference is still owned and still has
        to be released exactly once, but every read through it now fails the way
        the real bridge fails - FALSE or a null cookie, never an exception.
        """
        if cookie not in self._live:
            raise FakeBackendError(
                f"cannot make {cookie:#x} stale: it is not an outstanding cookie"
            )
        self._stale.add(cookie)

    def make_all_stale(self) -> None:
        """Invalidate every outstanding context, as a Swing tree rebuild does."""
        self._stale.update(self._live)

    def _resolve(self, vm_id: int, context: int) -> FakeNode | None:
        """The node behind a cookie, or ``None`` if that context went stale.

        Raises only for cookies that were never handed out or are already
        released - those are bugs in the caller, not conditions the real bridge
        reports. A stale context is an ordinary outcome that callers above must
        handle, so it comes back as ``None`` for the caller to translate into
        whatever the corresponding C call would have returned.
        """
        if vm_id != self.vm_id:
            raise FakeBackendError(f"unknown vmID {vm_id}")
        node = self._live.get(context)
        if node is None:
            raise FakeBackendError(
                f"context {context:#x} was never handed out or is already released"
            )
        if context in self._stale:
            return None
        return node

    def windows_run(self) -> None:
        self.windows_run_calls += 1

    def pump_messages(self) -> None:
        self.pump_turns += 1

    def is_java_window(self, hwnd: int) -> bool:
        if self.faults_before_ready > 0:
            # Simulates the native access violation seen when the bridge is
            # called before its message pump has turned. ctypes surfaces a
            # native fault as OSError, so that is what a not-yet-ready DLL
            # looks like from Python.
            self.faults_before_ready -= 1
            raise OSError("simulated access violation: bridge not ready")
        return hwnd in self._windows

    def get_accessible_context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        root = self._windows.get(hwnd)
        if root is None:
            return None
        return self.vm_id, self._mint(root)

    def get_accessible_context_info(
        self, vm_id: int, context: int
    ) -> ContextInfo | None:
        node = self._resolve(vm_id, context)
        if node is None:
            # What getAccessibleContextInfo does for a dead context: FALSE.
            return None
        return ContextInfo(
            name=node.name,
            description=node.description,
            role=node.localized_role,
            role_en_us=node.role_en_us,
            states=node.localized_states,
            states_en_us=node.states_en_us,
            index_in_parent=self._indexes[id(node)],
            children_count=len(node.children),
            x=node.x,
            y=node.y,
            width=node.width,
            height=node.height,
            accessible_component=node.accessible_component,
            accessible_action=node.accessible_action,
            accessible_selection=node.accessible_selection,
            accessible_text=node.accessible_text,
            accessible_interfaces=node.accessible_interfaces,
        )

    def get_accessible_child_from_context(
        self, vm_id: int, context: int, index: int
    ) -> int:
        node = self._resolve(vm_id, context)
        if node is None or index < 0 or index >= len(node.children):
            return 0
        return self._mint(node.children[index])

    def get_accessible_parent_from_context(self, vm_id: int, context: int) -> int:
        node = self._resolve(vm_id, context)
        if node is None:
            return 0
        parent = self._parents[id(node)]
        if parent is None:
            return 0
        return self._mint(parent)

    def release_java_object(self, vm_id: int, value: int) -> None:
        if vm_id != self.vm_id:
            raise FakeBackendError(f"unknown vmID {vm_id}")
        if self._live.pop(value, None) is None:
            raise FakeBackendError(
                f"double release of {value:#x}, or a cookie that was never owned"
            )
        # A stale context still has to be handed back exactly once: the JVM
        # object is gone, the reference to it is not.
        self._stale.discard(value)
        self.released += 1

    def get_hwnd_from_accessible_context(self, vm_id: int, context: int) -> int:
        node = self._resolve(vm_id, context)
        if node is None:
            return 0
        return self._root_hwnds.get(id(node), 0)

    def get_accessible_actions(
        self, vm_id: int, context: int
    ) -> tuple[str, ...] | None:
        node = self._resolve(vm_id, context)
        return None if node is None else node.actions

    def do_accessible_actions(
        self, vm_id: int, context: int, actions: tuple[str, ...]
    ) -> tuple[bool, int]:
        node = self._resolve(vm_id, context)
        if node is None:
            return False, 0
        for index, action in enumerate(actions):
            if action not in node.actions:
                return False, index
            self.performed_actions.append((context, action))
        return True, -1

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def fake_backend_factory(
    windows: Mapping[int, FakeNode] | None = None,
    *,
    vm_id: int = 1,
    faults_before_ready: int = 0,
) -> tuple[FakeBackend, Callable[[], NativeBackend]]:
    """Return a fake backend and a factory that yields exactly that instance.

    The runtime builds its backend on its own worker thread; tests still need a
    handle on the instance to assert against, hence the pair.
    """
    backend = FakeBackend(windows, vm_id=vm_id, faults_before_ready=faults_before_ready)

    def factory() -> NativeBackend:
        return backend

    return backend, factory
