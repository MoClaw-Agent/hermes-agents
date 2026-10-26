# SGG Parser Output Structure

## BO Container Layout

When the SGG parser processes a BO container PDF (`bo_*.pdf`), it produces:

1. **Container index JSON** at `data/corpus/sgg/json/{lang}/{stem}.json` — TOC metadata, `contained_documents` array, no full text
2. **Individual document JSONs** in `data/corpus/sgg/json/{lang}/bo_{number}/` subfolder — one per contained legal document, each with full text, structure tree, and metadata

Example:
```
data/corpus/sgg/json/ar/
├── bo_7513_ar.json                          # container index
└── bo_7513/                                  # child documents subfolder
    ├── bo_7513_ar_2-26-270.json
    ├── bo_7513_ar_954-26.json
    └── ...
```

## Key Fields

### Container Index
- `document_type`: `"bo_container"`
- `bo_number`: extracted from filename (e.g. `"7513"`)
- `publication_date`: resolved from sidecar or printed header
- `num_documents`: count of contained documents
- `contained_documents`: array of {official_ref, title, doc_type, date, issuing_authority, cites, num_articles, is_amendment}

### Child Document
- `file_name`: `{stem}_{ref_with_dashes}.pdf`
- `ref`: official reference from TOC (e.g. `"2.26.270"`)
- `document_type`: instrument type (decret, dahir, loi, arrete, decision)
- `bo_number`: parent BO number
- `text`: full document text (not in cache)
- `structure`: built from document text only (not full BO)
- `quality_status`/`quality_errors`/`quality_warnings`: from validate_document()

## BO Number Extraction

Filename pattern: `bo_{number}_{lang}.pdf`
- `bo_7513_ar.pdf` → `"7513"`
- `BO_7197-bis.pdf` → `"7197-bis"`
- `B0-7197.pdf` → `"7197"` (digit-zero variant)
- `2024_BO_7197.pdf` → `"7197"` (year prefix excluded)
- `ECI_42_fr.pdf` → `None` (ECI prefix, not BO)

## TOC Parsing

The SGG parser uses regex patterns to extract document entries from the BO table of contents. Arabic BOs use two patterns:

1. **Number-first** (`_TOC_ENTRY_RE`): matches `\d+\.\d+\s+(مرسوم|قرار|ظهير|قانون)\s+title` — for refs that appear BEFORE the keyword
2. **Type-first** (`_TOC_TYPE_FIRST_RE`): matches `(مرسوم|قرار|ظهير|قانون)\s+شريف?\s+رقم\s+\d+\.\d+\s+title` — for refs that appear AFTER the keyword

The type-first pattern MUST include optional `(?::\s+شريف)?` between the keyword and `رقم`. Moroccan legal text uses `ظهير شريف رقم X` (with `شريف` between), not `ظهير رقم X`. Omitting this causes silent instrument loss — dahirs are dropped from `contained_documents` without any error or warning. Example: BO 6000 lost `1.11.183` and `1.11.184` (both dahirs) because the regex did not match `ظهير شريف رقم 1.11.183`.

## Body Start Detection

Arabic BOs have variable TOC lengths (1-3 pages). The body start must be detected dynamically, not hardcoded.

**`_find_arabic_body_start(pages)`** scans from page 1 for the first page that:
1. Contains an instrument header (`ظهير شريف رقم X`, `مرسوم رقم X`, etc.)
2. Does NOT have TOC dot leaders (3+ occurrences of `.{4,}`)

**Pitfall**: Hardcoding `body_start = 2` causes text to bleed between documents when the TOC is only 1 page. The first document's header is skipped, and its text gets attributed to the previous document. Example: BO 6000's dahir 1.11.183 had its article 2 attributed to dahir 1.11.184 because the body started at page 2 instead of page 1.

## OCR-Garbled References in Body Matching

`_contained_document_ranges` matches instrument refs in body text to find document boundaries. OCR often garbles digit groups: `1.11.183` becomes `183.11.1` (digit reversal). The normal ref pattern only matches the garbled form inside cross-references (e.g., "الظهير الشريف رقم 1.11.183 الصادر" in another document's preamble), causing text to be attributed to the wrong document.

Fix: search both normal and reversed digit-group patterns. Penalize cross-references (text with `ال` prefix before the instrument keyword, indicating a citation rather than a header). Prefer the normal pattern when both match.

## Arabic Month Names in TOC Date Extraction

Arabic TOC titles use Arabic month names (e.g., `29 نوفمبر 2011`), not numeric `YYYY-MM-DD`. The date regex must handle both formats:

```python
ar_months = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4,
    "مايو": 5, "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8,
    "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}
```

Without this, `effective_date` stays `None` for documents whose titles use Arabic month names.

## `نظام موظفي` as Section Keyword

The structure parser only recognizes `section`/`القسم` in Arabic. Headings like "نظام موظفي الإدارات العامة" (system of public administration staff) are not matched and get absorbed into the preceding article's content. Add `نظام موظفي` (not bare `نظام` — too broad, catches unrelated text) to the Arabic section keyword list.

## Article Reset on Section Boundary

When `build_tree` creates a section node, `current["article"]` must be reset to `None`. Without this, all subsequent text continues to accumulate into the preceding article's content, even after a section boundary is detected. This caused Article 2 of a dahir to absorb an entire unrelated section.

## Ingestion Notes

- `ingestion/bdj_enrichment.py` uses `rglob("*.json")` (recursive) to find child JSONs in `bo_*` subfolders
- `tests/test_p7_sgg_pub_date.py` uses `glob("*.json")` (top-level only) — intentional, tests container index JSONs
- `ingestion/pre_converters/sgg.py` converts both Schema A (legacy BO) and Schema B (current split format)
