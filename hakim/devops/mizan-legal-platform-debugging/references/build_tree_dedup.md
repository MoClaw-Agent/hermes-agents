---
title: build_tree Dedup and Article Loss
description: Deep dive into how build_tree silently drops articles, dedup logic, and the article-loss probe tool.
---

## Pitfall: Articles Silently Dropped by build_tree Dedup

`build_tree` silently drops articles when dedup logic considers them duplicates. This section covers the dedup logic, the article-loss probe tool, and fix patterns.

### Detection

Run the article-loss probe before proposing a parser fix:

```bash
MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \
  venv/bin/python scripts/article_loss_probe.py data/corpus/ism/raw/ar/<domain>/<n>.pdf

# sweep an already-parsed directory, one row per JSON
... venv/bin/python scripts/article_loss_probe.py --json-dir data/corpus/ism/json/ar
```

A SUSPECT verdict means the numbers may be *wrong*, not merely missing — confirm with `scripts/digit_cmap_verify.py` before touching extraction code.

### Dedup Logic

The dedup logic in `build_tree` considers two articles duplicates when they share the same `(chapter_key, number, bis)` tuple. This is correct for most cases but can silently drop articles when:

1. **Cross-references are split into standalone lines** — `المادة 516 (الفقرة 3) من القانون السالف الذكر` becomes `المادة 516` after splitting, matching a real article 516 elsewhere in the document.
2. **Footnote markers are glued onto article numbers** — `المادة 4` with footnote `⁵` becomes `المادة 54`, which doesn't match any real article.
3. **Compound ordinals are truncated** — `الفصل الرابع والعشرون` (24) is parsed as `الفصل الرابع` (4), creating a duplicate of the real article 4.

### Fix Patterns

- **Cross-reference rejection**: Extend `_CITATION_TAIL_RE` to cover parenthesized paragraph references (`(الفقرة 3)`), `من القانون السالف الذكر`, `منه` mid-line, `من الظهير الشريف`, `السابقة الذكر`, and `منه؟` with Arabic question mark. Also add quote-mark, `من أنه`, `والبند`, `المرسوم رقم`, and `المصرح بعدم مطابقتها` for amendment notes and constitutional court decisions.
- **Footnote marker repair**: `_repair_glued_article_numbers()` in `vision_pipeline.py` splits footnote markers that vision OCR merges into article digits. Only touches standalone header lines; no-op on clean documents.
- **Compound ordinal support**: Extend `_AR_ARTICLE_HEADER_RE` to capture `الرابع والعشرون` as a single token, and extend `_ordinal_int` to parse compound ordinals (ones + tens). Also add indefinite and ش-suffix tens forms to `_AR_TENS_WORDS` (عشرون, ثلاثون, الثلاثين, etc.) since vision OCR often drops the definite article or adds ش.
- **Annex boundary detection**: `الملحق رقم N` must be recognized as a structural boundary in `build_tree`. Without it, annex content (templates, forms) gets absorbed into the preceding article's content. Fix: when a line matches `^\s*الملحق\s*(?:رقم\s*)?\d+`, close the current article and create a new `annex` node. Track `current["annex"]` and clear it when a new article or container starts.

### Quality Validator: bis Exemption

The `article_order` quality check must exempt `bis` (inserted) provisions. A `bis` article reuses its base article's number and sits out of numeric position by design — it's legally correct for amended instruments.

**Fix**: In `ingestion/quality_validation.py`, exclude `bis` articles from both the `article_order` check and the `article_numbers_ordered` metric. Use a shared helper so the two can never disagree.

**Verified**: `dahir 1.93.16` (18 articles, 3 bis) passes with 0 errors after the fix. Genuine disorder (swapped base articles) is still caught.
