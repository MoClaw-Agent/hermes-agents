# Mizan — Pitfall library

Extracted verbatim from `SKILL.md` (which had grown past the 100,000-char
write limit).  Each entry is a defect that actually shipped, with the
diagnostic that catches it.  Load this file when a symptom matches a title
below.

## Index

- OCR Quarantine MOVES PDFs Out of raw/
- A Setting That Gates a Branch Is Inert Until Every Branch Honours It
- Enforcing a Flag in the Wrong Layer Bypasses the Layer That Guards Quality
- Never Run a Parse, Test, or Batch Without Explicit Permission
- Compare the Two Providers Side by Side When One Is Missing a Feature
- Never Write Derived Artifacts Into a Directory Enumerated as Source
- Add Config as a Real Settings Field, Not a getattr Fallback
- Crawler Dedup That Keys on State Duplicates Every File After a Re-crawl
- Verify the Extraction Classifier on a Path, Not a Page List
- A Domain Filter Must Name a Value the Corpus Stores
- An Inferred Domain Must Never Hard-Filter Retrieval
- Qdrant Timeout in Cross-Document Reference Expansion
- Temporal Filter Config Leaking into MatchValue
- Page-Filtering Regex Missing Article Header Variants
- Articles Silently Dropped by build_tree Dedup
- SGG BO Parser Quality Gap vs ADALA
- API Quota Exhaustion Returns Silent Empty
- Verify Ingestion Before Debugging Ranking
- Pre-Converter Cache Loading by Stem+Head-Hash Serves Wrong Content Across Domains
- Hierarchical Retriever article_number Type Mismatch
- Verify the OCR Text Before Blaming the Parser
- A Patch Containing `\x00` Writes a Literal NUL Byte and Breaks the Module
- A Failed Patch Can Leave the File Completely Unchanged
- There Is No Scalable Visual Verification for This Corpus
- A Reader That Keys on a Field the Corpus Does Not Use Drops Everything
- A Delegated Audit Can Damage the Live System
- A Code Fix Does Not Change the Live Index

---

## Pitfall: OCR Quarantine MOVES PDFs Out of raw/

With `OCR_QUARANTINE_ENABLED=true` in `.env`, a PDF whose text layer yields ~0 chars is **moved** (not copied) from `data/corpus/<provider>/raw/<lang>/<domain>/` into `data/corpus/<provider>/ocr/<lang>/ar/<domain>/`. Note the doubled `ar` segment — the quarantine path appends the lang dir again on top of the base dir, so the layout does not mirror `raw/`.

This is a **destructive side effect of running a parser**, and the parse log only reports it as a `[QUARANTINE]` warning plus a `[SKIP] … (OCR quarantine)`.

**Always diff the file count before and after a batch and report the delta to the user:**
```bash
find data/corpus/<provider>/raw -name '*.pdf' | wc -l
find data/corpus/<provider>/ocr -name '*.pdf' | wc -l
```
A `raw/` count that dropped without the user asking is a finding to surface, not bookkeeping. Moving them back is a plain `mv` preserving the `ar/<domain>/` suffix.

## Pitfall: A Setting That Gates a Branch Is Inert Until Every Branch Honours It

A flag read inside one arm of a dispatch chain is not a policy — it is a policy for the
branch that happens to contain it. Measured: `OCR_FIRST_PROVIDERS=ism,adala` did nothing
for ADALA, for two independent reasons.

**1. Placement.** `_ocr_first_enabled_for()` was called only inside the final `else:` of
the extraction cascade. The three arms above it — `cid_fonts`, `scanned`, `native_small` —
never consulted it. Classify a real sample of the corpus against the dispatch to see which
arm your data actually takes:

```python
from collections import Counter
from fetching.pipeline_base.pdf_quality import _classify_pdf
from pathlib import Path
c = Counter(_classify_pdf(p, language_hint="ar") for p in list(root.rglob("*.pdf"))[:300])
print(c)   # measured: cid_fonts 299, scanned 1  → the gated branch was never entered
```

When one arm dominates, the reading that matters is **which branch your documents take**,
not what the gate's branch is called.

**2. Identity from a path string.** The gate inferred the provider from the filesystem:
`parts.index("corpus")` then the next segment. Any layout that is not literally
`corpus/<provider>/…` fails it — `corpus_consolidated/ar/adala__…pdf` has the provider
only in the *filename*, so the lookup returned False for every file and the flag was
skipped silently. Assert the gate directly on the real paths before concluding anything
about it:

```python
gate(Path("data/corpus_consolidated/ar/adala__x.pdf"))   # False  ← the bug
gate(provider="adala")                                    # True   ← the fix
```

**When a flag is "not working", confirm it fails for the reason you think.** Two causes
here were each sufficient on their own, and fixing only the first would have looked like
success while the flag stayed inert. Pass identity explicitly wherever the caller already
knows it; inferring it from a path couples a setting to a directory convention that will
change.

**Related — forcing a backend must resolve the engine through the same config the normal
path uses.** A "fix" that forces OCR by calling `_paddle_ocr_pages` directly bypasses the
provider's configured vision route, and PP-OCRv5 is documented in this codebase as
dropping Arabic article-header digits (`المادة 109` → `المادة9`). Forcing a route is not
choosing an engine; resolve it, then force it.

## Pitfall: Enforcing a Flag in the Wrong Layer Bypasses the Layer That Guards Quality

Each provider owns a native-first gate that escalates to its configured vision OCR and
then validates the result before letting it win. Setting a distrust-the-text-layer flag
there is safe. Setting it in the shared extraction cascade above the dispatch is not: it
short-circuits the engine selection *and* the post-hoc validation that decides whether the
OCR output is usable at all.

```python
# provider parser — reaches the configured vision engine, still validated
if mode in ("ocr_forced", "ocr"):
    native_usable = False
if _ocr_first_enabled_for(provider="adala"):
    native_usable = False
```

Enablement is not ordering. A structure-sufficiency gate measures *shape*, not
*correctness* — a text layer can carry every article and still have wrong digits — so a
"looks fine" layer can pass a gate whose job is to catch exactly that.

## Pitfall: Never Run a Parse, Test, or Batch Without Explicit Permission

This user asks to review plans before they execute and has twice stopped a run that was
launched on inference rather than instruction ("stop", "wtf are you doing"). Treat "parsing
X now" as ambiguous until the scope is agreed, and prefer asking over proceeding:

- Before a parse, test, batch, or audit — say what it will touch, how long it takes, and
  ask. Do not launch it into the background and report afterwards.
- A long-running OCR batch on a CPU-bound host is *minutes per page*; launching one
  unasked can occupy the machine for hours.
- "Execute" covers the specific step discussed, not the next thing you had planned.
- After a stop, do not resume, substitute, or relaunch. Report state and wait.

Prefer a cheap read-only check first and say what it would find.

## Pitfall: Compare the Two Providers Side by Side When One Is Missing a Feature

The same capability is often implemented for one provider and absent for another, and the
gap stays invisible until you read both call sites. Measured: ISM passed a `cache_path` to
`extract_vision_pages`, ADALA did not — so ADALA's vision output existed only in memory.
Every re-parse re-OCR'd every page, and a vision-derived ADALA document recorded nothing
about which text built its structure, leaving the extraction cache as the only file to audit
— which holds the *native* text, not the text the tree was parsed from.

Diff the providers when either misbehaves or a new capability lands:

```bash
grep -n "extract_vision_pages" fetching/ism/parser/pipeline.py fetching/adala/parser/pipeline.py
```

