# Extraction and structure-parser internals

Failure modes in `fetching/pipeline_base/` and the validators that guard it.
Each entry is a defect class with the check that catches it — use these when
article counts look wrong, structure looks scrambled, or a quality gate blocks
a document.

---

## Extraction cache: valid hit must return

The cache hit path loaded, validated, then discarded unless a separate
(masthead-repair) branch happened to fire. Every document re-extracted on every
run; at hundreds of seconds per page for OCR this dominates pipeline runtime.

The contract, both halves of which matter:

- **valid hit → return it**
- **invalidated hit → fall through and re-extract**

The naive fix (hoisting the `return` out of the nested branch) breaks the second
half: after `cache.unlink()` the page and mode variables still hold the values
that validation just rejected, so returning them serves the refused content.
Assert both directions — a test whose fixture is *valid* proves only the first.

Cache keys are `{stem}_{hash}.json`, not a fixed name. Writing a fixture under
the wrong name silently exercises the re-extract path instead, and the test
appears to fail for the wrong reason.

---

## Article identity is scoped to the enclosing chapter

Moroccan codes restart article numbering per chapter, so `المادة 41` under
الفصل 3 and under الفصل 4 are two different operative units. A document-global
dedup key discards the second. Scoping the key to `(part, book, chapter)`
recovers a large fraction of a corpus; scoping only to book does nothing for
codes with no كتاب.

The quality validator must agree with the parser. If dedup is chapter-scoped
while duplicate-identity and ordering checks run document-wide, every document
the fix rescued fails the gate — the fix and the gate contradict each other.
That is a validator bug, not a reason to undo the fix.

---

## Diacritics inside header keywords hide whole articles

OCR emits combining marks inside otherwise correct words: `المادَة 21` with
U+064E FATHA, `المـادة 7` with U+0640 TATWEEL. The header keyword then fails
to match and the article's text is absorbed into whichever article preceded it —
the provision simply does not exist in the output, with no error anywhere.

In one 76-page organic law, 19 FATHA occurrences hid two articles outright.

Strip marks as an **additional candidate variant** in the existing header-variant
helper, never as a blind rewrite of the input — the helper already absorbs
reversed lam-alef ligatures and dropped hamza, and a rewrite regresses those.

**Delete the marks; do not replace them with a space.** `المـادة` becomes
`الم ادة` and still fails, which reads as a fix that did not work. Ranges:
U+0640 tatweel, U+064B–U+065F harakat and extended marks, U+0670 superscript
alef, U+06D6–U+06ED Quranic annotation.

Check the character before naming it: what reads as tatweel in the extracted
text is often fatha. `unicodedata.name()` on the actual codepoint settles it in
one call — guessing sent a fix aimed at the wrong range.

Marks inside body text must stay inert; the line-start anchor is what prevents
this from inventing headers.

---

## Cross-references masquerading as headers

Two distinct shapes, both promoted to real nodes when a line break or OCR
reflow leaves a citation at the start of a line:

- **Containers** — `الفصل 96 من مدونة التسجيل ...` becomes a chapter. The
  article detector already rejected this shape via its citation-tail rule;
  containers had no equivalent until one was added for both the anchored and
  fuzzy match paths.
- **Articles** — `المادة 20 أعلاه` ("article 20 above") is a back-reference.
  Reject when the marker immediately follows the number; a real article opens
  with its operative verb or noun, so the marker can never begin one.

A citation carrying a *real-looking* number is the damaging case: one shadowed a
genuine chapter 1, re-scoping its articles and manufacturing duplicate failures.

Unresolvable by shape alone: a bare `الفصل 26` mid-sentence is indistinguishable
from a header. Accept the ambiguity; do not loosen the matcher to "fix" it.

**Count occurrences before concluding a node is malformed.** A node holding
several `المادة N` strings is usually ordinary prose — `وفقاً لأحكام المادة 74 من
القانون التنظيمي رقم 59.11` — and treating that as a swallowed header sends you
after a defect that does not exist. Confirm with context before acting.

**Do not drop a citation-shaped node outright.** Many carry real article text
behind the citation, and deleting them destroys content. Strip the citation
prefix and re-scan the remainder instead.

---

## Contents pages, including unstructured ones

Line statistics detect a contents page only when dot leaders and line breaks
survive extraction. OCR frequently returns the whole page as **one line with the
dot leaders dropped entirely** — page references appear as bare numbers with
nothing between them.

Add a second signal for that shape: an explicit contents marker together with a
dense run of sibling container headers, evaluated on flattened text before any
line-based test. Test against the **actual** extracted string; a hand-built
reconstruction can look like it already passes and hide the bug.

---

## OCR output arrives unsplit

Page text with zero newlines defeats any line-start-anchored header detector —
markers are present, just inline. Prompts do not help: three variants (the
production prompt, a locale-appropriate line-ordering prompt, and a merged prompt
with an explicit per-line instruction) all returned zero newlines with
output similarity 0.93–0.99. See `references/ocr-provider-quirks.md` in the
legal-corpus-pipeline skill.

Split run-on text at header markers before the line-anchored detector runs,
excluding citations so back-references cannot become phantom articles.

---

## State and reporting traps

**`to_dict()` filtering `!= 0`** silently erases `articles=0`, `pages=0` and
`duration_s=0.0`. A document that legitimately parsed zero articles becomes
indistinguishable from one never attempted — in the state file whose entire
purpose is recording what ran. Filter only `None` and `""`.

**Silent partial output is worse than failure.** When OCR drops a page, the
parse completes and the document looks complete. For a citation corpus, log
dropped pages at ERROR and prefer failing over indexing a document missing
content.

**Zero-valued parse states are meaningful**; distinguish "parsed, found
nothing" from "never attempted" before acting on any corpus count.