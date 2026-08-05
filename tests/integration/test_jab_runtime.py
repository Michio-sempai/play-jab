"""End-to-end checks against the JDK 17 Swing fixture and the real JAB DLL."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from play_jab._native.backend import NativeBackend
from play_jab._native.bridge import BridgeRuntime
from play_jab._native.dll import jab_enabled_for_current_user
from play_jab.exceptions import BridgeClosedError, BridgeNotEnabledError

from .conftest import SwingFixture

pytestmark = pytest.mark.integration_jab

_RACE_ITERATIONS = 5
_THREAD_TIMEOUT = 15.0


def _race_start_and_close(
    hwnd: int,
    backend_factory: Callable[[], NativeBackend],
) -> None:
    bridge = BridgeRuntime(backend_factory)
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def start() -> None:
        barrier.wait()
        try:
            bridge.start(probe_hwnd=hwnd)
        except BridgeClosedError:
            pass
        except BaseException as exc:
            failures.append(exc)

    def close() -> None:
        barrier.wait()
        try:
            bridge.close()
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=start), threading.Thread(target=close)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=_THREAD_TIMEOUT)

    bridge.close()
    assert all(not thread.is_alive() for thread in threads)
    assert failures == []


def test_real_fixture_traversal(
    swing_fixture: SwingFixture,
    backend_factory: Callable[[], NativeBackend],
) -> None:
    """Read and traverse the fixture tree, then release every native reference."""
    bridge = BridgeRuntime(backend_factory)
    bridge.start(probe_hwnd=swing_fixture.hwnd)
    try:
        with bridge.context_from_hwnd(swing_fixture.hwnd) as root:
            info = bridge.context_info(root)
            assert info.name == "fixture.main"
            assert info.role_en_us == "frame"
            assert info.children_count > 0
            assert bridge.hwnd_from_context(root) == swing_fixture.hwnd

            child = bridge.child(root, 0)
            assert child is not None
            with child:
                parent = bridge.parent(child)
                assert parent is not None
                with parent:
                    assert bridge.context_info(parent).name == "fixture.main"
        assert bridge.live_ref_count == 0
    finally:
        bridge.close()


def test_foreign_references_never_reach_another_native_runtime(
    swing_fixture: SwingFixture,
    backend_factory: Callable[[], NativeBackend],
) -> None:
    """A cookie is meaningful only to the runtime that acquired it."""
    owner = BridgeRuntime(backend_factory)
    other = BridgeRuntime(backend_factory)
    owner.start(probe_hwnd=swing_fixture.hwnd)
    other.start(probe_hwnd=swing_fixture.hwnd)
    try:
        with owner.context_from_hwnd(swing_fixture.hwnd) as root:
            foreign_calls = (
                lambda: other.context_info(root),
                lambda: other.child(root, 0),
                lambda: other.parent(root),
                lambda: other.hwnd_from_context(root),
            )
            for call in foreign_calls:
                with pytest.raises(ValueError, match="another bridge runtime"):
                    call()

            assert not root.closed
            assert owner.context_info(root).name == "fixture.main"
    finally:
        other.close()
        owner.close()


def test_concurrent_start_and_close_do_not_raise_or_leak_threads(
    swing_fixture: SwingFixture,
    backend_factory: Callable[[], NativeBackend],
) -> None:
    """Exercise the lifecycle boundary against the real DLL repeatedly."""
    for _ in range(_RACE_ITERATIONS):
        _race_start_and_close(swing_fixture.hwnd, backend_factory)


@pytest.mark.skipif(
    os.environ.get("PLAY_JAB_ISOLATED_DISABLED_PROFILE") != "1",
    reason="requires an isolated Windows profile with JAB disabled",
)
def test_disabled_jab_is_reported_during_startup(
    disabled_swing_fixture: SwingFixture,
    backend_factory: Callable[[], NativeBackend],
) -> None:
    """Run only when the operator guarantees an isolated, disabled profile."""
    if jab_enabled_for_current_user():
        pytest.fail("the current profile has JAB enabled; isolation is not valid")
    bridge = BridgeRuntime(backend_factory, ready_timeout=0.25)
    with pytest.raises(BridgeNotEnabledError):
        bridge.start(probe_hwnd=disabled_swing_fixture.hwnd)
    bridge.close()


def test_failed_backend_construction_unloads_the_real_dll(
    jab_dll_path: Path,
) -> None:
    """Verify loader ownership in a process where no earlier load can hide it."""
    script = """
import ctypes
import sys

from play_jab._native import backend

path = sys.argv[1]
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p

if kernel32.GetModuleHandleW(path):
    raise SystemExit("DLL was already loaded in the isolated process")

expected = RuntimeError("forced verification failure")

def fail_verification(*_args):
    raise expected

backend.verify_exports = fail_verification
try:
    backend.DllBackend.load(path)
except RuntimeError as exc:
    if exc is not expected:
        raise
else:
    raise SystemExit("backend construction unexpectedly succeeded")

if kernel32.GetModuleHandleW(path):
    raise SystemExit("DLL remained loaded after construction rollback")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(jab_dll_path)],
        capture_output=True,
        check=False,
        text=True,
        timeout=_THREAD_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
