"""Public contract tests for the synchronous read-only API.

These tests intentionally exercise the documented surface, rather than native
implementation details.  Backend-specific traversal tests live next to them
and replace the three module factories with deterministic fakes.
"""

from __future__ import annotations

import inspect
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


def _parameters(callable_object: object) -> tuple[str, ...]:
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
    snapshot_params = inspect.signature(ElementSnapshot).parameters
    values = {
        name: _sample_value(parameter.annotation)
        for name, parameter in snapshot_params.items()
    }
    snapshot = ElementSnapshot(**values)
    field = next(iter(snapshot_params))
    with pytest.raises(FrozenInstanceError):
        setattr(snapshot, field, getattr(snapshot, field))


def _sample_value(annotation: object) -> object:
    """Produce a harmless value solely for the frozen-dataclass contract."""
    rendered = str(annotation)
    if "bool" in rendered:
        return False
    if "int" in rendered:
        return 0
    if "tuple" in rendered:
        return ()
    if "None" in rendered and "str" not in rendered:
        return None
    return ""
