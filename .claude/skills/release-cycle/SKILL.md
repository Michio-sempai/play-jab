---
name: release-cycle
description: Use when cutting a play-jab release, bumping the version, generating the changelog, tagging, or debugging a failed GitLab CI `release` job — or when the user asks about CalVer, `bumpver`, `cz changelog`, publishing to PyPI, or why a tag didn't release. Also relevant when reviewing whether a commit message follows Conventional Commits, since that convention feeds the generated changelog.
---

# play-jab release cycle

This describes the exact, CI-enforced release process for this repository. It
is a thin, actionable layer over `CONTRIBUTING.md`'s "Versioning" and
"Release" sections — read those first if this skill and that file ever
disagree, `CONTRIBUTING.md` wins.

## Versioning: CalVer, not SemVer

Format: **`YYYY.MM.PATCH[PYTAGNUM]`**, e.g. `2026.08.0`, `2026.08.1`,
`2026.08.1rc0`, `2026.09.0`.

- `YYYY.0M` — release year and zero-padded month (`08`, not `8`).
- `PATCH` — release counter within that month. Resets to `0` automatically
  the moment `YYYY.MM` changes. It does **not** auto-increment on every
  `bumpver update` within the same month — you must pass `--patch` explicitly,
  or the command errors with "no change".
- `PYTAGNUM` (optional) — a glued-on PEP 440 pre/post/dev tag: `a0`, `b1`,
  `rc2`, `post0`, `dev3`. Set with `--tag=alpha|beta|rc|dev|post|final`
  (`final` removes it) plus `--tag-num`. Absent for a normal final release.

Version bumps are **not** driven by commit type (`feat`/`fix`/...) the way
semver-style tools do it — commitizen here only lints commit messages and
generates the changelog; `bumpver` alone decides the version number, and it's
always a human decision, not automatic.

## Commit messages

Every commit must be a [Conventional Commit](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `docs:`, `chore:`, `test:`, ...). This is enforced by the
local `commitizen` pre-commit hook and, on merge requests, by the
`commitizen-check` CI job. Non-conforming commit messages block the MR — fix
the message, don't bypass the hook.

## Release procedure

Run from a clean `dev` branch with all lint/test checks already green. This is
the literal sequence from `CONTRIBUTING.md`; do not reorder or skip steps —
each one exists because the next depends on it.

```sh
OLD_VERSION=2026.08.1
NEW_VERSION=2026.08.2

uv run bumpver update --patch                                              # 1
uv run cz changelog --start-rev "v$OLD_VERSION" --unreleased-version "v$NEW_VERSION"  # 2
git add pyproject.toml CHANGELOG.md                                        # 3
git commit -m "chore: release $NEW_VERSION"                                # 4
git tag -a "v$NEW_VERSION" -m "v$NEW_VERSION"                              # 5
git push origin dev                                                        # 6
git push origin "v$NEW_VERSION"                                            # 7 — only after step 6's CI is green
```

1. `bumpver update --patch` edits **only** version fields in `pyproject.toml`
   (`[project].version` and `[tool.bumpver].current_version`). For the first
   release of a new calendar month, `PATCH` resets on its own, so a plain
   `uv run bumpver update` (no `--patch`) is enough — don't pass `--patch`
   with a stale `OLD_VERSION` assumption in that case.
2. `cz changelog` generates the `## v$NEW_VERSION (<date>)` section in
   `CHANGELOG.md` from Conventional Commits since `v$OLD_VERSION`. This must
   run **before** the tag exists, which is why it's a separate step from
   tagging.
3–4. Both files are committed together as a single `chore: release …` commit.
   Don't split them or fold this into an unrelated commit.
5. The tag is **annotated** (`-a` + `-m`), not lightweight. It is created
   *after* the changelog commit exists, so the tag always points at a commit
   whose `CHANGELOG.md` already documents that version.
6. Push the branch **first** and wait for that pipeline to go green. The tag
   push is what triggers the `release` stage, so pushing it against red `dev`
   CI produces a release built from broken code.
7. Only then push the tag. This is the step that actually triggers publishing.

## What CI does with the tag

`.gitlab-ci.yml` stages: `lint → test → security → build → release`.

The `release` job only runs when the pushed tag matches
`^v[0-9]{4}\.(0[1-9]|1[0-2])\.[0-9]+((a|b|rc|post|dev)[0-9]+)?$` — i.e. a
well-formed `vYYYY.MM.PATCH[TAG]`. Before publishing, it hard-fails unless
**both** are true:

- `CI_COMMIT_TAG` equals `v<version>` read live from `pyproject.toml`
  (`[project].version`) — a tag that doesn't match the committed version is
  rejected.
- `CHANGELOG.md` contains a `## v<version> (` heading — a tag without release
  notes is rejected.

This is exactly why the procedure above is ordered the way it is: skip the
changelog step, or tag before bumping the version, and the `release` job will
fail this guard even though `build` succeeded.

Publishing itself uses PyPI's Trusted Publisher (OIDC) — `uv publish` with a
token minted from a GitLab CI ID token, no long-lived PyPI secret stored
anywhere. There is nothing to rotate or leak here; if publishing fails, look
at the OIDC/Trusted-Publisher configuration on pypi.org, not at CI secrets.

## Troubleshooting a failed release

| Symptom | Likely cause |
| --- | --- |
| `release` job fails on the version/tag equality check | The tag doesn't match `pyproject.toml`'s version — you likely tagged before or without `bumpver update`, or typo'd the tag. |
| `release` job fails on the `CHANGELOG.md` grep | `cz changelog` wasn't run, or its output wasn't committed before tagging. |
| `bumpver update --patch` errors "no change" | You're still in the same `YYYY.MM` and already at the intended patch, or you forgot `--patch` is required mid-month. |
| Tag pushed but no `release` pipeline ran | The tag doesn't match the CI regex (e.g. missing zero-padding on month, malformed pre-release suffix) — GitLab CI's `rules:if` silently skips the job for a non-matching ref. |
| MR blocked by `commitizen-check` | A commit in the MR range isn't a Conventional Commit; reword it (rebase/reword), don't bypass the hook. |

## Do not

- Do not hand-write `CHANGELOG.md` entries for a release — they come from
  `cz changelog` against Conventional Commit history, so a hand-written entry
  will drift from what the next `cz changelog` run expects.
- Do not create the `v<version>` tag before the release commit exists.
- Do not push the tag before the branch pipeline is green — the tag push is
  irreversible once PyPI accepts the upload (PyPI does not allow re-uploading
  a version).
- Do not bump `PATCH` "just in case" — it only moves when explicitly asked
  (`--patch`), matching one real release.
