# Dense leg returns 0 hits — diagnostic procedure

Trigger: `[HYBRID] Dense retrieval returned 0 hits while sparse returned N`.

## The timing signature localizes the failure first

Read the duration from the `[DENSE-SUB] qdrant_search: <t> (<n> hits)` log line. The
duration separates the causes before any filter or vector theory:

| observation | what it means |
|---|---|
| ~250–510 ms with hits | the populated collection answered normally |
| ~3–20 ms with 0 hits | an EMPTY collection answered — or the search never ran |
| `[DENSE-SUB] embed_query failed` / `No query vector available` | the embed step failed, not the search |

A fast 0-hit is therefore **not** a filter or vector problem. A populated Qdrant search
costs hundreds of milliseconds because of the index traversal; an empty collection answers
in single-digit milliseconds. Check the collection sizes before theorizing:

```bash
curl -s http://localhost:6333/collections | python -m json.tool
```

`mizan_case` and `mizan_bo` are legitimately empty in a law-only deployment — their fast
0-hit is expected and is NOT the failure. The failure is when `mizan_law` answers 0 fast.

## `search_all` merges three collections

`retrieval/dual_collection/manager.py::search_all` queries law + case + bo in parallel and
merges. A 0-hit merged result is invisible at that level, so the per-collection count is what
identifies the culprit. The manager logs it when the merged result is empty:

```
[HYBRID] dense search_all returned 0 points across collections: {col: n, ...} (query_vector_len=1024)
```

## Ruled out by direct measurement — do not re-derive

- **The default filter is not the cause.** With no filter, `_build_qdrant_filter` emits
  `must=[status == "active"]`. Verify the payload carries it:
  `client.count(collection_name=..., count_filter=<that filter>, exact=True)`. If the count
  equals the collection size, the filter matches everything.
- **Malformed vectors raise, they do not return 0.** Empty list, wrong dimension, NaN and inf
  all raise `UnexpectedResponse: 400`; an all-zero vector returns points. A 0-hit with no
  exception means the vector was well-formed.
- **The embed cache is not the cause** when the log shows a real embed (`embed_query: <t>ms`)
  rather than `CACHE HIT`.
- **Concurrency does not reproduce it** — firing the same query several ways simultaneously
  returns hits every time.
- **The collection is not being emptied** — poll `get_collection().points_count` over minutes;
  a stable count rules out a recreate.

## When it is intermittent and will not reproduce

Instrument at the merge point (as above) and wait for the next occurrence. Do NOT:

- add a retry that masks the symptom without identifying which collection failed;
- conclude "Qdrant is down" from a fast 0-hit — a connection failure costs more than 10 ms and
  raises;
- change the filter or the vector path speculatively.

## Related

- The dense leg is guarded: `retrieval/hybrid/fusion.py` and `raw.py` fall through to the sparse
  leg. Their guard message text is pinned by
  `tests/test_dense_degrades_to_sparse.py` — keep the pinned phrase when rewording.