Parity checks worth running per provider: vision-cache persistence, `structure_source` /
`structure_text_cache` in the output dict, sidecar ingestion, retry configuration.

Two rules follow from adding the missing half:

- **Cache keys must be collision-safe, and a sibling's scheme is not a safe template.** A
  bare stem collides wherever filenames repeat — measured over one corpus, 3 colliding
  stems covering 7 files, where the sibling's scheme was safe only because its filenames
  happened to be unique. Reuse the content-hash convention the extraction cache already
  uses, so the two caches cannot overwrite each other either. A surviving collision between
  byte-identical files is correct behaviour, not a defect — confirm with a full hash.
- **Ship the provenance fields with the cache, not later.** A cached result nobody can trace
  back to is not auditable; the flag and the path are what make the artifact evidence.

## Pitfall: Never Write Derived Artifacts Into a Directory Enumerated as Source

Any pipeline step that writes an intermediate artifact must write it **outside** the tree that later steps glob for input. Writing beside the source turns the artifact into source, and the next run processes it again.

The CMap repair step is the canonical case: `auto_repair_pdf` wrote `<stem>_mapping_repaired.pdf` next to the original, i.e. inside `data/corpus/<provider>/raw/<lang>/<domain>/`. Every parse run `rglob`s that tree, so each repair was ingested as a source PDF, repaired again, and written again — `N_mapping_repaired.pdf`, then `N_mapping_repaired_mapping_repaired.pdf`, indefinitely. Measured on one corpus: **30 artifacts, 45.6 MB**, with three distinct files sharing the name `1_mapping_repaired.pdf`, all inflating the parser's work list with non-source documents.

**Fix shape:** route derived output to a sibling directory (`data/corpus/<provider>/repaired/<lang>/`) and reject re-processing your own output (suffix guard). The fallback for paths with no `corpus/` layout must still climb *out* of the `raw/` subtree rather than falling back to `parent/repaired`, which is still inside it.

Detection, after any run that touched the corpus:

```bash
find data/corpus/<provider>/raw -name '*_derived_*' | wc -l   # must be 0
```

The general test: **does the pipeline enumerate this directory as input? If yes, nothing derived may be written into it.**

## Pitfall: Add Config as a Real Settings Field, Not a getattr Fallback

When adding a setting, declare it in the settings mixin as a typed field and read it directly. A `getattr(settings, "NEW_FLAG", default)` fallback compiles, passes a naive test, and is **silently unreachable in production** — the fallback always wins because the field does not exist, so the feature can never be enabled by anyone.

```python
# WRONG — the field does not exist, so 'openai' can never be selected
def _api_style() -> str:
    return str(getattr(settings, "API_STYLE", "ollama") or "ollama").strip().lower()

# RIGHT — declared field, validated, reachable
QARI_OCR_API_STYLE: Literal["ollama", "openai"] = Field("ollama", description="...")
```

Note the second trap: `Settings` is a strict Pydantic model. `monkeypatch.setattr(settings, "NEW", ...)` and `patch.object(..., create=True)` both raise `AttributeError`/`ValueError` on an undeclared field, which is the same signal that the field is missing in production. Tests must exercise real declared fields.

**Cover it with a test that asserts the field exists**, or the exact defect returns:

```python
field = type(settings).model_fields["QARI_OCR_API_STYLE"]
assert field.default == "ollama"
```

Mirror the new setting into both `.env` and `.env.example` with a comment explaining the two options and why the default is what it is. Treat "add a knob" as a four-part change: declared field, consumer reads it, `.env`, `.env.example`, plus a test asserting declaration.

## Pitfall: Crawler Dedup That Keys on State Duplicates Every File After a Re-crawl

Crawlers that disambiguate colliding filenames by consulting `downloaded_urls` in their own state file will write every document twice the moment that state is reset. The collision test has nothing to compare against, so each basename lands once plain (`14.pdf`) and once hash-suffixed (`14_9da6b234.pdf`) when the second URL for that basename arrives. Sources that serve `1.pdf`, `2.pdf`, ... in *every* domain (ISM does) maximise the exposure.

Measured on a real ISM crawl: **107 of 108 duplicated basename groups were content-identical**, 76 MB of redundant PDFs, and the parser then redid ~45% of its work on the copies because its output stem is keyed off the same basename.

**Make the dedup test content-based, not state-based.** Before the write, if the downloaded bytes hash-match a PDF already in the folder under a different name, skip the write and record the URL against the *existing* filename so the state map stops re-proposing it. That holds on cold state, warm state, and re-crawls alike, where a state-keyed check silently degrades.

```bash
venv/bin/python scripts/duplicate_download_probe.py data/corpus/ism/raw/ar
```

It reports DUPLICATE and COLLIDING groups separately, because they need opposite responses: delete the duplicate, but investigate the collision before touching anything — that one is a document that may already have been lost.

The same name resolver hides a worse bug: when two URLs for one basename resolve to the *same* path and nothing suffixes the second, the later download **overwrites** the earlier one and a distinct document is lost with no error. A probe that only counts duplicates will miss it — compare content hashes within each basename group and report the groups that are NOT identical, because those are the at-risk pairs.

Corollary for cost: when a batch is enumerated once at start-up, deleting source files mid-run leaves the already-queued workers pointing at missing paths, and path-keyed state keeps success records for files that no longer exist. Do corpus cleanup with nothing running, or not at all.

**Cleaning up after the fix — see `references/content_hash_cleanup.md`.** Group by `(folder, sha256)`, never by basename; same basename with a *different* hash is a collision that needs investigation, not a duplicate. Delete sidecars with their PDF, keep the plain basename as survivor, abort if any deletion would remove a hash's last copy, and write a manifest before touching anything.

## Pitfall: Verify the Extraction Classifier on a Path, Not a Page List

`fetching/pipeline_base/pdf_quality.py:_classify_pdf` takes a **path** and calls `fitz.open(pdf_path)` itself. Handing it an already-extracted list of page strings raises `TypeError: bad filename`, which is caught by the function's own `except` — and that handler then raises `AttributeError: 'list' object has no attribute 'name'` because it logs `pdf_path.name`. The second error masks the first and points nowhere near the real mistake.

When probing classifier/gate behaviour, open the PDF yourself, pass the path, and keep the page list for the gates that genuinely want pages.

The CID/Identity-H check reads `f[5]` behind an `isinstance(f[5], str)` guard. **The guard is sound on the installed build — do not report it as a bug without measuring.** A corpus-wide sweep of `get_fonts()` tuples showed every tuple is length 6, `f[5]` is always the encoding string, and the check catches exactly the files that contain `Identity-H` — no misses. The `isinstance` test is defensive, not a suppressor.

**Measure a suspected defect against runtime data before calling it one.** The `f[5]` claim originated from reading the `except` handler's own crash (`pdf_path.name` on a list argument) and generalising that the normal path was also broken; it was not. Sweep the real tuples and compare what the check catches against what actually contains the marker:

```python
for f in doc[pno].get_fonts():
    lens[len(f)] += 1
    if any(isinstance(v, str) and "Identity" in v for v in f): seen_any.add(path)
    if len(f) >= 6 and isinstance(f[5], str) and "Identity" in f[5]: seen_idx5.add(path)
# len(lens) == {6: N}  and  seen_any == seen_idx5  -> the check is correct
```

The same discipline applies to side effects: predict the shape of a consequence, then **count it** in the log before reporting. A batch's failure count is measurable — do not assert an expected number of not-found or failed files from an assumed enumeration order.

## Pitfall: A Domain Filter Must Name a Value the Corpus Stores

