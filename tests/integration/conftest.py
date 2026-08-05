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
import itertools
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
from play_jab.sync_api import PlayJab

_OPT_IN = "PLAY_JAB_RUN_INTEGRATION"
_WINDOW_TITLE = "JAB swing fixture"
_SECONDARY_WINDOW_TITLE = "JAB swing fixture secondary"
_WINDOW_TIMEOUT = 20.0
_PROCESS_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class SwingFixture:
    """A running Swing fixture and the HWND belonging to its process."""

    hwnd: int
    process: subprocess.Popen[str]
    stdout_log: Path
    stderr_log: Path


@dataclass(frozen=True, slots=True)
class DialogFixture:
    """A function-scoped JDialog reproducer and its owner HWND."""

    hwnd: int
    process: subprocess.Popen[str]
    stdout_log: Path
    stderr_log: Path


@dataclass(frozen=True, slots=True)
class JavaFixtureBuild:
    """Session-built Java classes and persistent diagnostic-log directory."""

    root: Path
    classes: Path
    log_directory: Path


_JVM_SEQUENCE = itertools.count(1)


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


def _log_tail(path: Path, *, limit: int = 8_000) -> str:
    """Return a bounded diagnostic tail without keeping a JVM pipe open."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"<could not read {path}: {exc}>"
    return content[-limit:]


@contextlib.contextmanager
def _running_jvm(
    build: JavaFixtureBuild,
    name: str,
    arguments: list[str],
) -> Iterator[tuple[subprocess.Popen[str], Path, Path]]:
    """Run one JVM with file-backed output so a verbose process cannot deadlock."""
    sequence = next(_JVM_SEQUENCE)
    stdout_path = build.log_directory / f"{sequence:02d}-{name}.stdout.log"
    stderr_path = build.log_directory / f"{sequence:02d}-{name}.stderr.log"
    with (
        stdout_path.open("w", encoding="utf-8", newline="") as stdout_file,
        stderr_path.open("w", encoding="utf-8", newline="") as stderr_file,
    ):
        process = subprocess.Popen(
            arguments,
            cwd=build.root,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
        try:
            yield process, stdout_path, stderr_path
        finally:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                _stop_process(process)


def _java_executable() -> str:
    explicit = os.environ.get("PLAY_JAB_JAVA_EXE")
    executable = explicit or shutil.which("java")
    if not executable:
        pytest.fail("Java was not found; set PLAY_JAB_JAVA_EXE to a JDK 17 java.exe")
    return executable


def _window_for_process(process_id: int) -> int | None:
    matches = raw_windows(process_id, title=_WINDOW_TITLE)
    return matches[0] if matches else None


def raw_windows(process_id: int, *, title: str | None = None) -> list[int]:
    """Enumerate raw top-level HWNDs by PID and optional exact title."""
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
        window_title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, window_title, len(window_title))
        if title is None or window_title.value == title:
            matches.append(int(hwnd))
        return True

    if not user32.EnumWindows(visit, None) and not matches:
        error = ctypes.get_last_error()
        if error:
            raise ctypes.WinError(error)
    return matches


def _process_diagnostics(stdout_log: Path, stderr_log: Path) -> str:
    return (
        f"stdout log: {stdout_log}\n{_log_tail(stdout_log)}\n"
        f"stderr log: {stderr_log}\n{_log_tail(stderr_log)}"
    )


def _wait_for_window(
    process: subprocess.Popen[str],
    stdout_log: Path,
    stderr_log: Path,
) -> int:
    deadline = time.monotonic() + _WINDOW_TIMEOUT
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            pytest.fail(
                f"Swing fixture exited with code {return_code}.\n"
                f"{_process_diagnostics(stdout_log, stderr_log)}"
            )
        hwnd = _window_for_process(process.pid)
        if hwnd is not None:
            return hwnd
        time.sleep(0.05)
    pytest.fail(f"Swing fixture did not create {_WINDOW_TITLE!r} within the timeout")


def wait_for_raw_window(
    process: subprocess.Popen[str],
    title: str,
    stdout_log: Path | None = None,
    stderr_log: Path | None = None,
) -> int:
    """Wait for one exact raw HWND, without consulting Java Access Bridge."""
    deadline = time.monotonic() + _WINDOW_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            diagnostics = ""
            if stdout_log is not None and stderr_log is not None:
                diagnostics = "\n" + _process_diagnostics(stdout_log, stderr_log)
            pytest.fail(
                f"Dialog fixture exited with code {process.returncode}; "
                f"expected {title!r}.{diagnostics}"
            )
        matches = raw_windows(process.pid, title=title)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            pytest.fail(f"multiple raw windows titled {title!r}: {matches!r}")
        time.sleep(0.05)
    pytest.fail(
        f"process {process.pid} did not create {title!r}; "
        f"raw HWNDs: {raw_windows(process.pid)!r}"
    )


def wait_for_raw_window_closed(process_id: int, title: str) -> None:
    deadline = time.monotonic() + _WINDOW_TIMEOUT
    while time.monotonic() < deadline:
        if not raw_windows(process_id, title=title):
            return
        time.sleep(0.05)
    pytest.fail(f"process {process_id} did not close raw window {title!r}")


def close_raw_window(hwnd: int) -> None:
    """Post WM_CLOSE without making any JAB call."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user32.PostMessageW.restype = ctypes.c_bool
    if not user32.PostMessageW(hwnd, 0x0010, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=_PROCESS_TIMEOUT)


