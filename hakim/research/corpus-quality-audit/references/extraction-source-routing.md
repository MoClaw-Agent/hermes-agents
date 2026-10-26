# Choosing an Extraction Source for a Legal Corpus

Which text source to trust, and how to route OCR per provider.

## The digit-transposition defect

Some Bulletin-Officiel-style PDFs ship a broken RTL `ToUnicode` CMap. The
glyphs decode to correct Unicode *letters* and correct *prose*, but digit runs
come out transposed by a straight glyph swap of `1` and `4`:

| printed | native text layer | OCR |
|---|---|---|
| `19.94` | `49.91` | `19.94` |
| `1439` | `4149` | `1439` |
| `1999` | `4999` | `1999` |
| `1.00.484` | `4.99.4` | `1.10.26` |

The layer looks clean. Nothing flags it. A citation index built on it points at
a different instrument than the one printed.

**Always establish which source is correct from the rendered page before
routing anything.** Do not infer it from a disagreement between extractors.

## Routing: `OCR_FIRST`

Two declared settings, both in `.env`, both scoped:

```
OCR_FIRST=false              # master switch
OCR_FIRST_PROVIDERS=ism      # comma-separated allow-list
```

When enabled for a provider, documents bypass the text layer and OCR every
page. Keep this **per-provider**: `pipeline_base/extraction.py` is shared by
ism, sgg, adala, bdj, dgssi and jurisprudence, so a global switch would force
OCR on corpora with healthy text layers at ~230 s/page.

**Pass the provider explicitly; never infer it from the path.** The gate takes
`provider="adala"`. Every provider parser knows its own name, so reading it off
the filesystem is a liability: an implementation that required a path segment
literally equal to `corpus` and took the *next* segment as the provider matched
`data/corpus/<provider>/…` and silently matched nothing under
`data/corpus_consolidated/`, where the provider lives in the filename. A
path-based fallback may remain for the shared cascade, but it must match the
provider directory against the allow-list rather than assert a literal root
name.

**A setting can have more than one independent reason to be inert — fixing one
proves nothing.** This flag was simultaneously (a) placed inside the final
`else:` of the extraction cascade, so the `cid_fonts`, `scanned` and
`native_small` branches never reached it — and ADALA's Arabic PDFs classify
almost entirely as `cid_fonts` — and (b) failing the path test above. Either
alone disables it. When a switch appears inert, enumerate every place that
reads it and test the gate function directly against the **configured input
path**, not just the code path you are reading.

**Enforce it in the provider's own native-first gate, not inside
`extract_pages`.** Each provider already decides native-versus-vision OCR:

```python
if mode in ("ocr_forced", "ocr"):
    native_usable = False
if _ocr_first_enabled_for(provider="adala"):     # or "ism"
    native_usable = False
```

That route uses the provider's **configured** engine and stays behind
`_vision_structure_usable`. Forcing OCR inside the shared cascade instead
hardcodes one engine across the fleet — and the obvious choice is the wrong
one: PP-OCRv5 is documented as systematically dropping Arabic article-header
digits that EasyOCR/Qari recover, so a hoisted `_paddle_ocr_pages` call makes
citations worse while looking like a fix.

Note also that the sufficiency test a provider applies measures **structure,
not correctness**. A text layer can carry every article and still have wrong
digits, which is the exact defect the flag exists for — so "the native layer
looked fine" is not a reason to skip the gate.

**Default to provider scoping, not detector gating.** A digit-reversal detector
cannot see swapped *dotted* references (see below), so gating on it silently
skips the very files it was meant to protect. Enable OCR_FIRST per provider
that has been *verified* affected; leave the rest on the text layer.

## Per-page source selection (neither source dominates)

Provider-level routing decides *which engine* runs. This is the finer decision,
*inside* one document: which of two available texts to build each page from.

Measured on a 207-page code, the two sources fail in opposite directions:

| | native layer | vision OCR |
|---|---|---|
| article headers | intact (`الفصل 58`) | dropped on dense pages |
| compound headers (`الفصل 1-35`) | shredded across lines — 4 of 137 | intact |
| lam-alef ligature | corrupt (968 `األ`, 338 `اال`) | clean |
| word-level text | shredded | clean |

**Choose per page, by DISTINCT article identities** (rule 0ac): the source
contributing more `(number, label)` pairs wins; ties go to the OCR route (cleaner
word-level text); a page the OCR route left empty is filled from native.

Two guards are required, and both were found by measurement rather than design:

1. **Raw header counts are the wrong score.** Cross-references match the header
   pattern, so the poorer page wins on 20 pages and 54 compound provisions are
   discarded. Count distinct identities.
2. **The native layer must compensate for the compounds it would lose.** It
   cannot represent `الفصل 1-35` (4 of 137), so it must beat the OCR route by
   *more* than the number of compound identities it would drop. Without this,
   pages are won on one extra ordinary article while several real provisions are
   silently discarded.

Then suppress bare-number phantoms per page — the native layer breaks dates
across lines, and the bare-number fallback turns each fragment into an article.
See `references/article-header-detection.md`.

### Validate a merge/selection change across many documents, not one

A per-page rule is a global behaviour change; one document cannot justify it.
Replay the rule over every cached document and report, per document, the mean
distinct-article count and the mean phantom count for each candidate (source A,
source B, the new rule), plus a win/lose/tie tally against the current behaviour.
Measured on 116 cached documents: mean distinct articles 32.3 → 33.5, mean
phantom nodes 0.2 → 0.4 (source B alone would be 3.4), better on 44 documents,
worse on 6, equal on 66. **Inspect every regression individually** — a rule that
wins on aggregate while wrecking six documents is not ready.

## Detector limits

A reversal detector needs the extracted token to be implausible as printed and
plausible once the `1<->4` swap is undone. That works for bare years and fails
for dotted references — `19.94` and `49.91` are both well-formed. Distinguishing
them needs a corpus of real references.

So: detect bare years, document the limitation in the docstring, assert it as a
test case, and never treat `False` as proof a text layer is sound.

## OCR backend reality

- Requests are per-page and serialised; a long document is hours.
- A dropped page is invisible in the output unless you count. Log
  transcribed/total, record failed pages in metadata, and treat a shortfall as
  a parse failure.
- Failures are often image-specific backend crashes
  (`model runner has unexpectedly stopped`), not size limits. Sweep every page
  individually and record status + pixel dimensions before theorising; all A4
  pages render to identical dimensions, so a size theory is refuted by a small
  payload failing.
- Resolution has real accuracy cost in Arabic. Below roughly 500K pixels,
  visually-similar letterforms collide (`جنازة`/`جائزة`, `المعبوم`/`المرسوم`).
  Measure before raising or lowering it, and expect lowering it to reintroduce
  those errors.

## Verification checklist for a routing change

1. Establish the correct digit values from the rendered page.
2. Sweep one document page-by-page through the OCR backend; record failures.
3. Parse one file end-to-end and read the counts and the digits out of the JSON.
4. Confirm the document's own reference number survives — if
   `metadata.reference_number` is `None` after an OCR parse, the OCR dropped
   the citation and the routing is not delivering what it promised.