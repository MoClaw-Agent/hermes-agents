# Test-Gate Repair Patterns

Making Mizan's red test gates green by fixing the real cause and re-pinning the
gate to measured truth. These are the reusable patterns; the workflow itself lives in
SKILL.md.

## Bounding a synchronous lookup inside an async endpoint

A cache/DB lookup that can block on a dead backend stalls the whole request
(measured: a Qdrant-backed semantic-cache `get` blocked ~10s on connect timeout).
Bound it so a slow backend degrades to a miss instead of stalling the request.

**Use a daemon thread + `join(timeout)`, NOT a `ThreadPoolExecutor` `with` block.**
The `with` block calls `shutdown(wait=True)` on exit, which blocks until the
abandoned lookup finishes — silently defeating the `future.result(timeout=...)`. A
daemon thread is abandoned cleanly and never blocks the request or process exit.

```python
def _bounded_get(cache, key, timeout=2.0):
    import threading
    holder = {}
    def _run():
        try: holder["hit"] = cache.get(key)
        except Exception: holder["hit"] = None
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return None if t.is_alive() else holder.get("hit")
```

Verify the healthy path still answers well under the bound (a live Qdrant is
<100ms; the 2s default never bites a hit) and that the timeout path returns fast.

**But bounding is NOT enough when the abandoned work loads a shared resource the
request path also needs.** A semantic-cache lookup abandoned mid-initialization
keeps loading the embedding model in the background; that thread then contends
with the search pipeline's own model load and the request still stalls past its
timeout. Before bounding, check what the abandoned thread loads — if it touches a
model/lock the request also needs, the real fix is failing fast at the source
(e.g. a cheap reachability probe BEFORE the heavy init) so the heavy work never
starts.

## Migrating a bare `except Exception` to a narrow tuple

When the original caught everything but discriminated on the error *message*
(e.g. `if not is_payload_limit_error(e): raise`), the narrow tuple must include
every exception type the discriminator's callers/tests can raise — not just the
"real" ones. A test that injects `RuntimeError("... larger than allowed")` and
expects a retry fails if the tuple only names the production SDK exception. List
the realistic surface (SDK wrapper, internal-guard `RuntimeError`, network
`ConnectionError`/`TimeoutError`/`OSError`) and let the message check decide
retry vs. propagate. Both the retry test and the propagate-test then pass.

## Walker / baseline pin ratcheting (bare-except debt)

Migrating bare excepts changes the walker count, which is pinned in many places.
Re-pin ALL of them in one commit or the suite stays red:

1. `tests/test_no_bare_except.py`: `BASELINE_COUNT`, `X1_BASELINE_FLOOR`, and a
   new `WALKER_COUNT_PINS` entry with the measured count and a breakdown.
2. Every per-PR gate that hard-codes the old count: `POST_PR_B5_WALKER`,
   `POST_PR_B6_WALKER`, `EXPECTED_WALKER_POST`/`EXPECTED_BASELINE` in the
   `test_pr_b*`/`test_pr_c*`/`test_pr_d*` files, and any
   `BASELINE_COUNT == <n>` regex assertions.
3. The `test_no_new_bare_except_sites` gate uses `<=` so it stays green; the
   exact-match `test_walker_count_exact_match_pin` does not.

Measure with `tests.test_no_bare_except._bare_except_sites_from_ast()` before and
after; the delta must equal the number of migrations. That walker counts
**bare-baseclass** excepts (`except Exception`, `except:`) — NOT every
`except` handler, so don't compute the delta from all `ast.ExceptHandler`
over all nodes or you'll chase phantom drift.

## Module-global state leaking across tests

Two failure shapes, both fixed by an autouse snapshot/restore fixture:

- `reload(core.settings)` rebinds the process-wide settings singleton while
  already-imported modules hold the old object; later `patch.object(settings,
  ...)` patches an object the code under test never reads.
