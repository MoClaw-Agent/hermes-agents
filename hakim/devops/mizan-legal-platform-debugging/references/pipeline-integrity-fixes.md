# Pipeline integrity fixes — latent defects in shared extraction code

Defects found by code audit of `fetching/pipeline_base/` and `core/`. Each is
silent by construction: no exception, no warning, output written normally. The
common theme is a value that decides correctness being dropped, defaulted, or
trusted on the way out.

## A `return` nested in a repair branch disables the extraction cache

`extract_pages()` read the cache, validated it, and then discarded it, because its
only `return` sat inside the masthead-repair branch:

```python
if pages and any(masthead_problem(p) for p in pages[:3]):
    repaired = repair_extracted_pages(pages)
    if repaired != pages:
        pages = repaired
        return pages, mode, tables        # <- only return path
pages = None                               # <- clobbers the cache we just read
```

Every document re-extracted on every run. Measured: a page that should have been
a cache hit took **105 s instead of 0.00 s**. Nothing logged oddly and the output
was correct, so this is invisible without timing a second identical run.

**The rule:** a cache contract is `valid → return`, `invalid → fall through`,
and that decision belongs in one place. A `return` inside any branch that is not
the validation decision is a silent cache killer.

**The instructive half is the wrong fix.** Dedenting the `return` so a valid
cache always returns is necessary but not sufficient: after an invalidation,
`pages` and `mode` still hold the values validation just rejected, so that
version returns exactly the refused content:

```python
if not should_invalidate:
    # optional repair applied in place
    return pages, mode, tables
# invalidated -> fall through to full re-extraction
```

Test three paths, not one: valid hit returns fast, invalidated falls through,
corrupt/unreadable cache does not raise. Each caught a different real defect.

## Do not erase legitimate zeros from persisted state

`core/parser_state.py` — `to_dict()` filtered `v != 0`:

```python
{k: v for k, v in asdict(self).items() if v is not None and v != "" and v != 0}
```

`articles=0`, `pages=0` and `duration_s=0.0` were dropped, so **a document that
parsed zero articles was indistinguishable from one never attempted**. Filter
only `None` and `""`; `from_dict` supplies dataclass defaults, so keeping zeros
round-trips cleanly.

Same class of error as an article-count bug: the number that decides whether a
document is usable is exactly the number that gets discarded.

## Never interpolate citation URLs into HTML

`core/citation/models.py` — `render_html()` emitted `<a href="{self.url}">`
verbatim. Citation URLs arrive from parsed document metadata, so they are
attacker-influenced input; `javascript:alert(...)` renders as a live link.

Parse the URL, allow only `http`/`https`, require a netloc, HTML-escape both the
href and the label, and add `rel="noopener noreferrer"`. Escape the label too —
it is built from reference/title/pinpoint fields and can carry markup. A
non-linkable URL degrades to escaped plain text rather than being dropped.

Verify against a fake hostile input, not just the happy path: `javascript:`,
`data:`, `vbscript:`, `file:`, an attribute-breakout URL (`https://ok/"><script>`),
and markup inside the label.

## Dead settings and unreachable branches

Small, cheap defects found in the same pass — each is a setting or code path an
operator would reasonably believe is active:

- `OLLAMA_SUPPORTS_STRUCTURED_OUTPUT` is read by `core/providers/__init__.py` but
  declared in no settings mixin. With `extra="ignore"` the env var is swallowed
  silently and the override is inert.
- Provider auto-detect is unreachable: `provider_type` is assigned from settings
  two lines above the `if not provider_type and "/" in model` test, so
  `model="openai/gpt-oss-120b:free"` silently routes to Ollama instead of failing.
- `--retry-failed` does nothing: both branches of `should_skip()` return `False`
  for `status="failed"`, so failed files always re-parse regardless of the flag.
- `FileState.to_dict()` and `settings` with `extra="ignore"` share a failure
  mode: a typo'd key or an unset field is indistinguishable from a working one.
  Confirm an effective value through `settings`, never by reading `.env`.

## A required engine that silently falls back still writes a normal-looking artifact

When a document *requires* a specific engine (vision/OCR for a CMap-corrupt
Arabic PDF) and that engine fails — timeout, unreachable endpoint, or the
rescue gate disabled — the pipeline falls through to a lesser engine and still
writes a normal JSON. The article tree is then silently wrong and
indistinguishable from a good parse.

