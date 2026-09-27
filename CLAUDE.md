# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Respond to the user in Russian** (also configured at the system level for this project).

## What this is

`play-jab` is a typed Python library (pre-alpha) that automates Java desktop
applications on Windows through the native Java Access Bridge (JAB), with a
Playwright-style locator API. It is Windows-only, has zero runtime
dependencies, and never launches or stops the target Java process — it only
attaches to an already-running one.

## Commands

```powershell
uv sync --all-groups                          # install all dev dependency groups
uv run pytest                                  # unit tests, terminal coverage (integration tests skipped)
uv run pytest tests/test_bridge_lifecycle.py   # single test file
uv run pytest tests/test_bridge_lifecycle.py::test_name -k pattern  # single test
uv run ruff check . && uv run ruff format --check .   # lint + format check
uv run flake8 src --select=WPS                 # wemake-python-styleguide smells (src/ only)
uv run mypy src                                # strict type checking (platform=win32)
uv run pre-commit run --all-files              # all local quality gates at once
uv build                                       # sdist + wheel into dist/
```

Integration tests require a real Windows desktop session, JDK 17, and JAB, and
are skipped by default (`--ignore=tests/integration` in CI). To run them
locally:

```powershell
$env:PLAY_JAB_RUN_INTEGRATION = '1'
uv run pytest tests/integration
```

