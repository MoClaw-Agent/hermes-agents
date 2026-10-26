# OCR provider quirks for legal corpora

Provider-specific defects found while ingesting Arabic legal corpora. Each entry
records the *signature* (how to detect it), the *consequence* (what it silently
breaks), and the *response*. Check the signature against a real document before
acting — a heuristic that cannot find a file you have confirmed is broken is
worse than no heuristic.

---

## Broken ToUnicode CMap: digit glyph transposition

**Signature.** A PDF's text layer reads fluently but its numbers are wrong.
Detect mechanically without reading any number by hand: find a 4-digit run whose
**reverse also appears in the same file**.

```
9591 -> 1959      (a Hijri/Gregorian year and its reverse)
4149 -> 1439      1<->4 glyph swap; 1 and 4 are near-identical in legal print
```

A run implausible either way (a bulletin number, a page marker) proves nothing —
ignore it. `9591` is not a year anybody printed.

**Consequence.** Silent and fatal for legal retrieval: prose reads correctly,
every legal reference is wrong, and nothing downstream flags it. A citation
index built on this points at the wrong instrument.

**Response.** OCR reads the rendered page and recovers the true numbers. Route
per provider — OCR costs orders of magnitude more per page than the text layer,
so only enable it where the defect is verified, never globally.

**The detector cannot see dotted references.** Printed `19.94` extracts as
`49.91`, and *both* are well-formed legal references, so no local plausibility
test separates them. Separating them needs a corpus of real references. Do not
build routing on a detector that cannot see the dominant defect form — and never
let a `False` result be read as "this text layer is sound".

**Validate against the printed page, never against the extracted text.** The
defective layer is the artifact under suspicion. Grading one source against
another inverts the evidence and will make a working OCR engine look broken.

---

## OCR returns one line per page

**Signature.** Page text arrives as a single line: zero newlines, header
markers present mid-sentence (`المادة يحدث بموجب...` — the number is gone or
inlined). Detected by counting newlines in the cached page text.

**Consequence.** Any parser anchoring on line-start sees nothing and the
document parses to zero articles. Chapter/article markers are still present in
the text; only the structure is missing.

**Prompts do not fix this.** Measured three variants on identical pages — the
production prompt, an Arabic line-ordering prompt, and a merged prompt with an
explicit "one output line per printed line" instruction. All returned zero
newlines, output similarity 0.93–0.99. Independent benchmarks agree: the
strongest frontier model reaches only ~65% accuracy on PDF-to-Markdown, so
structure is a capability ceiling rather than a prompting failure.

**Response.** Reconstruct structure on the parser side — split run-on text at
header markers that are *not* citations, before the line-start-anchored detector
sees them. Cheaper and more reliable than any model change, and it composes with
whatever OCR engine is in use.

**But first confirm the text that actually reached the parser.** A "the parser
lost articles" report is ambiguous until you know which text built the tree.
Rebuild it from the cached engine text and compare:

```python
import json
from fetching.pipeline_base import build_tree

pages = json.load(open(cache_path))["pages"]        # the engine's own output
tree  = build_tree(pages, document_language="ar")
print(sum(n.get("type") == "article" for n in tree))   # count article nodes
```

If this count is right, the matcher is not the defect — the parse consumed
different text. Check the output's provenance field (`structure_source`) and the
run log: a required engine that timed out and fell back to the cheap OCR
produces exactly this symptom, and the tree over the *fallback* text is what is
short. A correct matcher over the wrong text is indistinguishable from a broken
matcher; chasing the regex first wastes the session.

Also remember the cache can live in more than one place — a restored backup
directory is not the directory the parser reads. Resolve the expected cache path
from the same hash the parser computes before concluding the cache is missing.

---

## A timeout in a service behind a tunnel is the service's own request timeout

**Signature.** The client sees `{"status": "error", "error": "timed out"}` (or
the equivalent) after minutes of `pending`, while the service's own health probe
answers `200 ok` with `model_loaded: true`. Reachability and health are green;
the work never completes.