def _wait_for_accessible_windows(
    process: subprocess.Popen[str],
    dll_path: Path,
    *titles: str,
) -> None:
    """Wait until every expected top-level window is visible through JAB."""
    with PlayJab(timeout=int(_WINDOW_TIMEOUT * 1_000), dll_path=dll_path) as api:
        application = api.attach(pid=process.pid)
        for title in titles:
            application.window(title=title)


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
def java_fixture_build() -> JavaFixtureBuild:
    """Compile the Java fixture exactly once for the complete pytest session."""
    root = _fixture_root()
    _compile_fixture(root)
    classes = root / "build" / "classes" / "java" / "main"
    log_directory = (
        root / "build" / "integration-logs" / f"{os.getpid()}-{time.time_ns()}"
    )
    log_directory.mkdir(parents=True, exist_ok=False)
    return JavaFixtureBuild(root, classes, log_directory)


def _fixture_command(
    build: JavaFixtureBuild,
    *arguments: str,
    jab_enabled: bool = True,
) -> list[str]:
    command = [
        _java_executable(),
    ]
    if jab_enabled:
        command.append(
            "-Djavax.accessibility.assistive_technologies="
            "com.sun.java.accessibility.AccessBridge"
        )
    return [
        *command,
        "-cp",
        str(build.classes),
        "FixtureLauncher",
        *arguments,
    ]


@pytest.fixture(scope="session")
def swing_fixture(java_fixture_build: JavaFixtureBuild) -> Iterator[SwingFixture]:
    """Start the session Swing fixture with JAB explicitly activated."""
    with _running_jvm(
        java_fixture_build,
        "swing",
        _fixture_command(java_fixture_build, "swing"),
    ) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = _wait_for_window(process, stdout_log, stderr_log)
        yield SwingFixture(hwnd, process, stdout_log, stderr_log)


@pytest.fixture
def dialog_fixture(
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[DialogFixture]:
    """Start a fresh JVM for one modal-dialog scenario."""
    with _running_jvm(
        java_fixture_build,
        "dialog",
        _fixture_command(java_fixture_build, "dialog"),
    ) as launched:
        process, stdout_log, stderr_log = launched
        try:
            hwnd = wait_for_raw_window(
                process,
                "JAB dialog repro",
                stdout_log,
                stderr_log,
            )
            yield DialogFixture(hwnd, process, stdout_log, stderr_log)
        finally:
            with contextlib.suppress(OSError):
                for hwnd in raw_windows(process.pid):
                    close_raw_window(hwnd)


@pytest.fixture
def dialog_first_fixture(
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[DialogFixture]:
    """Start the standalone dialog-first diagnostic in a fresh JVM."""
    command = _fixture_command(java_fixture_build, "dialog")
    command.insert(1, "-Ddialog.first=true")
    with _running_jvm(
        java_fixture_build,
        "dialog-first",
        command,
    ) as launched:
        process, stdout_log, stderr_log = launched
        try:
            hwnd = wait_for_raw_window(
                process,
                "Scenario First",
                stdout_log,
                stderr_log,
            )
            yield DialogFixture(hwnd, process, stdout_log, stderr_log)
        finally:
            with contextlib.suppress(OSError):
                for hwnd in raw_windows(process.pid):
                    close_raw_window(hwnd)


@pytest.fixture
def lifecycle_fixture(
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[DialogFixture]:
    """Start a fresh JVM that publishes shutdown state and exits once."""
    with _running_jvm(
        java_fixture_build,
        "lifecycle",
        _fixture_command(java_fixture_build, "lifecycle"),
    ) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = wait_for_raw_window(
            process,
            "JAB lifecycle fixture",
            stdout_log,
            stderr_log,
        )
        yield DialogFixture(hwnd, process, stdout_log, stderr_log)


@pytest.fixture(scope="session")
def swing_fixture_with_second_window(
    jab_dll_path: Path,
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[SwingFixture]:
    """Start the locator fixture with two Java top-level windows."""
    with _running_jvm(
        java_fixture_build,
        "swing-second-window",
        _fixture_command(java_fixture_build, "swing", "--second-window"),
    ) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = _wait_for_window(process, stdout_log, stderr_log)
        _wait_for_accessible_windows(
            process,
            jab_dll_path,
            _WINDOW_TITLE,
            _SECONDARY_WINDOW_TITLE,
        )
        yield SwingFixture(hwnd, process, stdout_log, stderr_log)


@pytest.fixture(scope="session")
def disabled_swing_fixture(
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[SwingFixture]:
    """Start the fixture without a JAB JVM flag for isolated-profile testing."""
    if os.environ.get("PLAY_JAB_ISOLATED_DISABLED_PROFILE") != "1":
        pytest.skip("requires an isolated Windows profile with JAB disabled")
    with _running_jvm(
        java_fixture_build,
        "swing-jab-disabled",
        _fixture_command(java_fixture_build, "swing", jab_enabled=False),
    ) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = _wait_for_window(process, stdout_log, stderr_log)
        yield SwingFixture(hwnd, process, stdout_log, stderr_log)


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
