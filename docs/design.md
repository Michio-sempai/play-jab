# Design

[Русская версия](design.ru.md) · [Back to README](../README.md)

How `play-jab`'s module stack is shaped, in the vocabulary of the
[`codebase-design`](../.claude/skills/codebase-design/SKILL.md) skill: module,
interface, implementation, depth, seam, adapter. See that skill for the
definitions; this document applies them to the actual code rather than
re-explaining them.

## The stack as modules

Each layer in the architecture (see `CLAUDE.md`) is a **module**: it has one
**interface** and hides an **implementation** behind it. Layers only talk to
the interface of the layer below, never to its implementation.

| Module | Interface | Depth |
| --- | --- | --- |
| `_native/types.py` | ctypes structs/typedefs | N/A — pure data, no behaviour to hide |
| `_native/functions.py`, `dll.py` | `argtypes`/`restype` tables, `load()` | shallow by design — just ABI wiring and discovery order |
| `_native/backend.py` (`NativeBackend`) | ~30 Access Bridge calls | **the seam** — see below |
| `_native/bridge.py` (`BridgeRuntime`) | `start`/`close`/`context_from_hwnd`/`click`-level calls/... | deep |
| `_native/refs.py` (`JavaRef`) | `close()`, context manager, `.value`/`.vm_id`/`.closed` | deep |
| `_native/manager.py` (`RuntimeManager`/`RuntimeSession`) | `acquire()` → session with `close()`/`release()` | deep |
| `sync_api.py` (`PlayJab`, `JavaApplication`, `JavaWindow`, `Locator`) | ~30 locator methods, a handful of `PlayJab`/`JavaWindow` methods | deep |
| `registry.py` (`AccessibilityRegistry`) | `role()`, `state()` | deep for a small module — JDK role/state validation plus extension policy hides behind two calls |
| `exceptions.py` | the exception hierarchy itself | not a module in the usual sense — see [Interface as error modes](#interface-as-error-modes) |

## The central seam: `NativeBackend`

`_native/backend.py` defines `NativeBackend` as a `Protocol`. This is **the**
seam of the whole codebase: everything above it — `BridgeRuntime`, `refs.py`,
`manager.py`, all of `sync_api.py`, every `Locator` operation — is written
against this interface and never against `ctypes`, DLL handles, or a real
JVM.

Two adapters satisfy it:

- `DllBackend` — the real implementation, marshaling to the Access Bridge DLL.
- `FakeBackend` (`_native/fake.py`) — an in-memory node tree implementing the
  identical interface.

Per the skill's principle — *"one adapter means a hypothetical seam, two
adapters means a real one"* — this is a real seam: both adapters exist and are
both exercised (`DllBackend` by integration tests against a live Swing
fixture, `FakeBackend` by every unit test). Nothing above `NativeBackend` can
tell which one it's talking to, which is what lets the entire unit-test suite
run without a JVM, Access Bridge, or Windows desktop.

**Interface width is honest, not accidental.** `NativeBackend` has roughly
thirty methods — much larger than the "few methods" a deep interface usually
implies. That width is inherent to what the seam has to abstract over (the
vertical slice of the Access Bridge C API actually used), not a design smell:
shrinking it would mean collapsing operations that are genuinely independent
at the JAB level (text vs. table vs. selection vs. events) into a leakier,
harder-to-fake facade. The depth still shows up on the *implementation* side:
`DllBackend` hides struct marshaling, `JOBJECT64`-width footguns, and
callback-driven event draining; `FakeBackend` hides an entire fake node tree
with parent/child/table semantics — behind method signatures a caller reads
straight off the JAB spec.

**The seam carries interface invariants, not just method shapes.** Per the
skill's definition of "interface" — invariants and error modes are part of
it, not just the type signature. Both adapters commit to mirroring native
failure signaling (`FALSE`/null/`0`) as `None`/`False`/`0`, and *neither ever
raises a `play_jab` exception* — translating a backend failure into the public
exception hierarchy is `BridgeRuntime`'s job, one layer up. `FakeBackend` goes
further and encodes a second invariant directly into its own failure modes:
it distinguishes *stale contexts* (normal — a rebuilt Swing tree invalidates
handles, so reads just return `FALSE`/null) from *misuse* (double-release, an
unknown cookie — `FakeBackendError`, an `AssertionError` subclass, never
`PlayJabError`) so a test can't mistake "the fake caught you holding it
wrong" for a real native failure.

## Seams inside `sync_api.py`

`sync_api.py` needs two things `NativeBackend` doesn't provide — Win32 window
enumeration/synthetic input, and OS process liveness — so it defines its own
seams for them, each swapped in tests the same way:

- `WindowBackend` (`Protocol`, `sync_api.py:205`) — `enum_windows`,
  `get_window_title/pid`, cursor/DPI/click/wheel primitives. Real adapter is
  the Win32 implementation `_create_window_backend()` returns; test adapter is
  `FakeWindowBackend` in `tests/conftest.py`, shared across seven test files
  (previously copy-pasted per file — consolidating it was itself a depth
  improvement: one fake, one interface, instead of seven ad hoc doubles
  drifting apart).
- `_create_runtime` / `_is_process_alive` — module-level factory functions
  `PlayJab` calls instead of constructing `BridgeRuntime` or checking
  `psutil`-equivalent liveness directly. Tests monkeypatch these (see
  `install_fake_runtime()` in `tests/conftest.py`) to inject a `BridgeRuntime`
  that was itself built over a `FakeBackend`.

Note what `install_fake_runtime()` actually wires in: a **real**
`BridgeRuntime`, constructed with a `FakeBackend` factory. The seam that gets
faked for `sync_api` tests is `NativeBackend`, one layer down — `BridgeRuntime`
itself is never doubled. That is deliberate: `BridgeRuntime`'s job (thread
ownership, message-pump marshaling, exception translation) is exactly the kind
of behaviour worth exercising for real in every test, not mocking away.

