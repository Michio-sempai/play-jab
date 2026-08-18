# Performance: how to measure, and where to look

[Русская версия](performance.ru.md) · [Back to README](../README.md)

This document is self-contained: copy it into any repository where play-jab
drives a Java application. It answers two questions — **what to measure with**
and **what the numbers mean** — so that "the tests hang" turns into a diagnosis.

## 1. The cost model: everything is counted in nodes

play-jab has no slow Python. Time goes into Access Bridge calls, each of which
is a cross-process round-trip into the JVM. Measured against a real Swing
client (JDK 17, x64, Windows 11):

| Native call | Average |
| --- | --- |
| `getAccessibleContextInfo` | ≈ 500–780 µs |
| `getAccessibleChildFromContext` | ≈ 130–170 µs |
| `releaseJavaObject` | ≈ 85–120 µs |
| `getAccessibleText` | ≈ 400–500 µs |
| `pump_messages` | ≈ 20 µs |

Visiting one node costs child + info + release ≈ **0.75 ms**. That leaves a
single number that matters:

> **How many tree nodes did the locator visit?**

Five thousand nodes is four seconds, and no Python-level micro-optimisation
changes that. So measure "how many nodes, and why that many" rather than
milliseconds alone.

## 2. What to measure with: a 40-line profiler

Wrapping `DllBackend`'s methods and `BridgeRuntime._submit` is enough to break
any operation down into native calls plus queue overhead. Install it **before**
constructing `PlayJab`.

```python
import collections
import time

from play_jab._native import backend as backend_module
from play_jab._native.bridge import BridgeRuntime

STATS: dict[str, list[float]] = collections.defaultdict(list)
SUBMIT = {"count": 0, "time": 0.0}


def instrument() -> None:
    """Time every native call and every hop onto the worker thread."""
    cls = backend_module.DllBackend
    for attr in dir(cls):
        if attr.startswith("_") or not callable(getattr(cls, attr)):
            continue

        def wrap(name, original):
            def wrapper(self, *args, **kwargs):
                started = time.perf_counter()
                try:
                    return original(self, *args, **kwargs)
                finally:
                    STATS[name].append(time.perf_counter() - started)

            return wrapper

        setattr(cls, attr, wrap(attr, getattr(cls, attr)))

    original_submit = BridgeRuntime._submit

    def submit(self, fn):
        started = time.perf_counter()
        try:
            return original_submit(self, fn)
        finally:
            SUBMIT["count"] += 1
            SUBMIT["time"] += time.perf_counter() - started

    BridgeRuntime._submit = submit


def report(label: str, wall: float) -> None:
    native = sum(sum(samples) for samples in STATS.values())
    print(f"\n=== {label}: {wall * 1000:.0f} ms ===")
    print(f"  _submit: {SUBMIT['count']} calls, {SUBMIT['time'] * 1000:.0f} ms")
    print(f"  native: {sum(len(v) for v in STATS.values())}, {native * 1000:.0f} ms")
    for name, samples in sorted(STATS.items(), key=lambda kv: -sum(kv[1]))[:8]:
        total = sum(samples)
        print(
            f"    {name:38s} n={len(samples):6d} total={total * 1000:8.1f} ms "
            f"avg={total / len(samples) * 1e6:7.0f} us"
        )
    print(f"  queue/thread overhead: {(SUBMIT['time'] - native) * 1000:.0f} ms")


def reset() -> None:
    STATS.clear()
    SUBMIT.update(count=0, time=0.0)
```

Drive the application to the screen under test, then measure one operation at
a time:

```python
reset()
started = time.perf_counter()
page.field.text_content()
report("field.text_content()", time.perf_counter() - started)
```

**Always measure each operation twice.** The first call on a locator chain is
cold (a full traversal); the second is warm (a check of the remembered path).
One cold number says nothing about how a test suite will behave.

## 3. Reading the report

Read it in this order.

**`n` for `getAccessibleContextInfo` is the number of nodes visited.** The
headline figure; everything else follows from it.

- Thousands of nodes to find one button → the locator is walking subtrees that
  are not yours. Go to section 4.
- Dozens of nodes but still slow → the cost is not the search. Look at the top
  rows instead (`do_accessible_actions` can block on a modal dialog).

**`_submit: N calls` is the number of hops onto the worker thread.** A full
traversal should show a handful of `_submit` calls, not thousands: both the
tree walk and a path read happen entirely inside one worker step. A `_submit`
count proportional to node count means an older play-jab, or a tree walk
written by hand over the public API.

