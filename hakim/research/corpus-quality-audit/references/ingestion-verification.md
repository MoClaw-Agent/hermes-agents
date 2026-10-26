# Post-Ingestion Verification Workflow

After a corpus ingestion run, verify the index matches the JSON source before
declaring the corpus usable. The following checks form a standard suite — run
them in order and report each with pass/fail.

## 1. Ingestion history

Read `data/logs/ingest_history.json` — confirms documents_processed, skipped,
errors. If errors is non-empty, read the mizan.log tail for failure detail.

## 2. Quality validation sweep

Run `validate_document(d, "adala")` across all JSONs. Compare error counts
against the pre-ingestion baseline:
- `empty_text` should be 0 (vision docs carry structure content, not page text)
- `missing_title` should be 0
- `duplicate_article_number` should be 0
- `article_order` — count should decrease after parser fixes; remaining are
  known-unrecoverable OCR cases

## 3. Provision counts (Qdrant vs JSON)

Compare per-doc article counts in the JSON structure tree against Qdrant
point counts per doc_ref. A gap means the chunker produced fewer chunks than
articles — investigate chunker merge/skip logic.

Qdrant points EXCEED JSON article counts by design — the chunker emits
multiple chunk types per article (article chunks + paragraph/segment chunks).
Fewer points = dropped articles; more points = normal multiplication.

Use the REST API (POST to `/collections/mizan_law/points/scroll`) rather than
the Python client — the client's scroll OOMs on large collections (full
payloads exhaust memory). Use batched curl with small `limit` (200) and
`--max-time` per request. For field-level checks use filter queries (small
result sets) instead of full-collection pulls.

## 4. Hierarchy paths

Check that articles in Qdrant have populated `hierarchy_path` (or equivalent
hierarchy field). Articles with empty/null hierarchy are orphaned from the
document tree — they cannot be navigated by legal structure.

In the JSON, articles with all-null `position` blocks indicate the parser's
`build_tree` did not detect container headers — the structure is flat
(preamble + articles only). This is a parser detection issue, not an
ingestion issue.

## 5. Footnote counts

Compare footnote counts in the JSON against the pre-ingestion baseline.
Footnotes should be unchanged by ingestion.

**Footnote flow:** the parser extracts footnotes into the JSON top-level
`footnotes` field (list of `{page, text}`) and REMOVES them from the page
text — the footnote block stays OUT of the structure tree (footnote text
produces phantom article headers). Ingestion must read that field and emit
footnote items as searchable chunks (`chunk_kind: "footnote"` with a
distinct `Fn.N` id prefix). If ingestion ignores the field, footnotes are
completely unsearchable — they exist only in the JSON, never in Qdrant.

Verify: count `d.get("footnotes")` in the JSON; check a sample Qdrant point
for `chunk_kind: "footnote"` on a doc known to have footnotes.

## 6. Ref spot-check

Verify that previously-fixed refs survived ingestion. Sample a few docs and
confirm the top-level `ref` and `metadata.ref` match the expected value.

## Known Data Flow Issue: ref Field Location

The ADALA parser writes `ref` at the top level of the output JSON but does
not include it in the `metadata` sub-dict. The ingestion layer
(`law_adapter.py`) reads `metadata.get("ref")` — which returns None — and
falls back to extracting refs from text, producing wrong values.

The SOTA fix is at the parser level: add `"ref": str(ref)` to the metadata
sub-dict in the parser's output dict construction. Do not patch every
downstream consumer — fix the source.

## Collection Routing Pitfall

Law documents published in the Official Gazette carry a `bo_number` (the
gazette issue number). The dual-collection routing logic (`routing.py`)
routes any document with a non-empty `bo_number` to `mizan_bo` regardless
of provider. This misroutes law documents to the BO collection.

**Symptom:** Qdrant `mizan_law` has far fewer docs than expected; `mizan_bo`
contains law documents that should be in `mizan_law`.

**Diagnosis:** Compare `doc_refs` across collections. Check for doc_id
collisions (same doc_id, multiple refs). Check whether missing docs were
modified after ingestion (corpus drift) vs. truly missing (routing bug).

**Fix (SOTA):** In `routing.py::is_bo(payload)`, check provider before
`bo_number`. If `source_provider` is a known non-BO provider (e.g. `adala`),
return False before the `bo_number` check. Only route to BO based on
`bo_number` when the provider is a BO provider or unknown.

## Flat Document Hierarchy

Some documents genuinely have no container headers (no title/book/part).
The parser correctly produces a flat structure (preamble + articles only).
The chunker has no fallback, so `hierarchy_path` ends up empty in Qdrant.

**Symptom:** Articles in flat documents have `hierarchy_path: []`.

**Diagnosis:** Check the JSON structure — if it has only `preamble` and
`article` nodes with no container types, the document is genuinely flat.
Check the OCR page text for container headers — if none exist, the parser
is correct.

**Fix (SOTA):** In the chunker, when `hierarchy_path` is empty, synthesize
a fallback from the document title: `chunk_info.get("hierarchy_path") or [_title]`.
This is consistent with the existing `hierarchy_str` fallback pattern.

## Corpus Drift After Ingestion

The corpus may be modified by a re-parse AFTER ingestion completes.
Check file modification times against the ingestion completion timestamp.
Docs modified after ingestion are not in Qdrant by design — they need
ingestion. Docs from BEFORE ingestion that are missing indicate a
routing or processing bug.

## Cache-Rebuild Repair (Alternative to Full Re-parse)

When a document's structure is wrong but its vision cache is intact, rebuild
the structure from the cache with the fixed parser instead of re-running
the full OCR pipeline. This preserves metadata (timestamp, extraction_mode,
source_url) and avoids the OCR cost.

1. Load the vision cache (`structure_text_cache` field in the JSON)
2. Call `build_tree(pages, document_language="ar")` with the fixed parser
3. Dedup articles by number (keep first occurrence) — OCR reading-order
   artifacts produce duplicates
4. Write the rebuilt structure back to the JSON, preserving all top-level
   metadata fields

Verify the rebuild improves quality: run `validate_document` before and
after, comparing error counts. Only write back if errors decreased.