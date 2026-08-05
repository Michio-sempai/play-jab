"""DLL discovery and export verification."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from play_jab._native.dll import (
    DLL_NAME_32,
    DLL_NAME_64,
    find_access_bridge_dll,
    jab_enabled_for_current_user,
    load_access_bridge,
    process_bitness,
    verify_exports,
)
from play_jab._native.functions import REQUIRED_EXPORTS
from play_jab.exceptions import BridgeInitializationError

BITNESS_64 = 64
BITNESS_32 = 32

ACCESSIBILITY_PROPERTIES = ".accessibility.properties"
ENABLED_LINE = "assistive_technologies=com.sun.java.accessibility.AccessBridge"


def dll_name_for_this_process() -> str:
    return DLL_NAME_64 if process_bitness() == BITNESS_64 else DLL_NAME_32


def write_properties(home: Path, text: str) -> None:
    (home / ACCESSIBILITY_PROPERTIES).write_text(text, encoding="utf-8")


def test_bitness_follows_the_process_not_the_os() -> None:
    expected = BITNESS_64 if sys.maxsize > 2**32 else BITNESS_32
    assert process_bitness() == expected


def test_explicit_path_is_used_verbatim(tmp_path: Path) -> None:
    stand_in = tmp_path / DLL_NAME_64
    stand_in.write_bytes(b"")
    assert find_access_bridge_dll(stand_in) == stand_in.resolve()


def test_missing_explicit_path_is_reported(tmp_path: Path) -> None:
    with pytest.raises(BridgeInitializationError, match="not found"):
        find_access_bridge_dll(tmp_path / DLL_NAME_32)


def test_current_directory_is_never_searched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / DLL_NAME_64
    decoy.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    with pytest.raises(BridgeInitializationError):
        find_access_bridge_dll()


def test_java_home_is_searched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    name = DLL_NAME_64 if process_bitness() == BITNESS_64 else DLL_NAME_32
    (binaries / name).write_bytes(b"")
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))
    assert find_access_bridge_dll() == (binaries / name).resolve()


def test_missing_exports_name_the_missing_symbol() -> None:
    incomplete = cast("ctypes.CDLL", SimpleNamespace(Windows_run=object()))
    with pytest.raises(BridgeInitializationError, match="isJavaWindow"):
        verify_exports(incomplete, REQUIRED_EXPORTS)


def test_a_complete_dll_passes_verification() -> None:
    complete = cast(
        "ctypes.CDLL",
        SimpleNamespace(**{name: object() for name in REQUIRED_EXPORTS}),
    )
    verify_exports(complete, REQUIRED_EXPORTS)


def test_every_missing_export_is_listed_not_just_the_first() -> None:
    empty = cast("ctypes.CDLL", SimpleNamespace())
    with pytest.raises(BridgeInitializationError) as raised:
        verify_exports(empty, REQUIRED_EXPORTS)
    for name in REQUIRED_EXPORTS:
        assert name in str(raised.value)


def test_system_root_is_searched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system32 = tmp_path / "System32"
    system32.mkdir()
    (system32 / dll_name_for_this_process()).write_bytes(b"")
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
    assert (
        find_access_bridge_dll() == (system32 / dll_name_for_this_process()).resolve()
    )


def test_a_java_home_without_the_dll_falls_through_to_system_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    java_home = tmp_path / "jdk"
    (java_home / "bin").mkdir(parents=True)
    system32 = tmp_path / "windows" / "System32"
    system32.mkdir(parents=True)
    (system32 / dll_name_for_this_process()).write_bytes(b"")
    monkeypatch.setenv("JAVA_HOME", str(java_home))
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "windows"))
    assert find_access_bridge_dll().parent == system32.resolve()


def test_the_failure_names_every_place_that_was_searched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "jdk"))
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "windows"))
    with pytest.raises(BridgeInitializationError) as raised:
        find_access_bridge_dll()
    message = str(raised.value)
    assert "jdk" in message
    assert "System32" in message
    assert "dll_path" in message


def test_a_directory_is_not_accepted_as_the_dll(tmp_path: Path) -> None:
    masquerading = tmp_path / DLL_NAME_64
    masquerading.mkdir()
    with pytest.raises(BridgeInitializationError, match="not found"):
        find_access_bridge_dll(masquerading)


def test_loading_off_windows_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bridge does not exist on other platforms; say that, do not crash."""
    monkeypatch.setattr("play_jab._native.dll.sys.platform", "linux")
    with pytest.raises(BridgeInitializationError, match="Windows-only"):
        load_access_bridge(tmp_path / DLL_NAME_64)


@pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows loader")
def test_a_file_that_is_not_a_dll_is_reported_as_a_load_failure(
    tmp_path: Path,
) -> None:
    impostor = tmp_path / dll_name_for_this_process()
    impostor.write_bytes(b"this is not a portable executable")
    with pytest.raises(BridgeInitializationError, match="failed to load"):
        load_access_bridge(impostor)


def test_jab_is_not_enabled_without_a_properties_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert jab_enabled_for_current_user() is False


def test_jab_is_enabled_when_the_properties_file_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_properties(tmp_path, f"# written by jabswitch\n  {ENABLED_LINE}  \n")
    assert jab_enabled_for_current_user() is True


@pytest.mark.parametrize(
    "properties",
    [
        pytest.param(f"#{ENABLED_LINE}\n", id="hash-comment"),
        pytest.param(f"!{ENABLED_LINE}\n", id="bang-comment"),
        pytest.param("assistive_technologies=org.example.Other\n", id="other-tech"),
        pytest.param("screen_magnifier_present=true\n", id="unrelated-key"),
        pytest.param("assistive_technologies\n", id="no-separator"),
        pytest.param("", id="empty"),
    ],
)
def test_jab_is_not_enabled_by_these_properties(
    properties: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    write_properties(tmp_path, properties)
    assert jab_enabled_for_current_user() is False


def test_an_unreadable_properties_file_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory in place of the file stands in for any OSError while reading."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ACCESSIBILITY_PROPERTIES).mkdir()
    assert jab_enabled_for_current_user() is False