A domain filter that matches zero chunks produces NO error — it returns nothing and
the pipeline falls back to sparse-only results with weak citations. Check the
CONSEQUENCE (how many points the built filter matches), not the spelling.

The corpus stores only seven `domain` values — measure with `facet` on the
collection, never a scroll (it times out). The ontology declares 37 canonical keys,
so a filter naming any of the other thirty is guaranteed to match nothing; a mapping
whose target is not yet stored is a corpus coverage gap, not a code defect.
`detect_explicit_domain` returns the corpus key directly, so there is no
Arabic-enum round-trip to break.

**Depth**: the root-cause chain, the three-rule policy, the corpus domain
vocabulary and the ordered diagnostic live in `mizan-retrieval-benchmark` →
`references/domain-filter-exclusion.md`.

## Pitfall: An Inferred Domain Must Never Hard-Filter Retrieval

A domain inferred from the query's wording must be a ranking hint, never a
Qdrant filter. A fuzzy classifier can exclude the very instrument the user named:
a query that names «القانون رقم 15.01» but spends most of its text on answer
instructions was classified `droit_general`, the filter kept only the corpus's 27
`droit_general` chunks, and the target law (`droit_civil`, 851 chunks) never
entered the candidate set — stage 1 ranked six unrelated laws and the model
abstained for want of the provision.

The gate is `retrieval/hybrid/domain_policy.py`: an explicitly-named domain may
hard-filter, an inferred one is a `_domain_boost` only, and a query that names an
instrument suppresses the inferred domain entirely. `_domain_boost` is consumed
post-retrieval by `retrieval/domain_boost.py` — a boost key no stage reads is
worse than no signal.

**Detection**: the dense leg returns far fewer hits than the same query without
filters — compare `inject_domain_filter(query, {})` with
`dense.retrieve_parallel(query, filters=None)`.

**Arabic term matching must be whole-word, not substring**: `عام` matched `عامة`
and `قانون` matched `قانوني`. Bisect the trigger by dropping one word at a time.

**When a test asserts a literal Arabic string, check which contract the docstring
and the callers actually promise** — a stale expectation fails at HEAD and reads
like a code defect.

**Depth**: the root-cause chain, the three-rule policy, the corpus domain
vocabulary and the ordered diagnostic live in `mizan-retrieval-benchmark` →
`references/domain-filter-exclusion.md`.

## Pitfall: Qdrant Timeout in Cross-Document Reference Expansion

The hybrid retrieval pipeline calls `engine.dense.expand_top_k()` during fusion. This method internally calls `_expand_cross_document_refs()` → `_resolve_canonical_ref()` → `dcm.scroll_all()`, which can raise `qdrant_client.http.exceptions.ResponseHandlingException` when the Qdrant server times out.

The Qdrant log will show:
```
ERROR qdrant::actix::helpers: Error processing request: Service internal error: 1 of 1 read operations failed:
  Timeout error: Operation 'scroll_by_id' timed out after 60s
```

This exception is NOT caught by the existing `suppress_and_log` in `retrieval/hybrid/fusion.py` (which only catches ConnectionError, TimeoutError, RuntimeError, OSError) or the narrow except in `_resolve_canonical_ref`. The result is an unhandled 500 error that crashes the entire search request.

**Detection**: Search log shows `Dense retrieval failed in parallel path: ... timed out` followed by a 500 response.

**Fix pattern**: Expand the exception tuples at both layers:
- `retrieval/dense/_engine.py:_resolve_canonical_ref` — add ConnectionError, TimeoutError, and a catch-all except Exception for Qdrant client exceptions
- `retrieval/hybrid/fusion.py:expand_top_k` caller — wrap in broad try/except Exception so any Qdrant timeout degrades gracefully (skips cross-doc expansion) instead of crashing

## Pitfall: Temporal Filter Config Leaking into MatchValue

When the hierarchical retriever passes a `filters` dict containing a `temporal` key (e.g. `{"as_of": "2026-05-07", "include_historical": false}`), the filter builder must skip non-pod keys before iterating dict values. If the temporal config dict leaks into a `MatchValue`, Qdrant's Pydantic validation rejects it with:
```
value.bool / value.int / value.str — Input should be a valid boolean/integer/string
```

The error shows a full config dict `{"as_of": "2026-05-07", ...}` as the `input_value` instead of a scalar.

**Detection**: Log shows `[HYBRID] Dense retrieval failed in parallel path: N validation errors for MatchValue`.

**Fix pattern**: In `build_qdrant_filter`, ensure `temporal` and other config keys are consumed as intentional flags (e.g. `start_date`, `end_date` extraction) and NOT passed as raw dict values to Qdrent `MatchValue` constructors.

## Pitfall: Page-Filtering Regex Missing Article Header Variants

`fetching/adala/parser/pipeline.py:_is_operational_structure_page` decides which pages participate in structure parsing. Its regex for French article headers must include ALL variants recognized by `is_article_line` and `_is_french_article_line` — `premier|1er|unique|preliminary|[0-9]+`.

If a variant is missing, PDFs whose only article header uses that variant (e.g. "Article Unique") get filtered out → `build_tree` sees no articles → `count_articles` returns 0 → parser marks file as failed ("substantial text but zero article nodes").

**Symptom**: Files in `data/logs/adala_parser_failed.jsonl` with that exact error.

**Fix pattern**: Keep the filter regex alternation in sync with the article-detection regex. Audit includes `unique` and `preliminary` even though they map to `art_num=None` (these are real article nodes — they just have no sequential number).

## Pitfall: Articles Silently Dropped by build_tree Dedup

`num_articles_detected` lower than the real article count is usually **not** a detection failure — the header was found and then discarded by the `seen_articles` dedup in `fetching/pipeline_base/structure.py:build_tree`.

Two independent causes, both real, and fixing only the first leaves the file still short. Cause 2 is the more serious one: the articles that DO survive carry wrong numbers.

**Cause 1 — the dedup key is document-global, not per-scope.** `seen_articles` is keyed on `(art_num, inserted)` alone, so it carries no scope at all even though its own comment claims dedup applies "inside one باب/كتاب scope". Any document that restarts article numbering per chapter — a dahir reproducing a loi, or a Moroccan code that reuses `المادة 41` under four chapters — collapses the repeats into one. **Fix (LANDED): put the enclosing hierarchy in the key**, `((part, book, chapter), art_num, inserted)`. Scoping by *book alone* is not enough for codes that have no كتاب and restart per chapter. Keep `inserted` inside the scope so `المادة 14 مكرر` stays distinct from `المادة 14`.

When a comment states a scoping contract, verify the key implements it — the comment and the code disagreed for the entire life of this bug.

**Corpus-wide effect, measured by running `build_tree` over every PDF's page list (no OCR, no LLM, ~16 s):** articles emitted went **4,518 → 5,927 across 138 files** immediately after scoping, recovering **+1,401 (+31%)**, with 24 files gaining from scoping alone. TOC detection (below) then removed 344 of those as phantom, leaving **4,367 uniq → 5,583 emitted (+1,216, +27.8%)**. Quote whichever number matches the code you have actually landed — they are not interchangeable. The penal codes are where per-chapter restarts are most aggressive and the loss was largest: `droit_penal/7.pdf` **101 → 402**, `droit_penal/1.pdf` 358 → 656, `droit_penal/13.pdf` 43 → 94. A single-file figure hides this — the parser was discarding ~31% of every article in the corpus.

