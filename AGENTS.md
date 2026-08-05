# Repository Guidelines

Ты должен всегда отвечать на русском

## Project Structure & Module Organization

Production code uses a `src` layout under `src/play_jab/`. Native Java Access
Bridge bindings and lifecycle code live in `src/play_jab/_native/`; public
exceptions and exports live at the package root. Unit tests are in `tests/` and
follow the implementation by concern (for example, `test_bridge_lifecycle.py`).
Opt-in end-to-end tests live in `tests/integration/`, while the checked-in Swing
application they exercise is in `tests/java-fixtures/jab-swing-app/`.

## Build, Test, and Development Commands

- `uv sync --all-groups` installs Python 3.11+ development dependencies.
- `uv run pytest` runs all collected tests with terminal coverage; integration
  tests remain skipped unless explicitly enabled.
- `uv run ruff check . && uv run ruff format --check .` checks Python lint and
  formatting rules.
- `uv run flake8 src --select=WPS` checks additional implementation-level smells.
- `uv run mypy src` performs strict static type checking for Windows.
- `uv run pre-commit run --all-files` runs the configured local quality gates.
- `uv build` creates source and wheel distributions in `dist/`.

On Windows with JDK 17 and Java Access Bridge available, run integration tests
with `$env:PLAY_JAB_RUN_INTEGRATION='1'; uv run pytest tests/integration`.
Set `PLAY_JAB_JAVA_EXE` or `PLAY_JAB_DLL` when automatic discovery is unsuitable.

## Coding Style & Naming Conventions

Use four spaces in Python and two in YAML, TOML, JSON, and CFG files. Keep lines
within 88 characters, use double quotes, and preserve LF endings. Ruff sorts
imports and formats code. Name modules, functions, and variables in `snake_case`,
classes in `PascalCase`, and constants in `UPPER_SNAKE_CASE`. Add precise type
annotations: mypy runs in strict mode. Preserve upstream Java/Win32 ABI names
where interoperability requires them.

## Testing Guidelines

Pytest discovers `tests/test_*.py`; name test functions `test_<behavior>`. Add
focused unit tests for normal, error, and cleanup paths. Use fake backends for
portable tests and mark real JAB cases with `integration_jab`. Coverage is
reported for `src/play_jab`; avoid reducing coverage for changed code.

## Commit & Pull Request Guidelines

Use Conventional Commits, matching history such as `feat: add ...`, `fix: ...`,
and `test: ...`. Keep each commit focused. Pull requests should explain the
behavioral change, link relevant issues, list commands run, and call out Windows,
JDK, DLL-bitness, or accessibility setup needed for verification. Include logs or
screenshots when a GUI-facing failure or fix is difficult to demonstrate in tests.
