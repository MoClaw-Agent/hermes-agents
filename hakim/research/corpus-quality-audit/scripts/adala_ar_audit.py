# ADALA Arabic Corpus Audit Script

Reusable audit script for the ADALA Arabic corpus at `data/corpus/adala/json/ar/`.
Run with: `venv/bin/python scripts/adala_ar_audit.py`

## Checks performed

1. **Document type distribution** — dahir vs decret vs loi counts
2. **Extraction mode distribution** — native vs ocr_forced counts
3. **Structure source distribution** — extraction vs vision counts
4. **Article count distribution** — histogram of `num_articles_detected`
5. **Chapter count distribution** — histogram of `num_chapters_detected`
6. **Phantom titles** — nodes with keyword+digits title (no space), the OCR glue signature
7. **Empty chapters** — chapter nodes with no content (distinguish containers vs truly empty)
8. **Empty sections** — section nodes with no content
9. **Citation lead-in chapters** — chapters whose content starts with a citation pattern
10. **Cache resolvability** — missing extraction or vision caches
11. **Structure null** — `structure: null` but `num_articles_detected > 0`
12. **Preamble-only** — documents with only a preamble node
13. **Degraded** — `structure_degraded: true`
4. **Missing ref/title** — documents without ref or title
5. **Duplicate refs** — refs mapped to multiple files

## Phantom title pattern

```python
BAD_TITLE = re.compile(r'^(?:الفصل|فصل|المادة)\d+$')
```

A node with `type in ('chapter', 'article')` and a title matching this pattern is a
phantom — the OCR glued the keyword and number together, creating a node from a
cross-reference or split header.

## Empty node classification

- **Empty with children** (container) — legitimate, content is in children
- **Empty without children** (truly empty) — phantom or bug, investigate

## Citation lead-in patterns

```python
CITATION_LEAD = re.compile(r'(?:بناء|بحسب|وفق|طبق|عملا|بموجب|بمقتضى|استنادا|تمشيا|يلغى|يعوض)\s*(?:على|إلى|الى|لل|في|من|ل|ب|عن|حتى)\s*$')
POINTER = re.compile(r'^\s*(?:أعلاه|أدناه|اعلاه|ادناه|أعاله|اعله|بعده|بعدها|بعدهما|قبله|قبلها|قبلهما)')
SELF_REF = re.compile(r'(?:المشار\s+إليهم\s+في\s+ظهيرنا|المشار\s+إليه\s+في\s+ظهيرنا|أصدرنا\s+أمرنا\s+الشريف|طبقا\s+لظهيرنا\s+الشريف)')
```

## Output

The script prints a summary table with all metrics, then detailed tables for each
defect category. Use the output to track improvements between re-parses.
