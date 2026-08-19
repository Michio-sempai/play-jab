"""Public exception hierarchy for :mod:`play_jab`.

Only the exceptions that have a concrete raise site in the current native slice
are defined here. Locator, table and role/state registry errors named in the
concept document are added when the layers that raise them exist.
"""

from __future__ import annotations

__all__ = [
    "BridgeClosedError",
    "BridgeInitializationError",
    "BridgeNotEnabledError",
    "InputNotAvailableError",
    "JavaProcessExitedError",
    "JavaReferenceClosedError",
    "JavaVmExitedError",
    "JavaWindowAmbiguousError",
    "JavaWindowNotAccessibleError",
    "JavaWindowNotFoundError",
    "LocatorError",
    "LocatorTimeoutError",
    "NativeCallError",
    "PlayJabError",
    "StrictModeViolation",
    "TableIndexError",
    "UnsupportedAccessibleRoleError",
    "UnsupportedAccessibleStateError",
    "UnsupportedActionError",
]


class PlayJabError(Exception):
    """Base class for every error raised by play-jab."""


class BridgeInitializationError(PlayJabError):
    """The Access Bridge DLL could not be located, loaded or made ready."""


class BridgeNotEnabledError(BridgeInitializationError):
    r"""Java Access Bridge is not enabled for the current user.

    Raised instead of the generic initialization error when the bridge never
    becomes ready and the user's ``.accessibility.properties`` does not enable
    the Access Bridge assistive technology. play-jab never enables it silently;
    the user is expected to run ``%JAVA_HOME%\\bin\\jabswitch -enable``.
    """


class BridgeClosedError(PlayJabError):
    """A closed bridge runtime was used.

    Once :class:`~play_jab._native.bridge.BridgeRuntime` shuts down, the DLL is
    unloaded and every reference belonging to it is invalid, so any further
    operation fails with this error rather than calling into freed native code.
    """


class JavaReferenceClosedError(PlayJabError):
    """An individual Java reference was used after being released.

    A sibling of :class:`BridgeClosedError`, not a subclass, so that neither
    direction of conflation is possible. A broad ``except BridgeClosedError:
    give up`` cannot swallow a recoverable stale reference, and an ``except
    BridgeClosedError: retry`` cannot spin forever against a dead runtime.
    Subclassing would have prevented only the second.

    The two call for opposite responses: the runtime is still alive here, so the
    remedy is to re-resolve the node and retry, not to abandon the bridge.
    """


class JavaWindowNotFoundError(PlayJabError):
    """The requested window does not exist or is not a Java window."""


class InputNotAvailableError(PlayJabError):
    """Synthetic Win32 keyboard/mouse input was required but not available.

    Raised both when a caller has not explicitly opted into an operation
    that sends OS-level input (a ``force_input=True`` parameter was not
    passed) and when the underlying Win32 call itself failed (for example, a
    non-interactive session with no desktop to deliver input to). Both are
    the same category of problem for a caller: this operation cannot drive
    real keyboard/mouse input right now, and a broad ``except PlayJabError``
    should catch it like every other play-jab failure -- unlike the raw
    ``OSError`` this used to surface as.
    """


class JavaWindowNotAccessibleError(PlayJabError):
    """The window is a Java window but exposes no accessible context."""


class JavaProcessExitedError(PlayJabError):
    """The Java process exited before the requested operation completed."""


class JavaVmExitedError(PlayJabError):
    """The attached JVM shut down while its operating-system process survived."""


class JavaWindowAmbiguousError(PlayJabError):
    """More than one Java window satisfies a strict window query."""


class LocatorError(PlayJabError):
    """An accessibility locator could not be resolved."""


class StrictModeViolation(LocatorError):
    """An operation requiring one node resolved to multiple nodes."""


class LocatorTimeoutError(LocatorError):
    """A locator condition was not met before its deadline."""

    def __init__(  # noqa: PLR0913, WPS211
        self,
        message: str,
        *,
        locator: str | None = None,
        expected: str | None = None,
        last_state: object = None,
        elapsed_ms: int | None = None,
        tree: str | None = None,
        hwnd: int | None = None,
        pid: int | None = None,
        generation: int | None = None,
    ) -> None:
        self.locator = locator
        self.expected = expected
        self.last_state = last_state
        self.elapsed_ms = elapsed_ms
        self.tree = tree
        self.hwnd = hwnd
        self.pid = pid
        self.generation = generation
        super().__init__(message)


class UnsupportedActionError(LocatorError):
    """A locator target does not expose a suitable accessible action."""


class TableIndexError(LocatorError, IndexError):
    """A zero-based table row or column is outside the current dimensions."""


class UnsupportedAccessibleRoleError(PlayJabError, ValueError):
    """A locator used a role outside the configured role registry."""


class UnsupportedAccessibleStateError(PlayJabError, ValueError):
    """A locator used a state outside the configured state registry."""


class NativeCallError(PlayJabError):
    """A native Access Bridge call reported failure.

    Carries the DLL export name and the arguments so the failure is diagnosable.
    Only scalar arguments are recorded; text read from the application (which
    may include password field contents) is never attached.
    """

    def __init__(self, function: str, /, **arguments: object) -> None:
        self.function = function
        self.arguments = dict(arguments)
        parts = (f"{key}={value!r}" for key, value in arguments.items())
        rendered = ", ".join(parts)
        super().__init__(f"native call {function}({rendered}) failed")
