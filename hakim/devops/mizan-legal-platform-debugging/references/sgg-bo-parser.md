# SGG BO Container Parser Debugging

The SGG parser has multiple layers of BO container handling. Common failure modes:

## Missing documents in container JSON

1. **TOC regex doesn't match instrument pattern** — Arabic text uses `ظهير شريف رقم X` (with `شريف` between keyword and `رقم`). The `_TOC_TYPE_FIRST_RE` regex must accept optional `(?:\s+شريف)?` between keyword and `رقم`.
2. **Body start page is wrong** — Arabic BOs have variable TOC lengths (1-3 pages). Never hardcode `body_start = 2`. Use `_find_arabic_body_start()` to scan for the first page with an instrument header and no TOC dot leaders.
3. **OCR-garbled refs** — OCR may reverse digit groups (`1.11.183` → `183.11.1`). Search for both normal and reversed digit-group patterns. Penalize cross-references (`الظهير الشريف رقم X الصادر` pattern) so actual headers win.

## Articles attributed to wrong document

1. **Text bleed between documents** — When a section header is detected, `current["article"]` must be reset to `None`. Otherwise subsequent text accumulates into the preceding article.
2. **Missing section keywords** — `نظام موظفي` (civil service system) is a common section heading in Moroccan BOs. Add it to the Arabic section keyword list.
3. **Cross-references in body text** — A dahir's preamble may reference another dahir (`وعلى الظهير الشريف رقم X الصادر`). These must not be treated as the document's own header.

## Missing dates in container entries

Arabic TOC titles use Arabic month names (`29 نوفمبر 2011`). The date parser must handle both numeric `YYYY-MM-DD` and Arabic `DD Month YYYY` formats.

## Re-parsing from cache

To re-parse without OCR: `python -m fetching.sgg.parser --file <pdf> --lang ar --force`. The extraction cache (`data/corpus/sgg/cache/`) is keyed by content hash and reused automatically.

## Common Issues Checklist

- BO container not splitting → check filename prefix `bo_`, check `_is_bo_container()` heuristic
- Child JSONs not found by ingestion → ensure `rglob("*.json")` is used (not `glob`)
- Quality validation fails → check `validate_document()` for empty text, missing refs
- Container has fewer documents than expected → check TOC parsing, body start detection
- Articles overlap between documents → check section keyword list, `current["article"]` reset
- Dates missing in container entries → check Arabic month name parsing
- OCR-garbled refs → search reversed digit-group patterns, penalize cross-references