**Mechanism.** A health endpoint that only confirms the model server *responds*
(for example by calling `/api/tags`) does not prove the model can *generate*. A
wedged or OOM'd runner passes that probe and still never returns from a
generation request, so the worker thread blocks until its own per-request
timeout fires and the job is recorded as an error.

**Response.** Treat liveness, health, and the ability to actually generate as
three separate checks. Prove the last one with a real end-to-end request (post a
tiny image, poll the job to `done`) before reporting the endpoint as working.
When the job never completes, the fault is on the host side — check that the
server has the exact model tag pulled and that a runner is resident, rather than
re-testing the tunnel.

---

## Transient runner failures

**Signature.** The local model server intermittently answers HTTP 500 with
`{"error": "model runner has unexpectedly stopped"}`. Confirmed transient: the
same page succeeded and returned byte-identical output on retry. Not
size-related when every page renders to identical pixel dimensions.

**Consequence if unhandled.** The page is dropped and the parse continues, so
the document is silently incomplete — chapters vanish and downstream counts
look merely "off" rather than broken.

**Response.** Bounded retry with backoff on 5xx and transport errors. Do **not**
retry 4xx — a deterministic rejection just burns three round-trips. Log failed
pages at ERROR, never a warning: for a citation corpus a document missing a page
is worse than one that failed outright.

---

## Model runtime selection

**GGUF cannot be loaded by `transformers`.** Repos offering only `.gguf` files
plus a `mmproj-*.gguf` vision projector have no safetensors weights and no HF
`config.json`, so `from_pretrained` fails regardless of architecture class
detection. Load with `llama-cpp-python`, passing the projector separately as the
chat handler's `clip_model_path`.

**Projector quantisation must match the model's.** An F16 projector with a Q4
model is the usual cause of blank or garbled output. Tie both to one setting so
they cannot drift apart.

Check what the host already has before provisioning anything new — a model
already served locally removes an entire remote/tunnel/colab surface from the
problem.

---

## Endpoint config: base URL and wire format move together

An OpenAI-compatible `/v1/chat/completions` facade and Ollama's `/api/generate`
are different protocols. Pairing a chat-completions URL with the Ollama style
(or the reverse) 404s on every call while the server itself is perfectly
healthy.

Set both from one switch so they cannot drift, and **validate the configured
model name against the host's actual model list** — a single-character typo in a
model id fails every OCR call with no useful diagnostic. Probe each runtime on
its own endpoints: `/healthz` for an OpenAI facade, `/api/version` and
`/api/tags` for Ollama.

---

## One rejected page must not discard the pass

**Signature.** The log reports a required engine as "unavailable" after a
*single* page failed, and the whole document falls back to a cheap engine — so
the article count is wrong everywhere, not only where the page was. The giveaway
is a fallback line naming one page's failure ratio, immediately followed by a
document-wide fallback.

**Mechanism.** The transcribe helper's exception tuple omitted the error its own
job-polling branch raises (`RuntimeError` for `status == "error"`), so that error
escaped the retry loop. The page loop had no per-page guard, so it propagated to
the caller, which read "the vision route raised" as "the vision route is
unavailable" and threw away every page already transcribed.

**Response.** Guard each page *inside* the loop: catch, log the failed page,
record it, continue. Return the partial result as long as any page produced
text. Then classify the failure before retrying — a deterministic rejection
(next section) must fail the page immediately instead of burning the retry
budget three times on a long document.

---

## Degenerate transcription is deterministic — do not retry it

**Signature.** The engine answers HTTP 200 with text that repeats: the ratio of
distinct lines to total lines falls below a threshold (measured 0.48 twice on
the same page), and the service already retried internally at a second pixel
budget before giving up with "degenerate transcription on both attempts".

**Consequence.** It is a property of that page's pixels, not a transient fault.
Retrying from the client re-runs a known failure and, on a 200-page document,
costs minutes per bad page.

**Response.** Match the message and fail the page immediately. Keep the retry
budget for genuine transport faults (5xx, timeouts) — the same distinction as
the 4xx rule above.

