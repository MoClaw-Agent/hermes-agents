# VLM OCR Routing Patterns

## Full-page VLM (baseline)

Send one rendered page image to the VLM, get back one text string per page.
Fast (~1 call per page) but cannot preserve within-page reading order on
complex multi-column layouts — the VLM reads articles out of sequence.

## Layout-guided VLM

Use PP-DocLayoutV3 to detect text regions, sort them into reading order
via geometry (merge_boxes_into_lines), crop each line, and send each crop
to the VLM separately. Guarantees correct within-page article ordering but
multiplies API calls by 5–15x per page.

## Hybrid: Full-page first, layout-guided for bad pages only (SOTA)

1. Run full-page VLM on all pages (fast, ~1 call per page).
2. Check each page for article ordering issues via `_page_has_ordering_issues(text)` —
   uses `_article_header_info` (which rejects cross-references) to extract article
   numbers and detect out-of-order sequences.
3. Re-run only problematic pages through the layout-guided route.
4. Merge — replace bad pages with layout-guided results.

This avoids the cost of per-line VLM calls for pages that do not need them,
while still catching and fixing ordering issues when they occur.

Settings:
- `VISION_OCR_LAYOUT_GUIDED` (default true): enable layout-guided route
- `VISION_OCR_LAYOUT_GUIDED_FALLBACK` (default true): hybrid mode

Flow: full-page VLM → detect ordering issues → layout-guided re-run for bad pages
only. Falls back to layout-guided-first if hybrid is disabled, then to
EasyOCR/PaddleOCR if the VLM route is unavailable.