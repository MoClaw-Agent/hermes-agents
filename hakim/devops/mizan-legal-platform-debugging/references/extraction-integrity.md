# Extraction Integrity — deciding what the parser actually consumed

Applies when parsed output looks wrong (missing articles, scrambled order,
implausible numbers) and you must decide whether the fault is the parser, the
PDF, or the extractor.

## The rule that governs everything else

**Never derive ground truth from the artifact under test.** The PDF text layer
is the thing most likely to be corrupt; grading OCR output against it produces
confidently inverted conclusions. Verify at least one sample against the
*rendered page* before reporting any number as correct or wrong.

Concretely: if you report "OCR drops digits" or "OCR is clean", you have
compared OCR against `fitz.get_text()`. That is not a verdict. Have someone
read the printed page, or render the page and read it yourself.

## Choosing a ground truth source, in order

1. **Human read of the rendered page** — slowest, only method that settles it.
   Ask for one file, not a corpus.
2. **Rendered page read by vision** — good, but rate-limited hard; batch
   several questions per image and expect HTTP 429 between calls.
3. **Internal consistency** — no human needed. A gazette page pairs a Hijri
   year with a Gregorian one; if OCR yields `16 من رمضان 1432 (17 أغسطس 2011)`
   the numbers are right, because no reversal produces a valid pair. Hijri
   1000–1500 and Gregorian 1900–2100 are the plausible ranges.
4. **Never** the raw text layer of the file you are diagnosing.

## RTL ToUnicode CMap digit transposition

ISM Bulletin Officiel scans ship a broken CMap that swaps digit glyphs
**1 ↔ 4**. The extracted prose reads perfectly; every legal reference is wrong.

```
printed 19.94     extracts as 49.91
printed 1439      extracts as 4149
printed 1999      extracts as 4999
printed 1.10.26   extracts as 4.99.4
```

It is a glyph swap, **not** a string reversal — do not look for reversed
digit order, you will find nothing and wrongly conclude the layer is fine.

Detection: `pdf_quality.is_digit_reversed()` — a 4-digit run is evidence when
it is *not* a plausible year but becomes one after undoing the 1↔4 swap.
Thresholding is unreliable; treat it as a diagnostic, not a routing gate.

**Hard limit: it cannot see dotted references.** Detection needs the extracted
token implausible-as-printed and plausible once the swap is undone. That holds
for bare years (`4149` → `1439`) and fails for references: printed `19.94`
extracts as `49.91`, but *both* are well-formed references, so nothing local
separates them. Separating them would need a corpus of real references, which
does not exist here. A `False` result is therefore **not** evidence a text
layer is sound — it is the only case this function cannot see. Assert that
limitation as a test case so it is not quietly forgotten, and never gate
routing on it.

Note the existing `is_reversed_arabic()` detects whole-text visual-LTR order
and does **not** catch this. Different defect, different function.

## OCR line-breaking manufactures fake containers

OCR does not preserve a header's line boundaries. A citation and the prose
that follows it get glued into one line, which the parser then reads as a
header:

```
الفصل 96 من مدونة التسجيل تصير مستحقة مع زيادة نسبة 25% من م
الفصل 40 المكرر مرتبين من نفس المدونة محسوبة من تاريخ مضي أج
```

`الفصل N` here is an in-body cross-reference, not a container. It becomes a
chapter node, everything under it is re-scoped, and a document whose numbering
restarts per chapter suddenly shows dozens of "duplicate" identities.

This is a defect at the **OCR boundary, not in the parser** — `build_tree` is
faithfully parsing malformed input. It appears only in `ocr_forced` output;
the same file's native text layer parses cleanly.

**Do not diagnose it with a synthetic fixture.** A hand-written
`الفصل 40 المكرر ...` line stays inside its article on the native path, so the
fixture passes and the real defect looks absent. Reproduce on actual OCR output
from the real file before concluding anything about the parser.

## OCR output is a different SHAPE than the native text layer — validate detectors on the shape you actually ship

The container defect above was found on OCR output only; the native layer parsed the
same file cleanly. That asymmetry generalises: **anything that keys on line structure
fails on OCR text, because OCR frequently returns a page as one unbroken line.**

