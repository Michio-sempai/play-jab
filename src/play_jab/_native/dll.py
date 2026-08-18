"""Locating and loading ``WindowsAccessBridge``.

This module knows where the Access Bridge lives on a machine and how to load it
safely. It does not call any bridge function.
"""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from play_jab.exceptions import BridgeInitializationError

__all__ = [
    "DLL_NAME_32",
    "DLL_NAME_64",
    "JAB_NOT_ENABLED_MESSAGE",
    "find_access_bridge_dll",
    "jab_enabled_for_current_user",
    "load_access_bridge",
    "process_bitness",
    "verify_exports",
]

DLL_NAME_32 = "WindowsAccessBridge-32.dll"
DLL_NAME_64 = "WindowsAccessBridge-64.dll"

_BITNESS_64 = 64
_BITNESS_32 = 32
_MAX_32_BIT_INTEGER = (1 << _BITNESS_32) - 1

_ACCESSIBILITY_PROPERTIES = ".accessibility.properties"
_ASSISTIVE_TECHNOLOGIES_KEY = "assistive_technologies"
_ACCESS_BRIDGE_TECHNOLOGY = "AccessBridge"

JAB_NOT_ENABLED_MESSAGE = (
    "Java Access Bridge is not enabled for the current user. Enable it with "
    r"`%JAVA_HOME%\bin\jabswitch -enable` and restart the Java application."
)
"""Shared between :mod:`bridge` (readiness probe) and :mod:`sync_api`
(desktop-wide discovery), so the two diagnostic paths cannot drift apart."""


def process_bitness() -> int:
    """Return the bitness of the *current process*, not of Windows.

    A 32-bit CPython on 64-bit Windows must load the 32-bit bridge: the DLL is
    loaded into this process, so the OS bitness is irrelevant.
    """
    return _BITNESS_64 if sys.maxsize > _MAX_32_BIT_INTEGER else _BITNESS_32


def _dll_file_name() -> str:
    return DLL_NAME_64 if process_bitness() == _BITNESS_64 else DLL_NAME_32


def _search_directories() -> Iterator[Path]:
    """Yield directories that may contain the Access Bridge DLL.

    The current working directory is deliberately never searched. Bundling the
    DLL with the wheel is an unresolved licensing question, so only a locally
    installed Java runtime and the system directory are considered.
    """
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        yield Path(java_home) / "bin"
    system_root = os.environ.get("SYSTEMROOT")
    if system_root:
        # A 32-bit process is redirected from System32 to SysWOW64 by the OS,
        # so the same path is correct for both bitnesses.
        yield Path(system_root) / "System32"


def _resolve_explicit_path(dll_path: str | os.PathLike[str]) -> Path:
    explicit = Path(dll_path)
    if not explicit.is_file():
        raise BridgeInitializationError(
            f"Access Bridge DLL not found at the given path: {explicit}"
        )
    return explicit.resolve()


def find_access_bridge_dll(dll_path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve an absolute path to the Access Bridge DLL for this process."""
    if dll_path is not None:
        return _resolve_explicit_path(dll_path)

    file_name = _dll_file_name()
    candidates = [directory / file_name for directory in _search_directories()]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    locations = ", ".join(str(path) for path in candidates) or "<no candidates>"
    raise BridgeInitializationError(
        f"{file_name} not found for this {process_bitness()}-bit process. "
        f"Looked in: {locations}. Install a JDK/JRE with Java Access Bridge or "
        f"pass an explicit dll_path."
    )


def load_access_bridge(dll_path: str | os.PathLike[str] | None = None) -> ctypes.CDLL:
    """Load the Access Bridge DLL and return the raw ``ctypes`` handle.

    ``CDLL`` (cdecl), not ``WinDLL`` (stdcall), settled from the compiled code
    rather than from convention.

    The decisive evidence is the epilogue of the shipped 32-bit build: every
    export ends in a bare ``C3`` (``ret``), never ``C2 imm16`` (``ret n``). Only
    cdecl leaves the stack for the caller to clean; a stdcall function would
    have to pop its own arguments. ``isJavaWindow`` in full::

        8b 0d d0 e0 00 10   mov  ecx, [init_flag]
        85 c9               test ecx, ecx
        74 0a               jz   uninitialized
        ff 74 24 04         push [esp+4]
        e8 cf 2f 00 00      call real_impl
        c3                  ret                  <- no operand: caller cleans
        33 c0               uninitialized: xor eax, eax
        c3                  ret

    Undecorated export names (``isJavaWindow``, not ``_isJavaWindow@4``) point
    the same way but prove nothing on their own, since a .def file strips that
    decoration from stdcall exports too. The header agrees as well - no
    function-pointer typedef in AccessBridgeCalls.h carries ``WINAPI`` or
    ``__stdcall``, so each takes the MSVC default of ``__cdecl``.

    This only changes behaviour in a 32-bit process, since x64 has a single
    calling convention, and getting it wrong there corrupts the stack silently
    instead of failing loudly - which is why it is evidenced rather than assumed.
    """
    if sys.platform != "win32":  # pragma: no cover - guarded off-Windows
        raise BridgeInitializationError(
            f"Java Access Bridge is Windows-only; current platform is {sys.platform!r}"
        )

    path = find_access_bridge_dll(dll_path)
    # An absolute path means the loader performs no search of its own, so a DLL
    # dropped into the current working directory can never be picked up.
    try:
        return ctypes.CDLL(str(path))
    except OSError as exc:
        raise BridgeInitializationError(
            f"failed to load Access Bridge DLL {path}: {exc}"
        ) from exc


def verify_exports(dll: ctypes.CDLL, exports: Iterable[str]) -> None:
    """Fail fast if the loaded DLL is missing any required export."""
    missing = [name for name in exports if not hasattr(dll, name)]
    if missing:
        missing_names = ", ".join(missing)
        raise BridgeInitializationError(
            f"Access Bridge DLL is missing required export(s): {missing_names}. "
            "The loaded library is not a compatible "
            "WindowsAccessBridge build."
        )


def _access_bridge_setting(line: str) -> bool | None:
    stripped = line.strip()
    if stripped.startswith(("#", "!")):
        return None
    key, separator, configured = stripped.partition("=")
    if separator and key.strip() == _ASSISTIVE_TECHNOLOGIES_KEY:
        return _ACCESS_BRIDGE_TECHNOLOGY in configured
    return None


def jab_enabled_for_current_user() -> bool:
    r"""Report whether the user's Java accessibility properties enable JAB.

    ``jabswitch -enable`` writes ``assistive_technologies=...AccessBridge`` into
    ``%USERPROFILE%\\.accessibility.properties``. Used only to turn a failed
    bridge startup into a more precise diagnostic; play-jab never writes this
    file.
    """
    properties = Path.home() / _ACCESSIBILITY_PROPERTIES
    try:
        text = properties.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    for line in text.splitlines():
        enabled = _access_bridge_setting(line)
        if enabled is not None:
            return enabled
    return False
