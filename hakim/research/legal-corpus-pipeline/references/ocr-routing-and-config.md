# OCR routing and configuration in a layered parser

A multi-provider parser reaches OCR through several branches, each of which can
call a different engine. The settings that control this fail *quietly*: a
misplaced gate or an undeclared field produces a parse that completes, logs
nothing alarming, and quietly uses the wrong engine on the worst documents in
the corpus. Read this when OCR output looks wrong on some documents but not
others, or before adding a new engine/flag.

---

## Three layers, three questions, three settings

Conflating these is the root cause of most "my setting does nothing" reports.

| Question | Setting kind | Example |
|---|---|---|
| May this backend **load** at all? | resource gate | `OCR_PARSER_USE_PP_OCRV5` |
| Should this document bypass its **text layer**? | route | `OCR_FIRST` + provider allowlist |
| Which **engine** runs the OCR pass? | engine selector | `OCR_ENGINE` |

Resource gates are booleans about host capacity. Route is about document trust.
Engine is about quality. A resource gate is not a route selector — flipping it
changes what can load, never what is chosen.

**Both availability gates may be true at once.** They are independent, not
alternatives. Disabling one does not mean the other was preferred.

---

## `getattr(settings, "X", False)` means X does not exist

The single most expensive defect in this class. Reading a setting defensively
defeats the whole point of a declared schema:

```python
engine = "vision" if getattr(settings, "VISION_OCR_ENABLED", False) else "ppocr"
```

If `VISION_OCR_ENABLED` is absent from `Settings`, this expression is
**constant**. `.env` can say `true`, the operator can verify the file, and every
call resolves to the default. The parser then runs the *other* engine while the
log reports the route the operator asked for.

Rules:

- Declare the field on `Settings`. A field present only in `.env` is dead config.
- Assert it resolves: `getattr(settings, NAME) is not DEFAULT` under the real `.env`.
- Add a repo test that every non-comment key in `.env` exists in
  `Settings.model_fields`. That test is the general form of the bug and catches
  the next one, which will not be the same key.
- Settings exposed through the admin API need three places in sync — the field,
  the whitelist, and the admin `FIELD_META` — and drift between them is itself
  silent. Run the drift gate before every commit that touches them.

---

## A gate inside one dispatch branch governs only that branch

```python
if   pdf_type == "cid_fonts":  ...   # PP-OCRv5 / VL / CMap repair
elif pdf_type == "scanned":    ...   # <-- returns here
elif pdf_type == "native_small": ...
else:
    if OCR_FIRST: ...                # gate lives INSIDE this else
```

The gate is unreachable for `scanned`. That branch hardcodes its engine, so
every image-only PDF is OCR'd by whichever engine the branch names, and **no
setting can change it**. Measured: the affected branch was 77 of 195 queued
documents — and because a scanned PDF has no text layer to fall back on, the
hardcoded engine was also the one measured to misread Arabic article digits.

Read the dispatch as a table before trusting a flag: for each branch, which
engine does it call, and does any gate actually precede it? A gate is only as
broad as the code path that reaches it.

---

## One engine selector, shared by every call site

When engine choice is inlined at one call site and hardcoded at another, the
setting governs exactly one of them. Extract:

```python
def resolve_ocr_engine(value: str) -> str:
    """Interpret an engine setting value. Returns 'vision' or 'ppocr'."""
    return "vision" if str(value or "").strip().lower() in VISION_ALIASES else "ppocr"
```

- Put every interpretation of the setting value in this one function. Route
  branches and parsers call it; none re-derive it.
- Log the engine that actually ran, from the variable the branch used — not the
  configured value. The log line is how a future session learns the config is
  not what the operator thinks.
- An unrecognised value should degrade to the **cheap** engine and log it. A
  typo that silently selects minutes-per-page inference is worse than a typo
  that selects the fast path and is visible in the log.
- Keep accept-forever aliases (`qwen`, `qari`) mapping onto the current engine.
  They cost nothing and they stop a deployment rename from becoming a silent
  behaviour change.
- Preserve a **two-level fallback**: vision failure → cheap OCR at the route
  level, and model failure → layout-guided OCR inside the vision route. A
  degraded answer beats no answer for a citation corpus. This is a deliberate
  cost, not an oversight; do not "clean it up" into a single path.

Cache OCR output keyed by **content hash**, never by bare filename stem.
Providers reuse stems (`1.pdf` appears across domain folders), and a stem-keyed
cache collides across documents.

---

## `--force` is not "re-extract": parse state and the text cache are separate layers

A parser's skip logic and its page-text cache are two independent gates, and
`--force` opens only the first one. A run can delete every output JSON, reparse
every document, and still rebuild each article tree from the **same cached page
text** — no OCR, no VLM, no extraction. Read this before promising that a force
run re-reads a document, and before concluding that a parser fix changed nothing.