---

## Vision models hallucinate page furniture

**Signature.** Article nodes whose content opens with a masthead that does not
belong to the document: a Moroccan code whose page 1 correctly reads
`المملكة المغربية` produced nodes opening `الجمهورية العربية السورية وزارة العدل`
on several later pages. The model reproduced a header template it associates
with the layout.

**Consequence.** Each hallucinated masthead becomes a bogus article node — it
inflates the count and collides with real article numbers.

**Response.** Reject header candidates whose line opens with page furniture
(`الجمهورية`, `وزارة العدل`, `المملكة المغربية`, a bare page number) before they
become nodes. Anchor on the document's own masthead: a *repeated foreign*
masthead is a model artifact, not content.

---

## Compound article numbers are truncated by the header matcher

**Signature.** Moroccan codes number inserted provisions as a compound:
`الفصل 1-35`, `الفصل 4-218-42`. A header regex that captures a single numeric
run takes only the first component, so `الفصل 1-35` yields article `1` and
collides with the plain `الفصل 1`. Symptom: duplicate article numbers
concentrated at low values, while the compound provisions are missing.

**Consequence.** The tree looks populated but is wrong: real provisions vanish
and low-numbered articles appear many times.

**Response.** Capture the full compound token (every dash-separated component)
as the unit's identity, and keep it distinct from the plain number. Verify with
both assertions — the recovered count AND that the compound identity survives.
A capture loosened only enough to stop truncating can also start admitting
cross-references, which is what the structure-fix test in SKILL.md rule 16 is
for.

**The hyphen must be flush — require it with no surrounding whitespace.** In
this corpus `الفصل 1-35 - العقوبات` is a compound header whose body starts with
a dash, while `المادة 5 - يجب` is a plain article 5 followed by a dash. A pattern
allowing `\s*-\s*` conflates the two and mangles every plain article.

**The compound identity must also enter the dedup key, and the two layers need
two different keys.** Article nodes are deduplicated on a key that a
structure-aware reflow may build as `(scope, number, inserted)`; add the compound
label to *that* key, or provisions sharing a leading number across different
codes (`الفصل 1-35` vs `الفصل 1-448`) collapse onto each other. Keep the
**numeric** `number` field as the leading component (it orders the article
inside its code) and carry the full token in a separate `number_label` field.
For a duplicate-number audit, group by the pair `(number, number_label)` —
grouping by `number` alone reports the correctly-distinguished compounds as
collisions and hides the real ones.

**A container scope keyed on the container's number alone collapses distinct
containers.** Moroccan codes legitimately reuse container numbers: one code
carries four separate `الجزء الأول` parts (`في العقوبات` / `في الجريمة` /
`في الجنايات` …), all numbered `1`. A validator that scopes article identity on
the container *number* merges those four parts into one scope and reports
duplicates the document does not have — six phantom collisions in one file. The
parser's own dedup already scopes on `(number, title)`; the audit must mirror
the parser's scope key exactly, or the two layers disagree about what a
duplicate even is. When an audit reports duplicates, first print the scope key
it computed and confirm it distinguishes the containers the parser treats as
distinct.

**A loosened matcher can change a document-level decision, not just the line.**
A code's `الفصل`-as-article-unit decision is made once per document from the
*resolved numbers* of its headers (a median test over low numbers). If your
compound change alters how those numbers resolve, it can flip the unit decision
and reclassify the whole document — a wide blast radius from a narrow regex edit.
Re-measure the article count on a real document, not only on the fixture.

---

## Page folios and mastheads become article nodes

**Signature.** Phantom article nodes whose numbers sit at exactly the page
count of the document, or whose content opens with a masthead. Diagnose with
one measurement: for each page, is the **last** non-empty line a standalone
number, and does that number equal the page's 1-based index? On the document
that exposed this, 76 of 77 such digits matched their page index exactly — that
near-perfect match is the signal that they are printed folios, not content.