Measured on a BO contents page under `ocr_forced`:

```
page 16: 410 characters, 0 newlines
```

One line. And OCR **dropped the dot leaders entirely** — page references appear as
bare `4`, `8`, `9`, `10.` with nothing between them. A TOC detector written as
"count lines carrying a dot run, require a majority" sees exactly one line, bails on
its `len(lines) < 3` guard, and **never reaches its marker fallback**. The contents
page is then parsed as nine real chapters, re-scoping every article beneath it and
manufacturing duplicate identities.

This bit twice: the detector was written and unit-tested against the native text layer
and assumed OCR would behave the same. It does not. A fix declared complete on the
native path can be absent on the OCR path for a reason no test on that path would catch.

**Test on the actual OCR string, read out of the extraction cache — never a
reconstruction.** A hand-built imitation of the OCR page *passed* the detector while
the real text failed, because the imitation kept the dots and line breaks the real
output lacked. A reconstruction is a fixture that agrees with your model of the data
rather than the data.

```python
raw = json.load(open('data/corpus/ism/cache/<stem>_<hash>.json'))
ocr_page = raw['pages'][15]          # the string that actually shipped
assert _is_toc_page(ocr_page)        # test against THIS
```

**Give an unstructured-text path its own signal.** When the line-based test cannot
apply, test the flattened text for the structural signature instead:

```python
flat = " ".join(page.split())
if _TOC_MARKER_RE.search(flat) and len(_TOC_DENSE_HEADER_RE.findall(flat)) >= 3:
    return True     # marker + a dense run of sibling container headers
```

A contents page is a dense run of near-identical sibling headers (`فصل`/`باب`/`قسم`
+ number), which a legal body page is not. Assert both shapes in the test: the native
page with dot leaders, the real OCR page without them, and at least two body pages
that must not fire. Confirm the flag list across every page of a real file, not just
the one you fixed.

**Ask what shape the input has before choosing a detector.** `p.count("\n")` on the
text you are about to parse answers it in one line.

## OCR-first is opt-in, per provider

```
OCR_FIRST=false            # master switch
OCR_FIRST_PROVIDERS=ism    # comma-separated allow-list
```

The gate lives in `fetching/pipeline_base/extraction.py` and derives the
provider from the `data/corpus/<provider>/` path segment, so it needs no
per-call-site changes. It runs before the native-quality checks and skips
documents already classified `scanned`.

Do not make this global. `extraction.py` is shared by ism, sgg, adala, bdj,
dgssi and jurisprudence; a global switch bills ~230 s/page for every corpus
including ones whose text layers are healthy.

## A landed fix is not delivered until it is documented and indexed

Writing a doc, adding a CHANGELOG entry, and updating `.env.example` does not
finish the job. A file nothing links to is orphaned: nobody finds it, and the
defect it documents recurs. This was caught only because the operator said "fix
the doc list" after a doc had already been written, changelogged and
env-updated.

This repository has its own required-update rule in `doc/DOCUMENTATION_STATUS.md`,
which classifies documents as **current instructions** versus **historical
evidence**. A new document is live documentation and must be registered as such.

Register in all three, every time:

1. **`doc/README.md`** — the navigation table ("Diagnose X issues → `[X.md](X.md)`")
   and the reference list at the bottom.
2. **`doc/DOCUMENTATION_STATUS.md`** — under **Source of truth** for the area it
   covers, and under **Current documents**. Bump its **Reviewed:** date while
   you are there.
3. **`CHANGELOG.md`** and **`.env.example`** — every new setting gets an entry in
   both, with the evidence behind the default.

State each fix's *limit* alongside its claim. "Cannot detect dotted references",
"a bare `الفصل 26` mid-sentence still becomes a chapter", "a partial OCR parse
completes rather than failing" — a doc that lists only what works will be trusted
past the point where it stops being true.

While inside `DOCUMENTATION_STATUS.md`, check its "Known intentional differences"
list against the code. Two claims there named an OCR engine this codebase does not
use. Fix a stale claim only when you verified current behaviour directly — an
unverified "correction" is the same error in the other direction.

