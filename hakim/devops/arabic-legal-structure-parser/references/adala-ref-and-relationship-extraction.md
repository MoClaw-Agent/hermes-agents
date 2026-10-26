# ADALA ref and relationship extraction — patterns

Depth for the `fetching/adala/parser/` ref / relationship layer. The always-on
rules live in SKILL.md; this file holds the full patterns, the regex bodies and
the worked examples.

Files involved: `fetching/adala/parser/_shared.py` (shared patterns),
`fetching/adala/parser/extraction.py` (ref + relationship extraction),
`fetching/adala/parser/classification.py` (rank / doc-type),
`fetching/adala/parser/pipeline.py` (call sites).

## 1. Citation connector guard — whole word, but the clitic may be glued

**Root cause**: the guard that decides "is this ref a CITED instrument or the
document's OWN ref" matched connectors as substrings. `من` fired inside
ordinary words — `المنتدب`, `الأمن`, `مندوبية`, `منظمة`, `منشورات`, `الأعلى` —
and made a real own header look like a citation, so the parser took the cited
law's ref as the document's own.

**Fix** — two-branch alternation, not one pattern with an optional clitic:

```python
_AR_LETTER = "\\u0621-\\u064A"
_CITED_REF_PREFIX_AR = re.compile(
    rf"(?:"
    # bare connector: whole word on BOTH sides
    rf"(?<![{_AR_LETTER}])(?:بناء\\s+على|من|على|وفق|وفقا|طبقا|مقتضى|تطبيق|تنفيذ)(?![{_AR_LETTER}])"
    # clitic + connector: the clitic (ب/ل/و/ف/ك) may be glued to the preceding
    # word — "مرسوملتطبيق" is مرسوم + لتطبيق in real OCR — but the connector
    # itself must still be a whole word
    rf"|[وفبلك](?:بناء\\s+على|من|على|وفق|وفقا|طبقا|مقتضى|تطبيق|تنفيذ)(?![{_AR_LETTER}])"
    rf")[\\s\\u0600-\\u06FF]{{0,30}}$"
)
```

**Pitfall**: a single pattern with an optional clitic (`(?<![AR])[وفبلك]?(?:conn)`)
is wrong in the other direction — the optional clitic branch can never fire,
because the lookbehind is evaluated BEFORE the clitic, so a clitic glued to the
preceding word is rejected by the lookbehind and the real line-wrap shape
(`مرسوملتطبيق`) stops guarding. The two branches are not interchangeable: the
bare form needs a leading AND a trailing boundary, the clitic form needs only
the trailing one.

The same shape applies to the amendment connectors
(`تعديله`/`تغييره`/`نسخ` family).

The French counterpart is a separate pattern: `vu`, `modifiant`, `complétant`,
`abrogeant`, `remplaçant`, `application`, `conformément`, `promulgation`,
`portant`, `en vertu`, … with `(?<![^\W\d_])` / `(?![^\W\d_])` boundaries.

## 2. `نسخ` (abrogation) vs `نسخة` (a copy)

**Root cause**: the amendment-keyword list contained bare `نسخ`, which also
matches `نسخة` — so "نسخة طبق الأصل" (certified copy) flipped a document into
amendment-style ref mode, which makes `extract_ref` prefer the filename ref
over the real own-header ref.

**Fix**: `نسخ(?!ة)` — the verbal noun (abrogation) stays amendment-style, the
noun (a copy) does not.

**General rule**: a keyword that inflects by suffix (`نُسخ` / `نُسخة`) cannot
be listed as a bare stem. Use a negative lookahead for the suffix letter, and
test the sibling form explicitly.

## 3. Only a law in the enacting clause is the target instrument

**Root cause**: the body scan labelled EVERY cited law in the first pages as
`promulgates`/`implements`. A preamble citing four laws produced four
`promulgates` edges — the instrument's relationship graph claimed authority
over laws it merely references.

**Fix**: the target is the law cited in the SAME CLAUSE as an
enacting/application formula:

- Arabic: `يأمر`/`نأمر`/`أمر` + `بتنفيذ`, `بتنفيذ القانون`, `بتطبيق القانون`,
  `تطبيق أحكام القانون`, `لتنفيذ القانون`
- French: `ordonne l'exécution de la loi n° X`, `arrêté qu'il est ordonné`,
  `portant application`, `application de la loi`

Enacting formulas are **deliberately separate from the visa formulas**
(`بناء على` / `بمقتضى` / `Vu la loi`) — a visa states what the instrument is
*founded on*, not what it *enacts*.

The clause is bounded by newline and Arabic/French clause punctuation
(`\n،,；;:`). **Dots are NOT boundaries** — refs contain dots (`2.14.391`,
`26.16`).

Everything else found in the body is a plain `references` edge.

**Direction rule**:

| document type | target cited in enacting clause | direction |
|---|---|---|
| `dahir` | yes | `promulgates` / `upward` |
| `decret` | yes | `implements` / `downward` |
| any | no | `references` / `lateral` |

## 4. Ref comparison must be canonicalised, not literal

**Root cause**: Arabic and filename refs use dots (`26.16`), French refs use
dashes (`26-16`). Literal string comparison treated them as two different
laws, so one law produced two relationship edges.

**Fix**: a comparison-only canonical key (normalise separator and group order)
used for equality and dedup; the ORIGINAL spelling is kept for storage and
display. Keep the two functions separate — one canonical key for comparison,
one stored value — and never overwrite the stored spelling with the canonical
form.

## 5. `extract_relationships` must receive the caller's resolved own ref

**Root cause**: the function recomputed the own ref internally, using a
different extraction path than the one that had already settled it (LLM
override, derivative gate, deterministic cross-check, synthetic ref). The
self-reference exclusion compared against the wrong value, so a self-edge
could survive.

