## v2026.08.9 (2026-08-19)

### BREAKING CHANGE

- `play-jab-skill` no longer exists as a console script.

### Feat

- remove the bundled Claude Code skill and its installer CLI

### Fix

- heal TableCellLocator.fill()'s activation race and require explicit consent
- unpin the correct FakeNode in FakeBackend.remove_last_child()
- heal action-path staleness, wait for check/uncheck, redact table passwords, diagnose disabled JAB

## v2026.08.8 (2026-08-18)

### Feat

- add `TableCellLocator.fill()` for standard Swing in-place text editing
- add a bounded, thread-safe locator path cache with an exhaustive opt-out

### Perf

- batch locator tree traversal into one bridge worker step
- prune collapsed subtrees for showing-only locators

### Fix

- preserve strict-mode ambiguity checks after a preceding `exists()` call
- replace every UTF-16 code unit when editing cells containing supplementary text

## v2026.08.7 (2026-08-10)

### Fix

- resolve expect_window() ambiguity from JAB semantics, not raw HWND count

## v2026.08.6 (2026-08-10)

### Feat

- add max_depth to bound locator traversal
- prune non-showing locator subtrees
- add root-only window snapshot

### Fix

- filter non-java hwnds before expect_window ambiguity check
- raise accessibility traversal limit
- select nested JComboBox options
- use JDK 17 spinbox role name
- use JDK 17 multiple line state name

### Perf

- short-circuit positional locator traversal

## v2026.08.5 (2026-08-10)

### Feat

- add play-jab-skill CLI to bundle a Claude Code skill

## v2026.08.4 (2026-08-10)

### Fix

- mint owned references for FakeBackend events and drop dead code

## v2026.08.3 (2026-08-05)

### Feat

- add deadline-aware read/action locators, postcondition waits, structured
  redacted timeout diagnostics, and explicit wheel scrolling
- add read-only AccessibleValue current/minimum/maximum snapshots
- add materialized visible-child traversal and lazy table cell/header bounds
- extend the Swing fixture with virtual list/tree, deterministic dynamic state,
  table row mutation, and a function-scoped JVM lifecycle launcher

### Breaking

- locator reads no longer require actionable states; actions validate the full
  ancestor chain and required Accessible interface
- resolving APIs now accept per-call `timeout`; table upper bounds are checked
  when a lazy cell/header is operated, not when it is created
- replace the untyped runtime-session forwarding hook with an explicit typed facade

## v2026.08.2 (2026-08-05)

### Feat

- add form text, focus, checkbox, option-selection, and attribute APIs
- add zero-based AccessibleTable snapshots, cells, headers, selection, and waits
- add process-wide runtime leases, event-assisted waits, and JVM-exit diagnostics

### Changed

- remove pre-alpha `PlayJab.launch()` and make the public API attach-only
- require 64-bit JDK 17 and an external JAB DLL resolved from an explicit path,
  `JAVA_HOME`, or `System32`

## v2026.08.1 (2026-08-05)

### Feat

- add synchronous action and window API
- add native Java Access Bridge runtime

### Fix

- honor Python versions in CI matrix
- publish pytest results to GitLab
- type-check Windows backend in CI
- harden JAB lifecycle and lint configuration
- restrict PyPI releases to matching CalVer tags