When a working plan is partly wrong, do not leave the retracted findings in it.
Replace it with a status document carrying the corrections and linking to verified
detail; a plan file that keeps a fabricated finding misleads the next reader.

## Article-count debugging order

Before touching the parser, establish which layer produced the text:

1. Check `extraction_mode` in the JSON (`native` vs `ocr_forced`). A
   `native` result means OCR never ran — config or routing, not parsing.
2. Compare the count against the printed page. A 30–40% shortfall on a
   "clean" file is normal until proven otherwise; do not trust a screen that
   reports "no year signature".
3. Only then debug the parser.

Known-good fixes already landed in `fetching/pipeline_base/structure.py`,
each with a regression test:

- Article dedup keyed `(part, book, chapter, number, qualifier)`. A
  document-global key silently collapses articles in codes that restart
  numbering per chapter — worth ~30% of all articles corpus-wide.
- Header junk class `[\s.·‧․]*` between keyword and number, so `الفصل.1`
  parses. Use `*`, not `+`; `+` breaks headers with no separator.
- TOC page detection: ≥3 dot-leader lines plus either leader-majority or an
  explicit `فهرس`/`محتويات` marker, **plus an unstructured path** for OCR text
  that arrives as a single newline-free line with the leaders stripped. The
  line-based half alone cannot see an OCR contents page.
- Bare-digit nodes whose content is only dot leaders or a date are page
  furniture, drop them.
- Container cross-reference rejection. `_container_hit` had none, unlike the
  article detector. A citation carrying number `1` (`الفصل الأول من مدونة
  الجمارك ... المشار إليها في`) shadowed a document's real chapter 1, re-scoping
  its articles and manufacturing the duplicate failures. 12 chapters -> 8.
- Citation pointers: `المادة 20 أعلاه` is a back-reference, not an article.
  The marker sits **immediately** after the number, whereas a real article opens
  with its operative verb or noun (`المادة 35 يجوز ...`)، so
  `^\s*(أعلاه|أدناه|اعلاه|ادناه)` is a precise discriminator — include
  `\s*` because OCR drops the space (`المادة 12أعلاه`).
- **Validate to the same scope the parser uses.** `duplicate_article_number`
  and `article_order` compared `(number, bis)` across the whole document while
  dedup was chapter-scoped, so every document the dedup fix rescued failed the
  gate. Identity is `(chapter, number, bis)` and ordering is checked *within*
  each chapter. A parser fix that makes structure more correct can break a
  validator that was written against the parser's old, wrong behaviour — when
  one changes scope, check whether the gate shares the assumption.

## Re-measure after every fix before reporting a number

Fixes interact, and a count reported mid-investigation describes the state at
that moment. On the same document across one session: 25 -> 39 -> 52 -> 50 ->
46 -> 55 articles, 12 -> 8 -> 18 -> 9 chapters, with two quality errors that
changed *identity* rather than count. Some of that movement was fixes landing;
some was a fixed file re-parsed by a newly-fixed path.

Report a count as belonging to a specific set of fixes, and re-measure when
another change lands. A number quoted without its fix-set is not a fact about
the document.

## Pitfalls that cost real time

- **`.env` duplicate keys: the last value wins, silently.** Adding a setting
  that already exists does not error — it overrides. Grep for `^SETTING`
  before editing and after, and confirm the effective value through
  `settings`, not the file.
- **Never `git stash` while a live test run is importing those files.** It
  swaps source out from under the run and can leave your work sitting in the
  stash when the process is killed. Recovering work outranks finishing a
  measurement.
- **Regression baselines need two runs.** Diff `FAILED` lines against a run
  with the change stashed; a single run tells you nothing. Store snapshots
  outside `/tmp`, which can be cleared mid-session.
- **A self-test that validates the rule is not the same as one that
  validates the outcome.** Write the test against the file you care about.
- Flaky concurrency tests (`test_phase9_checkpoint_integration`) appear in
  full-suite runs; re-run in isolation before attributing them to your change.

## Before claiming a corpus is usable

Article counts being right does not make article *numbers* right, and
citations are keyed on the numbers. Report structure and digits as separate
claims, and say which files were hand-verified — "44 articles" means nothing
without saying who counted 44.