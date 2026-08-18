# Getting Started

[Русская версия](getting-started.ru.md) · [Back to README](../README.md)

This guide prepares a Windows environment for `play-jab` and documents the
package surface available in the current pre-alpha release.

## 1. Check the prerequisites

Use 64-bit Python 3.11–3.14 and 64-bit JDK 17 with Java Access Bridge.
Confirm that both tools are available:

```powershell
python --version
java -version
$env:JAVA_HOME
```

Python and the external JAB DLL must both be 64-bit. Check Python with:

```powershell
python -c "import struct; print(struct.calcsize('P') * 8, 'bit')"
```

If `JAVA_HOME` is empty, set it to the JDK directory in your user or system
environment, then open a new terminal.

## 2. Enable Java Access Bridge

Enable JAB for the current Windows user:

```powershell
& "$env:JAVA_HOME\bin\jabswitch.exe" -enable
```

Restart any running Java applications afterward. Enabling JAB does not retrofit
accessibility support into an already running JVM.

`play-jab` does not bundle Microsoft's/Oracle's JAB DLL. It resolves
`WindowsAccessBridge-64.dll` from an explicit `dll_path`, then `JAVA_HOME`, then
Windows `System32`; it never searches the current working directory.

## 3. Install and verify play-jab

```powershell
python -m pip install play-jab
python -c "import play_jab; print(play_jab.__file__)"
```

The second command should print the installed package path without an import
error.

## 4. Attach and automate

Start the Java application yourself, then attach by exactly one HWND, PID, or
exact top-level title. `PlayJab` is attach-only and closing it never terminates
the target process.

If the HWND, PID, or exact title is not already known, discover it first:

```python
for info in jab.list_windows():
    print(info.hwnd, info.pid, info.title)
```

`list_windows()` enumerates every currently visible top-level Java window as
cheap `JavaWindowInfo(hwnd, pid, title)` records; it never opens a JAB context.

```python
from play_jab import PlayJab

with PlayJab(timeout=5_000) as jab:
    app = jab.attach(pid=12_345)
    window = app.window(title="Application")

    username = window.get_by_name("login.username")
    username.focus()
    username.fill("alice")
    window.get_by_name("login.remember").check()
    window.get_by_name("login.role").select_option("Admin")
    window.get_by_name("login.submit").click()

    jobs = window.get_by_name("jobs.table").as_table()
    print(jobs.snapshot())
    jobs.select_row(7)
    jobs.cell(7, 3).wait_for_text("Done", timeout=10_000)
```

Locators resolve again for every operation and use exact, case-sensitive string
matching. Form operations verify their observable postconditions. Explicit
password `text_content()` reads are allowed, but secret values are excluded from
snapshots, dumps, logs, and exceptions. Table indices are zero-based and invalid
indices raise `TableIndexError`.

Use `window.snapshot()` for root-window metadata without a descendant scan and
`locator.exists()` for an immediate, non-strict first-match check. `first()` and
`nth()` stop after the requested match. A locator with `showing_only=True`
matches showing nodes and prunes non-showing subtrees; `visible_only=True` only
filters matches and intentionally does not prune. `max_depth=` caps how far a
locator descends relative to its own starting point, so a deep, showing
sibling that sorts before a shallow target is never fully walked.

Do not import from `play_jab._native`: its names, signatures, and lifecycle
contracts may change without notice.

## Deadlines, virtualization, and scrolling

All reads and actions that resolve a locator accept a millisecond `timeout`.
The nearest value wins: call, then `JavaWindow`, then `PlayJab`; `timeout=0`
means one immediate observation. Reads are permitted for hidden and disabled
nodes, while actions validate the target and its ancestor chain. On timeout,
inspect the structured fields on `LocatorTimeoutError`; its bounded tree is
best-effort and password metadata is redacted.

For a virtualized list or tree, only materialized children can be found. Use
`locator.scroll(steps)` to send wheel input over an actionable viewport and
then resolve the item again. Positive steps scroll down, negative steps scroll
up, and zero is a no-op. Scrollbar `accessible_value()` returns immutable
`current`, `minimum`, and `maximum` strings; JDK 17 JAB has no supported setter.

## Troubleshooting

| Symptom or exception | What to check |
| --- | --- |
| `BridgeNotEnabledError` | Raised when `attach()`/`window()` times out and no Java window on the desktop ever answered the bridge. Run `jabswitch.exe -enable` as the same Windows user and restart the Java application. |
| `BridgeInitializationError` | Check `JAVA_HOME`, DLL availability, and Python/JAB bitness. |
| `JavaWindowNotFoundError` | At least one Java window exists, so the bridge itself works; confirm the HWND still exists and belongs to a Java window matching your selector. |
| `JavaWindowNotAccessibleError` | Confirm JAB was enabled before the target JVM started. |
| `JavaProcessExitedError` | The attached operating-system process ended. Start it again and attach a new session. |
| `JavaVmExitedError` | The attached JVM announced shutdown; old locators and references cannot be reused. |
| `JavaReferenceClosedError` | Reacquire the element after its native reference has been released. |
| `BridgeClosedError` | Create a new automation session; a closed runtime cannot be reused. |
| `NativeCallError` | Inspect its function name and scalar arguments for the failing JAB operation. |

`NativeCallError` deliberately excludes application text, which may contain
sensitive field values.

## Developing from source

```powershell
git clone https://gitlab.com/dashanovsd/play-jab.git
Set-Location play-jab
uv sync --all-groups
uv run pytest
```

Real JAB integration tests additionally require an interactive Windows desktop
and JDK 17. They run serially with:

```powershell
$env:PLAY_JAB_RUN_INTEGRATION = "1"
uv run pytest tests/integration
```

JVM stdout/stderr diagnostics are written under
`tests/java-fixtures/jab-swing-app/build/integration-logs/`. Contributor setup is
covered in [CONTRIBUTING.md](../CONTRIBUTING.md).

The GitHub real-JAB job requires a self-hosted runner labelled `windows`, `x64`,
`interactive`, and `jab`, protected by the `real-jab` environment. Set the
repository variable `PLAY_JAB_REAL_JAB=1` to enable it; configure
`PLAY_JAB_DLL` and, when needed, `PLAY_JAB_JAVA_EXE` as environment variables.
