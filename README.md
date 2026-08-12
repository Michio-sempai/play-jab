<div align="center">

# play-jab

**Playwright-style automation for Java desktop applications through Java Access Bridge**

[Русская версия](README_RU.MD)

[![Project status](https://img.shields.io/badge/status-pre--alpha-orange)](#project-status)
[![Python](https://img.shields.io/badge/python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Pipeline](https://gitlab.com/dashanovsd/play-jab/badges/main/pipeline.svg)](https://gitlab.com/dashanovsd/play-jab/-/pipelines)
[![Coverage](https://gitlab.com/dashanovsd/play-jab/badges/main/coverage.svg)](https://gitlab.com/dashanovsd/play-jab/-/graphs/main/charts)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

</div>

`play-jab` is a typed Python library for inspecting and automating Java desktop
interfaces on Windows. It builds a safer, modern API on top of the native Java
Access Bridge (JAB), including dedicated message-pump ownership and explicit
native-reference lifecycle management.

## Project status

> [!IMPORTANT]
> **Pre-alpha MVP.** The synchronous attach-only automation API is available,
> but breaking changes are still possible. `PlayJab` never launches or stops the
> target Java process.

## Highlights

- Windows-native Java Access Bridge integration
- Python 3.11–3.14 support and strict type checking
- Explicit diagnostics for setup, window, reference, and native-call failures
- Automated ABI, lifecycle, ownership, and real JDK 17 integration tests
- Lazy strict locators, forms, selection, polling/event-assisted waits, and tables

## Requirements

- Windows
- 64-bit Python 3.11–3.14
- 64-bit JDK 17 with Java Access Bridge enabled before the target JVM starts
- An external `WindowsAccessBridge-64.dll` (the wheel does not bundle it)

## Quick start

Install the package:

```powershell
python -m pip install play-jab
```

Enable Java Access Bridge for the current Windows user, then restart the Java
application you want to inspect:

```powershell
& "$env:JAVA_HOME\bin\jabswitch.exe" -enable
```

Verify the public API:

```powershell
python -c "from play_jab import PlayJab; print(PlayJab.__name__)"
```

DLL discovery is deterministic: an explicit `dll_path`, then `JAVA_HOME`, then
Windows `System32`. The current working directory is never searched.

## Synchronous API

```python
from play_jab import PlayJab

with PlayJab(timeout=5_000, dll_path=r"C:\JAB\WindowsAccessBridge-64.dll") as jab:
    app = jab.attach(title="Application")
    window = app.window(title="Application")
    window.get_by_name("login.username").fill("alice")
    window.get_by_name("login.remember").check()
    window.get_by_name("login.role").select_option("Admin")
    window.get_by_name("login.submit").click()

    table = window.get_by_name("jobs.table").as_table()
    print(table.row_count(), table.column_count())
    table.cell(7, 3).wait_for_text("Done")
```

`attach(hwnd=...)`, `attach(pid=...)`, and `attach(title=...)` connect to an
existing process. Window titles and ordinary string locators use exact,
case-sensitive matching. Locators are lazy and acquire fresh JAB contexts for
every operation; snapshots and accessibility trees contain copied metadata and
do not own Java references. Closing any or all `PlayJab` sessions leaves every
attached process alive. There is intentionally no `PlayJab.launch()`.
`PlayJab.list_windows()` enumerates every currently visible top-level Java
window as cheap `JavaWindowInfo(hwnd, pid, title)` records — no JAB context is
opened.

`JavaWindow.snapshot()` reads only the window root. `Locator.exists()` is an
immediate, non-strict first-match check; use `wait_for()` when polling is
required. Positional `first()` and `nth()` locators stop traversal once their
requested match is found. Set `showing_only=True` to match showing nodes and
prune non-showing subtrees; `visible_only=True` keeps its non-pruning behavior.
Pass `max_depth=` to cap how far a locator descends relative to its own
starting point, so a shallow target behind a deep, showing sibling does not
force a full traversal of that sibling first.

`Locator.all()` returns lazy per-match locators, so reading `.snapshot()` on
each one re-resolves the whole locator, including a fresh tree traversal, once
per match. When you only need to read every match, call `all_snapshots()`
instead: it reuses the single traversal `count()` already performs.

Form locators support `focus()`, `fill()`, `clear()`, `check()`, `uncheck()`,
`select_option()`, `text_content()`, and state/attribute reads. Password text may
be read explicitly, but is redacted from dumps, snapshots, logs, and errors.
Table indices are zero-based; `as_table()` exposes dimensions, snapshots,
headers, row selection, cells, and cell text waits.

Reads (`snapshot`, `text_content`, attributes, table cells) also work for hidden
or disabled nodes. Actions require the target and every ancestor to be visible,
showing, and enabled. Every resolving operation accepts `timeout=`; `0` performs
one immediate check. `LocatorTimeoutError` carries structured, bounded and
password-redacted diagnostics.

Virtualized lists and trees expose only currently materialized children. Move
their viewport explicitly and resolve the lazy locator again; play-jab does not
auto-scroll while searching. Wheel input and read-only values are explicit:

```python
scrollbar = window.get_by_name("jobs.scrollbar")
print(scrollbar.accessible_value())
window.get_by_name("jobs.list").scroll(6)
```

Positive `scroll()` steps move down and negative steps move up. Cursor position
and DPI context are restored even when Win32 input fails.

`click()` uses the element's synchronous JAB `AccessibleAction`. When its
handler opens a modal `JDialog`, the call can remain blocked until that dialog
closes; no other operation can use the serialized bridge worker meanwhile.
Use the explicit physical-input path for controls that open windows:

```python
with app.expect_window(title="Confirmation") as pending:
    window.get_by_name("open.confirmation").click(opens_window=True)
dialog = pending.value
dialog.get_by_name("confirmation.ok").click()
```

The opt-in mouse path requires an interactive Windows desktop session. It does
not fall back automatically from JAB and restores the cursor position and the
calling thread's DPI-awareness context after the click.

See the **[Getting Started guide](docs/getting-started.md)** for environment
checks, JAB setup, currently available imports, and troubleshooting.

## Claude Code skill

Installing `play-jab` also installs a `play-jab-skill` console script that
copies a bundled [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills)
into your project so Claude picks up play-jab's API, constraints, and
exceptions automatically:

```powershell
python -m pip install play-jab
play-jab-skill            # writes .claude/skills/play-jab in the current project
play-jab-skill --user     # writes ~/.claude/skills/play-jab instead, for every project
play-jab-skill --force    # overwrite an existing installation
```

## Documentation

- [Getting Started](docs/getting-started.md)
- [Design](docs/design.md) ([Russian](docs/design.ru.md)) — module/interface/seam
  vocabulary applied to the actual stack, for contributors
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

Modules under `play_jab._native` remain implementation details and should not be
imported by application code.

## Development

```powershell
uv sync --all-groups
uv run pytest
uv run pre-commit run --all-files
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for all checks, commit conventions, and
the release process.

## License

Licensed under the [Apache License 2.0](LICENSE).
