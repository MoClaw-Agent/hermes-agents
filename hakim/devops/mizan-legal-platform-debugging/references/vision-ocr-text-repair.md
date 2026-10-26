# Vision OCR text repair: footnote markers, cross-references, and cache staleness

Depth for diagnosing and repairing systematic defects in vision-OCR text before
they reach `build_tree`. Companion to `references/ocr-extraction-truth.md`.

## BO footnote markers glued onto article numbers

The Bulletin Officiel prints a superscript footnote number immediately beside
each article header. Vision models reading left-to-right merge the marker into
the article digits:

```
true «المادة 4»  with footnote ⁵   →  OCR reads  «المادة 54»
true «المادة 5»  with footnote ⁶   →  OCR reads  «المادة 65»
true «المادة 16» with footnote ¹⁵  →  OCR reads  «المادة 1615»
```

Verified on ظهير 1.17.109 (20 pages): the PDF text layer carries the
footnote as a separate 11.5pt span next to the 18pt header («المادة4» + «5»),
and vision glued all six markers (54, 65, 78, 89, 1615, 1717). Each glued
number filled exactly one gap in the 1–53 sequence.

### Detection

The pattern is systematic and testable:

1. Collect standalone `المادة N` header lines in reading order.
2. Walk the sequence tracking the expected next number (previous + 1).
3. When `N ≠ expected`, try splitting `N`'s digits (prefix or suffix) to find
   a value equal to `expected`.
4. If a split matches, replace `N` with that value.

On 1.17.109 this produced exactly 6 corrections, all verified against the PDF
text layer. On clean documents nothing matches the first condition.

### Fix

`_repair_glued_article_numbers()` in `vision_pipeline.py` implements the
correction. It runs on fresh vision output before caching, so the repaired text
is what gets stored and structured.

Key constraints:
- Only touches standalone header lines (`^المادة <digits>$`) — never body prose.
- Only fires when the number does not match the expected next article AND a
  split of its digits equals that expected value.
- When no split matches, the number is left exactly as OCR produced it.
- Tracks the CORRECTED previous value (not raw) so consecutive repairs work.

## Cross-reference patterns: amendment notes and constitutional decisions

Vision OCR splits amendment notes into isolated header lines. The following patterns in `_CITATION_TAIL_RE` reject them:

- `^\s*["""\u201c\u201d]` — quote mark after article number (amendment note split by OCR)
- `^من\s+أن` — "from that" cross-reference (e.g., `المادة 121 من أنه`)
- `^والبند` — "and the article" cross-reference (e.g., `المادة 54 والبند الأخير`)
- `^المرسوم\s+رقم` — cross-reference to another decree (e.g., `المادة الأولى المرسوم رقم`)
- `^المصرح\s+بعدم\s+مطابقتها` — constitutional court decision reference

Additionally, `_CROSS_REFERENCE_TAIL_RE` has `^\s*["""\u201c\u201d]` to reject bare header lines followed by quote-starting lines (OCR split the header from its citation body).

**Verified**: ISM 1.15.83 went from 262 articles (6 phantoms) to 256 (correct) after adding these patterns.

### Additional cross-reference patterns (added after systematic audit)

These patterns were identified by auditing phantom articles across multiple documents:

- `^تطبيقاً?\s+للمادة\s+\d+\s+من\s+القانون` — "pursuant to Article N of the Law" (with optional tanwin)
- `^تطبيق\s+المادة\s+\d+\s+من\s+القانون` — variant without tanwin
- `^في\s+المادة` — "in Article" cross-reference (e.g., `المادة 6 في المادة 6 المكررة مرتين`)
- `^[:：]\s*$` — colon at end of line (isolated header from amendment note)
- `^انظر\s+المادة` / `^انظر\s+المادتين` — "see Article" cross-reference
- `^السابقة\s+الذكر` — "aforementioned" cross-reference pointer
- `^منه(?:ا)?\s*؟` — "thereof?" with Arabic question mark

**Key insight**: Diacritics (harakat) must be optional in regex patterns. The word `تطبيقاً` has a FATHATAN (U+064B) that OCR may add or drop. Use `تطبيقاً?` (optional tanwin) rather than separate patterns.

**Verified**: ISM 1.14.192 went from 36 articles (7 phantoms) to 29 (correct) after adding these patterns.

## Cross-reference pointer gap: بعده not covered

