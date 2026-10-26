# Measuring a parser change before shipping it

Depth for the class of work "change the structure parser, then prove the change
is safe". The always-on rules live in SKILL.md; this file holds the harness,
the metric set and the classifier.

## Why the measurement is mandatory

Every fix that removes a phantom class also removes *something*. A guard that
drops a table, a citation or an OCR-glued header can equally drop a real
provision. The only thing that separates the two is a measured diff over the
corpus — not a spot check, and not a passing test suite (the suite is small
relative to the corpus).

## The metric set

For each document, over the same input, report:

| metric | why it matters |
|---|---|
| `provisions` | total provision nodes — must not collapse |
| `unique` | DISTINCT provision numbers — the number that matters |
| `real_lost` | numbers present before and absent after, where the document prints the number as a SPACED header — blocking |
| `artefact_lost` | numbers present before and absent after, where the number only ever appears GLUED — removable |
| `retention` | kept flat-article chars / source chars — a drop here means text left the index |
| `phantom` | nodes matching the defect signature you are fixing (e.g. strict-glue chapters, pipe-titled provisions) — must fall |

`unique` matters more than `provisions`: a duplicate node for a provision that
also exists genuinely is a phantom, and removing it lowers `provisions` while
`unique` stays flat. Retention catches the failure mode where the fix removes
nodes but the text is now unreachable.

## Step 1 — baseline the current behaviour

Run the real functions over the real caches, not over a reconstruction:

```python
from fetching.pipeline_base.structure import build_tree
from ingestion.pre_converters.helpers import _flatten_adala_structure

tree = build_tree(pages, document_language="ar")
flat = _flatten_adala_structure(tree, None)
```

The provider's own page selection must run first when the JSON was built from
a selection between layers (see the pitfall below).

## Step 2 — measure candidate POLICIES side by side

When a fix changes a *signal* rather than a rule (which text source wins, what
counts as a provision), enumerate the candidate policies, run all of them
over the same corpus, and let the metrics choose. Worked example from the
citation-signal fix, over 144 documents:

```
policy   provisions  unique  glue   retention
P0 (current)      31.4    27.8  1.7      0.9373
P1 (glue never counts) 31.0 27.6  0.2      0.9448
P4 (glue + citation-tail check) 31.4 27.7 1.3  0.9383
```

P1 removes the most artefacts but the tail check alone (P4) keeps every real
provision — the difference between the two policies is what the classifier in
step 3 measures. Ship the policy the classifier clears, not the one with the
best headline number.

## Step 3 — the two-root diff and the REAL/ARTEFACT classifier

Materialise the committed tree, run the SAME probe against both roots, and
classify every number the diff reports as lost.

```python
SPACED = re.compile(r"^\s*(?:الفصل|فصل)\s+\d+\s*$")

spaced = set()          # numbers the document prints as a spaced header
for page in pages:
    for line in page.split("\n"):
        if SPACED.match(line.strip()):
            for tok in re.findall(r"\d+", line):
                spaced.add(int(tok))

lost = before_numbers - after_numbers
real_lost     = lost & spaced          # blocking
artefact_lost = lost - spaced           # removable
```

`scripts/compare_parser_roots.py` runs this end to end over the corpus.

The classifier is the load-bearing step. Without it the same diff reads as
"4 provisions lost" and gets reverted; with it the same diff reads as "0 real
lost, 4 artefacts" and ships. Real example: four numbers disappeared from
one document and all four turned out to exist ONLY inside a cross-reference
table row — the real provisions were elsewhere in the document and survived.

## Step 4 — leave a guard that fails under the old behaviour

Every shipped fix gets a regression test whose assertions fail on the
pre-fix code: assert the phantom class is ABSENT (not merely that the count
changed), and assert a known-good provision SURVIVED. Copy the fixture lines
from the real cache rather than hand-typing them — a hand-typed Arabic
fixture drifts from the data and stops reproducing the defect.

## Pitfalls

- **A probe that rebuilds from one layer alone does not reproduce the
  pipeline.** The JSON on disk was built from a SELECTION between the vision
  and native layers. Call the provider's selection function inside the probe,
  or the diff reports provisions the pipeline never dropped.
- **`glob.glob(..., recursive=True)` does not descend into a symlinked
  directory.** Symlinking the untracked corpus into a scratch root makes the
  probe find nothing and report "no documents". Pass the corpus root as an
  argument.
- **A detached test run reports the LAUNCHER's exit code.** A green exit code
  can hide an OOM-killed pytest. Read the log.
- **A synthetic example in a finding is not evidence the shape exists.**
  Search the corpus for the real shape before building a fix.
- **Count with the strictest pattern that still matches, and state it next
  to the number.** A loose pattern conflates real spaced headers with
  OCR-glued ones and inflates the rate several-fold.
- **Do not accept "the test suite is green" as the safety argument.** Run the
  corpus diff; the suite is a necessary condition, not the sufficient one.