**Fix**: take `own_ref` as a parameter and pass the already-resolved value;
only fall back to a fresh extraction when the caller supplies none. The
exclusion must compare canonical keys too.

## 6. Own instrument type is identified by the document's own header, in its language

**Root cause**: the French head had no own-markers, so only `décret`/`arrêté`
could ever be found in a French header — a French law or dahir that cited a
décret in its head was typed by the CITED instrument. The Arabic citation
guard also never saw French text, so the two languages silently diverged.

**Fix**: add the missing French own-markers (dahir, loi) AND a French
citation-connector guard. A guard added for one language is inert for the
other — write both.

## 7. Rank classification uses the EARLIEST instrument keyword, whole-word

**Root cause**: the rank fallback matched substrings (`emploi` contains `loi`,
`استقرار` contains `قرار`) and a fixed priority order promoted an instrument
that merely CITES another — a decree citing a dahir was typed `dahir`.

**Fix**: whole-word matching (Arabic letters count as word characters; an
optional `ال` allowed) and the **earliest** match in the head decides, because
the instrument's own word comes first and cited ones follow. The same
classifier must be shared by every caller that derives a rank or a type, or
two code paths will disagree about the same document.

A framework law (`قانون إطار` / `loi cadre`) is checked AFTER the own-instrument
scan, so a decree that merely cites a framework law keeps its own type. Do not
keep a second, differently-spelled copy of that pattern in a second module —
import the shared one.

## 8. French title stop markers — earliest match, correct alternation precedence

**Root cause**: two bugs in the same list.

- (a) Only the FIRST matching marker in list order was applied, not the
  EARLIEST, so an end-anchored marker pre-empted an enacting-clause marker that
  fires much earlier and let preamble visas leak into the title.
- (b) An alternation without a group (`\\s*:modifiant|complétant|abrogeant`)
  had its precedence scoped wrongly, cutting titles mid-word ("…complétant le
  Code penal" → "…et") and never matching the intended `": modifiant"` form.

**Fix**: cut at the earliest match across all markers, and group the
alternation: `\\s*:\\s*(?:modifiant|complétant|abrogeant)`.

## 9. Filename extension stripping must not truncate a ref

**Root cause**: `filename.rsplit(".", 1)[0]` strips the last dot-segment
unconditionally, but a Moroccan ref itself ends in a dot group —
`ظهير شريف رقم 1.12.34` became `1.12`.

**Fix**: strip the crawler timestamp FIRST (a digit run of 10+ chars, optionally
followed by a real extension), then remove only a REAL extension
(`pdf`/`doc`/`docx`/`txt`/`html`). A bare `rsplit(".", 1)` is never correct here.

## 10. Output stem derived from the filename

The output stem is derived from the source filename. When a crawler timestamp
is present, the policy decision is measured, not guessed: strip the timestamp
only when the remaining base name is unique within its directory, otherwise
keep it (always-strip makes colliding names overwrite each other's JSON;
always-keep leaks the timestamp into every output name). Cache the directory
listing per resolved directory and invalidate on the directory mtime — the
listing is otherwise re-read once per document, which is O(N²) over a crawl.

## 11. A consolidated law is its own identity — the title is a second opinion

**Root cause**: `_consolidated_law_own_ref` asks the title as a second opinion
and the guard vetoed EVERYTHING when the title did not lead with a law. The
pipeline's real title for a consolidated law is the promulgating dahir's line
— `extract_title` returns the first PATTERN that matches, and the dahir
pattern is listed before the law pattern — so the law was indexed under the
dahir that enacted it, through a route the unit tests did not cover (they
hand-crafted a title that leads with the law, which the pipeline never
produces).

**Fix — the title may VETO, not REQUIRE**:

```python
if title_law is not None and _ref_key(ref) != _ref_key(title_law):
    return None
```

The head's own order already decides the annex case: a dahir that reproduces a
law as an annex names its own instrument first, and `_first_own_instrument_at`
/ `_first_consolidated_law_at` apply the earliest-header rule. The title guard
is redundant for that case and must not override the head.

**`_title_lead_law_ref` decides by the first INSTRUMENT keyword, not the first
character.** A consolidated law's title begins with its promulgation formula
and then names the law — `تم نسخ القانون رقم 41.10 المتعلق بـ ...` — and that IS
the law's title; the formula is not an instrument. A dahir that reproduces a
law as an annex names the dahir first (`ظهير شريف رقم 1.10.191 ... بتنفيذ
القانون رقم 41.10`) and returns None. An anchored `^\s*(?:ال)?قانون` misses the
first and rejects the second only by accident.

**A guard test that asserts the defect is not a guard.** One test asserted that
a document whose head contains ONLY the law's reproduction line — no dahir
header at all — is the dahir, because the TITLE names the dahir. That is the
defect. The head's own order decides; the title is a second opinion.

**The self-amendment is a CONSEQUENCE of the same defect.** `detect_amendment`
matches the bare `تعديل` inside `كما تم تعديله بالقوانين التالية`, and
`extract_amended_doc_ref` takes the first `قانون <num>` in the head — the law's
OWN ref for a consolidated law. `_drop_self_references` removes such an edge by
comparing `amends_ref` against the STORED ref, which was the dahir's, so the
comparison missed. Fixing the consolidated law's own reference makes the
comparison land; clear the `amendment_note` with the flag, because
`detect_amendment` returns a non-empty note only together with
`is_amendment=True` and a surviving note is necessarily stale.

**Share the helper, re-export it from the provider.** When a fix moves a
provider-local helper into the shared module, import it back into the provider
module rather than duplicating it: an import binds the name in the provider's
namespace, so every test that imports it from the provider keeps working, and
the two providers cannot drift on it again.