- A module-level dict (e.g. a rebuild-status global) left dirty by one test makes
  every later test that reads it fail — green in isolation, red in full-suite order.

Snapshot the global(s) before each test and restore them (join any background
thread) after, so each test sees a clean process.

### `patch.dict(sys.modules, ...)` evicts a C extension's module-level singleton

The nastiest variant, and it produces an error that names a third-party library
rather than the test: `TypeError: int() argument must be a string, a bytes-like
object or a real number, not '_NoValueType'` at `numpy/_core/_methods.py:47`.

**The mechanism, pinned.** `numpy._globals` defines the "no value" sentinel as a
MODULE-LEVEL SINGLETON:

```python
class _NoValueType: ...
_NoValue = _NoValueType()          # numpy/_globals.py:63
```

The compiled reduction compares its `initial` argument against that object **by
identity**, not by type. `mock.patch.dict(sys.modules, {...})` restores the dict
to its snapshot on exit, dropping every key ADDED inside the window — so if the
heavy stack is first imported inside that window, numpy and its submodules are
EVICTED afterwards. The next import builds a fresh `numpy._globals` whose
`_NoValue` is a **different object** (verify: `id()` differs AND `type()`
differs, because the reloaded C extension creates a new `_NoValueType`), while
the already-loaded C extension still holds the OLD one. It no longer recognises
it, falls through to treating it as a real number, and raises.

**Confirm it in three steps** (all read-only):

```python
import numpy as np, numpy._globals as gl
np.min(np.array([1.0, 2.0]), initial=np._NoValue)   # OK in a clean process
del sys.modules["numpy._globals"]
import importlib; gl2 = importlib.import_module("numpy._globals")
gl2._NoValue is gl._NoValue                          # False
np.min(np.array([1.0, 2.0]), initial=gl2._NoValue)  # TypeError ... _NoValueType
```

**The fix is a test-isolation repair, not a production change.** Import the heavy
stack ONCE at MODULE level in the test file, before any `sys.modules` patching,
so the first-time import happens outside the patched window; and make the
injecting helper RESTORE the real module rather than leaving it absent. A
`patch.dict` that installs a fake for a module the production code imports is
fine — the defect is the eviction side effect, not the fake.

**It is order-dependent**, which is the tell: the affected class passes alone and
fails only when a sibling class ran first. Bisect with
`pytest "file::ClassA" "file::ClassB"` vs each alone.

## Isolating a request-path stall

When an endpoint times out in a test env, don't guess — bisect by toggling the
suspected component off via its env/settings flag and re-measuring. A cache
backend that lazily loads ML models in the request path is a classic stall; if
disabling it makes the request pass fast, you've found the cost. Then measure the
component's standalone timing (and confirm whether its backend is even up — a
`socket.create_connection` to the host:port is a ~1s probe) before and after any
bound, so you know the bound actually removed the stall and didn't just move it.

## Fixture / doc / env gate repairs

- **Image fixtures**: if production decodes a payload with PIL, a stub byte string
  raises `UnidentifiedImageError` before anything is posted — build a real tiny PNG
  (`Image.new("RGB",(16,16)).save(buf, format="PNG")`); the re-encode is
  byte-identical for a small image.
- **Golden fixtures**: every item must define the contract (e.g. `s2_normalize`),
  not just the first few.
- **God files**: a file over the LOC limit must either be split (canonical split
  per `doc/CANONICAL_SPLIT_PATTERN.md`) or pinned in the `ALLOWLIST` with its
  current LOC; a pin blocks further growth.
- **`.env` hygiene**: keys with no `Settings` field are silently ignored — remove
  dead keys; path values must match the canonical suffix (trailing slash or not).
- **Doc gates**: `doc/MANUAL.md` needs the versioned release/closeout sections the
  gates regex for; `CHANGELOG.md`'s top entry must be a `vX.Y.Z` release entry,
  not `[Unreleased]`.