Real case: a 52-page Arabic decree whose vision cache was missing re-transcribed
through a tunnel, **timed out**, fell back to PP-OCRv5, and produced
`num_articles_detected: 40` where the vision text yields **197**. The output
carried `structure_source: "extraction"` — which is *also* the legitimate value
for a clean native layer, so the field could not tell the two apart.

**Rule:** a required-engine failure must be recorded as an explicit degraded
state, not absorbed into a success. Emit a dedicated flag and reason
(`structure_degraded` + `structure_degraded_reason`), a distinct log line
(`[OK-DEGRADED] … | vision REQUIRED but <reason>`), a counter in the run summary,
and a distinct run status (`completed_with_degraded`). Set the flag **only** when
the engine was required and lost — never for a legitimate fallback path, or it
becomes noise nobody reads.

**Close every gate that reaches the same fallback, not just the obvious one.**
The vision branch was not the only silent path: "vision rescue not requested
(VISION_ENGINE_ENABLED disabled) while the native layer is unusable" reached the
same degraded output through a different `elif`. Enumerate the branches that can
land on fallback text and flag each.

## An override parameter shadowed by a module-level constant

`process()` accepted `cache_vision_dir` and stored it in `_cache_vision_dir`, but
the vision-cache path was built from the module-level `CACHE_VISION_DIR`:

```python
_cache_vision_dir = cache_vision_dir or CACHE_VISION_DIR   # override accepted
...
vision_cache = CACHE_VISION_DIR / f"{stem}_{key}_vision.json"   # override ignored
```

Provider wrappers (ISM) and scratch/test runs therefore read and wrote the
**live** cache. Symptom: a test run meant to be isolated silently consumed the
real cache and reported a passing result that proved nothing.

**Rule:** when a function takes a path/config override, grep the function body
for the module-level constant it replaces. A single leftover reference makes the
override inert everywhere it matters. Test isolation is the canary: if a scratch
run touched the live tree, an override is being ignored.

## `%s`/`%d` in a loguru call never formats — the log shows the placeholders

`loguru` uses `{}`-style formatting, not `%`-style. A call written for the
stdlib `logging` API passes through literally:

```python
logger.info("[OCR_FIRST] %s - %d pages via %s", name, n, engine)  # loguru
# output: [OCR_FIRST] %s - %d pages via %s
```

No exception, no warning — the message is emitted with the placeholders intact,
so the operator sees a log line that looks like a template rather than data.

**Rule:** in this repo `pipeline_base` modules import `loguru`'s `logger`
(not `logging.getLogger`). Use `logger.info("… {0} … {1}", a, b)` — positional
`{}` placeholders with the values as trailing args, or an f-string. When a log
line renders literal `%s`/`%d`, the logger is loguru and the call site was
written for stdlib logging; fix the format string, do not chase the data.

## Reviewing this class of defect

Silent-by-construction defects need targeted probes, not code reading:

1. Run the behaviour and time it. The cache bug was only visible as a 105 s
   page that should have been instant.
2. Feed hostile input to anything that renders or stores. The XSS needed a
   `javascript:` URL to exist at all.
3. Check that a "fixed" result is not a *less wrong* result. The zero-filter fix
   had to keep `error="boom"` while restoring `articles=0`.
4. Assert a setting is declared, not merely read. `getattr(settings, "X", None)`
   returning `None` forever is indistinguishable from a default that never fires.

## "No monkeypatches, SOTA only" — what else that rule covers

This preference was restated three times in one session, each time rejecting a
shortcut that looked like a fix. It is broader than the `getattr` pattern it
was first raised about.

**Speculative infrastructure is the same failure in a new costume.** Writing a
sidecar, persistence helper, or module-level registry that no caller invokes
invents a contract nobody agreed to — and persisting data from inside a function
that previously returned a value quietly changes that function's contract. Ship
the smallest change that makes the defect *observable* (log at `ERROR`, return
the real number), then let the operator choose whether to build on it.

**A configurable heuristic is not automatically SOTA.** One added this session
could not see the defect class that motivated it: a swapped dotted reference and
a correct one are both well-formed legal references, so nothing local separates
them. Shipping it as a routing gate would have skipped exactly the files it was
built to protect, while looking authoritative. When the honest answer is "this
cannot be detected locally", put that in the docstring and assert it as a test
case so a later session does not wire it into a gate on the strength of its name.

**Frame the limit, do not lower the bar.** The fix that shipped checks bare
years only, says so explicitly, and carries a test asserting that dotted
references are undetectable. That is stronger than a broader detector that
appears to work and fails silently in production.