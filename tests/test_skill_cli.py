"""Contract for the play-jab-skill installer console script."""

from __future__ import annotations

from pathlib import Path

import pytest

from play_jab._skill import cli


def test_default_scope_installs_into_project_claude_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main([])

    target = tmp_path / ".claude" / "skills" / "play-jab" / "SKILL.md"
    assert exit_code == 0
    assert target.is_file()
    assert "name: play-jab" in target.read_text(encoding="utf-8")


def test_user_scope_installs_into_home_claude_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    exit_code = cli.main(["--user"])

    target = tmp_path / ".claude" / "skills" / "play-jab" / "SKILL.md"
    assert exit_code == 0
    assert target.is_file()


def test_existing_installation_without_force_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    cli.main([])

    exit_code = cli.main([])

    assert exit_code == 1
    assert "already exists" in capsys.readouterr().err


def test_existing_installation_with_force_is_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    cli.main([])
    stray_file = tmp_path / ".claude" / "skills" / "play-jab" / "stray.txt"
    stray_file.write_text("stale", encoding="utf-8")

    exit_code = cli.main(["--force"])

    assert exit_code == 0
    assert not stray_file.exists()
    assert (tmp_path / ".claude" / "skills" / "play-jab" / "SKILL.md").is_file()