Verified by diffing `FAILED` sets against a worktree at the parent commit (see below): 3,726 tests, **0 new failures**. Regression test `tests/test_article_dedup_scope.py` — 2 of its 4 cases fail without the fix; the two that pass either way are deliberate guards (same-chapter repeat still collapses; `المادة 14 مكررة` stays distinct).

**Direction of error flips after the fix — expect over-detection, not loss.** The same 16-page code then reached 52 articles via `build_tree` against a human read of 44, i.e. TOC entries and inline cross-references start surviving. `build_tree` and the full pipeline also disagree (52 vs 39) because the pipeline applies filters `build_tree` does not, so compare like with like and do not treat a `build_tree` count as the emitted count.

**Over-detection has two named sources — find them by printing each node's content, not its number.** Once dedup stops collapsing, page furniture that merely *starts* with a 1-2 digit number becomes a phantom article, because the bare-digit fallback in `_article_header_info` accepts any line matching `\d{1,2}`. Two shapes account for it:

```
table of contents : "3 ......................... 47"   <- dot leaders
page footer/date  : "41 ديسمبر 0545 )"  "14 فبراير0559 ) ص .45"
```

Both create a node whose accumulated content is *only* punctuation, dots, or a date — never prose. Real articles always carry prose. A post-pass over the built tree that drops an article node whose content strips to ≤2 non-furniture characters (`_TOC_LEADER_RE`, `_FOOTER_DATE_RE`) fixes the cheap half. Guard it: nodes whose title matches `_AR_ARTICLE_HEADER_RE` are exempt, so a genuinely short real article (`المادة 5` → `لا شيء.`) survives — test that case explicitly, because "short content" is exactly what a too-aggressive filter destroys.

**This filter is a partial patch, not the fix — do not widen it to hit a target count.** On the 16-page code it removed only 2 of ~8 junk nodes: `ديسمبر` (Egyptian) is missing from a month list holding `دجنبر` (Moroccan), and `. 7 ...` leaves a digit behind the leaders. Patching a month list until one file hits its expected count is how the losses above get reintroduced while the output looks more complete.

### TOC page detection (LANDED) — density alone is not enough

The contents page is the remaining source of phantom chapters and articles: every line starts with a number and matches the bare-digit fallback. Fix it by **skipping TOC pages** at the point `build_tree` flattens a page list, before any header is emitted.

```python
_TOC_DOT_RUN = re.compile(r"[.·․…]{3,}")
_TOC_MARKER_RE = re.compile(r"فهرس|محتويات")

def _is_toc_page(page: str) -> bool:
    lines = [ln.strip() for ln in page.split("\n") if ln.strip()]
    if len(lines) < 3:
        return False
    leaders = sum(1 for ln in lines if _TOC_DOT_RUN.search(ln))
    if leaders < 3:
        return False
    return leaders * 2 >= len(lines) or bool(_TOC_MARKER_RE.search(page))
```

**Leader density alone fails, and fails silently.** The first version required a dot leader on ≥50% of lines and detected **zero** pages in the target file. Inspecting the page showed the text layer reflows each leader onto **two separate lines** and interleaves title lines carrying no dots — ~13 leader lines out of ~40, so density never reaches a majority on a page that is plainly a contents page. The explicit `فهرس` ("index") marker is what makes it general: it does not depend on layout, so it survives any reflow. Keep `leaders >= 3` in both branches or prose pages start matching.

**Measured effect:** the 16-page code went **18 chapters → 9** (exactly the human read) and **52 → 46** articles against a human read of 44; corpus-wide **5,927 → 5,583** (−344 phantom). Sweep found 38 TOC pages across 24 files, 0.83% of pages — and on the target file it flagged p16 *only*, not the other 15.

**Result:** 9/9 chapters, 46/44 articles. Close enough that the residual question is verification, not parsing. **If the remaining 2 need removing, ask the user which two** — do not infer them from a month list and tune until one file matches.

**Distinguish front matter from body before counting.** A code's opening pages are the promulgating dahir (`مادة فريدة`), publication notes, and the consolidated-version dahir — none of them articles. If the first body header reads `المادة 4`, that is not a missing 1-3; look at pages 1-3 first. Rendered-page inspection is the only reliable way to tell a title/promulgation page from a body page.

**Cause 2 — the dedup key is built on WRONG numbers, because the text layer's digit font is corrupt.** This is worse than article loss: the articles that survive dedup carry confidently incorrect numbers, so citations derived from the file are wrong even where the article exists. Do **not** assume glued footnote digits — see the verification gate below before proposing any number-repair fix.

Observed on a dahir reproducing a loi (11 pages, native text layer, `extraction_mode: native`):

| Text layer | Actually printed |
|---|---|
| `المادة1` | المادة 5 |
| `المادة 0` | المادة 6 |
| `المادة22` | المادة 11 |
| `المادة2.` | المادة 12 |
| `المادة27` | المادة 17 |
| `المادة28` | المادة 18 |

This is **glyph substitution in the embedded digit font**, not footnote glue. It is also *not* a consistent per-digit map — `2` maps to both `1` and `2`, and `22` → `11` is not reachable by any per-digit substitution. So there is no deterministic repair function; the number is simply absent from the text layer.

Confirmed in **three files across three domains** (render + vision read): `ism/…/droit_penal/1.pdf` p4 `المادة511` → printed **33**; `ism/…/droit_foncier/1.pdf` p2 `المادة23` → printed **3** (a LEADING digit is wrong here, so right-trimming can never help). The Arabic prose is intact in all three; only digits are damaged.

**A "missing article" here is not a missing article — it is a misnumbered one.** Report it as wrong data, not as a count shortfall. Renumbering or splitting tokens in `_article_header_info` would emit plausible-but-wrong article numbers, which is the worst failure mode in a legal corpus: silent bad citations. The only correct fix is upstream — route the file to a vision/OCR path and keep the native layer for the prose, which is intact.

**Verify numbers against the rendered page BEFORE proposing any fix** — run `scripts/digit_cmap_verify.py`, which emits one 400 DPI crop per header band:

```bash
MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \\
  venv/bin/python scripts/digit_cmap_verify.py data/corpus/ism/raw/ar/<domain>/<n>.pdf
```

Read each PNG with vision, then **solve for a per-digit substitution map across several pairs before writing any repair code.** Digit runs are right-aligned (Arabic renders RTL). If one map cannot explain all the pairs, the same text digit decodes differently in different places — the corruption is positional, not a font table, so there is no deterministic repair and the number is simply absent from the text layer. A repair attempt in that state emits plausible-but-wrong article numbers.

```python
# inside the script: check_map([("1", "5"), ("22", "11"), ...])
# -> prints CONFLICT lines and "consistent per-digit map: False"
```

Two cropping traps that produce a false "no corruption" read: `get_text("words")` **splits** a header like `المادة511` into separate tokens, so matching a token equal to the whole header finds nothing — anchor on the keyword and take the whole line band; and the printed number is often offset from the keyword's baseline, so a tight bbox crop excludes it and vision returns a bare dash. Pad generously and crop at 400 DPI; a 150 DPI full page is not enough to trust a digit read.

### Detection defect: `\s*` between keyword and number misses period-separated headers

Broken RTL digit maps emit a **period run where a space belongs**: `الفصل.1`, `الفصل..1`, even `المادة.7`. `_AR_ARTICLE_HEADER_RE` was `keyword + \s* + [open bracket] + \s* + number`, and `\s*` cannot consume a period, so every one of those real headers was dropped. On the 16-page code the الفصل 1 and 2 headers appeared **only** as `الفصل.1`/`الفصل.2`, which is why their articles attached to the root and the emitted order came out scrambled (`4, 3, 1, 9, 2, ...`) — the cause of the `article_order` block, not a separate bug.

