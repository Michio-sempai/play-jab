# Contributing

## Environment

The project uses [uv](https://docs.astral.sh/uv/) to manage the environment and build.

```sh
uv sync --all-groups
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type commit-msg
```

## Checks

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run flake8 src --select=WPS
uv run mypy src
```

The same checks run in CI (`.gitlab-ci.yml`, `lint`/`test` stages). Pre-commit runs
the lint checks locally; run `uv run pytest` separately for the test suite.

## Commits

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `docs:`, ...) - enforced by the `commitizen` hook and in CI (on merge requests).

## Versioning

Calendar versioning (CalVer): **`YYYY.MM.PATCH[PYTAGNUM]`**, e.g. `2026.08.0`,
`2026.08.1`, `2026.08.1rc0`, `2026.09.0`. Not tied to commit types - it reflects the
release month plus a release counter within that month:

- **`YYYY.MM`** - year and month of the release (`0M` is zero-padded, `08` not `8`).
- **`PATCH`** - the release number within the month. Automatically resets to `0` whenever
  `YYYY.MM` changes; within the same month it does not auto-increment - you have to ask
  for it explicitly with `--patch` (otherwise `bumpver update` errors out with "no change").
- **`PYTAGNUM`** (optional, in brackets) - a PEP 440 pre/post/dev release tag glued to its
  number with no separator: `a0`, `b1`, `rc2`, `post0`, `dev3` (`a`/`b` are the PEP 440
  short forms of alpha/beta). Set via `--tag=alpha|beta|rc|dev|post|final` (`final` drops
  the tag) and `--tag-num` to bump the number. Absent entirely for a regular final release.

## Release

```sh
OLD_VERSION=2026.08.1
NEW_VERSION=2026.08.2
uv run bumpver update --patch
uv run cz changelog --start-rev "v$OLD_VERSION" --unreleased-version "v$NEW_VERSION"
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release $NEW_VERSION"
git tag -a "v$NEW_VERSION" -m "v$NEW_VERSION"
git push origin dev
git push origin "v$NEW_VERSION"  # triggers release only after the branch CI is green
```

`bumpver` only edits version fields. The changelog, release commit, and annotated
`v<version>` tag are explicit steps so the tag cannot be created before release
notes are generated. The CI `release` job rejects a tag whose version is absent
from `CHANGELOG.md`.

For the first release of a new month, `PATCH` resets on its own, so a plain
`uv run bumpver update` is enough.

Publishing to PyPI happens in the CI `release` stage (Trusted Publisher / OIDC, no secrets
stored in CI variables) and only runs on a pushed tag matching `vYYYY.MM.PATCH[...]`.
