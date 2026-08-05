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