**Mechanism (two cooperating defects).** The run-on splitter breaks the printed
page number off as its own line, and the bare-number article fallback accepts a
standalone digit as an article header. When page numbers sit at the *end* of a
page, page N's folio is adjacent to page N+1's masthead, so the phantom article
is born from two lines on different pages.

**Response.** Two independent rejections, both requiring the line to be nothing
but a number: (1) drop a standalone number that is the last real line of its
page and equals that page's 1-based index — do this where page boundaries are
still known, before pages are flattened into one line stream; (2) reject any
header candidate whose content is Bulletin-Officiel letterhead (`الجمهورية`,
`وزارة العدل`, `المملكة المغربية`, …). Either rule alone has a gap: the index
rule misses a folio whose value drifted, the letterhead rule misses a folio
followed by body text. Do **not** simply reject every bare number — real
articles do appear as bare digits when the keyword is OCR'd onto the previous
line.

**Verify the removals are phantoms, not articles.** After the rule fires,
confirm each removed number has no `الفصل N` (or `المادة N`) header anywhere in
the source text. If it has none, it was never an article and a falling coverage
number is a correction, not a regression.

---

## Locating where missing content actually is, before building a recovery path

**Signature.** A count is short — "the code should have 612 articles, the JSON
has 565" — and the tempting next step is a recovery mechanism for the pages
that look bad. Do not build it yet. A shortfall has two independent causes that
need different fixes, and they are distinguishable by measurement alone:

1. **the page is unreadable** (no text layer, scan only, engine returned
   nothing) — a per-page recovery could help;
2. **the engine read the page fine but skipped content on it** — the page is
   not the problem, and no amount of re-scanning that page recovers anything.

**Locate each missing unit by its neighbours.** For every missing number, find
the nearest present article *before* and *after* it in document order and note
their pages. Then read what the neighbours say:

```python
# page -> article numbers the engine produced for that page
page_arts = {i: nums_of(vision[i-1]) for i in range(1, len(vision)+1)}
# for a missing number m, the pair (page of nearest lower, page of nearest higher)
# tells you whether it falls on a page that transcribed at all.
```

A missing number whose two neighbours sit on *adjacent* pages that both
transcribed is an engine skip, not an unreadable page — the content was
readable and the engine dropped it. Measured on one code: 47 missing numbers
all landed between pages that had transcribed normally (e.g. page 14 returned
`19, 24, 25, 26` — it skipped `20–23` outright), while the three genuinely
unreadable pages held only boundary articles that were already captured from
their neighbours. Re-scanning those three pages would have recovered roughly
four articles and **none** of the 47. Report the two lists separately and say
which fix each one needs; a recovery path aimed at the wrong cause is wasted
work that also looks like progress.

**Classify an image-only page before assuming it is a scan of the body.** A
page can carry its content as an embedded raster while the PDF also holds a
shared background template. Fingerprint every image by content hash: an image
whose sha1 appears on *every* page is a template/masthead, not content, and the
page's real content is the image unique to it. Compute the effective DPI of the
placed raster — `image_pixels / (placement_box_points / 72)` — because a large
pixel count means nothing if it is stretched over a bigger box. A ~100 DPI
content image is a genuine scan; a `688x463` image in a `420x519pt` box is
`118x64` DPI, distorted, and was a duplicate of the preceding page rather than
new content.

**Check the sibling copies before declaring a page irrecoverable.** The same
instrument is often present in several raw directories (e.g. `raw/ar`,
`raw/org`, `raw/corrupted`). Compare the text length on the suspect pages across
copies: if every copy is byte-identical there, no sibling can rescue it, and
that is worth stating so the user does not ask for a re-download that cannot
help.

**A page-subset OCR call already exists — splitting and merging needs no new
capability.** `extract_vision_pages(pdf_path, pages=[...])` accepts 1-based page
numbers, returns one string per requested page in ascending order (empty string
for a page that produced nothing), and returns `None` only when every requested
page failed. Splice the result back by index. So "scan these pages separately
and merge" is a supported operation today; the question is only whether the
measurement above says it will help.

