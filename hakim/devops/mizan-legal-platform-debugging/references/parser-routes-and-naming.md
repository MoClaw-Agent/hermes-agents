# Parser Routes, Naming, and Consolidation

## ADALA Parser Route Diagram

See `doc/ADALA_PARSER_DIAGRAM.md` for the complete route diagram. Key points:

### Entry Point
```
python -m fetching.adala.parser [options]
```

Use `__main__.py` entry point (not `python -m fetching.adala.parser.pipeline`) to avoid sys.modules collision.

### Output Naming: doc_type + ref Scheme

JSON output files are named `{doc_type} {ref}.json` (e.g., `dahir 1.02.202.json`) instead of the raw PDF stem. Falls back to stem-based naming when `doc_type` or `ref` is missing.

**Collision handling**: Appends ` (2)`, ` (3)`, etc. before the extension.

**Migration**: Existing JSONs with old names are not automatically renamed. A migration script is needed to rename files and update parser state.

**ISM parser**: `_naming_stem()` in `fetching/ism/parser/pipeline.py` uses the same `doc_type + ref` convention. It reads `doc.get("document_type")` and `doc.get("ref")` first, then falls back to metadata reference, title, and default stem.

**Vision cache naming**: Both ADALA and ISM use `{pdf_path.stem}_{_file_sha256(pdf_path)[:12]}_vision.json`. The ISM parser previously used `{stem}_vision.json` (no hash), causing duplicate cache files. Fixed by importing `_file_sha256` from the shared module.

### Parser Consolidation (ISM → ADALA)

The ISM parser is now a thin wrapper around the ADALA parser. Both share a single code path — bug fixes in ADALA automatically apply to ISM.

**Key files**:
- `fetching/adala/parser/` — canonical implementation
- `fetching/ism/parser/__init__.py` — thin wrapper, only overrides paths and provider ID
- `fetching/parser_base/` — shared facade re-exporting ADALA symbols

**Path overrides**: ISM passes its own `json_dir`, `cache_dir`, `cache_vision_dir` through to ADALA's `run()` and `process()` via optional parameters. No monkey-patching of module-level constants.

## Pitfall: Parser Skips All Files with json_fallback

**Symptom:** Parser state file shows all files with `"error": "json_fallback"` and `"duration_s": 0.0`. No new JSON files are written. The parser completes instantly.

**Cause:** The parser finds existing JSON files with matching `source_file` and `content_hash`, and skips the PDF without re-parsing. This is by design for resumability, but it means stale JSONs are never refreshed.

**Fix:** Run with `--force` to bypass the JSON fallback check:
```bash
python -m fetching.adala.parser --lang ar --force
```

Or delete the state file to start fresh:
```bash
rm data/logs/adala_parser_state.json
python -m fetching.adala.parser --lang ar
```

**Root cause:** The state file tracks by PDF path, not JSON path. If JSONs are deleted but the state file remains, the parser still skips those PDFs because it thinks they were already processed.

## Pitfall: Vision Cache Hash Mismatch Causes Double OCR Scans

When two code paths write to the same cache directory with different naming conventions, the cache is never shared and the document is scanned twice.

**Detection**: `ls data/corpus/<provider>/cache_vision/ | grep <stem>` shows two files with different hash suffixes for the same document.

**Root cause**: One path hashed the first 4KB of the PDF (`sha256(head)[:12]`), the other hashed the entire file (`_file_sha256(pdf_path)`). Same document, different hashes, different filenames.

**Fix pattern**: Both paths must use the SAME hashing function. Import `_file_sha256` from the shared module rather than reimplementing hash logic locally.

**Verification**: After fix, `ls data/corpus/<provider>/cache_vision/ | grep <stem>` should show exactly one file per document.

## Pitfall: `الفصل N منه` False Article Detection

Cross-references like `الفصل 102 منه` ("Article 102 thereof") are detected as new article headers because the regex matches `الفصل` + number, and the cross-reference rejection only checks for `من` + instrument noun (القانون, ظهير, مرسوم). The pronoun `منه` ("thereof") without an instrument noun slips through.

**Detection**: `num_articles_detected` is higher than expected; structure contains articles with `منه` or `منها` in the content.

**Fix pattern**: Add `منه`/`منها` as citation tail patterns. Also add negative lookbehind `(?<!\w)` to reject any header keyword preceded by a word character (e.g., `على الفصل 102`).

**Verification**: `is_article_line('الفصل 102 منه')` returns `(False, None)`; `is_article_line('الفصل الأول')` returns `(True, 1)`.

## Metadata Extraction Fixes

### ref Extraction
- `_OWN_REF_PAT_AR` must tolerate OCR artifacts in publication markers (`ق صادر`, `قصاد`)
- Derivative instruments (بتطبيق/بتنفيذ/بمقتضى) need OWN-ref pattern with publication marker

### bo_number Extraction
- `_extract_bo_number()` parses `الجريدة الرسمية عدد N` from page footers
- Previously hardcoded to `None`

### references Validation
- LLM cross_references can return placeholder values like `[{"type": "type", "value": "value"}]`
- `_refs_are_valid()` checks for valid law reference pattern before accepting LLM result
- Falls back to `extract_refs()` regex when LLM result is invalid

### num_articles_detected Tolerance
- LLM article count tolerance tightened from 50% to 20%
- Prevents LLM under-counting from being accepted (e.g., LLM=4 when structure has 7)

## Pitfall: Promulgation-Title Trap in ref Extraction

**Symptom**: A dahir that promulgates a law gets the LAW's ref instead of the DAHIR's ref. Example: `dahir 1.04.22` (which promulgates Law 70.03) was named `loi 70.03.json`.

**Cause**: The title is "القانون رقم 70.03 بمثابة مدونة الأسرة" (the law being promulgated). The dahir ref `1.04.22` is on page 3 in the promulgation header. The standard filename→title→pages priority returns the law ref from the title.

**Fix**: In `extract_ref()` in `extraction.py`:
1. Detect: title has a law ref (`_LAW_REF_PAT_AR`), filename has no dotted ref → trigger derivative gate
2. In derivative gate, prioritize promulgation header pattern: `ظهير شريف رقم X صادر` over any `ظهير شريف رقم X` reference
3. This skips amendment references on page 2 ("الصادر بتنفيذ الظهير الشريف رقم Y") and matches the actual promulgation header on page 3

**Verification**: `extract_ref(pages, 'ar', title='القانون رقم 70.03...', filename='مدونة الاسرة...')` returns `1.04.22`.

## Pitfall: Corrupted PDFs Re-ingested After CMap Repair

**Symptom**: After CMap repair, the original PDF is moved to `raw/corrupted/<lang>/` but `rglob("*.pdf")` still picks it up, causing infinite re-repair loops.

**Fix**: Exclude `corrupted` from PDF enumeration in both ISM and ADALA parsers:
```python
all_pdfs.extend(
    p for p in pdf_lang_dir.rglob("*.pdf")
    if "corrupted" not in p.parts
)
```

**CMap repair naming**: Repaired PDF keeps the original filename (e.g., `1.pdf`). Corrupted original is moved to `raw/corrupted/<lang>/1_corrupted.pdf`. Temp file used during repair for atomic swap.
