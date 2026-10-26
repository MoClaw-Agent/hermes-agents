# AST-based audit sweeps

The highest-yield audit instrument in this repo: a static sweep over the
source tree that finds a whole CLASS of defect in one pass. Reading the
code is slower and only finds what you thought to look for; a sweep finds
what the code actually does across every call site. Pair it with
`scripts/ab_verify.py` to prove the test you write for the finding
discriminates, and with a probe script for the behavioural number.

## The sweeps that paid off

| the sweep | the defect class it finds |
|---|---|
| **route authentication** | a route that reads or writes per-user data, or an admin/operational action, with no `Depends(require_*)` |
| **path traversal** | a request value (a body field, a query param, a path param) used to build a file path |
| **ignored request fields** | a request model field the route that accepts it never reads — a silent contract break |
| **pinned-API match** | the code calling an API the INSTALLED dependency does not have |
| **process-global caches** | a module-level dict keyed without the user (a cross-tenant leak) |
| **schema owners** | a per-user table with no owner column (ownership cannot be checked) |
| **unguarded risky calls** | a route body calling a store, a model, or a Qdrant client with no try around it |

## The gotchas that cost real time

### A route-scoped sweep MISSES defects built in a helper

The benchmark's `set_id` traversal was **not in the route** — it was in
`_run_retrieval_benchmark_sync(set_id=...)`, called by the route. A sweep
that only looks inside the route function finds nothing. **Sweep every
function in the module, then check whether the parameter can be traced
back to a request.** The ignored-request-fields sweep works precisely
because it goes the other way: it enumerates the model's fields and asks
which of them the route never reads.

### Python 3.11 keeps argument defaults in a SEPARATE list

`ast.arg` has no `.default` attribute. The defaults live in
`node.args.defaults`, aligned to the **LAST N** positional arguments:

```python
positional = list(node.args.args)
defaults = list(node.args.defaults)
pairs = list(zip(positional[-len(defaults):], defaults)) if defaults else []
pairs += list(zip(node.args.kwonlyargs, node.args.kw_defaults))
```

Without this, every route looks like it declares no authentication
dependency and the sweep reports 143 false positives.

### The import-binding rule for the API sweep

- `import a.b.c` binds the name **`a`** to the TOP package.
- `import a.b.c as x` binds **`x`** to the module `a.b.c`.
- `from a import b` binds `b` to the attribute (or the SUBMODULE) `b`.

Resolve the bindings PER FILE, or a local variable that happens to share
a name with a module becomes a false positive. Then check every
`Name.attr` access against the bound module with `hasattr`.

### `from X import Y` where Y is a SUBMODULE gives a false positive

`hasattr(module, 'algorithm')` is False until the submodule is imported,
even though `from bidi.algorithm import get_display` works fine. For a
`from`-import, check `importlib.util.find_spec(parent + '.' + name)`;
only a `None` spec is a real break. This is how a sweep reported
`bidi.algorithm` as absent when it was installed and working.

### f-strings are too noisy for path detection

Matching `f"...{name}..."` finds every log line and every message
string. For path traversal, filter to `ast.BinOp` with `ast.Div` (the real
path join) — that alone took a 116-hit sweep down to the few that matter.

### Do not re-run the whole file walk per imported module

The naive version (for each module, re-parse every project file) took
250 s. Collect the imports in ONE pass, then walk each file once.

### The sweep finds candidates; the probe proves them

A sweep is a candidate list. For each hit: read the code, then reproduce
it with a synthetic input (in-memory, never the corpus) before reporting
it as a finding. A sweep that reports "19 routes with an unguarded risky
call" is noise until each is checked — most are acceptable 500s for a
genuine server-side failure, and only some are wrong responses.

## The defect classes the sweeps surfaced here

- **A request field silently ignored** — `WSSearchRequest` carried
  `workspace_ids` / `folder_ids` and the route never passed them, so a
  folder-scoped search returned the whole user's documents. Found by the
  ignored-fields sweep; the fix is at the choke point so every caller is
  protected.
- **A pinned dependency's API the code does not use** — the project pins
  `ulid==1.1` (whose API is `ulid.ulid()`) while the code called
  `ulid.ULID().to_string()` (the `python-ulid` API). Every call raised
  `AttributeError`, which killed the whole private-workspace flow. Found
  by the pinned-API sweep; turned into a permanent gate test.
- **A process-global cache keyed without the user** — the exact query
  cache's key was `query | filters | role | mode`, so one user's private
  documents were served to another. Found by the cache sweep; the fix is
  to namespace the key by user and to keep private results out of the
  shared semantic cache.
- **A per-user table with no owner column** — `query_log` had no
  `user_id`, so the feedback endpoint could not check ownership and any
  user could thumbs-up another's query. Found by the schema-owner sweep.
- **A path traversal** — a benchmark's `set_id` and a crawler's `lang`
  were interpolated into paths; the crawler's crawl route validated the
  language but its status/log/failed routes did not.
