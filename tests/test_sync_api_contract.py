"""Public contract tests for the synchronous read-only API.

These tests intentionally exercise the documented surface, rather than native
implementation details.  Backend-specific traversal tests live next to them
and replace the three module factories with deterministic fakes.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from play_jab.exceptions import (
    JavaProcessExitedError,
    JavaWindowAmbiguousError,
    LocatorError,
    LocatorTimeoutError,
    PlayJabError,
    StrictModeViolation,
    UnsupportedAccessibleRoleError,
    UnsupportedAccessibleStateError,
    UnsupportedActionError,
)
from play_jab.sync_api import (
    AccessibilityNode,
    ElementSnapshot,
    JavaApplication,
    JavaWindow,
    Locator,
    PlayJab,
    WindowExpectation,
    contains,
)


def _parameters(callable_object: Callable[..., object]) -> tuple[str, ...]:
    return tuple(inspect.signature(callable_object).parameters)


def test_the_public_types_are_exported_from_sync_api() -> None:
    assert _parameters(PlayJab)[:4] == (
        "timeout",
        "dll_path",
        "extra_roles",
        "extra_states",
    )
    assert not hasattr(PlayJab, "launch")
    assert _parameters(PlayJab.attach) == (
        "self",
        "hwnd",
        "pid",
        "title",
        "timeout",
    )
    assert _parameters(JavaApplication.window) == (
        "self",
        "hwnd",
        "title",
        "timeout",
    )
    assert _parameters(JavaWindow.locator) == (
        "self",
        "role",
        "name",
        "description",
        "states",
        "index_in_parent",
        "visible_only",
    )
    assert _parameters(Locator.wait_for) == ("self", "state", "timeout")
    assert _parameters(Locator.click) == ("self", "opens_window", "timeout")
    assert _parameters(JavaApplication.expect_window) == ("self", "title", "timeout")
    assert inspect.isclass(WindowExpectation)


@pytest.mark.parametrize(
    "exception_type",
    [
        JavaProcessExitedError,
        JavaWindowAmbiguousError,
        LocatorError,
        LocatorTimeoutError,
        StrictModeViolation,
        UnsupportedAccessibleRoleError,
        UnsupportedAccessibleStateError,
        UnsupportedActionError,
    ],
)
def test_new_public_errors_belong_to_the_package_hierarchy(
    exception_type: type[BaseException],
) -> None:
    assert issubclass(exception_type, PlayJabError)


def test_contains_is_an_explicit_matcher_not_a_string() -> None:
    matcher = contains("needle")
    assert not isinstance(matcher, str)
    assert matcher != contains("different")


def test_snapshot_and_diagnostic_tree_are_immutable_value_objects() -> None:
    assert inspect.isclass(ElementSnapshot)
    assert inspect.isclass(AccessibilityNode)
    assert "__dataclass_fields__" in vars(ElementSnapshot)
    assert "__dataclass_fields__" in vars(AccessibilityNode)
    snapshot_params = inspect.signature(ElementSnapshot, eval_str=True).parameters
    values: dict[str, object] = {
        name: _sample_value(parameter.annotation)
        for name, parameter in snapshot_params.items()
    }
    snapshot = ElementSnapshot(**values)  # type: ignore[arg-type]
    field = next(iter(snapshot_params))
    with pytest.raises(FrozenInstanceError):
        setattr(snapshot, field, getattr(snapshot, field))


def _sample_value(annotation: object) -> object:
    """Produce a harmless value solely for the frozen-dataclass contract.

    Resolved against the real annotation object (``eval_str=True`` above),
    not its string spelling, so a future field like ``list[bool]`` cannot be
    mistaken for ``bool`` the way a substring match on ``str(annotation)``
    would (see unit-tests-review.md finding B-7).
    """
    origin = typing.get_origin(annotation)
    if origin is frozenset:
        return frozenset()
    if origin is tuple:
        return ()
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is str:
        return ""
    if annotation is type(None):
        return None
    raise AssertionError(
        f"add a sample value for ElementSnapshot annotation {annotation!r}"
    )
