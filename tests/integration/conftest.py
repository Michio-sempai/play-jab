"""Fixtures for the opt-in Java Access Bridge integration suite.

Set ``PLAY_JAB_RUN_INTEGRATION=1`` on an interactive Windows runner with JDK 17.
The suite compiles the checked-in Swing fixture and resolves a bitness-compatible
DLL from ``JAVA_HOME``/``System32``. ``PLAY_JAB_JAVA_EXE`` and ``PLAY_JAB_DLL``
override those discoveries. The disabled-JAB scenario additionally requires an
isolated user profile and ``PLAY_JAB_ISOLATED_DISABLED_PROFILE=1``.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from play_jab._native.backend import NativeBackend, dll_backend_factory
from play_jab._native.dll import find_access_bridge_dll
from play_jab.exceptions import BridgeInitializationError

_OPT_IN = "PLAY_JAB_RUN_INTEGRATION"
_WINDOW_TITLE = "JAB swing fixture"
_WINDOW_TIMEOUT = 20.0
_PROCESS_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class SwingFixture:
    """A running Swing fixture and the HWND belonging to its process."""

    hwnd: int
    process: subprocess.Popen[str]


def _integration_requested() -> bool:
    return os.environ.get(_OPT_IN, "").lower() in {"1", "true", "yes"}


def _fixture_root() -> Path:
    return Path(__file__).parents[1] / "java-fixtures" / "jab-swing-app"


def _compile_fixture(root: Path) -> None:
    wrapper = root / "gradlew.bat"
    if not wrapper.is_file():
        pytest.fail(f"Gradle wrapper is missing: {wrapper}")
    completed = subprocess.run(
        [str(wrapper), "--no-daemon", "classes"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
        timeout=180,
    )
    if completed.returncode:
        pytest.fail(
            "Could not compile the Java integration fixture.\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def _java_executable() -> str:
    explicit = os.environ.get("PLAY_JAB_JAVA_EXE")
    executable = explicit or shutil.which("java")
    if not executable:
        pytest.fail("Java was not found; set PLAY_JAB_JAVA_EXE to a JDK 17 java.exe")
    return executable


def _window_for_process(process_id: int) -> int | None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    matches: list[int] = []

    user32.EnumWindows.argtypes = [enum_callback, ctypes.c_void_p]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.GetWindowThreadProcessId.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int

    @enum_callback
    def visit(hwnd: int, _parameter: int) -> bool:
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != process_id:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value == _WINDOW_TITLE:
            matches.append(int(hwnd))
            return False
        return True

    if not user32.EnumWindows(visit, None) and not matches:
        error = ctypes.get_last_error()
        if error:
            raise ctypes.WinError(error)
    return matches[0] if matches else None


def _wait_for_window(process: subprocess.Popen[str]) -> int:
    deadline = time.monotonic() + _WINDOW_TIMEOUT
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            stdout, stderr = process.communicate(timeout=_PROCESS_TIMEOUT)
            pytest.fail(
                f"Swing fixture exited with code {return_code}.\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        hwnd = _window_for_process(process.pid)
        if hwnd is not None:
            return hwnd
        time.sleep(0.05)
    pytest.fail(f"Swing fixture did not create {_WINDOW_TITLE!r} within the timeout")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=_PROCESS_TIMEOUT)


@pytest.fixture(scope="session")
def jab_dll_path() -> Path:
    """Resolve a DLL matching the current Python process architecture."""
    explicit = os.environ.get("PLAY_JAB_DLL")
    try:
        return find_access_bridge_dll(explicit)
    except BridgeInitializationError as exc:
        pytest.fail(str(exc))


@pytest.fixture(scope="session")
def backend_factory(jab_dll_path: Path) -> Callable[[], NativeBackend]:
    """Create real backends using the integration suite's selected DLL."""
    return dll_backend_factory(jab_dll_path)


@pytest.fixture(scope="session")
def swing_fixture() -> Iterator[SwingFixture]:
    """Compile and start the existing fixture with JAB explicitly activated."""
    root = _fixture_root()
    _compile_fixture(root)
    classes = root / "build" / "classes" / "java" / "main"
    command = [
        _java_executable(),
        "-Djavax.accessibility.assistive_technologies=com.sun.java.accessibility.AccessBridge",
        "-cp",
        str(classes),
        "FixtureLauncher",
        "swing",
    ]
    process = subprocess.Popen(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        yield SwingFixture(_wait_for_window(process), process)
    finally:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _stop_process(process)


@pytest.fixture(scope="session")
def disabled_swing_fixture() -> Iterator[SwingFixture]:
    """Start the fixture without a JAB JVM flag for isolated-profile testing."""
    if os.environ.get("PLAY_JAB_ISOLATED_DISABLED_PROFILE") != "1":
        pytest.skip("requires an isolated Windows profile with JAB disabled")
    root = _fixture_root()
    _compile_fixture(root)
    classes = root / "build" / "classes" / "java" / "main"
    process = subprocess.Popen(
        [
            _java_executable(),
            "-cp",
            str(classes),
            "FixtureLauncher",
            "swing",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        yield SwingFixture(_wait_for_window(process), process)
    finally:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _stop_process(process)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip native integration tests unless the operator opts in explicitly."""
    if _integration_requested():
        return
    skipped = pytest.mark.skip(
        reason=f"set {_OPT_IN}=1 to run real Windows/JAB integration tests"
    )
    for item in items:
        if "integration_jab" in item.keywords:
            item.add_marker(skipped)


def pytest_configure(config: pytest.Config) -> None:
    """Reject opt-in early on platforms where JAB cannot run."""
    if _integration_requested() and sys.platform != "win32":
        pytest.exit("Java Access Bridge integration tests require Windows")