`_CITATION_POINTER_RE` in `structure.py` rejects header-shaped lines followed by
back-reference words. `أعلاه`/`أدناه` ("above"/"below") were covered, but
`بعده`/`بعدها`/`بعدهما` ("after it") were not — despite being the same class.

Real case: «أحكام المادة 36 بعده.» ("the provisions of Article 36 below") inside
article 28's body became a phantom article 36 after `_split_runon_article_headers`
extracted it to a standalone line.

Fix: extend `_CITATION_POINTER_RE` to cover `بعده|بعدها|بعدهما|قبله|قبلها|قبلهما`.

Verify the extension does not reject genuine article openings (e.g. «المادة 12
إذا كانت نسخة» must still match).

## Bis (inserted) provisions and the quality gate

Amendments insert provisions into existing instruments. The inserted provision
reuses its base article's number with a `مكرر` (bis) marker:

```
1, 1(bis), 2, 11(bis), 2(bis), 3, 4, ...
```

The `article_order` quality check must exempt `bis` articles from monotonic
ordering — they legitimately sit out of numeric position by design.

Fix: `ingestion/quality_validation.py` — `bis` articles are excluded from both
the `article_order` check and the `article_numbers_ordered` metric (shared
helper, so they cannot disagree).

## Vision cache staleness

Repairs applied to fresh vision output do NOT automatically apply to cached
vision text. When pipeline code changes that affect text post-processing:

1. Delete the relevant cache files in `data/corpus/<provider>/cache_vision/`.
2. Re-run the parser — it will call the vision service again and apply repairs.

Symptom: a fix is committed but the JSON still shows old numbers. Check the
cache file mtime vs the fix commit.

```bash
# Check if a cache file predates a fix
stat -c '%y  %n' data/corpus/adala/cache_vision/*<stem>*_vision.json

# Delete and re-parse
rm data/corpus/adala/cache_vision/*<stem>*_vision.json
venv/bin/python -m fetching.adala.parser --file <pdf> --force
```

## Annex boundary detection

Moroccan decrees include annexes (الملحق رقم N) after the last article. Without annex boundary detection, all annex content gets absorbed into the preceding article's node.

**Detection**: A single article node has 9000+ characters and contains text like `الملحق رقم 1 نموذج رسالة الملاحظات`.

**Fix**: In `build_tree()`, detect lines matching `^\s*الملحق\s*(?:رقم\s*)?\d+` and create a separate `annex` node. The annex node accumulates subsequent lines as its content.

**Verified**: decret 2.19.720 article 10 went from 9305 chars (with 3 annexes absorbed) to 362 chars (clean), with 3 separate annex nodes.

## Compound Arabic ordinals

Arabic compound ordinals (الرابع والعشرون = 24) are truncated by `_ordinal_int()` because it only looks up single tokens in `AR_ORDINAL_MAP`.

**Fix**: Extend `_AR_ARTICLE_HEADER_RE` to capture the optional `وال(?:عشرون|ثلاثون|...)` suffix, and extend `_ordinal_int()` to parse compound ordinals by splitting on `وال` and summing the parts.

**Indefinite tens forms**: `_AR_TENS_WORDS` only had definite forms (العشرون, الثلاثون, ...). Vision OCR often drops the definite article. Added indefinite forms (عشرون, ثلاثون, ...) and ش-suffix variants (العشرين, الثلاثين, ...).

**Verified**: `الفصل الرابع والعشرون` → 24 (was 4), `الفصل الثالث والثلاثون` → 33 (was 3).

## Cloudflare Tunnel URL changes on every Colab restart

The tunnel URL (`*.trycloudflare.com`) is ephemeral. After each Colab runtime
restart:

1. Re-run the tunnel cell in the notebook.
2. Copy the new URL.
3. Update `VISION_OCR_BASE_URL` in `.env`.

Symptom: parser times out on every file. Check with:
```bash
curl -s --max-time 10 https://<tunnel-url>/v1/models
# DNS resolution failure = tunnel is down
```

## extract_pages() returns a 3-tuple

`extract_pages()` returns `(native_pages, ocr_pages, cache_pages)` — NOT a
2-tuple. Code that unpacks two values will fail. This has caused confusion in
debugging sessions.

```python
native, ocr, cache = extract_pages(pdf_path)
# or
pages = extract_pages(pdf_path)[0]  # native only
```
