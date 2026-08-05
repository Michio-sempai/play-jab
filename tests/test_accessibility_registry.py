"""Contract for the generated JDK 17 role and state registry."""

from __future__ import annotations

import pytest

from play_jab.exceptions import (
    UnsupportedAccessibleRoleError,
    UnsupportedAccessibleStateError,
)
from play_jab.registry import STANDARD_ROLES, STANDARD_STATES, AccessibilityRegistry

JDK_17_ROLES = frozenset(
    {
        "alert",
        "awt component",
        "canvas",
        "check box",
        "color chooser",
        "column header",
        "combo box",
        "date editor",
        "desktop icon",
        "desktop pane",
        "dialog",
        "directory pane",
        "editbar",
        "file chooser",
        "filler",
        "font chooser",
        "footer",
        "frame",
        "glass pane",
        "group box",
        "header",
        "hyperlink",
        "icon",
        "internal frame",
        "label",
        "layered pane",
        "list",
        "list item",
        "menu",
        "menu bar",
        "menu item",
        "option pane",
        "page tab",
        "page tab list",
        "panel",
        "paragraph",
        "password text",
        "popup menu",
        "progress bar",
        "progress monitor",
        "push button",
        "radio button",
        "root pane",
        "row header",
        "ruler",
        "scroll bar",
        "scroll pane",
        "separator",
        "slider",
        "spin box",
        "split pane",
        "status bar",
        "swing component",
        "table",
        "text",
        "toggle button",
        "tool bar",
        "tool tip",
        "tree",
        "unknown",
        "viewport",
        "window",
    }
)

JDK_17_STATES = frozenset(
    {
        "active",
        "armed",
        "busy",
        "checked",
        "collapsed",
        "editable",
        "enabled",
        "expandable",
        "expanded",
        "focusable",
        "focused",
        "horizontal",
        "iconified",
        "indeterminate",
        "manages descendants",
        "modal",
        "multi line",
        "multiselectable",
        "opaque",
        "pressed",
        "resizable",
        "selectable",
        "selected",
        "showing",
        "single line",
        "transient",
        "truncated",
        "vertical",
        "visible",
    }
)


def test_standard_roles_are_the_complete_jdk_17_registry() -> None:
    assert STANDARD_ROLES == JDK_17_ROLES


def test_standard_states_are_the_complete_jdk_17_registry() -> None:
    assert STANDARD_STATES == JDK_17_STATES


def test_unknown_is_a_standard_role() -> None:
    assert AccessibilityRegistry().role("unknown") == "unknown"


def test_application_extensions_are_scoped_to_their_registry() -> None:
    extended = AccessibilityRegistry(
        extra_roles=("application widget",),
        extra_states=("application state",),
    )
    assert extended.role("application widget") == "application widget"
    assert extended.state("application state") == "application state"
    with pytest.raises(UnsupportedAccessibleRoleError):
        AccessibilityRegistry().role("application widget")
    with pytest.raises(UnsupportedAccessibleStateError):
        AccessibilityRegistry().state("application state")


@pytest.mark.parametrize("invalid", ["", 1, None])
def test_invalid_role_extensions_are_rejected(invalid: object) -> None:
    with pytest.raises(ValueError):
        AccessibilityRegistry(extra_roles=(invalid,))  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", ["", 1, None])
def test_invalid_state_extensions_are_rejected(invalid: object) -> None:
    with pytest.raises(ValueError):
        AccessibilityRegistry(extra_states=(invalid,))  # type: ignore[arg-type]


def test_registry_matching_is_exact_and_case_sensitive() -> None:
    registry = AccessibilityRegistry()
    with pytest.raises(UnsupportedAccessibleRoleError):
        registry.role("Push Button")
    with pytest.raises(UnsupportedAccessibleStateError):
        registry.state("Visible")
