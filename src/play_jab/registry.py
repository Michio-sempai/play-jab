# flake8: noqa
"""JDK 17 accessibility role and state registries."""

from __future__ import annotations

from collections.abc import Iterable

from play_jab.exceptions import (
    UnsupportedAccessibleRoleError,
    UnsupportedAccessibleStateError,
)

__all__ = ["STANDARD_ROLES", "STANDARD_STATES", "AccessibilityRegistry"]

# Generated from javax.accessibility.AccessibleRole in JDK 17.  Values are the
# stable en_US strings exposed by Java Access Bridge, not Java constant names.
STANDARD_ROLES = frozenset(
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
        "table",
        "text",
        "toggle button",
        "tool bar",
        "tool tip",
        "swing component",
        "tree",
        "unknown",
        "viewport",
        "window",
    }
)

# Generated from javax.accessibility.AccessibleState in JDK 17.
STANDARD_STATES = frozenset(
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


class AccessibilityRegistry:
    """Validated per-API registry with opt-in application extensions."""

    def __init__(
        self,
        extra_roles: Iterable[str] = (),
        extra_states: Iterable[str] = (),
    ) -> None:
        self.roles = STANDARD_ROLES | self._extensions(extra_roles, "role")
        self.states = STANDARD_STATES | self._extensions(extra_states, "state")

    @staticmethod
    def _extensions(values: Iterable[str], kind: str) -> frozenset[str]:
        result: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value:
                raise ValueError(f"extra {kind}s must be non-empty strings")
            result.add(value)
        return frozenset(result)

    def role(self, value: str) -> str:
        if value not in self.roles:
            raise UnsupportedAccessibleRoleError(
                f"unsupported accessible role: {value!r}"
            )
        return value

    def state(self, value: str) -> str:
        if value not in self.states:
            raise UnsupportedAccessibleStateError(
                f"unsupported accessible state: {value!r}"
            )
        return value
