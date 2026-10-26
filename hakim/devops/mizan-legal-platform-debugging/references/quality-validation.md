# Quality Validation & Cross-Reference Detection

## Document Quality Validator (`ingestion/quality_validation.py`)

The validator produces a `QualityReport` with `QualityIssue` entries at `error` or `warning` severity. It is report-only — it does not block ingestion. Common error codes:

| Code | Meaning | Typical cause |
|------|---------|---------------|
| `empty_text` | No extractable text | Vision-parsed doc with empty `page_texts_sample` but populated structure |
| `missing_title` | Title extractor returned empty | LLM didn't supply a title; regex didn't match the format |
| `article_order` | Article numbers out of sequence | Cross-ref false article, OCR transposition, or digit misread |
| `duplicate_article_number` | Same article number twice | OCR noise or genuine source defect |

### `_text()` helper

Reads `text` then `page_texts_sample`. For vision-parsed documents (`mode="vl"`), `page_texts_sample` is built from empty native pages — so the sample is `['', '', ...]`. The structure carries the operative article text. **Pitfall**: `if values:` checks list non-emptiness, not content non-emptiness — a list of empty strings passes. Use `if joined.strip():`.**

## Cross-Reference Detection (`fetching/pipeline_base/structure.py`)

`_CITATION_TAIL_RE` rejects cross-references to other laws from being parsed as articles. The regex matches the *rest* (text after the article header number).

### Patterns

- `المادة N من قانون X` — article N of law X (cross-reference)
- `المادة N المكررة من قانون X` — article N bis of law X (cross-reference)
- `من <instrument>` — direct "من" + instrument noun (no intervening word)

### The `ال?` vs `(?:ال)?` pitfall

In Arabic regex, `ال?` means "ا" + optional "ل" — the `?` binds only to the immediately preceding character (ل), NOT the whole "ال". So `ال?` matches "ا" or "ال", never empty. To make the definite article optional, use `(?:ال)?` — this matches empty or "ال".

**Rule**: When making an Arabic definite article optional in a regex, always use `(?:ال)?`, never `ال?`.

### Article order patterns

Three distinct root causes for `article_order` errors:

1. **High-number-first** (cross-ref false article): A preamble citation like "المادة 16 المكررة من قانون المالية" parsed as article 16, appearing before article 1. Fix: cross-reference rejection in `_CITATION_TAIL_RE`.
2. **Transposition** (OCR reading-order): Adjacent articles swapped (e.g., `[...19, 22, 20, 21...]`). Hard to fix generically.
3. **Digit misread / repeat** (OCR noise): Repeated or garbled digits (e.g., `[1, 82, 82, 82, 2, 347, 347]`). Hard to fix generically.

## Debugging workflow

1. Identify the error code from the quality report.
2. For `empty_text`: check if the doc is vision-parsed (`mode="vl"`) and has structure content. If so, it's a false positive — fix `_text()`.
3. For `article_order`: sample the flagged doc's article sequence. If high-number-first, check for cross-references. If transposition/repeat, it's OCR noise.
4. For `missing_title`: check if the title extractor matched the document's format. The parser has a title-fallback mechanism.
