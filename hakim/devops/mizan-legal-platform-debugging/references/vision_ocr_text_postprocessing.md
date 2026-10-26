---
title: Vision OCR Text Post-Processing
description: Fixes for vision OCR output quality issues — footnote markers, cross-references, compound ordinals, and stale cache invalidation.
---

# Vision OCR Text Post-Processing

## Overview

Vision OCR (Qwen3-VL, olmOCR) produces high-quality Arabic text but with systematic defects that the parser must handle. This reference covers the post-processing fixes applied in `vision_pipeline.py` and `structure.py`.

## Footnote Marker Glue

**Problem**: The Bulletin Officiel prints a superscript footnote number immediately beside an article header. The vision model merges it into the digits:

```
true «المادة 4»  with footnote ⁵   →  OCR reads  «المادة 54»
true «المادة 5»  with footnote ⁶   →  OCR reads  «المادة 65»
true «المادة 16» with footnote ¹⁵  →  OCR reads  «المادة 1615»
```

**Detection**: The PDF text layer carries the footnote as a separate smaller-font span next to the header. The vision output glues all of them.

**Fix**: `_repair_glued_article_numbers()` in `vision_pipeline.py`:
- Only touches standalone `المادة N` header lines
- Only when `N` ≠ expected and a split of `N`'s digits equals the expected next number
- Tries prefix and suffix splits
- No-op on clean documents

**Verified**: 6 corrections on `ظهير 1.17.109` (54→4, 65→5, 78→8, 89→9, 1615→16, 1717→17), 0 on all other caches.

## Cross-Reference Phantom Articles

**Problem**: Cross-references like `المادة 516 (الفقرة 3) من القانون السالف الذكر` are split into standalone lines by `_split_runon_article_headers` and matched as article headers.

**Fix**: Extend `_CITATION_TAIL_RE` in `structure.py` to cover:
- Parenthesized paragraph references: `(الفقرة 3)`, `(المقطع 2)`
- `من القانون السالف الذكر` — "from the aforementioned law"
- `منه` mid-line (not just at end): `المادة 568 منه`
- `من الظهير الشريف` / `من المرسوم` / `من المدونة`
- `السابقة الذكر` — "aforementioned"
- `منه؟` — "thereof?" with Arabic question mark

**Verified**: `arrete 1356.19` (516 phantom eliminated), `arrete 2937.19` (568 phantom eliminated), `dahir 1.70.190` (101 phantom eliminated).

**Additional patterns added** (all in `_CITATION_TAIL_RE`):
- `في المادة` — "in Article" cross-reference
- `تطبيقا للمادة N من القانون` / `تطبيق المادة N من القانون` — cross-reference to another law's article (with optional tanwin)
- `المرسوم رقم` / `الظهير` — instrument nouns in `من <noun> <instrument>` pattern
- `المصرح بعدم مطابقتها للدستور` — constitutional court decision reference
- Colon at end of line (`^[:：]\s*$`) — isolated header from amendment note
- `من أنه` / `والبند` — cross-reference connectors

**In `_CROSS_REFERENCE_TAIL_RE`**:
- `تطبيقا للمادة N من القانون` — cross-reference to another law
- `انظر المادة` / `انظر المادتين` — "see Article" cross-reference

**Verified**: `dahir 1.14.192` (36→31 articles, 5 phantoms rejected), `decret 2.08.528` (26→25, article 2 cut-off fixed).

## Compound Ordinal Truncation

**Problem**: `الفصل الرابع والعشرون` (chapter 24) is parsed as `الفصل الرابع` (4) because the regex only captures the first ordinal word.

**Fix** (two parts):
1. Extend `_AR_ARTICLE_HEADER_RE` to capture compound ordinals: `الرابع والعشرون` as a single token
2. Extend `_ordinal_int` to parse compound ordinals: ones + tens = 4 + 20 = 24

Also add indefinite tens forms (عشرون, ثلاثون…) and ش-suffix variants (العشرين, الثلاثين…) to `_AR_TENS_WORDS` in `ingestion/patterns.py`.

**Verified**: `الفصل الرابع والعشرون` → 24, `الفصل الثالث والثلاثون` → 33.

## Image Preprocessing for Vision OCR

Dense Arabic legal PDFs with small fonts and complex layouts cause VLMs to produce degenerate transcription (repeated lines, garbled text). Before sending a page to the vision model, preprocess:

1. **Grayscale** — `img.convert("L")` removes color noise
2. **Contrast** — `ImageOps.autocontrast(img, cutoff=1)` enhances faint text
3. **Binarization** — `img.point([0 if i < 128 else 255 for i in range(256)])` cleans background noise

This gives the VLM cleaner input, reducing degenerate transcription failures. Quality over speed — the extra preprocessing time is acceptable if it fixes article detection.

## Hybrid Structure: PP-OCRv5 + Vision OCR

When both OCR sources produce text, build structure trees from both and pick the better one:

```python
ppocr_structure = build_tree(ppocr_pages, document_language='ar')
vision_structure = build_tree(vision_pages, document_language='ar')

# Count articles recursively in each tree
def count_articles(tree):
    return sum(1 for n in tree if n.get('type') == 'article') + \
           sum(count_articles(n.get('children', [])) for n in tree)

if count_articles(vision_structure) > count_articles(ppocr_structure):
    structure = vision_structure
else:
    structure = ppocr_structure
```

PP-OCRv5 finds `المادة N` headers even when garbled; vision OCR produces cleaner text but may miss headers on dense layouts. The hybrid approach picks the best of both.

## Stale Vision Cache After Code Fixes

**Problem**: After patching vision-OCR post-processing code, the vision cache files on disk still contain the OLD corrupted text. Re-running the parser on a cached file will NOT apply the fix.

**Fix**: Delete the vision cache file before re-running:
```bash
rm data/corpus/adala/cache_vision/<name>_vision.json
```
Then re-run with `--force`.

**Prerequisite**: The Cloudflare Tunnel must be alive. Check with:
```bash
curl -s --max-time 10 https://<tunnel-url>/v1/models
```

## Quality Validator: bis Exemption

**Problem**: The `article_order` quality check counts `bis` (inserted) provisions when testing whether article numbers are monotonic. A `bis` article reuses its base article's number and sits out of numeric position by design.

**Fix**: In `ingestion/quality_validation.py`, exclude `bis` articles from both the `article_order` check and the `article_numbers_ordered` metric. Use a shared helper so the two can never disagree.

**Verified**: `dahir 1.93.16` (18 articles, 3 bis) passes with 0 errors. Genuine disorder is still caught.

## CMap Corruption vs OCR Errors

**Clarification**: CMap corruption breaks only the PDF's text layer (glyph→Unicode mapping). OCR never reads that — it renders pixels and reads the image. So CMap corruption cannot produce OCR errors by itself.

The correlation is: a bad scan produces both a broken text layer (forcing OCR) and low-quality raster images (making OCR produce wrong digits). CMap corruption is a *marker* of a bad scan, not the *cause* of OCR errors.

## Annex Boundary Detection

**Problem**: Annex content (templates, forms) after the last article gets absorbed into the preceding article's content. Example: `decret 2.19.720` article 10 had 9305 chars including 3 annexes.

**Fix**: In `build_tree()` in `structure.py`, detect `الملحق رقم N` as a structural boundary:
- Creates a new `annex` node type
- Closes the current article
- Subsequent lines attach to the annex node
- `current["annex"]` is reset when a new article or container starts

**Verified**: `decret 2.19.720` article 10 went from 9305 chars (with annexes) to 362 chars (clean), 3 annexes as separate nodes with full content.
