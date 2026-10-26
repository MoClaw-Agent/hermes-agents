## Pitfall: Articles Silently Dropped by build_tree Dedup

Two distinct causes, both verified by worktree testing:

### Cause 1 — the dedup key is document-global, not per-scope

`seen_articles` is keyed on `(art_num, inserted)` alone, so it carries no scope information. An article in a later chapter is dropped when the same number appeared in an earlier one.

**Corpus-wide effect, measured by running `build_tree` over every PDF's page list (no OCR, no LLM, ~16 s):** articles em

Verified by diffing `FAILED` sets against a worktree at the parent commit (see below): 3,726 tests, **0 new failures**.

**Direction of error flips after the fix — expect over-detection, not loss.** The same 16-page code then reached 52 articles via `build_tree`.

### Cause 2 — the dedup key is built on WRONG numbers

The text layer's digit font is corrupt. This is **glyph substitution in the embedded digit font**, not footnote glue. It is also *not* a consistent per-digit map — `2` maps to both

Confirmed in **three files across three domains** (render + vision read): `ism/…/droit_penal/1.pdf` p4 `المادة511` → pri

**A "missing article" here is not a missing article — it is a misnumbered one.** Report it as wrong data, not as a count

Read each PNG with vision, then **solve for a per-digit substitution map across several pairs before writing any repair**

Two cropping traps that produce a false "no corruption" read: `get_text("words")` **splits** a header like `المادة511` i

Broken RTL digit maps emit a **period run where a space belongs**: `الفصل.1`, `الفصل..1`, even `المادة.7`. `_AR_ARTICLE_HEADER_RE` handles this.

### TOC page detection (LANDED) — density alone is not enough

### Detection defect: `\s*` between keyword and number misses period-separated headers

### Self-test a probe regex against hand-written cases before trusting its corpus count

### Attribute test failures with a worktree, never a stash

### Screen the corpus BEFORE committing to a long parse

### Two distinct corruptions need two different responses

| Year tokens hit, **Arabic ratio high** (>25%) | Prose readable, digits wrong | OCR/vision re-read of numbers; prose is |
| **Arabic ratio ~0%** | Text layer fully scrambled (`الوادج11 ٠غت أْ`) | Nothing to preserve — needs OCR from scratch |

### Automatic detectors that do NOT work — measured, do not re-try

### DEAD END — do not re-attempt: re-reading digits by template matching

The idea: the prose text layer is intact and only digits are wrong, so render the digit run from the page and template-m

**Do not plan around hand-labelling dozens of crops.** Vision calls are rate-limited to roughly one per several minutes,

- **Contact sheets render blank.** Building one page per N crops via `page.insert_image(...)` produced empty image slots
- **Batching multiple crops per vision call** is the only way to make labelling tractable, and it needs the montage to a

**The remaining trustworthy option is real OCR/vision on rendered pixels** — it is the only method verified end-to-end h

### Reconcile article counts in the unit the parser emits

Four different numbers describe the same document, and **none of them is automatically the true source count.** Measured on a 16-page code w

  bare-digit lines        : 16   <- page markers, years, footnote refs

### `article_order` disqualifies a document independently of its count

### The quality gate prints a verdict without protecting the filesystem

Validation runs **after** the JSON is written (in the ISM pipeline, write near line 1164, `validate_document` near line