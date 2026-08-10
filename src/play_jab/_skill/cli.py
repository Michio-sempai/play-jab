# flake8: noqa
"""Console entry point that installs the bundled play-jab Claude Code skill."""

from __future__ import annotations

import argparse
import shutil
import sys
from importlib import resources
from pathlib import Path

__all__ = ["main"]

_SKILL_NAME = "play-jab"
_SKILL_PACKAGE = "play_jab._skill.skill_files"


def _target_directory(*, use_user_scope: bool) -> Path:
    if use_user_scope:
        return Path.home() / ".claude" / "skills" / _SKILL_NAME
    return Path.cwd() / ".claude" / "skills" / _SKILL_NAME


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="play-jab-skill",
        description="Install the play-jab Claude Code skill.",
    )
    parser.add_argument(
        "--user",
        action="store_true",
        help=(
            "install into the personal skills directory (~/.claude/skills) "
            "instead of the current project's .claude/skills"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing installation",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Copy the bundled skill into a `.claude/skills/play-jab` directory."""
    args = _parse_args(argv)
    target = _target_directory(use_user_scope=bool(args.user))

    if target.exists():
        if not args.force:
            message = f"{target} already exists; pass --force to overwrite."
            print(message, file=sys.stderr)
            return 1
        shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    source = resources.files(_SKILL_PACKAGE).joinpath(_SKILL_NAME)
    with resources.as_file(source) as source_path:
        shutil.copytree(source_path, target)

    print(f"Installed the play-jab skill to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
