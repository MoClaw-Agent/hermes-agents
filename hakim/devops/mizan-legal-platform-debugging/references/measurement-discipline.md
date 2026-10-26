# Measurement discipline — counting, probing and regression

Depth for the counting and verification traps that recur while debugging
article extraction. The governing rule lives in
`references/extraction-integrity.md`; this file is the how.

## Reconcile article counts in the unit the parser emits

Four different numbers describe the same document, and **none is automatically
the true source count.** Measured on a 16-page code whose JSON emitted 25
articles:

| Measure | Value | Comparable? |
|---|---|---|
| JSON emitted articles | 25 | the target |
| unique article NUMBERS from exact `المادة N` headers | 28 | **no — undercounts** |
| lines matching exact `المادة N` | 47 | closest, minus duplicate lines |
| `is_article_line` hits | 81 | no — inflated by non-articles |
| total occurrences of the word `المادة` | 68 | no — includes inline cross-references |

**Deduplicating by number is wrong and it inverts the error.** That document
had **44 printed articles** (user's visual read) but only 25 distinct numbers,
because the code restarts numbering per chapter — `المادة 41` sits under the
الفصل 3, 4, 5 and 8. Comparing 25 against 28 produced a confident "shortfall
of 3" when the real shortfall was 19 (43%). Unique-number counting collapses
exactly the articles a document-global dedup also collapses, so it hides the
defect instead of exposing it.

Anchor the count on **headers within their enclosing scope**, and expect a
document's article count to exceed its distinct number count whenever numbering
restarts. Before reporting any shortfall, confirm against the user's read of
the rendered page — the text layer is itself a suspect artifact here.

Chapter headers inflate the source count: `الفصل 1` … `الفصل 9` are numbered
1..N exactly like articles and collide in any set comparison. **Exclude chapter
markers from the source count** before computing a shortfall. When the user's
count disagrees with yours by a wide margin, decompose both sides before
concluding the parser is at fault — an unexplainable mismatch is more often a
unit mismatch than a defect.

## Self-test a probe regex against hand-written cases before trusting its count

Three separate corpus "findings" in one session were artifacts of the probe,
not of the corpus. Each produced a confident number that was wrong:

| Mistake | Consequence |
|---|---|
| Wrote the keyword as a character class `[الفصلالبابالقسم]` instead of an alternation `الفصل\|الباب\|القسم` | Matched stray `ا`/`ل` characters; reported **92.4% of headers missed** across 145k phantom hits |
| Excluded only Arabic-Indic digits from a gap class `[^٠-٩]` | `الفصل 114` parsed as gap=`1`; reported a nonsense separator distribution |
| Judged the regex by its corpus output rather than known inputs | Would have shipped the `+` vs `*` regression below |

**Rule: every regex that produces a number gets a self-test block first, run
before the corpus loop**, with hand-written `(input, expected)` cases covering
each shape you intend to match and at least two you must NOT match:

```python
CASES = [
    ("الفصل.1", "."), ("الفصل..1", ".."), ("الفصل 4", " "),
    ("الفصل114", ""),          # no separator — catches + vs *
    ("الفصل\n1", "\n"), ("المادة.7", "."),
    ("هذا الفصل. ثم نص", None),  # must NOT match
    ("نص عادي دون الفصل", None),
]
```

Two lessons the self-test also teaches: write your *expected* values honestly
(a space separator is a match, not a miss — sloppy expectations produce false
alarms that mask real ones), and prefer writing expectations **derived from the
rule** over hardcoding them, or the test re-encodes your mistake.

## Attribute test failures by stashing the change and diffing FAILED sets

Never decide whether your change broke something from the pass/fail count
alone. Stash, re-run, and set-diff the failure lists:

```bash
pytest tests/ -q --no-header -p no:cacheprovider 2>&1 | grep '^FAILED' | sort > before.txt
git stash push <file> -m wip && pytest tests/ -q ... | grep '^FAILED' | sort > after.txt
git stash pop
comm -13 before.txt after.txt   # introduced by my change
comm -23 before.txt after.txt   # fixed by my change
```

On a 3,726-test suite with ~90 pre-existing failures (RAG/embedding tests
needing network and model services), this is the only way to see that a change
introduced **0** failures. Check that a new regression test *fails* with the
fix reverted — a test that passes both ways validates nothing.

Never `git stash` while a live test run is importing those files: it swaps
source out from under the run and can strand your work in the stash when the
process is killed. Recovering work outranks finishing a measurement. Store
baselines outside `/tmp`, which can be cleared mid-session.

## An early-return nested in a repair branch silently disables caching

The most expensive defect found in this codebase was three lines of control flow.
A cache hit was read, validated, and then dropped, because the `return` sat
**inside** the branch that handles masthead repair:

```python
if pages and any(masthead_problem(p) for p in pages[:3]):
    repaired = repair_extracted_pages(pages)
    if repaired != pages:
        pages = repaired
        return pages, mode, tables        # <- only return path
pages = None                               # <- clobbers the cache we just read
```

Every document re-extracted on every run; one page went from 105 s to 0.00 s once
fixed. Nothing errored, no log line looked wrong, and the output file was written
correctly every time — the cache simply never did anything.

**Rule: a cache contract is `valid → return`, `invalid → fall through`, and that
decision belongs in ONE place.** Any `return` inside a conditional branch that is
not the validation decision is a silent cache killer.

The instructive half is the wrong fix. Dedenting the `return` so a valid cache
always returns is necessary but not sufficient: when validation *did* fail,
`pages` and `mode` still hold the rejected values, so that version returned
exactly the content the validator had just refused. The fix is:

```python
if not should_invalidate:
    # optional repair, applied in place
    return pages, mode, tables
# invalidated -> fall through to full re-extraction
```

Test all three paths, not just the happy one — valid hit returns fast,
invalidated falls through, corrupt/unreadable cache does not raise. Each of those
caught a different real defect here.

## Test fixtures must satisfy the validator they are testing

A stub fixture that is *correctly* rejected proves nothing. Three false
conclusions came from fixtures that did not meet the code's own quality gate:

- A stub cache of three stub pages was invalidated by `ocr_missing_own_ref`, so
  the test reported "the fix does not work" while the code was fine. Real cached
  OCR pages contain `رقم N` references; the stub did not.
- A fixture written to `<stem>.json` when the cache key is `{stem}_{hash}.json`
  was never read at all, so the test silently exercised the re-extract path and
  "passed" against the wrong code.
- A byte-string stub passed to a function that decodes and downsizes images
  raised `UnidentifiedImageError` — a test-construction error that read as a
  product failure.

Before trusting a negative result, confirm the fixture reaches the branch you are
testing. Assert against the cache path/key the function actually uses, and log
the fixture identity so a never-read fixture is visible.

## When a verification harness errors, it has disproved nothing

Three checks returned `FAIL` because the harness raised — wrong dataclass
constructor kwargs, wrong enum values, a missing import. Reporting those as
"BROKEN, claim does not hold" was wrong: an errored check is not a refutation.

Distinguish three outcomes explicitly, and fix the harness before reading any
verdict: `ok` (claim holds), `disproven` (ran, claim false), `errored` (unknown).
Also check that *expectations* are derived from the rule rather than hand-written
— asserting "fires for SGG = False" in a test that had just configured
`OCR_FIRST_PROVIDERS=ism,sgg` inverts its own premise, and asserting a real
`error="boom"` string should be *absent* from a dict is simply wrong. Both
produced misleading failures here.

## Verify every premise in a plan before executing it

A plan you wrote is a hypothesis set, not an instruction set. When told to
execute it, the unverified items get laundered into "fixed" — the work is done,
the diff is clean, the suite passes, and the wrong premise is now embedded in
code.

This session's plan contained two such items. One was **fabricated**: a claim
that `quality_validation.py` emitted the wrong error code, produced by reading
a truncated window that cut mid-block. One was **impossible as stated**: the
detector could not be extended to dotted references, because a swapped `19.94`
and a correct `19.94` are both well-formed — the fix would have been an
over-confident heuristic that failed silently in production.

**Run the verification pass as its own step, before the first edit.**

For each item, produce an executable claim — a script that prints what the code
actually does — not a prose one. Classify each outcome three ways:

| Outcome | Meaning | Action |
|---|---|---|
| holds | claim confirmed by running it | implement |
| disproven | ran, claim is false | strike the item, say so |
| errored | harness raised | unknown; fix the harness first |

An `errored` item is the dangerous one, because it is easiest to misread as
`disproven` and then to skip silently.

**Write the plan's corrections into the artefact, not just the reply.** A plan
file that keeps a retracted finding will mislead the next session that reads it.
When items are struck, replace the file with a status document that carries the
corrections and points at the verified detail.

**A fix list built on unrun claims inherits their errors.** Two items in this
session's plan had to be re-scoped after execution began — one moved from the
parser to the OCR boundary, one was deleted outright — because the premise had
never been tested. Discovering that during execution costs a re-do; discovering
it before the first edit costs one script.

## When a probe contradicts an established suite, suspect the probe first

A self-written harness is the least reliable component in the chain, because
nothing else checks it. A probe rebuilt from codepoint escapes reported **every**
case as failing — including cases the same suite had proved green minutes
earlier — and that output nearly caused a measured fix to be reverted. The
defect was the probe's input, not the product code.

**Never revert a proven-good change on the evidence of an unrun probe.** That
trades a known-good change for an unknown one, and the reversal is invisible
until much later. Re-derive the input from the source artefact and re-run before
changing anything under test; if the probe and the suite still disagree, print
the raw text around the first marker and read it.

Generalises to any change made this session: a fixture that does not reproduce a
failure you already observed is a fixture problem, not evidence about the code.

Building correct fixtures (extract strings from the corpus rather than typing
them), keeping two entry points of a `str | list[str]` function in agreement,
and refusing to compare counts taken from differently-shaped inputs are all
covered in the `corpus-quality-audit` skill — see its always-on rules 0e and 0g
rather than restating them here.

## Re-verify a claimed defect against the file before reporting it

A reported defect that turns out not to exist costs more than a missed one: it
sends the operator to fix correct code, and the correction has to be public.
Before stating "this line emits the wrong error code", read the line with enough
context to be sure of its indentation and neighbours — a truncated window around
a similar-looking block produced a confidently fabricated finding here, and the
response to it was "re-verify".

Two habits catch this cheaply:

- Re-read the exact line with `grep -n` and a couple of lines of context before
  naming it in a report.
- Prefer an executable claim over a prose one. `sed -n '150,154p'` to see a
  branch, then a two-line script that prints what the branch actually emits,
  costs seconds and cannot be misread.

When a finding is retracted, say so plainly and name what produced the error.
The operator needs to know which other claims from the same batch deserve the
same scrutiny.