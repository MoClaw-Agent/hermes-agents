# ISM OCR / extraction: which text is the truth

Applies when auditing an ISM document's JSON against a human count, or when
article counts disagree with what a person sees in the PDF.

## Two OCR passes exist. Find out which one built the tree.

`extract_pages()` writes the **extraction cache**
(`data/corpus/<provider>/cache/<stem>_<hash>.json`).

The ISM parser separately runs a **vision rescue** (`extract_vision_pages`,
gated by `_vision_structure_usable`) and prefers it for CMap-corrupt legal
PDFs. That pass is the expensive one — a full VLM transcription of every page.

Before the persistence fix the vision result was never written anywhere: it
existed only in memory. So the JSON's `structure` could be parsed from text
that did not exist on disk, while `full_text_in_cache: true` pointed at
*different, lower-quality* text. Anyone auditing from the cache reads the wrong
document.

The output JSON now carries `structure_source` (`vision` | `extraction`) and
`structure_text_cache`. **Check those first**, then audit the file they name.

Confirm artifact identity before reading content — cheapest checks first:

```bash
stat -c '%y  %n' <output.json> data/corpus/ism/cache/<stem>_*.json
```
Then probe distinctive strings from the JSON's node text against the cache. If
they are absent, you are looking at the wrong artifact. Cache files are keyed
`<stem>_<hash>` and the stem is only unique within a domain, so two documents
can share one.

## A low article count is often an operational fallback, not a parser bug

Before touching any regex or tree-builder, prove where the loss happens by
running the tree builder on each candidate text source directly:

```python
from fetching.pipeline_base import build_tree
tree_v = build_tree(vision_pages, document_language="ar")   # the vision cache pages
tree_e = build_tree(extract_pages_pages, document_language="ar")  # PP-OCRv5 / native
# count distinct article nodes in each
```

If `build_tree` yields the true count on the good text, the parser is fine and
the defect is upstream: the wrong text reached the tree. In one audit this
single probe ended a long regex hunt — `build_tree(vision_pages)` gave **197**,
`build_tree(ppocr_pages)` gave **40**, and the JSON had been built from the
latter because the vision pass timed out and fell back silently.

**Prove the text source, then look at the pipeline that chose it.** Reach for
`structure_source` in the output JSON: `vision` means the vision pass won;
`extraction` means it did not — and (unless a degraded flag says otherwise) a
plain `extraction` value is ambiguous between a clean native layer and a silent
fallback. When the count is wrong and `structure_source` is `extraction`, suspect
the fallback path before the parser.

## Confirm which tree is live before quoting counts

An article count is only meaningful for the tree that is actually being written.
Before reporting "the cache has N articles", confirm the directory is the live
output, not a backup or an older run:

```bash
stat -c '%y  %n' <live_json_dir> <suspected_backup_dir>   # newest writer wins
```

Reading a count out of a backup and reporting it as current produces a
confident wrong answer. The consumer's configured path (e.g. `JSON_DIR`,
`CACHE_VISION_DIR` from settings) is the source of truth, not whichever
directory happens to contain the number you were hoping for.

## Measure the OCR engine's fidelity BEFORE writing parser rules

When parsed structure looks wrong, the first question is not "which parser rule
is broken" — it is **does the OCR text still contain the ground-truth
markers**. A parser can only segment markers that survived extraction. If the
engine already dropped or merged digits, no header rule can recover what is not
there, and every fix applied upstream of that finding is wasted work.

Run the engine on a page whose article numbers you have read off the rendered
image, and diff:

```python
doc = fitz.open(PDF); doc.select([page - 1])
out = _paddle_ocr_pages(tmp, "ar")            # or the vision backend
found = [m.group(1) for m in re.finditer(AR, out)]
# compare against the numbers you read off the image yourself
```

Measured on `droit_administratif/1.pdf` page 35, printed articles 109–114:

| printed | PP-OCRv5 |
|---|---|
| المادة 109 | `المادة9` — leading digit dropped |
| المادة 110 | absent |
| المادة 111 | `المادة11` — trailing digit dropped |
| المادة 112 | absent |
| المادة 113 | absent |
| المادة 114 | `المادة114` — correct |

Three of six wrong at the engine, before any parsing. PP-OCRv5 also returned
the page as **one continuous block with zero line breaks**, so correct markers
arrive mid-sentence even when present.

Corollary for audits: an article whose header is absent from the OCR text is
not "swallowed by the parser" — there is nothing to split on. Confirm by
searching the previous article's content for the article's opening words; if the
text is there with no marker before it, the boundary was destroyed upstream.

**Do not generalise one engine comparison.** Native vs vision across five
ADALA documents: vision won on 2, native on 3 — and the single best result was
native (43 distinct numbers, one gap). The best source is per-document, so
measure the document you are auditing rather than adopting a global winner.

### Score both header orders, or a perfect engine reads as total failure

A vision engine can emit every article number correctly and still score zero,
because it renders headers in visual clip order: `109 المادة` rather than
`المادة 109`. Measured here — the engine returned 109/110/111 … all correct,
with 31 line breaks against PP-OCRv5's 0, and a keyword-first scorer reported
**MISSING all six** on it.

The number is right and the ordering is a rendering artefact the parser already
resolves, so a scorer that matches one order measures its own regex. Accept
either order:

