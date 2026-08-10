"""Fixtures for the opt-in Java Access Bridge integration suite.

Set ``PLAY_JAB_RUN_INTEGRATION=1`` on an interactive Windows runner with JDK 17.
The suite compiles the checked-in Swing fixture, resolves ``java`` from ``PATH``
then ``JAVA_HOME``, and resolves a bitness-compatible DLL from ``JAVA_HOME``/
``System32``. ``PLAY_JAB_JAVA_EXE`` and ``PLAY_JAB_DLL`` override those two
discoveries respectively. The disabled-JAB scenario additionally requires an
isolated user profile and ``PLAY_JAB_ISOLATED_DISABLED_PROFILE=1``.
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import threading
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
_TEARDOWN_WATCHDOG_SECONDS = 30.0


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


def _discover_java_executable() -> str | None:
    """Find a `java` executable: explicit override, then PATH, then JAVA_HOME.

    A machine with JDK 17 correctly installed and `JAVA_HOME` set, but no `java`
    on `PATH`, is a normal, supported configuration - the Gradle wrapper already
    resolves Java that way. Stopping at `shutil.which` alone made the whole suite
    fail on exactly such a machine (integration-tests-review.md finding K-1).
    """
    explicit = os.environ.get("PLAY_JAB_JAVA_EXE")
    if explicit:
        return explicit
    on_path = shutil.which("java")
    if on_path:
        return on_path
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / "java.exe"
        if candidate.is_file():
            return str(candidate)
    return None


_ENUM_WINDOWS_CALLBACK = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
)


@functools.lru_cache(maxsize=1)
def _user32() -> ctypes.WinDLL:
    """Bind and configure user32 exactly once.

    `raw_windows()` polls every 50 ms while a test waits for a window; rebuilding
    the WinDLL handle and re-assigning every argtypes/restype on each call added
    real overhead to that hot loop for no benefit
    (integration-tests-review.md finding H-2).
    """
    dll = ctypes.WinDLL("user32", use_last_error=True)
    dll.EnumWindows.argtypes = [_ENUM_WINDOWS_CALLBACK, ctypes.c_void_p]
    dll.EnumWindows.restype = ctypes.c_bool
    dll.GetWindowThreadProcessId.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    dll.GetWindowThreadProcessId.restype = ctypes.c_ulong
    dll.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    dll.GetWindowTextLengthW.restype = ctypes.c_int
    dll.GetWindowTextW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    dll.GetWindowTextW.restype = ctypes.c_int
    dll.PostMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    dll.PostMessageW.restype = ctypes.c_bool
    dll.IsWindowVisible.argtypes = [ctypes.c_void_p]
    dll.IsWindowVisible.restype = ctypes.c_bool
    dll.BringWindowToTop.argtypes = [ctypes.c_void_p]
    dll.BringWindowToTop.restype = ctypes.c_bool
    dll.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    dll.SetForegroundWindow.restype = ctypes.c_bool
    dll.GetForegroundWindow.argtypes = []
    dll.GetForegroundWindow.restype = ctypes.c_void_p
    return dll


_FOREGROUND_PROBE_ATTEMPTS = 3


def can_change_foreground_window(hwnd: int) -> bool:
    """Probe whether this session can make ``hwnd`` the Windows foreground window.

    Mirrors the exact call sequence `_Win32WindowBackend.set_foreground_window`
    uses (``BringWindowToTop`` + ``SetForegroundWindow``, verified through
    ``GetForegroundWindow``), on the harness's own independent user32 binding.
    A locked, non-interactive, or RDP-backgrounded desktop session can make
    Windows' foreground-lock rules refuse this unconditionally - without this
    probe that environment limitation is indistinguishable from a real
    regression in the library's retry loop, which is exactly what
    `opens_window=True` tests observed failing
    (integration-tests-review.md finding K-2).
    """
    user32 = _user32()
    for _ in range(_FOREGROUND_PROBE_ATTEMPTS):
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if int(user32.GetForegroundWindow() or 0) == hwnd:
            return True
        time.sleep(0.01)
    return False


def _window_for_process(process_id: int) -> int | None:
    """Resolve the fixture's one main window, failing loudly on ambiguity.

    Previously took `matches[0]` silently while `wait_for_raw_window` failed on
    the same condition - one law for two functions checking the same thing
    (integration-tests-review.md finding H-1).
    """
    matches = raw_windows(process_id, title=_WINDOW_TITLE)
    if len(matches) > 1:
        pytest.fail(f"multiple raw windows titled {_WINDOW_TITLE!r}: {matches!r}")
    return matches[0] if matches else None


def raw_windows(process_id: int, *, title: str | None = None) -> list[int]:
    """Enumerate raw top-level HWNDs by PID and optional exact title."""
    user32 = _user32()
    matches: list[int] = []

    @_ENUM_WINDOWS_CALLBACK  # type: ignore[untyped-decorator]
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
    if not _user32().PostMessageW(hwnd, 0x0010, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def is_window_visible(hwnd: int) -> bool:
    return bool(_user32().IsWindowVisible(hwnd))


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=_PROCESS_TIMEOUT)


@contextlib.contextmanager
def _bounded_playjab(*, timeout: int, dll_path: Path) -> Iterator[PlayJab]:
    """Same as ``with PlayJab(...) as api:``, but ``close()`` cannot hang the
    whole session silently.

    ``BridgeRuntime._submit()``/``close()`` (src/play_jab/_native/bridge.py)
    are deliberately unbounded - an in-flight native call cannot be safely
    cancelled. If a modal-dialog interaction anywhere in this session leaves
    that process-wide shared worker wedged, the next fixture to close a
    ``PlayJab`` here would otherwise block forever with no diagnostic output
    (see .todo/play-jab-bugs/integration-modal-suite-hang.md). This watchdog
    does not change that production behaviour; it only turns a silent hang
    into a loud, diagnosable test failure, on a thread separate from the one
    actually blocked in the native call.
    """
    api = PlayJab(timeout=timeout, dll_path=dll_path)
    api.__enter__()
    try:
        yield api
    finally:
        finished = threading.Event()

        def _close() -> None:
            try:
                api.close()
            finally:
                finished.set()

        threading.Thread(target=_close, daemon=True).start()
        if not finished.wait(_TEARDOWN_WATCHDOG_SECONDS):
            pytest.fail(
                "PlayJab.close() did not return within "
                f"{_TEARDOWN_WATCHDOG_SECONDS:.0f}s - the shared JAB worker "
                "is likely wedged by a blocked native call from an earlier "
                "modal-dialog interaction, see "
                "integration-modal-suite-hang.md"
            )


def _wait_for_accessible_windows(
    process: subprocess.Popen[str],
    dll_path: Path,
    *titles: str,
) -> None:
    """Wait until every expected top-level window is visible through JAB."""
    with _bounded_playjab(
        timeout=int(_WINDOW_TIMEOUT * 1_000), dll_path=dll_path
    ) as api:
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
    # Outside Gradle's own build/ tree: a JVM's log file handle staying open
    # past this session previously made `gradle clean` fail to delete build/
    # (test-app-review.md finding B10).
    log_directory = (
        Path(tempfile.gettempdir())
        / "play-jab-integration-logs"
        / f"{os.getpid()}-{time.time_ns()}"
    )
    log_directory.mkdir(parents=True, exist_ok=False)
    return JavaFixtureBuild(root, classes, log_directory)


_JAVA_EXECUTABLE: str | None = None


def _java_executable() -> str:
    """Return the java executable resolved once in `pytest_configure`."""
    if _JAVA_EXECUTABLE is None:  # pragma: no cover - guarded by pytest_configure
        pytest.fail("Java was not found; set PLAY_JAB_JAVA_EXE to a JDK 17 java.exe")
    return _JAVA_EXECUTABLE


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
def swing_fixture(
    jab_dll_path: Path,
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[SwingFixture]:
    """Start the session Swing fixture with JAB explicitly activated.

    Waits for the window to become accessible *through JAB*, not just visible
    at the Win32 level - `swing_fixture_with_second_window` already did this;
    without it, the first JAB-touching test on a freshly started fixture could
    race the bridge's own readiness (integration-tests-review.md finding B-7).
    """
    with _running_jvm(
        java_fixture_build,
        "swing",
        _fixture_command(java_fixture_build, "swing"),
    ) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = _wait_for_window(process, stdout_log, stderr_log)
        _wait_for_accessible_windows(process, jab_dll_path, _WINDOW_TITLE)
        yield SwingFixture(hwnd, process, stdout_log, stderr_log)


@pytest.fixture
def swing_fixture_dpi_125(
    jab_dll_path: Path,
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[SwingFixture]:
    """A fresh Swing fixture JVM scaled to 125% (`-Dsun.java2d.uiScale=1.25`).

    `Locator.click(opens_window=True)`/`scroll()` send synthetic Win32 input at
    physical coordinates taken from JAB's reported bounds, wrapped in
    `SetThreadDpiAwarenessContext(PER_MONITOR_AWARE_V2)` so Windows does not
    additionally rescale them - unit-tests-review.md finding A4 flagged this
    path as implemented but never exercised against a real, non-100%-scaled
    JVM. A dedicated fixture (rather than reusing the session-scoped
    `swing_fixture`) is required because the scale factor is fixed for a
    JVM's whole lifetime.
    """
    command = _fixture_command(java_fixture_build, "swing")
    command.insert(1, "-Dsun.java2d.uiScale=1.25")
    with _running_jvm(java_fixture_build, "swing-dpi125", command) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = _wait_for_window(process, stdout_log, stderr_log)
        _wait_for_accessible_windows(process, jab_dll_path, _WINDOW_TITLE)
        yield SwingFixture(hwnd, process, stdout_log, stderr_log)


@pytest.fixture
def swing_fixture_windows_laf(
    jab_dll_path: Path,
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[SwingFixture]:
    """A fresh Swing fixture JVM running the real Windows look and feel
    (`-Dfixture.lookAndFeel=windows`) instead of the cross-platform default -
    proves locator/accessible-name resolution does not depend on which L&F
    rendered the widgets (test-app-review.md finding B4).
    """
    command = _fixture_command(java_fixture_build, "swing")
    command.insert(1, "-Dfixture.lookAndFeel=windows")
    with _running_jvm(java_fixture_build, "swing-windows-laf", command) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = _wait_for_window(process, stdout_log, stderr_log)
        _wait_for_accessible_windows(process, jab_dll_path, _WINDOW_TITLE)
        yield SwingFixture(hwnd, process, stdout_log, stderr_log)


@pytest.fixture
def swing_fixture_no_auto_node(
    jab_dll_path: Path,
    java_fixture_build: JavaFixtureBuild,
) -> Iterator[SwingFixture]:
    """A fresh Swing fixture JVM with `fixture.auto_node`'s 3000ms
    attach/detach cycle disabled (`-Dfixture.autoNode=false`), for tests that
    need an exact, stable `live_ref_count` unaffected by the timer's own
    traffic (test-app-review.md finding C9).
    """
    command = _fixture_command(java_fixture_build, "swing")
    command.insert(1, "-Dfixture.autoNode=false")
    with _running_jvm(java_fixture_build, "swing-no-auto-node", command) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = _wait_for_window(process, stdout_log, stderr_log)
        _wait_for_accessible_windows(process, jab_dll_path, _WINDOW_TITLE)
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
                # Skip invisible/service AWT windows (e.g. the shared owner
                # frame): WM_CLOSE has no business reaching them.
                for hwnd in raw_windows(process.pid):
                    if is_window_visible(hwnd):
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
                # Skip invisible/service AWT windows (e.g. the shared owner
                # frame): WM_CLOSE has no business reaching them.
                for hwnd in raw_windows(process.pid):
                    if is_window_visible(hwnd):
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
    """Start the fixture without a JAB JVM flag for isolated-profile testing.

    The gate lives only on `test_disabled_jab_is_reported_during_startup`'s own
    `skipif`, which runs before this fixture and gives a skip reason without
    starting a JVM. A second, redundant gate here (integration-tests-review.md
    finding H-5) would only ever matter if that one were bypassed.
    """
    with _running_jvm(
        java_fixture_build,
        "swing-jab-disabled",
        _fixture_command(java_fixture_build, "swing", jab_enabled=False),
    ) as launched:
        process, stdout_log, stderr_log = launched
        hwnd = _wait_for_window(process, stdout_log, stderr_log)
        yield SwingFixture(hwnd, process, stdout_log, stderr_log)


_DEFAULT_INTEGRATION_TIMEOUT_SECONDS = 120


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip native integration tests unless opted in on a platform that can run them;
    otherwise give each one a watchdog timeout.

    Non-Windows is a `skip`, not `pytest_configure`'s `pytest.exit`: exiting would
    also abort the portable unit suite when both trees are collected together
    (`uv run pytest tests`), which is exactly the cross-platform guarantee
    AGENTS.md makes for that suite (integration-tests-review.md finding B-6).

    The timeout is the other half of that same finding (B-3): this suite's whole
    subject is JAB hangs, so a regression that makes a call block forever must
    fail the test, not the CI job.
    """
    reason: str | None = None
    if not _integration_requested():
        reason = f"set {_OPT_IN}=1 to run real Windows/JAB integration tests"
    elif sys.platform != "win32":
        reason = "Java Access Bridge integration tests require Windows"

    for item in items:
        if "integration_jab" not in item.keywords:
            continue
        if reason is not None:
            item.add_marker(pytest.mark.skip(reason=reason))
        elif "timeout" not in item.keywords:
            item.add_marker(pytest.mark.timeout(_DEFAULT_INTEGRATION_TIMEOUT_SECONDS))


def pytest_configure(config: pytest.Config) -> None:
    """Resolve the Java executable once, so a missing one fails with one message.

    `_java_executable()` used to look this up lazily on every fixture use, so a
    machine without `java` on PATH failed the same way 19 times over
    (integration-tests-review.md finding K-1).
    """
    if not _integration_requested() or sys.platform != "win32":
        return
    global _JAVA_EXECUTABLE  # noqa: PLW0603 -- resolved once, read-only after this
    _JAVA_EXECUTABLE = _discover_java_executable()
    if _JAVA_EXECUTABLE is None:
        pytest.exit(
            "Java was not found on PATH or via JAVA_HOME; "
            "set PLAY_JAB_JAVA_EXE to a JDK 17 java.exe"
        )
