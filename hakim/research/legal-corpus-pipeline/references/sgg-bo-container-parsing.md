# SGG BO Container Parsing Patterns

## When to Read

- BO container JSONs are missing documents (dahirs, decrets)
- Contained document articles are attributed to the wrong document
- `effective_date` is empty despite dates in the title
- Body text bleeds between contained documents
- Re-parsing BO containers from cache

## Architecture

The SGG parser has two output paths:

1. **BO container** (`bo_*.pdf`): `SGGPipeline.process()` intercepts by filename prefix, parses TOC, writes:
   - Container index JSON at `data/corpus/sgg/json/{lang}/{stem}.json`
   - Individual document JSONs in `data/corpus/sgg/json/{lang}/bo_{number}/` subfolder

2. **Individual document** (non-`bo_` prefix): falls through to `super().process()` → `build_output()`

## Pattern 1: OCR Garbles Digit Order in References

OCR can reverse digit groups in references: `1.11.183` becomes `183.11.1` on the actual body header. The normal regex pattern only finds the correct form inside cross-references (e.g., in another document's preamble), causing text ranges to be completely swapped.

**Fix:** In `_contained_document_ranges`, also search for reversed digit-group patterns:
```python
parts = ref.split(".")
reversed_ref = ".".join(reversed(parts))
# Search both normal and reversed patterns
```

**Why:** The reversed pattern matches the actual (garbled) body header, while the normal pattern only matches cross-references. Scoring must prefer the actual header.

## Pattern 2: Cross-References vs Actual Headers

A cross-reference has the form `الظهير الشريف رقم X الصادر` (with `ال` prefix before the marker), while an actual header has `ظهير شريف رقم X صادر` (without `ال` prefix). Cross-references must be penalized so actual headers always win.

**Fix:** Check the text before the header match for `ال` prefix:
```python
pre_text = window[:header_match.start()]
if re.search(r"ال\s*$", pre_text):
    score -= 10  # Cross-reference penalty
```

**Why:** Without this penalty, a cross-reference in document A's preamble can outrank the actual header of document B, causing all text boundaries to shift.

## Pattern 3: Arabic BO TOC Length Varies

Arabic BOs have variable TOC lengths (1-3 pages). A hardcoded `body_start = 2` is wrong when the TOC is only 1 page — it skips the first document's header and shifts all text boundaries.

**Fix:** Use `_find_arabic_body_start()` that scans from page 1 for the first page with an instrument header and no TOC dot leaders:
```python
body_marker = re.compile(
    r"(?:ظهير|مرسوم|قرار|مقرر|قانون)(?:\s+شريف)?\s+رقم",
    re.IGNORECASE,
)
for index, page in enumerate(pages[1:], start=1):
    if not body_marker.search(page_str):
        continue
    if len(re.findall(r"\.{4,}", page_str)) >= 3:
        continue  # TOC page with dot leaders
    return index
```

**Why:** TOC pages carry dot leaders (`. . . . .`) to page numbers; body headers never do. A page dominated by dot leaders is still TOC.

## Pattern 4: Arabic Month Names in TOC Dates

Arabic TOC titles use Arabic month names like `(29 نوفمبر 2011)`. The date regex must handle both numeric `YYYY-MM-DD` and Arabic `DD Month YYYY` formats.

**Fix:** Add fallback parsing for Arabic month names:
```python
ar_months = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4,
    "مايو": 5, "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8,
    "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}
ar_match = re.search(
    r"(\d{1,2})\s+(" + "|".join(ar_months.keys()) + r")\s+(\d{4})",
    title,
)
```

**Why:** Without this, `effective_date` is `None` for any document whose TOC title uses Arabic month names, even though the date is clearly present.

## Pattern 5: Re-Parse from Cache (No OCR)

To re-parse a BO container without re-running OCR, use the `--force` flag. The `extract_pages` function checks for an existing cache file before running OCR:

```bash
python -m fetching.sgg.parser --file data/corpus/sgg/raw/ar/bo_6000_ar.pdf --lang ar --force
```

**Why:** The cache file (`data/corpus/sgg/cache/{stem}_{hash}.json`) contains the extracted pages. With `--force`, the parser skips the OCR step and goes straight to TOC parsing and output generation. This makes iteration on parser fixes fast (sub-second vs minutes per page).

## Pattern 6: Article Content Bleeds After Section Boundary

When a section header (e.g. `نظام موظفي الإدارات العامة`) appears mid-document, `build_tree` creates the section node but does NOT reset `current["article"]`. All subsequent text continues to accumulate into the preceding article's content.

**Fix:** Add `current["article"] = None` after section node creation in `build_tree`:
```python
current["section"] = n
current["article"] = None  # Reset article so text after section doesn't bleed
```

**Why:** Without this reset, `current["article"]` still points to the previous article, and the `elif current["article"]:` branch at the bottom of the loop keeps appending text to it.

## Pattern 7: `نظام موظفي` as Arabic Section Keyword

BO PDFs contain section headings like `نظام موظفي الإدارات العامة` (civil service system). The `build_tree` section detector only recognized `section`/`القسم` in Arabic, so these headings were absorbed into the preceding article.

**Fix:** Add `نظام موظفي` to the Arabic section keyword list in `build_tree`:
```python
_container_hit(line, ["section", "القسم", "نظام موظفي"])
```

**Why:** Use `نظام موظفي` (not bare `نظام`) to avoid false positives where `نظام` appears in unrelated body text. Bare `نظام` is too generic and would catch prose mentioning "system" in any context.

## Known Limitation: BO PDF 2-Column Layout

BO PDFs have pages split into 2 columns. Arabic text reads right-column first, then left-column. The current text extraction does NOT account for column layout — it reads all text in extraction order, which may interleave columns. This affects text ordering within pages and can cause article content to appear out of order. Column-aware extraction (detect column boundaries, read right-to-left for Arabic) is needed for correct text ordering.

## Verification

After any SGG parser fix:
1. Run tests: `pytest tests/test_sgg_parser.py tests/test_sgg_bo_extraction.py -x -q`
2. Re-parse affected BOs from cache with `--force`
3. Verify container JSON has correct `num_documents` and all expected refs
4. Spot-check individual document JSONs for correct article isolation
5. Check `effective_date` is populated when dates exist in titles