**Never present an untested recovery as a validated workflow.** When the OCR
endpoint is down, the diagnosis above is still complete and worth reporting —
but the recovery itself is a hypothesis, not a fix. Say which parts were
measured and which were not, and hand the user the concrete next probe rather
than a recommendation dressed up as a result.

---

## Choosing between the native layer and the OCR, page by page

Neither source dominates, and which one is better is a property of the *page*,
not of the document. Vision/OCR reconstructs clean words but drops article
headers on dense pages; the native text layer carries headers faithfully but
shreds words (`اال` for `لا`, `األ` for `الأ`) and breaks dates across lines. On
one 207-page code the native layer was better on 145 of the 150 pages where the
two disagreed on article count — but it collapsed catastrophically on another
document (194 articles against the OCR's 584), so a document-level choice is
wrong in both directions. Decide per page.

**Score the page by distinct article identities, not by header matches.**
Cross-references inside body text (`وفقا للفصل 25`, `المشار إليه في الفصل 40`)
match the header pattern, so a page that only *cites* articles scores as richer
than one that *defines* them. A raw match count selected the wrong source on 20
pages, where the incumbent carried 54 compound provisions the native layer
could not represent at all. Key the identity on `(number, compound_label)` so
that two provisions of one code count as two while a repeated citation of one
article counts once.

```python
identities = set()
for line in reflow(page):
    for cand in split_runon_headers(line):
        if not keyword_start(cand):
            continue                      # keyword-less lines are not identities
        matched, number, _ = article_header_info(cand)
        if matched and number is not None:
            identities.add((number, compound_number_label(cand)))
score = len(identities)
```

**Require the candidate to compensate for the structure it cannot represent.**
The native layer shreds compound headers across lines, so it is *incapable* of
representing them — it produced 4 of the 137 compounds visible in the OCR text.
A plain `>` comparison therefore lets a page win on one extra ordinary article
while silently discarding several real provisions (measured: 33 compound
identities lost across 14 pages). Subtract the compounds the candidate would
drop before comparing:

```python
at_risk = len(vision_compounds - native_compounds)
use_native = len(native_identities) > len(vision_identities) + at_risk
```

Ties go to the incumbent OCR engine — its word-level text is cleaner, so the
native layer should only win a page on demonstrated extra structure. A page the
incumbent left empty is filled from the native layer. French is left untouched:
the shared vision module is Arabic-oriented and French native text is already
authoritative.

**Validate across the corpus, not on the document that motivated the change.**
Run the new rule end-to-end over every cached document and report mean unique
articles, mean phantom/trivial nodes, and the win/lose/tie counts against the
previous behaviour. On the change above: mean unique articles 32.3 → 33.5, mean
trivial nodes 0.2 → 0.4 (the native layer alone would be 3.4), better on 44
documents, worse on 6, equal on 66. A rule tuned to one document is a rule that
silently regresses the other hundred — and the losers are the ones you must
name in the hand-off.

---

## A date fragment becomes an article when the source breaks dates across lines

**Signature.** Many phantom article nodes carrying trivial content that is a
month or a stray dash: `22 أغسطس2024 (، ص5327`, `14 يونيو2021 (، ص4162؛`,
`25 -`. They cluster on pages whose real headers *do* carry the
`الفصل`/`المادة` keyword.

**Mechanism.** The native layer splits a date across lines — the day lands on
its own line, the month on the next — and the bare-number article fallback
accepts the standalone day as an article header. The native layer produced 104
trivial nodes this way against the OCR's 11.

**Response.** Suppress a standalone 1–2 digit line **only on a page whose
headers carry the article keyword**; there the bare number is provably a date
fragment or an enumeration item. On a page with *no* keyword header, keep the
fallback untouched — the bare number is the only structural signal such a
document offers, and suppressing it drops every article. Cap the suppression at
1–2 digits so years (`1970`) and 3–4 digit numbers are never removed.

**Do not suppress bare numbers globally as a "cleanup".** The same fallback is
what recovers articles when the keyword itself was OCR'd onto the previous line;
the page-level condition is what makes the rule safe.