```python
BOTH = re.compile(
    r"(?:الماد[\u064e\u0640]?[ةه]?\s*([0-9\u0660-\u0669]+)"
    r"|([0-9\u0660-\u0669]+)\s*الماد[\u064e\u0640]?[ةه]?)"
)
n = to_int(m.group(1) or m.group(2))
```

Before reporting an engine as failing, print the raw text around its first
marker and read it. A run that emits a plausible-looking number sequence is
either working or broken — it is never both, and the scorer decides which
message you send, not the engine.

## OCR-first is engine-pinned in code, not by the flags it looks like

The `OCR_FIRST` branch called `_paddle_ocr_pages` unconditionally, so
`OCR_PARSER_USE_PADDLE_VL=true` could not redirect it and `OCR_FIRST=true` sent
every ISM document to PP-OCRv5 regardless of `VISION_OCR_ENABLED`. Read the
branch before assuming a flag selects an engine; if the engine is hardcoded, the
setting is inert.

It now selects via `OCR_FIRST_ENGINE` (default `vision` when
`VISION_OCR_ENABLED`), keeps PP-OCRv5 as the offline fallback, and caches to
`cache_vision/`.

Also note the vision route is a **contender**, not the primary: it replaces the
extraction text only when `_vision_structure_usable` wins the comparison. That
comparison picks on article count, and an engine that invents plausible numbers
can win on the wrong criterion. Enablement is not ordering.

Vision output lives in `data/corpus/ism/cache_vision/<stem>_vision.json`, kept
apart from `cache/` because two engines write different text for the same PDF
into what was one directory.

## Score against distinct numbers, never container nodes

Counting parsed nodes overstates recovery badly. A run reporting 255 nodes may
hold only 166 distinct article numbers.

```python
seen = {int(m.group(1)) for m in re.finditer(r'الماد[ةهة]\s*(\d+)', alltext)}
missing = sorted(set(range(1, GROUND_TRUTH + 1)) - seen)
```

Report both numbers, and name the gap as contiguous runs — contiguous gaps mean
a whole region of text was lost, which is a different defect from scattered
misses.

## Native ISM text layers transpose digits

The CMap in BO/ISM PDFs maps some digit glyphs to the wrong code point, so
extracted numbers are silently wrong (`19.94` prints, `49.91` extracts). Never
treat native numbers as ground truth, and never recover a legal reference by
regex over native text. It is also why filenames and refs cannot be derived
pre-parse.

## Headers lost to Arabic diacritics and tatweel

OCR intermittently emits combining marks inside the keyword:
`المادَة 21` (U+064E FATHA), `المـادة 7` (U+0640 TATWEEL). `is_article_line`
rejects every such spelling, so the header never resolves and the article's
text is absorbed into the preceding article — which is how whole provisions go
missing while the node count looks plausible.

Fix belongs in `_header_candidates`, which already absorbs lam-alef ligature
and dropped-hamza variants: add a mark-stripped candidate, as an *additional*
variant, never a blind rewrite of the line.

- **Delete the marks, never substitute a space.** `المـادة` → `"الم ادة"` with
  a space still fails to match.
- Strip only on the candidate copy so every other spelling path survives.
- Covered ranges: U+0640, U+064B–U+065F, U+0670, U+06D6–U+06ED.
- Build the table from codepoint ranges; `str.maketrans` rejects multi-char
  keys.

## Verify a claimed defect's contexts before fixing it

Counting regex hits in a container is not a defect. Nodes containing several
`المادة N` occurrences were nearly all ordinary in-body cross-references —
`وِفْقاً لأحكام المادة 74 من القانون التنظيمي رقم 59.11`,
`البند 8 من المادة 22 أعلاه` — with nothing lost.

Print the surrounding text for every hit before writing a fix. Legitimate legal
prose is citation-dense; a regex count cannot distinguish a swallowed header
from a citation. Retract the claim when the contexts do not support it.

Related: legal prose also contains repeal/citation fragments shaped
`المادة N من هذا القانون ...`. A node matching that where N equals its own
declared number is a citation, not an article body. Do **not** drop such nodes
outright — many carry real content for a neighbouring article, and the correct
handling falls out once the diacritic fix lets the embedded header parse.

## Structure order

A preliminary block (`الكتاب التمهيدي`, `القسم التمهيدي`, or `القسم الأول`
titled `أحكام تمهيدية`) precedes the numbered sections. Order it explicitly;
OCR reflow routinely surfaces it late. Keep the rule narrow — guarantee the
preliminary block leads and leave all sibling order untouched.

## Output naming

JSON filenames prefer the reference number, then a sanitised title, then the
crawler ordinal. Reject placeholder titles so documents are not all renamed to
the same useless name, and disambiguate collisions with a path digest rather
than overwriting. Naming must happen **after** parsing — the ref comes from the
LLM metadata pass.

## Operational

```bash
MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \
  venv/bin/python -m fetching.ism.ism_parser --lang ar --retry-failed
```

Never a hand-rolled wrapper script: calling the runner at import time
re-enters under multiprocessing `spawn` and floods the log.

Watch for `ACCEPTED` vs `REJECTED` vs `unavailable` in the vision log — these
are three distinct outcomes and must not share a message.

OCR is the corpus bottleneck. Confirm whether the host is actually offloading
to GPU before quoting any per-page timing.