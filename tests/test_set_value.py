"""Contract tests for ``Locator.set_value()``.

Covers only the v1 scope agreed for this method: an integer, unit-step
``AccessibleValue`` component exposing "increment"/"decrement"
``AccessibleAction``s (a real ``JSlider``, or an integer-step ``JSpinner``) -
confirmed empirically against both widgets in the play-jab-demo-app fixture
that a batch of N same-named actions in one native call applies N steps, not
one (see the matching integration test in ``tests/integration/``).

Locale-dependent action names, ``snapToTicks``, and a non-integer/non-unit
step are out of scope and not covered here.
"""

from __future__ import annotations

import time

import pytest

from play_jab import sync_api
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.fake import FakeBackend, FakeNode
from play_jab.exceptions import (
    LocatorError,
    LocatorTimeoutError,
    UnsupportedActionError,
)
from play_jab.sync_api import AccessibleInterface, PlayJab

from .conftest import FakeWindowBackend

PID = 4242
HWND = 0xCAFE
MAX_ACTIONS_TO_DO = 32
_LARGE_DELTA_TARGET = 50
_DEADLINE_TEST_ABORT_BUDGET_S = 0.2


def _slider_node(  # noqa: PLR0913 -- independent config knobs for a test fixture
    *,
    value: int,
    minimum: int = 0,
    maximum: int = 10,
    actions: tuple[str, ...] = ("increment", "decrement"),
    states: str = "enabled,visible,showing",
    applies_value_step: bool = True,
) -> FakeNode:
    return FakeNode(
        name="Slider",
        role_en_us="slider",
        states_en_us=states,
        accessible_interfaces=int(AccessibleInterface.VALUE),
        value=str(value),
        minimum_value=str(minimum),
        maximum_value=str(maximum),
        actions=actions,
        applies_value_step=applies_value_step,
    )


def _wire(monkeypatch: pytest.MonkeyPatch, node: FakeNode) -> FakeBackend:
    """Wire ``node`` as the sole child of the fixture root and patch it in."""
    roots = {
        HWND: FakeNode(
            name="Fixture",
            role_en_us="frame",
            states_en_us="enabled,visible,showing",
            children=[node],
        )
    }
    backend = FakeBackend(roots)
    runtime = BridgeRuntime(lambda: backend, pump_interval=0.001)
    windows = FakeWindowBackend({HWND: "Fixture"}, pid=PID)
    monkeypatch.setattr(sync_api, "_create_runtime", lambda _path, _timeout: runtime)
    monkeypatch.setattr(sync_api, "_create_window_backend", lambda: windows)
    monkeypatch.setattr(sync_api, "_is_process_alive", lambda pid: pid == PID)
    return backend


def test_set_value_increments_toward_a_higher_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=3)
    backend = _wire(monkeypatch, node)

    with PlayJab(timeout=1_000) as api:
        window = api.attach(pid=PID).window(hwnd=HWND)
        window.get_by_name("Slider").set_value(6)
        assert api.live_ref_count == 0

    assert node.value == "6"
    assert [action for _ctx, action in backend.performed_actions] == ["increment"] * 3


def test_set_value_decrements_toward_a_lower_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=6)
    backend = _wire(monkeypatch, node)

    with PlayJab(timeout=1_000) as api:
        api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider").set_value(3)

    assert node.value == "3"
    assert [action for _ctx, action in backend.performed_actions] == ["decrement"] * 3


def test_set_value_with_no_delta_sends_no_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=3)
    backend = _wire(monkeypatch, node)

    with PlayJab(timeout=1_000) as api:
        api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider").set_value(3)

    assert node.value == "3"
    assert backend.performed_actions == []


def test_set_value_rejects_a_value_outside_the_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=3, minimum=0, maximum=10)
    backend = _wire(monkeypatch, node)

    with PlayJab(timeout=1_000) as api:
        locator = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider")
        with pytest.raises(ValueError, match=r"outside \[0, 10\]"):
            locator.set_value(11)

    assert node.value == "3"
    assert backend.performed_actions == []


def test_set_value_raises_when_no_matching_action_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=3, actions=())
    _wire(monkeypatch, node)

    with PlayJab(timeout=1_000) as api:
        locator = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider")
        with pytest.raises(UnsupportedActionError, match="increment"):
            locator.set_value(6)

    assert node.value == "3"


def test_set_value_batches_a_large_delta_into_max_actions_to_do_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=0, maximum=100)
    backend = _wire(monkeypatch, node)
    batch_sizes: list[int] = []
    original = backend.do_accessible_actions

    def recording_do_accessible_actions(
        vm_id: int, context: int, actions: tuple[str, ...]
    ) -> tuple[bool, int]:
        batch_sizes.append(len(actions))
        return original(vm_id, context, actions)

    backend.do_accessible_actions = recording_do_accessible_actions  # type: ignore[method-assign]

    with PlayJab(timeout=1_000) as api:
        api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider").set_value(
            _LARGE_DELTA_TARGET
        )

    assert node.value == str(_LARGE_DELTA_TARGET)
    assert sum(batch_sizes) == _LARGE_DELTA_TARGET
    assert all(size <= MAX_ACTIONS_TO_DO for size in batch_sizes)
    assert len(batch_sizes) > 1


def test_set_value_enforces_the_overall_deadline_across_progressing_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: each batch was individually re-checked for *no progress*,
    but the loop never checked the caller's own deadline against batches
    that kept progressing - a large enough delta over a slow enough
    transport could run well past ``timeout`` before this fix, never
    raising ``LocatorTimeoutError`` as documented (code-review finding)."""
    node = _slider_node(value=0, maximum=1_000)
    backend = _wire(monkeypatch, node)
    original = backend.do_accessible_actions

    def slow_do_accessible_actions(
        vm_id: int, context: int, actions: tuple[str, ...]
    ) -> tuple[bool, int]:
        time.sleep(0.01)  # simulates real per-batch IPC latency
        return original(vm_id, context, actions)

    backend.do_accessible_actions = slow_do_accessible_actions  # type: ignore[method-assign]

    with PlayJab(timeout=1_000) as api:
        locator = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider")
        started = time.monotonic()
        with pytest.raises(LocatorTimeoutError):
            locator.set_value(1_000, timeout=50)
        elapsed = time.monotonic() - started

    # Needs ceil(1000/32)=32 batches at 10ms each (~320ms) to actually
    # converge; a correct deadline check aborts near the 50ms timeout, not
    # anywhere close to that.
    assert elapsed < _DEADLINE_TEST_ABORT_BUDGET_S


def test_set_value_raises_timeout_immediately_when_a_batch_makes_no_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=3, applies_value_step=False)
    _wire(monkeypatch, node)

    with PlayJab(timeout=1_000) as api:
        locator = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider")
        with pytest.raises(LocatorTimeoutError):
            locator.set_value(6, timeout=1_000)

    assert node.value == "3"


def test_set_value_rejects_a_non_int_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=3)
    _wire(monkeypatch, node)

    with PlayJab(timeout=1_000) as api:
        locator = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider")
        with pytest.raises(TypeError, match="int"):
            locator.set_value(6.0)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="int"):
            locator.set_value(True)  # type: ignore[arg-type]


def test_set_value_on_a_hidden_node_is_rejected_as_not_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = _slider_node(value=3, states="")
    _wire(monkeypatch, node)

    with PlayJab(timeout=1_000) as api:
        locator = api.attach(pid=PID).window(hwnd=HWND).get_by_name("Slider")
        with pytest.raises(LocatorError, match="not actionable"):
            locator.set_value(6, timeout=0)