`PLAY_JAB_JAVA_EXE` / `PLAY_JAB_DLL` override automatic JDK/DLL discovery when
needed. `PLAY_JAB_DEMO_APP_JAR` overrides the Swing fixture JAR discovery.
Integration fixtures launch that JAR directly (`java -jar`); play-jab never
compiles it. The JAR is built and committed in the separate
[`play-jab-demo-app`](https://gitlab.com/dashanovsd/play-jab-demo-app) repo,
found by default as a sibling checkout at
`../play-jab-demo-app/dist/jab-swing-app.jar` (see
`tests/integration/conftest.py`).

CI (`.gitlab-ci.yml`) runs `ruff`, `flake8-wps`, and `mypy` as separate lint
jobs, then `test` across Python 3.11–3.14 (unit tests only), then `build`, then
`release` (tag-triggered PyPI publish via Trusted Publishing).

## Architecture

### Layering

The codebase is a strict bottom-up stack; each layer only talks to the one
below it and never leaks its own abstractions upward:

1. **`src/play_jab/_native/types.py`** — handwritten `ctypes` ABI mirror of the
   Access Bridge C structs/typedefs (`AccessibleContextInfo`,
   `AccessibleTableInfo`, etc.), plus the `JOBJECT64`-as-`jlong` width
   footguns documented inline. Pure data, no behavior.
2. **`src/play_jab/_native/functions.py`** / **`dll.py`** — `argtypes`/`restype`
   wiring for the DLL exports actually used, and DLL discovery/loading
   (explicit `dll_path` → `JAVA_HOME` → `System32`, never the cwd) plus
   `jabswitch`-enablement detection.
3. **`src/play_jab/_native/backend.py`** — `NativeBackend` Protocol: the entire
   native surface the rest of the library depends on (the vertical slice of
   Access Bridge calls, message-queue draining, readiness probing).
   `DllBackend` is the real implementation; backends mirror native failure
   signaling (`FALSE`/null/`0`) as `None`/`False`/`0` and never raise
   `play_jab` exceptions themselves — that translation is the runtime's job.
   Backends are **not thread-safe**; every call must come from the thread that
   created the backend.
4. **`src/play_jab/_native/fake.py`** — `FakeBackend`: an in-memory
   implementation of the same `NativeBackend` Protocol over a plain node tree,
   used to test everything above it without a JVM/JAB/platform dependency. It
   deliberately distinguishes *stale contexts* (normal — Swing tree rebuilds
   invalidate handles; reads return `FALSE`/null, no exception) from *misuse*
   (double-release, unknown cookie — raises `FakeBackendError`, an
   `AssertionError` subclass, never `PlayJabError`, so tests can't mistake a
   fake-only tripwire for a real native failure).
5. **`src/play_jab/_native/bridge.py`** — `BridgeRuntime`: owns exactly **one
   thread, one Win32 message pump, one loaded DLL** per runtime. All native
   calls are marshaled onto that worker thread via a command queue; this is
   what makes the otherwise not-thread-safe backend safe to call from
   arbitrary caller threads. Turns raw backend failures into the public
   exception hierarchy. `traverse()` and `read_path()` are the batched
   primitives: a whole subtree walk or a whole path read happens in a single
   queued step instead of three per node, and neither mints a `JavaRef` --
   cookies live and die inside that one step.
6. **`src/play_jab/_native/refs.py`** — `JavaRef`: owns exactly one Access
   Bridge reference (an `AccessibleContext` is a live JVM reference the JVM
   cannot collect until `releaseJavaObject` is called, not a plain ID).
   Deterministic release via `close()`/context manager; a `weakref.finalize`
   is a safety net only, never load-bearing.
7. **`src/play_jab/_native/manager.py`** — `RuntimeManager`/`RuntimeSession`:
   process-wide leasing so multiple `PlayJab` instances in one process can
   share (or correctly reject mismatched) a single `BridgeRuntime`.
8. **`src/play_jab/sync_api.py`** — the public synchronous API surface:
   `PlayJab`, `JavaApplication`, `JavaWindow`, `Locator`, `TableLocator`,
   `TableCellLocator`, `WindowExpectation`, snapshot dataclasses
   (`ElementSnapshot`, `AccessibilityNode`, `TableSnapshot`,
   `AccessibleValueSnapshot`), and `JavaWindowInfo` (the cheap
   hwnd/pid/title record `PlayJab.list_windows()` returns for window
   discovery, without opening a JAB context). This is also where the opt-in synthetic-input
   path lives (Win32 mouse/cursor/DPI handling, serialized by
   `_SYNTHETIC_INPUT_LOCK`), used for controls that open native modal dialogs
   JAB's `AccessibleAction` can't safely drive.
9. **`src/play_jab/registry.py`** — `AccessibilityRegistry`: validates roles
   and states against JDK 17's `AccessibleRole`/`AccessibleState` string sets,
   with opt-in extension for application-specific values.
10. **`src/play_jab/exceptions.py`** — the complete public exception
    hierarchy. Notably `JavaReferenceClosedError` is a **sibling**, not a
    subclass, of `BridgeClosedError` — that's deliberate so a broad `except
    BridgeClosedError` can't swallow a recoverable stale reference and an
    `except BridgeClosedError: retry` can't spin against a dead runtime; read
    the class docstrings before changing this hierarchy.

`play_jab/__init__.py` re-exports the public surface only; `play_jab._native`
is a private implementation detail and must never be imported by application
code (also enforced by docs/README).

### Locator model

Locators (`Locator`, `TableLocator`, `TableCellLocator` in `sync_api.py`) are
lazy: they resolve fresh JAB contexts on every operation rather than caching a
tree. What is remembered is a *path*, not a context: an operation that acts on
a single node stores the child-index path it resolved to (on `PlayJab`, keyed
by hwnd plus locator chain), and the next such operation re-reads only that
path via `BridgeRuntime.read_path`, falling back to a full scan the moment any
step of the chain stops matching. The cache is a thread-safe 1,024-entry LRU;
warm reads intentionally do not scan for newly added duplicates.
`PlayJab(path_cache=False)` disables it;
`clear_path_cache()` empties it. Key contracts to preserve when touching this
code:

- `exists()` is an immediate, non-strict first-match check; `wait_for()` is the
  polling variant.
- **Reads** (snapshot, text content, attributes, table cells) work on hidden or
  disabled nodes. **Actions** (click, fill, etc.) require the target *and every
  ancestor* to be visible, showing, and enabled.
- `showing_only=True` matches showing nodes and prunes non-showing subtrees,
  including the subtree of a `collapsed` node (its descendants are never
  rendered, and reading them one by one is what made an unrelated search pay
  for a thousand-row tree); `visible_only=True` filters without pruning.
  `max_depth=` caps descent relative to the locator's own starting point (not
  the tree root).
- A whole scan runs inside **one** worker-thread step via
  `BridgeRuntime.traverse`, which calls a visitor per node and takes a
  `Verdict` (descend / skip subtree / stop) back. The visitor runs on the
  worker thread and must not call back into the runtime; node and depth
  budgets belong to the visitor, not to `traverse`.
- Virtualized lists/trees expose only currently materialized children;
  play-jab never auto-scrolls to search — callers must move the viewport and
  re-resolve.
- `LocatorTimeoutError` carries structured, bounded, password-redacted
  diagnostics (`locator`, `expected`, `last_state`, `tree`, `hwnd`, `pid`,
  `generation`); extend this dataclass-like payload rather than stringifying
  more into the message.
- Password-role (`"password text"`) values are redacted from dumps, snapshots,
  logs, and errors; only explicit reads may return them.

### Testing conventions

- Unit tests (`tests/test_*.py`) run against `FakeBackend`/`FakeWindowBackend`
  and never touch a real JVM or Win32 desktop; see `tests/conftest.py` for the
  shared `FakeWindowBackend` double and `install_fake_runtime()` helper that
  most test files use to wire a fake `BridgeRuntime` into `sync_api`.
- An autouse fixture in `tests/conftest.py` fails any test that leaks
  `sync_api._RUNTIME_MANAGER` in a non-`"stopped"` state — a sign the test
  forgot to release/close its `PlayJab` instance. If you hit this failure in
  an unrelated test, look for a missing `close()`/context-manager in a test
  that ran earlier in the same file.
- Integration tests (`tests/integration/`, marker `integration_jab`) launch the
  real Swing fixture app (a pre-built JAR from `play-jab-demo-app`) and
  exercise the actual DLL; they're opt-in (`PLAY_JAB_RUN_INTEGRATION=1`) and
  Windows/JDK-17-only.
- Name test functions `test_<behavior>`, and cover normal, error, and cleanup
  paths — not just the happy path. Coverage is measured on `src/play_jab`;
  don't let it drop on the code you touched.

## Style notes beyond the linters

- 4-space indents in Python, 2-space in YAML/TOML/JSON/CFG, 88-char lines,
  double quotes, LF endings — enforced by `ruff format`/`.editorconfig`, not
  manual.
- `snake_case` for modules/functions/variables, `PascalCase` for classes,
  `UPPER_SNAKE_CASE` for constants — except where preserving upstream
  Java/Win32 ABI names is required for interoperability (see `types.py`).
- mypy runs in `strict` mode targeting `platform = "win32"`; add precise
  annotations rather than `# type: ignore`.
- `setup.cfg` scopes `flake8` to WPS-only checks (ruff already covers
  E/F/W/isort); several WPS rules are deliberately disabled project-wide for
  ABI names, ctypes metadata, and explicit `__all__` exports — see the
  `extend-ignore` comment there before re-enabling one.
- Commits follow Conventional Commits (enforced by commitizen), each kept
  focused; versioning is CalVer (`YYYY.MM.PATCH[PYTAGNUM]`), not
  semver-from-commit-type — see `CONTRIBUTING.md` for the full release
  procedure before bumping a version or touching `CHANGELOG.md`.

## Pull requests

Explain the behavioral change, link relevant issues, and list the commands
run to verify it. Call out any Windows, JDK, DLL-bitness, or accessibility
setup a reviewer needs to reproduce the verification. Include logs or
screenshots when a GUI-facing failure or fix is hard to demonstrate in tests.

## Agent skills

### Issue tracker

Задачи хранятся markdown-файлами в `.scratch/`. См.
`docs/agents/issue-tracker.md`.

### Triage labels

Пять стандартных ролей triage (`needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`), названия меток не менялись.
См. `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` в корне репозитория. См.
`docs/agents/domain.md`.