| Layer | Skip condition | What `--force` does | File |
|---|---|---|---|
| Parse state | status=`success` + content hash match | bypassed (returns `False, "force"` unconditionally) | `data/logs/<provider>_parser_state.json` |
| Output JSON | JSON exists (+ hash match) | deleted before the run | `data/corpus/<provider>/json/<lang>/**` |
| Extraction text cache | cache file exists | **not touched** | `data/corpus/<provider>/cache/<stem>_<hash12>.json` |
| Vision text cache | cache file exists | **not touched** | `data/corpus/<provider>/cache_vision/<stem>_<hash12>_vision.json` |

`<hash12>` is the first 12 hex of sha256 over the PDF's **first 4 KB** — a
deliberate fast key. Editing the PDF changes the key and forces a fresh
extraction; changing the cache format, the parser, or the engine does not.

To actually re-extract one document, delete both cache files — they share the
`<stem>_<hash12>` prefix, so glob on it. A provider whose *downloader* keeps its
own state (jurisprudence crawls HTML) does honour `--force` at that layer, via a
module-level `_force_mode` flag; that is a re-download, not a text re-extraction.

A cache hit is validated before it is served, and a rejected cache is unlinked
and re-extracted. The rejection gates are quality signals: garbled, reversed
Arabic, CMap-corrupt, language-route mismatch, cached OCR missing the document's
own reference, pre-linebreak legacy caches. A cached page list that looks fine to
a human passes all of them — so "stale but plausible" is the common case, and it
is the one `--force` cannot fix.

Verify which text a run actually used before theorising about the parser:

```python
import glob, json, os
for f in sorted(glob.glob("data/corpus/adala/cache/*.json"), key=os.path.getmtime)[-3:]:
    d = json.load(open(f))
    print(os.path.basename(f), d.get("mode"), d.get("language_hint"), len(d.get("pages") or []))
```

`mode` is the provenance field (`native` / `vl` / `docling` / `ocr_forced`). An
unchanged mode after a force run means nothing was re-extracted.

**Pitfall: a parameter accepted but never passed is a dead override.** A
`process(..., cache_dir=None)` that computes `_cache_dir = cache_dir or CACHE_DIR`
and then calls `extract_pages(pdf, CACHE_DIR, ...)` with the module constant has
an override that works nowhere. The shared extractor has no `force` parameter at
all — adding one is a change to the cascade, not to the caller. Before
advertising a bypass or a path override, grep for the parameter's **read** sites,
not its declaration: a local variable whose only occurrence is its own assignment
is dead code.

---

## Renaming a configuration key

- **Code and `.env` land in the same commit.** Splitting them leaves the old
  key unread, which silently defaults the model, base URL, and timeout — the
  exact `getattr` failure above, self-inflicted by the rename.
- **Check for substring collisions before a blanket replace.** Replacing
  `QARI_OCR_` also rewrites `ADALA_QARI_OCR_ENABLED` into a duplicate of
  `ADALA_VISION_OCR_ENABLED`. Pydantic silently keeps one field; a whole
  setting disappears with no error and no warning. `mypy`'s `no-redef` catches
  it — do not commit with that hook skipped.
- **Assert the code default, not the value you can see in `.env`.** They
  differ constantly. `git show HEAD:<file> | grep` the old declaration before
  writing the expected value into a test.
- **Rename production code before the tests that name it.** Renaming test
  fixtures ahead of the code they exercise produces failures that read as
  regressions and are not.
- Before renaming a value **persisted to disk**, grep for its readers. A
  write-only provenance field (written, never read back) can be renamed freely;
  one that a loader compares against cannot.
- When two flags collapse into one, confirm the merge is intended. Two flags
  that are OR-ed together may encode two separable decisions; collapsing them
  removes the ability to choose separately. Say which decision is lost.

---

## Verify before claiming

A settings diff proves nothing about runtime. Before reporting that a routing
change works, run the narrowest check that exercises the path end to end:

1. Resolve the settings object and print the effective values.
2. Confirm the log line names the engine that actually ran, on a real document.
3. For a speed-sensitive route, state the measured cost — minutes-per-page
   inference on a 4B VLM is orders of magnitude above a local OCR pass, and
   that ratio decides whether the queue goes to a cloud scanner instead.

Reporting "config verified" when only the config object was read is the failure
this section exists to prevent.

---

## Executing a rename plan task by task

A rename split across tasks will produce failures that look like regressions and
are not. Two rules, both learned the hard way:

- **Keep each commit internally consistent.** A task boundary that leaves code
  and its `.env` in different commits is a broken intermediate state, not a
  safe increment. When a plan defers part of a rename, move that part forward
  rather than shipping the gap.
- **Never apply a later task's names early, even in files you are already
  editing.** A blanket rename touches test fixtures too; pointing them at a
  symbol production code does not define yet produces a burst of failures whose
  cause is invisible in the traceback. Rename the production symbol first, then
  let the tests follow it.