**"queue/thread overhead" is `_submit` time minus native time.** A few percent
is normal; tens of percent means the operation is being split into many small
round-trips.

## 4. Three usual sources of wasted nodes

To see the shape of the tree, print subtree sizes — that is usually enough for
the cause to become obvious:

```python
tree = window.accessibility_tree(max_depth=100, max_nodes=50_000)


def sizes(node, path=(), depth=0):
    size = 1 + sum(
        sizes(child, (*path, i), depth + 1) for i, child in enumerate(node.children)
    )
    if depth <= 6 and size >= 50:
        snap = node.snapshot
        print(
            f"{'  ' * depth}[{size:6d}] {snap.role} {snap.name!r} "
            f"states={sorted(snap.states)} path={path}"
        )
    return size


sizes(tree)
```

Then look for one of three things.

**(a) Every screen of the application lives in the tree at once.** Typical of
CardLayout: one panel is active and the rest stay in the tree in full. They
carry no `showing` state.
*Fix:* `showing_only=True` on the locator — play-jab prunes such subtrees
whole, at one `getAccessibleContextInfo` per panel instead of thousands.

**(b) A collapsed tree or table still reports every descendant.** A JTree with
collapsed nodes returns a `childrenCount` in the thousands; those children have
neither `showing` nor `visible`, only `collapsed`.
*Fix:* the same `showing_only=True` — play-jab does not descend into a node
that is `collapsed`. Without it, each of those thousands is read and rejected
individually.

**(c) The target sits late in traversal order.** DFS goes left to right: if the
element is a right-hand sibling of a large tree control, the walk pays for the
tree first.
*Fix:* anchor the locator to the nearest stable container
(`window.get_by_name("app.editor").get_by_name("app.editor.name")`) and/or pass
`max_depth=`, which caps descent relative to the locator's own start.

## 5. What play-jab already does (and how to turn it off for comparison)

| Mechanism | Effect | How to disable |
| --- | --- | --- |
| Whole-subtree walk inside one worker step (`BridgeRuntime.traverse`) | ~1.9× | — |
| Path cache: a repeat resolution reads the remembered path (`read_path`) instead of walking | 100–700× warm | `PlayJab(path_cache=False)`, `PlayJab.clear_path_cache()` |
| Pruning `collapsed` subtrees under `showing_only=True` | up to 50× cold | do not use `showing_only` |

The path cache is keyed by (HWND, locator chain), so **the same chain has to be
reused**. It is a thread-safe LRU bounded to 1,024 chains. The classic
page-object mistake:

```python
# two different chains -> two cold traversals
locator = window.get_by_role("push button", name=name)
if locator.exists():
    return locator.first()

# one chain -> one traversal, then cache hits
locator = window.locator(role="push button", name=name, showing_only=True).first()
if locator.exists():
    return locator
```

A remembered path heals itself: once it stops satisfying any step of the chain
the entry is dropped and the ordinary traversal runs. The trade-off is that
`StrictModeViolation` ("more than one match") is reported by the traversals
rather than by every call. To compare against the old behaviour, profile with
`path_cache=False`; use it whenever discovering newly added duplicates on
every strict operation matters more than warm-path latency.

## 6. Reference numbers

On a client whose window tree holds ~13,000 nodes, with all three mechanisms on:

| Operation | Before | Cold | Warm |
| --- | --- | --- | --- |
| `element(...).exists()` | 6,000 ms | 81 ms | 14 ms |
| read one card field | 6,700 ms | 124 ms | 31 ms |
| write one card field | 13,400 ms | 90 ms | 54 ms |
| select a tree node | 13,100 ms | 66 ms | 50 ms |
| list 15 fields | 27,800 ms | 571 ms | 126 ms |

Numbers an order of magnitude worse are almost always case 4 (a) or (b): a
locator searching without `showing_only` and paying for other screens.

## 7. What the profiler will not show

- **Waiting on the application itself.** `do_accessible_actions` blocks until
  the Java handler returns, and a synchronously opened modal dialog holds the
  worker thread. That shows up as one call taking tens or hundreds of
  milliseconds, not as a large `n`.
- **`time.sleep()` in your own code.** The gap between an operation's wall time
  and the `_submit` total is your code and your explicit waits.
- **Swing tree rebuilds.** Minimising or maximising a window invalidates
  remembered paths, so the next operation is cold again. That is expected, not
  a leak.
