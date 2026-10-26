# Provision Content-Coverage Audit

How to tell whether a parsed legal JSON is actually usable, when every field it
reports about itself is self-consistent and clean.

## Why a counter cannot validate the tree it came from

`num_articles_detected` is computed **from** the `structure` tree. So comparing
the field against the node count is a tautology: it holds identically on a sound
document and on one whose provisions are empty shells. The same applies to
`num_chapters_detected`, and to any flag derived from the same walk
(`has_article_structure` is true as soon as one node exists).

**A self-consistent document can still be structurally gutted.** Measured on a
207-page Moroccan code (vision OCR, both caches resolving,
`structure_degraded: false`):

| Signal | Value |
|---|---|
| `num_articles_detected` | 700 |
| tree provisions | 700 = 561 `chapter` + 139 `article` |
| **empty-shell provisions** | **499 (71%)** |
| merged nodes (content holds >1 provision header) | 48 |
| duplicated provision numbers | 50 (`الفصل 1` in 29 separate nodes) |
| nodes touching a compound header (`الفصل N-M`) | 131 |
| source provisions absent from the tree | 81 |

Counter/tree agreement was perfect. The document was unusable for
article-level retrieval or citation.

## The three metric families

### 1. COVERAGE — does each provision carry text?

`empty_shell` = a node whose `type` is `chapter` or `article`, whose `content`
is empty after `.strip()`, **and** which has no `children`.

A container that is empty but *has* children is normal (the text lives in the
children). Only the childless empty node is the defect.

### 2. INTEGRITY — is the numbering sane?

- **merged node** — a node whose `content` contains more than one distinct
  provision header. Measured worst case: one node carrying 35,320 chars across
  11 headers.
- **duplicated provision number** — the same number on more than one provision
  node. Legitimate in a code that restarts numbering per scope, so read it
  together with the hierarchy: the same number appearing as both `chapter` and
  `article`, or repeating at the same depth under the same parent, is a
  collision, not a per-chapter restart.
- **compound header** — a node whose title or content head matches
  `(?:الفصل|المادة)\s*\d+\s*[-–]\s*\d+`. A code that mixes base provisions
  (`الفصل 1..610`) with inserted compound provisions (`الفصل 36-6`) is the
  collision-prone shape: a header regex that captures only the leading integer
  maps `الفصل 36-6` onto `36` and collides with base `الفصل 36`.
- **phantom title** — title matching `^(?:الفصل|فصل|المادة)\d+$` (keyword
  glued to the number, no space — the OCR glue signature).
- **long title** — title longer than ~100 chars: body text absorbed into the
  title field.

### 3. LOCATION — lost or misplaced?

This is the decisive question, and it decides which fix is even possible.

For each provision header found in the source text the parser consumed, take a
distinctive ~40-char slice of the body that follows it, then search the
**concatenation of every tree node's `content`**:

| Result | Meaning | Fix |
|---|---|---|
| present in the tree | **MISPLACED** — the text survived, attached to the wrong node | structure repair / re-parse; text is recoverable |
| absent from the tree | **LOST** — the text never reached the tree | text-source gap; re-OCR or a different source |

Report the **retention ratio** beside both counts. "89.5% retained but in the
wrong nodes" and "89.5% retained and correctly placed" call for opposite fixes,
and a high retention ratio sitting next to a high empty-shell count is itself
the proof that the defect is placement, not loss.

## Reading the combination

| empty-shell ratio | retention | reading |
|---|---|---|
| high | high | text is present but misplaced — a structure/identity defect |
| high | low | text genuinely absent — an OCR or source defect |
| low | high | healthy |
| low | low | few provisions declared; check the document has numbered provisions at all |

Two further discriminators on an empty shell:

- title well-spaced (`الفصل 36`) → misplaced-content or compound-collision
  symptom
- title glued (`الفصل36`) → the phantom-node class

## Running the probe

```bash
python scripts/provision_text_coverage_probe.py <parsed.json>
# explicit source text, when auto-resolution picks the wrong cache:
python scripts/provision_text_coverage_probe.py <parsed.json> --source-cache <cache_vision/...json>
# bound the scoring cost on a large document:
python scripts/provision_text_coverage_probe.py <parsed.json> --sample 100
```

The source text is resolved from the JSON's `structure_text_cache` field, else
from the `cache_vision/` or `cache/` sibling of the corpus root. The probe
prints which file it graded against and that file's `mode`/`source` — never
score against a source you cannot name.

The script exits 0 and prints a verdict; read the output rather than the exit
code.

## What not to conclude

- **Do not report a shortfall from the counter.** The counter is the thing under
  audit. Report empty-shell counts and retention instead.
- **Do not assume a high empty-shell count means the text was lost.** Run the
  location pass first — the common case is that the text is present in the tree
  and attached to the wrong node.
- **Do not assume a contiguous run of missing numbers is a defect.** A
  contiguous run is often a repealed block or a range label; see rule 0z.
- **Do not treat duplicated numbers as duplicate articles.** In a code they are
  usually an identity collision (compound label truncated to its leading
  integer), which means two *different* provisions are sharing one number.
- **Do not read a zero delta after a re-parse as proof the fix failed.** A
  re-parse rebuilds the tree from the same cached text, so an unchanged result
  is the stale-text signature; compare the JSON's `timestamp` against the cache
  file's mtime first (rule 0ad).

## Related

- `references/article-header-detection.md` — the compound-label identity rules
  the integrity metrics above are symptoms of.
- `references/cache-resolution-audit.md` — resolving which cache file a JSON
  actually depends on.
- `scripts/adala_ar_audit.py` — corpus-wide version of the coverage and
  integrity metrics.
