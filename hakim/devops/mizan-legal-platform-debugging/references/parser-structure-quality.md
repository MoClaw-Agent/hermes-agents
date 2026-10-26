# Parser Structure Quality Patterns

## Phantom Articles from Run-On Splitting

**Symptom**: JSON contains an article number that does not exist in the PDF.

**Root cause**: OCR returns a whole page as one line. `_split_runon_article_headers` in `fetching/pipeline_base/structure.py` splits at any mid-line `المادة N` / `الفصل N` match. Prepositional citation lead-ins (`بناء على`, `بحسب على`, `وفق على`, `طبق على`, `عملا على`, `بموجب`, `بمقتضى`, `استنادا إلى`) signal a cross-reference — the keyword they govern is NOT a new header.

**Fix**: Add `_CITATION_LEAD_RE` regex matching these lead-ins. Guard in `_split_runon_article_headers`: skip split when `scan[:m.start()]` matches. Trailing preposition is REQUIRED — bare `بناء` is a noun, not a lead-in.

**Tests**: `tests/test_runon_marked_header.py` — `test_citation_lead_preposition_does_not_split`, `test_citation_lead_does_not_create_phantom_article`, `test_real_header_after_plain_text_still_splits`.

## Material vs. Chapter Conflation

The code at `structure.py:75` lumps المادة (article) and الفصل (chapter) into the same `_AR_ARTICLE_KEYWORD` and emits them as the same `article` node type. This is a separate structural issue from the phantom-article bug.

## Cache Bypass

`--force` does NOT bypass page-text caches. It only bypasses parse-state / existing-JSON skip checks. `extract_pages()` has no force parameter. To re-extract, delete:
- `data/corpus/adala/cache/<stem>_<hash12>.json`
- `data/corpus/adala/cache_vision/<stem>_<hash12>_vision.json`

The `<hash12>` is the first 12 hex of sha256 over the PDF's first 4KB.

## `--force` Actual Behavior

- `fetching/adala/parser/pipeline.py:1760-1766` — deletes existing JSON outputs under `JSON_DIR/<lang>/**`
- `fetching/adala/parser/pipeline.py:1812-1813` — `state.should_skip(..., force=True)` → `core/parser_state.py:270-271` returns `False, "force"`
- `fetching/adala/parser/pipeline.py:1014-1025` — same for single-file `process()` path

Does NOT touch:
- `fetching/adala/parser/pipeline.py:1057-1062` — calls `extract_pages(pdf_path, CACHE_DIR, ...)` with no force argument
- `fetching/pipeline_base/extraction.py:340-455` — cache hit returns immediately, only way past is automatic quality invalidation
- `fetching/pipeline_base/vision_pipeline.py:715-717` — vision cache returns before inference
