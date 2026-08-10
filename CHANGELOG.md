## Unreleased

### Feat

- add root-only `JavaWindow.snapshot()`, immediate `Locator.exists()`, and
  pruning `showing_only` locator traversal
- stop `first()` and `nth()` traversal once the requested match is found
- add `max_depth` to `locator()`/`get_by_role()`/`get_by_name()` to bound
  traversal depth

### Fix

- filter non-Java HWNDs out of `expect_window()` before its ambiguity check

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