**Fix:** introduce `_AR_HEADER_JUNK = r"[\s.·‧․]*"` in place of the first `\s*`, shared by every header consumer. Corpus sweep over real header tokens: `gap=''` 1386, `' \n'` 60, `' '` 42, `'\n '` 32, `'.'` 29, `'..'` 14 — only the period forms were actually broken, so the gain is small (+8 articles corpus-wide, +13 on the 16-page code). Sweep before assuming a detection pattern is worth widening.

**Write the quantifier as `*`, never `+`.** The first attempt used `+`, which silently stopped matching headers with **no separator at all** (`الفصل114`) — a case that had always worked — because `+` demands one or more. A regex that appears to be widening a pattern can narrow it.

### Self-test a probe regex against hand-written cases before trusting its corpus count

Three separate corpus "findings" in one session were artifacts of the probe, not of the corpus. Each produced a confident number that was wrong:

| Mistake | Consequence |
|---|---|
| Wrote the keyword as a character class `[الفصلالبابالقسم]` instead of an alternation `الفصل\|الباب\|القسم` | Matched stray `ا`/`ل` characters; reported **92.4% of headers missed** out of 145k phantom hits |
| Excluded only Arabic-Indic digits from a gap class `[^٠-٩]` | `الفصل 114` parsed as gap=`1`; reported a nonsense separator distribution |
| Judged the regex by its corpus output rather than known inputs | Would have shipped the `+` regression above |

**Rule: every regex that produces a number gets a self-test block first, run before the corpus loop**, with hand-written `(input, expected)` cases covering each shape you intend to match and at least two you must NOT match:

```python
CASES = [
    ("الفصل.1", "."), ("الفصل..1", ".."), ("الفصل 4", " "),
    ("الفصل114", ""),          # no separator — catches + vs *
    ("الفصل\n1", "\n"), ("المادة.7", "."),
    ("هذا الفصل. ثم نص", None),  # must NOT match
    ("نص عادي دون الفصل", None),
]
ok = all((m := RE.search(t)) and m.group(1) == want for t, want in CASES if want)
```

Two lessons: write your *expected* values honestly (a space separator is a match, not a miss — sloppy expectations mask real ones), and never hand-transcribe a non-Latin fixture — extract it from the corpus and commit the generated test. Literal Arabic and `\uXXXX` assembly were each corrupted in transit, and every corruption produced a false failure that named the parser. **A private probe reporting total failure while the suite is green is the suspect, not the code.** See `references/parser-probe-fidelity.md`.

### Attribute test failures with a worktree, never a stash

Diff the FAILED sets against the parent commit; counts alone prove nothing.

```bash
git worktree add -q /tmp/prev HEAD~1
(cd /tmp/prev && MIZAN_HOME=/tmp/prev PYTHONPATH=/tmp/prev <abs>/venv/bin/python -m pytest tests/ -q 2>&1 | grep '^FAILED' | sort > /tmp/before.txt)
git worktree remove /tmp/prev --force; comm -13 /tmp/before.txt /tmp/after.txt   # introduced
```

**Never `git stash` for this.** Forbidden on working-tree files, and a silent no-op in the case you need it: once the change is committed the tree is clean, so the "baseline" run still contains your change and you report a regression as pre-existing. Use the absolute venv path.

On a 3,726-test suite with ~90 pre-existing failures (RAG/embedding tests needing network and model services), this is the only way to see that your change introduced **0** failures. Check that the new regression test *fails* with the fix reverted — a test that passes both ways validates nothing.

### Screen the corpus BEFORE committing to a long parse

**Run the screen first, then decide what to parse.** A digit-corruption screen over the corpus costs seconds; a parse of the same corpus costs hours and produces confidently-wrong JSON that must then be discarded. Screening after the parse is backwards — you have already paid for the batch and now hold output you cannot trust.

```bash
MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \
  venv/bin/python scripts/corruption_screen.py data/corpus/ism/raw/ar
```

Report the three buckets and let the user choose the parse scope. Measured on a 139-file ISM crawl: 22 digit-corrupt, 36 with a dead text layer, 83 clean — so ~40% of a naive full parse is waste and a source of bad citations.

### Two distinct corruptions need two different responses

The screen separates them, and conflating them sends the fix in the wrong direction:

| Signal | Meaning | Correct response |
|---|---|---|
| Year tokens hit, **Arabic ratio high** (>25%) | Prose readable, digits wrong | OCR/vision re-read of numbers; prose is salvageable |
| **Arabic ratio ~0%** | Text layer fully scrambled (`الوادج11 ٠غت أْ`) | Nothing to preserve — needs OCR from scratch, or exclude |

A file with a 0% Arabic-letter ratio is not a digit problem and no number-repair fixes it. Confirmed by rendering: `droit_penal/1.pdf` reads `الفصل 21` in the text layer where the page prints `80`, while `droit_sante/2.pdf` is scrambled at the word level. The cheap discriminator is the ratio of `[\u0600-\u06FF]` characters to total text — no model, no rendering.

**Cheap corpus-wide screen for the digit defect.** Broken digit CMaps corrupt dates too, and impossible years are greppable — Hijri 1444 renders as `3222`/`3232`/`3242`, Gregorian 2022 as `6666`/`3266`:

```python
HIJRI_BAD = re.compile(r"\b3[01]\d\d\b"); GREG_BAD = re.compile(r"\b6666\b|\b3266\b|\b2255\b|\b6662\b")
ARABIC = re.compile(r"[\u0600-\u06FF]")
```

This is a **screen, not a gate**: one visibly corrupt file scored 1 while clean controls scored 0, so a `> N` threshold drops a real case. Use it to prioritise, never to clear a file. After ranking, confirm the top hits visually before acting — a screen that flags 22 files has proved 2, and the rest are ranked rather than proven.

**The screen's clean bucket is a floor, not a boundary — it contains files that fail anyway.** The screen only separates digit-only corruption from a dead text layer, so digit corruption *below* its detection resolution passes both checks. Measured on a 77-file "clean" parse: **3 of the first 8 files came back `QUALITY BLOCKED`** on `article_order` / `zero_article_number` — the same defect class, at a magnitude the screen cannot see. Do not tell the user a subset is clean, and do not treat "clean" as a licence to trust the resulting JSON without the per-file gate verdict.

### Automatic detectors that do NOT work — measured, do not re-try

Every cheap structural signal was tested against confirmed-corrupt (`14.pdf`, `penal/1.pdf`, `foncier/1.pdf`) vs confirmed-clean (`13.pdf`, `6.pdf`) and **discriminates nothing**:

| Detector | Result |
|---|---|
| `is_arabic_cmap_corrupt` / `is_garbled` / `is_reversed_arabic` | **False on all three corrupt files.** They read the Arabic text, which is clean; the damage is confined to the digit font. This is the single most misleading signal. |
| Article-number monotonicity (must strictly increase) | Flags **all six** test files, clean included (violation rate 0.38-0.58 everywhere). Codes restart numbering per باب, so the invariant does not hold. |
| Glyph-id ambiguity via `get_texttrace()` | Clean files show the *same* pattern. Note the API: `chars` are `(unicode_ord, glyph_id, origin, bbox)` — the first field is an **int**, so `c[0] in "0123456789"` raises `TypeError`; test `48 <= c[0] <= 57`. |
| Drawn-glyph shape vs claimed digit (pixmap ink-profile signature) | Clean `13.pdf` shows *more* shape variants than corrupt `14.pdf` — anti-correlated. |
| `ToUnicode` CMap presence (`doc.xref_get_key(xref, "ToUnicode")`) | **ABSENT on corrupt and clean alike.** No signal. |

