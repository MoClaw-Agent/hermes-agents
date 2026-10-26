# Debugging recipes — the mechanisms behind rules in SKILL.md

Each entry here is the depth behind a one-line rule in `SKILL.md`. Load this
when the rule fires and you need the mechanism, the call shape, or the fix.

## A logger that owns handlers must not also have an ancestor that owns handlers

Giving every module logger its own console + file handlers, in a hierarchy
where a parent and a child both exist, writes every record TWICE: the
child's handlers and then, by propagation, the parent's. Measured: one
`logger.info()` printed twice and landed twice in EACH log file.

Put the handlers on the NAMESPACE ROOT (`logging.getLogger("mizan")`) and
let the module loggers be children that propagate to it. Keep the handler
levels at `NOTSET` so the ORIGINATING logger's level decides — an
ancestor's LOGGER level is not consulted during propagation; Python checks
the ancestor's HANDLER level. Keep `propagate = True`, or pytest's `caplog`
stops capturing the module's records.

## Never count a Qdrant collection by scrolling its payloads

A per-domain count fetched with `with_payload=True` pulls every chunk's full
text over the wire to read one field: **289 seconds** on 13,092 points.

The facet API returns byte-identical counts in **0.01 s**:

```python
client.facet(collection_name=..., key="domain", limit=..., exact=True)
```

The scroll fallback should ask for the one field
(`with_payload=["domain"]`), never the whole payload. The points that carry
no key are the remainder and belong in the `__unknown__` bucket the old
implementation reported.

## The camel `TypeError` is a test-isolation defect, not a production one

`numpy._globals` defines its "no value" sentinel as a MODULE-LEVEL SINGLETON
and the compiled reduction compares against it BY IDENTITY.
`mock.patch.dict(sys.modules, ...)` drops every key added inside the window,
so a numpy first imported there is EVICTED and the next import builds a
different sentinel the loaded extension does not recognise
(`numpy/_core/_methods.py:47`).

The fix is to import the heavy stack ONCE at MODULE level in the test file,
outside every patch window — the tests patch the FUNCTION, never the package,
so the import changes nothing they assert.
