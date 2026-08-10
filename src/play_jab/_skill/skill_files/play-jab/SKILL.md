---
name: play-jab
description: Use when writing, reviewing, or debugging Python code that automates or tests a Java desktop (Swing/AWT) application on Windows through the play-jab library (`from play_jab import PlayJab`). Covers attaching to a running JVM, locators (`get_by_name`), forms, tables, waits/timeouts, `expect_window` for modals, scrolling virtualized lists, and diagnosing Java Access Bridge (JAB) exceptions such as `BridgeNotEnabledError` or `LocatorTimeoutError`.
---

# play-jab

`play-jab` is a typed, Playwright-style Python API for automating Java Swing/AWT
applications on Windows via Java Access Bridge (JAB). It only runs on Windows,
against a real, already-running JVM.

## Non-negotiable constraints

- **Attach-only.** There is no `PlayJab.launch()`. The target Java process must
  already be running; start it yourself before calling `attach()`.
- **Closing never kills the target.** Exiting the `with PlayJab(...)` block, or
  closing any/all sessions, leaves the attached process alive.
- **Exact, case-sensitive matching.** Window titles and string locators
  (`get_by_name`, etc.) do not do fuzzy or substring matching by default; use
  the `contains(...)` helper when partial matching is actually wanted.
- **Locators are lazy.** Every locator operation re-resolves a fresh JAB
  reference; nothing is cached across calls, and re-running a snapshot after
  the UI changed is expected, not a smell.
- **Never import `play_jab._native`.** It is a private implementation layer
  with no stability guarantees. Only import from the `play_jab` package root
  (`PlayJab`, `JavaApplication`, `JavaWindow`, `Locator`, exceptions, `contains`).
- **Reads vs. actions differ.** Reads (`snapshot`, `text_content`, attribute
  reads, table cell reads) work on hidden/disabled nodes. Actions (`click`,
  `fill`, `check`, `select_option`, ...) require the target *and every
  ancestor* to be visible, showing, and enabled — they will time out
  otherwise.
- **Passwords are redacted everywhere except an explicit read.** Password
  `text_content()` can be read on purpose, but the value never appears in
  snapshots, dumps, logs, or exception messages.

## Environment prerequisites (mention these when things fail)

- 64-bit Windows, 64-bit Python 3.11–3.14.
- 64-bit JDK 17 with Java Access Bridge enabled **before** the target JVM
  started: `& "$env:JAVA_HOME\bin\jabswitch.exe" -enable`, then restart the
  Java app. Enabling JAB does not retrofit an already-running JVM.
- An external `WindowsAccessBridge-64.dll` — play-jab does not bundle it.
  Discovery order is: explicit `dll_path` argument, then `JAVA_HOME`, then
  Windows `System32`. The current working directory is never searched.

## Minimal shape of a script

```python
from play_jab import PlayJab

with PlayJab(timeout=5_000, dll_path=r"C:\JAB\WindowsAccessBridge-64.dll") as jab:
    app = jab.attach(title="Application")  # or hwnd=..., or pid=...
    window = app.window(title="Application")

    window.get_by_name("login.username").fill("alice")
    window.get_by_name("login.remember").check()
    window.get_by_name("login.role").select_option("Admin")
    window.get_by_name("login.submit").click()
```

`dll_path` is optional if DLL discovery succeeds. `attach()` takes exactly one
of `hwnd=`, `pid=`, or `title=`.

## Timeouts

Every resolving operation accepts `timeout=` in milliseconds. The nearest
scope wins: per-call `timeout`, then the owning `JavaWindow`, then the
`PlayJab` session default. `timeout=0` means "check exactly once, right now."
On failure, catch `LocatorTimeoutError` and inspect its structured, bounded,
password-redacted diagnostic fields rather than re-deriving state manually.

## Forms

Form locators support `focus()`, `fill()`, `clear()`, `check()`, `uncheck()`,
`select_option()`, `text_content()`, plus attribute/state reads. Actions
verify their own observable postcondition (e.g. `check()` confirms the box
ended up checked) before returning.

## Tables

`locator.as_table()` exposes a `TableLocator` with zero-based row/column
indices: `row_count()`, `column_count()`, `snapshot()`, headers, row
selection, `cell(row, col)`, and `cell(...).wait_for_text(value, timeout=...)`.
Reads work even on hidden rows; selecting/acting on a row follows the same
visible/showing/enabled rule as any other action.

## Modal dialogs opened by a click

`click()` uses JAB's synchronous `AccessibleAction`. If the handler opens a
modal `JDialog`, the call blocks until that dialog closes, and no other
operation can use the (serialized) bridge worker meanwhile. For any control
that opens a window, use the explicit pattern instead of a bare `click()`:

```python
with app.expect_window(title="Confirmation") as pending:
    window.get_by_name("open.confirmation").click(opens_window=True)
dialog = pending.value
dialog.get_by_name("confirmation.ok").click()
```

## Virtualized lists/trees and scrolling

Only currently materialized children can be found by a locator — play-jab
never auto-scrolls while searching. Move the viewport explicitly, then
re-resolve:

```python
window.get_by_name("jobs.list").scroll(6)  # positive = down, negative = up
```

Scrollbar `accessible_value()` returns immutable `current`/`minimum`/`maximum`
strings; JDK 17's JAB has no supported setter for it. The opt-in physical
mouse-input path (used by `opens_window=True` clicks) requires an interactive
desktop session, does not fall back automatically from JAB, and restores the
prior cursor position and DPI-awareness context afterward even on failure.

## Diagnosing exceptions

All exceptions inherit `PlayJabError`. Map symptom to cause instead of
guessing:

| Exception | Likely cause |
| --- | --- |
| `BridgeNotEnabledError` | JAB wasn't enabled (`jabswitch.exe -enable`) for the current user before the app started. |
| `BridgeInitializationError` | Bad/missing `JAVA_HOME`, missing DLL, or a Python/JAB bitness mismatch. |
| `JavaWindowNotFoundError` | The HWND is gone or doesn't belong to a Java window. |
| `JavaWindowNotAccessibleError` | JAB was enabled *after* the target JVM had already started. |
| `JavaProcessExitedError` | The attached OS process ended; attach a new session. |
| `JavaVmExitedError` | The attached JVM announced shutdown; old locators/references are dead. |
| `JavaReferenceClosedError` | Reacquire the element — its native reference was released. |
| `BridgeClosedError` | The runtime was closed; create a new `PlayJab` session. |
| `NativeCallError` | A JAB call itself failed; inspect `.function_name` and its scalar args (app text is deliberately excluded — it may be sensitive). |
| `LocatorTimeoutError` | The locator never resolved within its deadline; read its structured diagnostic fields. |
| `TableIndexError` | An out-of-range row/column index was passed to a table locator. |

## When asked to write tests against play-jab

Prefer asserting through the public API (locators, table snapshots, explicit
waits) rather than reaching into `_native`. Real end-to-end runs need a live
JDK 17 + JAB + Windows desktop session — if that isn't available, say so
instead of fabricating results.