There is no cheap automatic gate for this defect. Detection requires rendering pixels and reading them.

### DEAD END — do not re-attempt: re-reading digits by template matching

**Measured at 11.3% self-consistency against clean controls. It does not work.**

The idea: the prose text layer is intact and only digits are wrong, so render the digit run from the page and template-match it against `0-9` rendered from the document's own embedded font (`fitz.Font(fontbuffer=...)`). Avoids VLM/OCR entirely — attractive, and it looked like it worked.

**It does not work. Validate any such reader on CLEAN files before believing a small hand-labelled score:**

```python
# label-free test — text layer is KNOWN CORRECT on clean files, so the reader
# must agree with it. No labels required.
CLEAN-FILE SELF-CONSISTENCY: 12/106 = 11.3%   # <- reader is broken
truth=42 read=34   truth=0 read=5   truth=1 read=6
```

A 5/7 score on 7 hand-read pairs from ONE file was coincidence, not accuracy. Small labelled sets on already-suspicious files cannot validate a reader — you need a **negative control** (clean files) before you trust a positive result.

**Do not plan around hand-labelling dozens of crops.** Vision calls are rate-limited to roughly one per several minutes, so a 50-pair labelled set is a multi-hour wall — and two cheaper attempts to batch it both failed silently:

- **Contact sheets render blank.** Building one page per N crops via `page.insert_image(...)` produced empty image slots; every vision read came back "unreadable" for all rows at once, which looks like a bad read but is a failed montage. Verify a montage on one known-good crop before reading a whole sheet.
- **Batching multiple crops per vision call** is the only way to make labelling tractable, and it needs the montage to actually contain pixels.

Reach for the label-free negative control first: any proposed extractor must agree with a KNOWN-CORRECT source, which needs no labels at all.

Implementation traps hit along the way, all of which fail *silently*:
- `segment()` double-thresholding: passing an already-bool mask then testing `> 40` yields all-False and returns `[]` with no error.
- `get_texttrace()` emits Arabic in **reversed visual order**, so keyword search always fails; use `get_text("rawdict")` (logical order, per-char bboxes).
- `Pixmap` layout: `samples` is a flat `height*stride` buffer with `stride == width*n`; reshape via `stride`, never `height, stride, n`.
- `fitz.TextWriter.write_text` needs a `Page`/`Rect`, not a `Pixmap` (`Pixmap` has no `.rect`).
- Per-char bboxes collapse on a broken CMap — segment the rendered band by ink-column gaps instead.

**The remaining trustworthy option is real OCR/vision on rendered pixels** — it is the only method verified end-to-end here, because it is what produced the ground truth. Everything cheaper is unproven.

`scripts/digit_pixel_reread.py` preserves the whole attempt, including the `--selfcheck` negative control and every PyMuPDF trap hit (`Pixmap` stride layout, `get_texttrace()` visual-order reversal, `TextWriter` needing a `Page` not a `Pixmap`, bool-mask double-thresholding, per-char bbox collapse on a broken CMap). Run its `--selfcheck` before believing any positive score on a reader like this.

**Never infer this from `num_articles_detected` alone.** Compare against the raw PDF text layer — but **normalise the source side to unique article HEADERS per scope, not to unique numbers, and not to raw header lines.** Both extremes mislead:

```python
import re, fitz
doc = fitz.open(pdf); txt = "\n".join(doc[i].get_text() for i in range(len(doc))); doc.close()
hits = re.findall(r'(?m)^\s*الماد[ةه]\s*[\u0660-\u0669٠-٩0-9]+', txt)
```

### Reconcile article counts in the unit the parser emits

Four different numbers describe the same document, and **none of them is automatically the true source count.** Measured on a 16-page code whose JSON emitted 25 articles: JSON emitted 25; unique article NUMBERS 28 (**undercounts**); exact `المادة N` header lines 47 (closest); `is_article_line` hits 81 (inflated by non-articles); word occurrences 68 (includes inline cross-refs).