**Establish a failure baseline before judging any result.** Run the affected
tests at the parent commit (stash the change), record which tests already fail,
then compare. A rename reporting the same failures before and after is clean
regardless of the count. Without the baseline you cannot tell a pre-existing
failure from one you caused — you will either chase a phantom or dismiss a real
regression as pre-existing.

Run the hooks. `mypy`'s `no-redef` is what catches the duplicate-field bug in
the rename section; a framework that silently drops one of two same-named
settings will not warn you.

---

## Prefix-probing reader helpers go dark on rename

A provider that inherits gates from another provider reads them through a
prefix chain:

```python
def _ism_setting(name, default=False):
    return getattr(settings, f"ISM_{name}", getattr(settings, f"ADALA_{name}", default))
```

The chain looks like it covers everything. It covers exactly two **prefixed**
names. The moment a rename produces a bare name — `VISION_ENGINE_ENABLED`, with
no `ISM_` or `ADALA_` prefix — the chain walks off the end and returns
`default`. The route goes dark for that entire provider, with no log line,
because nothing failed: the expression simply answered the question it was never
asked.

The declaration is not the deliverable. **Resolving the setting through each
reader is.** After a rename:

```python
# every reader, not just Settings
assert settings.VISION_ENGINE_ENABLED is True
assert _ism_setting("VISION_ENGINE_ENABLED") is True
assert _vision_engine_enabled() is True
```

When the bare name is intentional, add the tier and probe it explicitly:

```python
for candidate in (f"ISM_{name}", f"ADALA_{name}", name):
    if hasattr(settings, candidate):
        return bool(getattr(settings, candidate))
return default
```

### The test that should have caught it, and did not

```python
assert _ism_setting("X") == settings.X        # PASSES with the route disabled
assert _ism_setting("X") is True              # catches it
```

The first form compares two views of the same broken lookup — the defect is in
the resolution path, so both sides inherit it. Any test whose expected value is
derived from the same source it is testing is vacuous. Assert the **intended
truth** (`is True`), never agreement between two reads.

Use a stub object rather than `monkeypatch.setattr` to test tier *order*:
`Settings` is a pydantic model and refuses to have an undeclared attribute set,
so the test fails on the fixture rather than the behaviour.

---

## Keeping renamed keys working: `AliasChoices`, not a before-validator

With `extra="ignore"`, an old key is dropped without error and the new field
keeps its default. The obvious migration — a `model_validator(mode="before")`
that renames keys in the incoming dict — **breaks the framework's own source
precedence.** That validator receives init kwargs and `.env` already merged, so
it cannot tell them apart, and its "new key wins" guard then overwrites an
explicitly-passed constructor argument with the `.env` value.

Use `validation_alias`, which resolves per source:

```python
VISION_OCR_MODEL: str = Field(
    "default",
    validation_alias=AliasChoices("VISION_OCR_MODEL", "QARI_OCR_MODEL"),
)
```

List the **current** name first: the first match wins at every priority level,
so the live key always beats the legacy one.

**A type change needs a validator too.** Aliasing a bool onto a str field copies
the value verbatim, giving `OCR_ENGINE="True"`, which the engine resolver does
not recognise and maps to the *other* engine — the alias looks like it works
while selecting the wrong thing. Pair it:

```python
@field_validator("OCR_ENGINE", mode="before")
@classmethod
def _normalize_engine_value(cls, value):
    if isinstance(value, bool):
        return "vision" if value else "ppocr"
    if isinstance(value, str) and value.strip().lower() in ("true", "1", "yes", "on"):
        return "vision"
    return value
```

Two guards on the alias table itself: no legacy name may also be a live field,
and every name in the table must actually appear in some field's `AliasChoices`
— otherwise the table drifts into a list of comments that silently does nothing.

Verify the upgrade path against a **real pre-rename config in an isolated
directory** (temp dir, old `.env`, `os.chdir`), not just unit assertions. That
is the only check that proves an operator who edits nothing still gets the
behaviour they had.

---

## Dead vs live-but-inert: classify before you touch an undeclared key

A sweep for undeclared `.env` keys returns a mixed bag. Deciding per key:

| Evidence | Verdict | Action |
|---|---|---|
| No reader in any form | **dead** | Delete from `.env` and `.env.example` |
| Read via `getattr(settings, X, None)`, applied only when not `None` | **live-but-inert** | **Declare it**, keep the `None` default |
| Read via `getattr(settings, X, default)` and used directly | **declared under another name** | Fix the reader |
| Out of scope for the rename (different subsystem) | **out of scope** | Comment with the reason; do not delete intent |

The middle row is the one that matters. A key set in `.env`, read with a `None`
sentinel, and never declared is a switch the operator set that has never fired —
indistinguishable, from the outside, from one that works. Declaring it must keep
the sentinel as the default: a `bool` default of `False` would silently disable
the capability for every deployment that had not set the key.

The sweep also finds keys deleted from `.env` in an earlier change but left in
`.env.example`. Check both files, and check them in both directions.