## A narrowing that isn't a seam: `_RuntimeFacade`

`sync_api.py:225` defines `_RuntimeFacade`, a `Protocol` covering the subset of
`BridgeRuntime` that `sync_api` actually calls (context/text/table/selection
operations — no `start()`/`close()`/thread internals). Only one adapter ever
satisfies it (`BridgeRuntime`), so by the skill's principle this is a
**hypothetical seam**, not a real one — it exists for interface segregation
and readability (it documents, in one place, the exact slice of
`BridgeRuntime` that `sync_api` depends on), not for swappability. Don't
mistake it for a second testing seam: faking `_RuntimeFacade` directly instead
of going through `BridgeRuntime` + `FakeBackend` would skip the exception
translation and thread marshaling that `sync_api`'s tests are supposed to
exercise.

## Depth deep-dives

Applying the skill's **deletion test** — delete the module, see where the
complexity reappears — to the modules doing the most hiding:

- **`BridgeRuntime`.** Delete it and every caller (`refs.py`, `manager.py`,
  all of `sync_api.py`) would need its own thread, its own Win32 message pump,
  and its own command-queue marshaling to safely call the not-thread-safe
  `NativeBackend` from arbitrary caller threads. One deep module instead of
  N re-implementations of "own a worker thread correctly."
- **`JavaRef`.** Delete it and every call site holding an `AccessibleContext`
  would need to remember it's a live, JVM-owned reference that must be
  explicitly released — not a plain integer id — and get the
  double-release/leak tradeoff right itself. `JavaRef` collapses that to
  `close()`/context-manager, with a `weakref.finalize` safety net that is
  explicitly *not* load-bearing (deterministic release still happens through
  `close()`).
- **`Locator`.** Delete it and every caller would inline: JAB context
  re-resolution on every operation (locators are lazy), the
  visible/showing/enabled ancestor-chain check actions require but reads
  don't, `showing_only` pruning vs. `visible_only` filtering, the remembered
  child-index path that lets a repeat resolution re-check a handful of nodes
  instead of walking a tree of tens of thousands, and `LocatorTimeoutError`'s
  bounded, password-redacted diagnostic capture. The public surface is close
  to thirty methods across query/read/act/wait families — wide for a "deep
  module," but it stays deep because each family shares the same private
  resolution machinery (`_resolve_single`, `_resolve_once`, `_scan`,
  `_wait_strict`) rather than duplicating it, and no caller can reach that
  machinery directly.
- **`RuntimeManager`/`RuntimeSession`.** Delete it and every `PlayJab`
  instance in a process would need to coordinate directly over whether a
  `BridgeRuntime` (one thread, one DLL) can be shared or must be rejected as
  mismatched — `acquire()`/`release()` plus a generation counter is what
  stands between "share a runtime" and "silently corrupt across two DLL
  paths."

## Interface as error modes

The skill's glossary is explicit that an interface includes "error modes,"
not just call shapes. `exceptions.py` is where that shows up as a standalone
design decision rather than an implementation detail: `JavaReferenceClosedError`
is a **sibling** of `BridgeClosedError`, not a subclass. That's deliberate,
not an oversight — a broad `except BridgeClosedError` handler (treating the
whole runtime as dead) must not also swallow a recoverable stale reference,
and `except BridgeClosedError: retry` must not spin forever against a runtime
that is actually dead. The hierarchy is part of the public interface exactly
as much as any method signature is; changing it is a compatibility decision,
not a refactor.

## Relationships, applied

Per the skill: a module has one interface; depth is measured against that
interface; a seam is where the interface lives; an adapter satisfies it.
Concretely in this codebase:

```text
NativeBackend (seam, _native/backend.py)
├── DllBackend        (adapter — real DLL)
└── FakeBackend        (adapter — in-memory node tree)
        ↑ both consumed only through BridgeRuntime

WindowBackend (seam, sync_api.py)
├── real Win32 implementation (adapter)
└── FakeWindowBackend         (adapter — tests/conftest.py)

_RuntimeFacade (interface-segregation narrowing, not a seam — one adapter: BridgeRuntime)
```

Everything above `NativeBackend`/`WindowBackend` gets its **leverage** (one
`BridgeRuntime`/`Locator` implementation paying back across every call site
and every test) and its **locality** (a JAB quirk gets fixed once, in
`DllBackend` or `BridgeRuntime`, not re-discovered at each call site) from
those two seams staying exactly where they are.