**Deduplicating by number is wrong and it inverts the error.** That document had **44 printed articles** (user's visual read) but only 25 distinct numbers, because the code restarts numbering per chapter — `المادة 41` sits under الفصل 3, 4, 5 and 8. Comparing 25 against 28 produced a confident "shortfall of 3" when the real shortfall was 19 (43%). Unique-number counting collapses exactly the articles a document-global dedup also collapses, so it hides the defect instead of exposing it.

Anchor the count on **headers within their enclosing scope**, and expect a document's article count to exceed its distinct number count whenever numbering restarts. Before reporting any shortfall, confirm against the user's read of the rendered page — the text layer is itself a suspect artifact on this corpus.

**Chapter headers inflate the source count; a `$`-anchored regex hides them instead.** `الفصل الخامس :النظام الجمركي` carries a title suffix, so a pattern anchored to end-of-line after the number matches **zero** chapters and the document looks chapter-less. Allow the suffix, and subtract chapters explicitly:

```python
HDR = re.compile(r'^\s*(الماد[ةه]|الفصل)\s*([\u0660-\u0669\u0600-\u06FF0-9]+)\s*(?::|：)?\s*(.*)$')
```

**Decompose the detector's hits before trusting any of them.** An Arabic legal PDF mixes three line shapes that `is_article_line` accepts, and only the first is an article:

```
is_article_line hits: 81
  exact "المادة N" headers : 47   <- articles
  bare-digit lines        : 16   <- page markers, years, footnote refs
  الفصل headers           : 18   <- CHAPTERS, not articles
```

`الفصل` (chapter) lines such as `الفصل الخامس :النظام الجمركي` are the largest single source of phantom inflation, and they are numbered 1..N exactly like articles, so they collide in any set comparison. **Exclude chapter markers from the source count before computing a shortfall.** When a user's reported count disagrees with yours by a wide margin, decompose both sides before concluding the parser is at fault — a mismatch you cannot explain is more often a unit mismatch than a defect.

### `article_order` disqualifies a document independently of its count

A document can emit a plausible article count and still be unusable, because the surviving articles are in the wrong order:

```
emitted: [4, 3, 1, 9, 2, 7, 8, 41, 44, 43, 49, 42, ...]
```

Citations resolve by lookup, so a scrambled tree returns whichever node the consumer reaches first — a citation to `المادة 5` points at a different article. **Treat out-of-order emitted articles as disqualifying on their own, no matter how good the count is.** Note this is a distinct claim from the monotonicity *screen* below, which is useless for detecting corrupt files because legal codes legitimately restart numbering per باب: monotonicity cannot screen a *source*, but it can absolutely disqualify an *emitted tree* for one document.

Run `scripts/article_loss_probe.py` to get both the reconciled count and the ordering verdict in one pass.

### The quality gate prints a verdict without protecting the filesystem

Validation runs **after** the JSON is written (in the ISM pipeline, write near line 1164, `validate_document` near line 1173). A file reported `QUALITY BLOCKED` is therefore **still on disk**, and an operator auditing `json/` by file presence will conclude blocked output is fine.

The gate updates statistics and state; it does not delete or relocate what it rejects. When establishing that a corpus is clean, check the gate outcome per file — never the presence of its JSON. through `is_article_line` / `_article_header_info` and reporting which hits were dropped by the dedup key. That distinguishes "never detected" from "detected then discarded" in one run, and turns a vague count mismatch into a named line number:

```python
seen = set()
for line in lines:
    ok, num = is_article_line(line)
    if not ok: continue
    _, number, inserted = _article_header_info(line)
    key = (num, inserted) if num is not None else None
    if key in seen: print("DROPPED", line[:70])
    elif key: seen.add(key)
```

**Check whether it is file-specific before reporting.** A single short file is a defect report; the same ratio across a whole corpus is a systemic parser bug and must be reported as such with the per-file table. Zero `المادة` hits with a nonzero `num_articles_detected` is *not* under-detection — those documents number with الفصل or split headers across lines, a separate concern.

## Pitfall: SGG BO Parser Quality Gap vs ADALA

The SGG parser (`fetching/sgg/parser/pipeline.py`) has a fundamentally different code path from ADALA for BO containers:

- **ADALA**: Calls `build_tree(pages)` on every single PDF, producing a full hierarchy tree with article nodes.
- **SGG BO containers**: Parse TOC into metadata-only entries, then count articles via Arabic-only regex (`re.findall(r"(?:المادة|الماده|اده|الفصل)\s+\d+", ...)`).

This means French BO documents (which use "Article 1", "Article Unique", etc.) are never properly parsed. The article count is always 0 for French docs → validation fails ("substantial text but zero article nodes") → file gets marked as failed.

**Detection**: Compare `ada_parser_failed.jsonl` with SGG BO JSONs — French BO docs show `structure: []` and `num_articles_detected: 0`.

**Fix pattern**: In `_build_bo_container_output()` and `_build_individual_doc_json()`, call `build_tree([doc_text], document_language=language)` + `count_articles(structure)` — the same approach ADALA uses. Also add `source_provider: "sgg"` and `source_url` from sidecar data (both were `None` in the output JSONs).

## Pitfall: API Quota Exhaustion Returns Silent Empty

When the configured LLM provider hits its quota (e.g. OpenRouter returns `anonymous_quota_exceeded`), the `/search` endpoint returns HTTP 200 with:
- `answer`: empty string or "No output from model."
- `confidence_score`: 0
- `citations`: []
- `timing.total_ms`: near-zero

This is a silent failure — the user sees a blank response with no error indication. The pipeline does not detect quota exhaustion or fall back to a secondary model.

**Detection**: Check `data/logs/mizan.log` for `[LLM reasoning] Empty response from LLM` or `[ERROR] Quota exceeded`. Compare API response `confidence_score` against a threshold (< 0.1 = likely empty).

**Fix pattern**: When the primary LLM provider returns quota errors, the engine should auto-fallback to the next configured provider (e.g. Ollama local → OpenRouter → NVIDIA). If all providers are exhausted, return a structured error in the response payload rather than an empty 200.

### The sibling: a misclassified payload, not a broken filter

A filter that is correct but a payload classified under the WRONG domain
key also yields 0 matches, and looks identical from the outside. When QU
detects `domain=commercial` but the payload holds `domain=droit_civil`,
normalization yields a valid key that simply has no points. Here the
filter is right and the payload is wrong.

**Detection**: Run a 5-query audit against known documents. If dense
always returns 0 while sparse retrieves the correct ref, compare the
payload's `domain` field with the query's detected domain.

**Fix pattern**: (Landed) `retrieval/hybrid/domain_policy.py` makes the domain
a soft signal — a `_domain_boost` consumed post-retrieval by
`retrieval/domain_boost.py` — rather than a hard exclusion, so misclassified
docs still appear. Do not reintroduce a hard filter on an inferred value.
(Long-term) re-ingest the affected documents with a corrected
classification.

## Pitfall: Verify Ingestion Before Debugging Ranking

Identity boosts, hybrid fusion, and CrossEncoder reranking all operate on a candidate pool retrieved from Qdrant. If the target documents are not indexed, no ranking logic can surface them — and debugging the ranker is a waste of time.

**Always check ingestion first** before investigating why a document doesn't rank:

1. **Check by doc_id** — use `qm.client.retrieve(collection_name='mizan_law', ids=[doc_id], with_payload=False)` for each QA target's doc_id. If `retrieve` returns `None`, the document is not in Qdrant at all.
2. **Check by doc_ref** — if doc_id lookup fails, scan payloads for the expected `doc_ref` (via scroll with a filter on `metadata.doc_ref`). A 200-point sample had **0 French points** — sample size matters; French docs may be sparse in the collection.
3. **Check collection and vector dimension** — Qdrant returns `Vector dimension error: expected dim: 1024, got 768` if you pass the wrong vector size. Always read the collection's actual vector config before querying. Use `client.get_collection('mizan_law')` and inspect `config.params.vectors`.
4. **Check language distribution** — scroll a sample and count `metadata.language` values. A collection that is overwhelmingly Arabic will not surface French identity-boost targets.

**Detection**: retrieval returns the wrong document, or no document, for a query that names an indexed ref verbatim.

**Fix sequence**: ingestion gap → re-ingest or wait for batch → then debug ranking. Do not debug `_apply_identity_boosts`, `_apply_heuristics`, or the top-N cut until step 1 confirms the target is in the collection.

**Distinction from the top-N-cut pitfall below**: the top-N-cut problem assumes the target IS in the pool but gets dropped by the heuristic cut. The ingestion-gap problem is that the target is NEVER in the pool. Check ingestion first — it is the cheaper diagnosis and the more common failure mode when evaluating against a QA set that was generated against a different corpus state.

## Pitfall: Pre-Converter Cache Loading by Stem+Head-Hash Serves Wrong Content Across Domains

The pre-converter's `_load_pages_from_cache` resolves cache files by `<stem>_<sha256(first-4KB)[:12]>.json` and `_cache_names` falls back to the bare `<stem>.json` name when no hashed cache exists. When multiple PDFs across different domains share the same stem (e.g. `7.pdf` in `droit_civil/`, `droit_foncier/`, `droit_penal/`, `droit_sante/`, `droit_environnement/`), the head-hash is not a content fingerprint — different PDFs can have near-identical first 4KB (same BO masthead boilerplate) and produce the same cache name, or a hashed cache for one domain can be absent while another domain's hash-named cache exists and gets loaded.

**Concrete failure this session**: 21 documents across 5 domains (civil, foncier, penal, sante, environnement) all loaded `5_a8c9707406b6.json` (gum Arabic law text) or `7_<hash>.json` files belonging to a different domain's `7.pdf`. The result: `droit_environnement/5.json` had `title: "قانون الجنسية"` (nationality law) instead of environment law, and all `7.pdf` docs showed gum-arabic text (`العبث`, `الطين`, `غوم اثمان`) instead of their actual content. The page count matched (so the check passed) but the content was wrong.

**Detection**: A JSON's `title`/`ref`/`document_type` don't match the expected law for that domain, but the page count and structure look structurally valid. Or cache files in `data/corpus/<provider>/cache/` have names like `7_<hash>.json` where the hash matches multiple PDFs' first-4KB. Or a grep for domain-specific keywords (e.g. "نزع الملكية" for foncier, "العبث" for gum arabic) across JSONs reveals cross-domain content leakage.

**Fix pattern**: Before accepting a cache file, verify it actually belongs to the document:
1. **Page count must match or exceed** `data["num_pages"]` — a cache with 12 pages for a 132-page doc is the wrong cache even if the stem+hash matches.
2. **Content hash verification**: if `data["metadata"]["content_hash"]` is available, recompute the hash from the cached pages' text and compare. If they don't match, skip this cache file and try the next candidate.
3. **Domain-keyed cache directories**: if the cache layout puts caches in domain-specific subdirectories (e.g. `cache/ar/droit_civil/`), scope the search to the document's own domain directory so cross-domain collisions are structurally impossible.
4. **Fallback to raw PDF re-extraction**: if no cache passes verification, fall back to extracting from the raw PDF directly rather than silently loading a wrong cache.

The fix in `ingestion/pre_converters/base.py:_load_pages_from_cache` this session: iterate all candidate cache names, skip any whose page count is below `num_pages`, and verify content hash matches `metadata.content_hash` before accepting. Clearing `__pycache__` after patching is mandatory — stale bytecode will keep serving the old (wrong) cache resolution.

## Pitfall: Hierarchical Retriever article_number Type Mismatch

The hierarchical retriever's `stage2_article_targeting` calls `.lower()` on `article_number` from Qdrant payloads. Production data stores this field as `int` (not `str`), causing `AttributeError: 'int' object has no attribute 'lower'`.

**Detection**: 500 error in hierarchical retrieval with the above traceback.

**Fix pattern**: Always coerce to `str` before string operations: `str(p.get("article_number")) or "".lower()`. Verify payload types with a direct Qdrant scroll before assuming string fields.

## Pitfall: Verify the OCR Text Before Blaming the Parser

Structure that comes out wrong is usually wrong *upstream*. Before writing any
header, dedup or split rule, run the OCR engine on a page whose article numbers
you have read off the rendered image and diff them — engines silently drop and
merge digits on three-digit Arabic article numbers, and an engine that returns a
page as one unbroken block puts correct headers mid-sentence where a line-start
anchor cannot see them. A parser can only split on markers that survived
extraction; when they did not, every fix applied above that layer is wasted
effort and each one looks plausible while it changes nothing.

Corollary: an article missing from the parse may simply be absent from the OCR
text. Search the preceding article's content for the missing article's opening
words — text present with no marker before it means the boundary was destroyed
before parsing, not swallowed by the parser.

Do not adopt a global OCR winner from one sample: native beat vision on 3 of 5
documents and produced the single best recovery. Measure the document in hand,
and read the engine-selection code rather than assuming a `.env` flag chooses it
— the `OCR_FIRST` branch was engine-pinned to PP-OCRv5 regardless of
`OCR_PARSER_USE_PADDLE_VL`.

See `references/ocr-extraction-truth.md`.

## Pitfall: A Patch Containing `\x00` Writes a Literal NUL Byte and Breaks the Module

Writing `"\x00"` as a sentinel through the `patch` tool inserts a real NUL byte into the file rather than the four-character escape, because the replacement string is written verbatim. Python then refuses to import the module with `SyntaxError: source code string cannot contain null bytes` — an error that names neither the offending line nor the tool that caused it.

**Prefer a named sentinel over any control-character escape** when patching source:

```python
_NEVER_MATCHES = "\u0000never-a-header\u0000"   # written via patch
match(title or _NEVER_MATCHES)                # instead of title or "\x00"
```

If the module will not import after a patch, count NULs before debugging anything else:

```bash
python3 -c "d=open('path/to/module.py','rb').read(); print('nulls:', d.count(b'\x00'))"
```

and rewrite the byte range, then re-check the count is 0. A `SyntaxError` at import time immediately after a successful-looking patch is this, not a syntax mistake.

## Pitfall: A Failed Patch Can Leave the File Completely Unchanged

A `patch` call can fail in the tool layer and return without touching the target, while the error surfaces somewhere unrelated (inside a heredoc, inside the tool runner). The file then still holds the **old** code, and the next measurement silently measures the old behaviour — which reads exactly like "my fix did nothing".

**Rule: after any patch whose effect you did not see in the tool result, re-read the file before drawing a conclusion from it.** Cheap and definitive:

```bash
grep -n 'the_new_symbol' path/to/module.py   # must appear
venv/bin/python -c "import ast;ast.parse(open('path/to/module.py').read());print('OK')"
```

If the symbol is absent, the patch never landed — apply the edit through a script file instead of the patch tool, which is also what to do when the edit contains nested quotes that terminate a heredoc early. This bit once in the same session as the `\x00` pitfall above: two different ways a patch fails to take effect, both of which look like "the fix had no effect" rather than "the fix never applied".

## Pitfall: There Is No Scalable Visual Verification for This Corpus

Verification of a legal document requires reading the **rendered page**, because the text layer is itself a suspect artifact — but vision calls are rate-limited to roughly **one image per several minutes** (`429`, `retry_after` ranging from seconds to ~50 min). A 105-file audit at that rate is not a plan.

So the ground truth for a whole corpus is **the user's eyes**, not a tool. That has hard consequences for what you may claim:

- Report counts as *your parser's opinion*, explicitly contrasted with the user's read. Never present a self-measured count as the document's count.
- When your count and the user's count disagree, the user's read is the authority — and the productive move is usually to ask which specific nodes are wrong rather than to tune thresholds until the numbers coincide.
- Do not plan a multi-hour parse whose only validation is a visual audit you cannot actually perform.

Measure the state honestly instead: of 138 files, 35 had no text layer at all (SCANNED), 44 had wrong signatures (CORRUPT), and 59 were untested CANDIDATES. Only the last bucket can be improved by parsing, and a 46-article tree over a 44-article document is *more* dangerous than a 25-article one because it looks more complete.

## Pitfall: A Reader That Keys on a Field the Corpus Does Not Use Drops Everything

A converter that reads one field while the corpus stores the data in another emits **zero items and reports success**. The pipeline is green, the index has no rows for that provider, and nothing in the logs says "empty".

- Measure the produced item set against the corpus, not against the code path: for each provider, the number of documents that produced a non-stub item, and the characters of text that reached the index. A provider with **0** documents in the index while the corpus holds dozens is a dropped-conversion defect until proven otherwise.
- Read the corpus's actual node shape before trusting a reader: print the node's keys and the field that holds the text, not the field the code prefers. The canonical reader usually already exists — look for a shared `*_node_text` helper before writing a new one.
- A dispatch **gate** is a second, independent filter: a converter reached only when "at least one node has property X" silently excludes every document that lacks X. The real precondition is usually "the structure carries text".
- A guard that `continue`s on empty text is a **silent drop**: it must be counted and reported, never left as a bare `continue` in a path whose output is the whole provider.

## Pitfall: A Delegated Audit Can Damage the Live System

Delegated audits run concurrently against the real services. One batch OOM-killed Qdrant (three agents each loading a ~2.5 GB embedding model), wrote a stray point into a live collection, left four scratch collections in the live Qdrant, and wrote a file into the repo root.

- The brief must forbid writing to the live index, the live database and the corpus; probes use a **temporary collection** or a **copy** of the database. No agent loads an embedding model — stub the transport and keep the rest of the code real.
- After the batch returns, verify the live state yourself: per-collection point counts, document/chunk counts, and `git status` for stray files. A clean audit report is not evidence that the system is clean.
- Report leftovers by name and let the user decide before deleting anything from the live index.

The layer map, the delegation brief that keeps findings reproducible, and the measurement rules: `references/ingestion-layer-audit.md`.

## Pitfall: A Code Fix Does Not Change the Live Index

A committed fix changes what the **next** ingest does. The rows already in SQLite and Qdrant keep the defect until the data is rebuilt, and a report that says "fixed" without that sentence is misleading.

Keep three operations apart — the code fix, the data cleanup of the artifacts the old code produced, and the re-ingestion that applies the fix — and say which one a wave delivered. State the live state in numbers ("the index still carries 84 duplicate document identities and 3,740 duplicate-class chunks until it is rebuilt"). Never let a report imply the live data changed because a commit landed, and never silently delete stale data to make the numbers look better.

