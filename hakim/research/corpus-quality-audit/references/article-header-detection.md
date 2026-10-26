# Article Header Detection & Identity in Arabic Legal Text

Detectors for the header shapes that produce phantom articles, wrong identities,
and silently dropped real articles. Each entry is a rule, its mechanism, and the
measured size of the blind spot.

## Compound provision identity

A code numbers its provisions `<provision>-<code>`:

| printed | meaning |
|---|---|
| `الفصل 1-35` | provision 1 of code 35 |
| `الفصل 4-218-42` | provision 4 of code 218, itself amended, code 42 |
| `الفصل 35-6` | provision 35 of code 6 |

Capturing only the leading integer makes every provision of every code collide
with the small real articles. Measured on one 207-page code: 137 compound
headers produced 85 duplicated numbers and 118 phantom nodes.

Rules:

- The hyphen must be **flush** (`\d+-\d+`, no surrounding space). `المادة 5 - يجب`
  is a real article 5 followed by a dash; `الفصل 1-35` is compound. Allowing a
  spaced hyphen turns ordinary prose into compound headers.
- Normalise Arabic-Indic digits in the label (`٨-٣٥` → `8-35`) so the label is
  stable as a dedup key.
- Report the leading integer as `number` (it orders the provision inside its
  code) and the full span as the identity/label. Do **not** try to fold the code
  into the number.
- The plural range form is not a header: reject `الفصول 19 - 23` / `المواد 4 - 8`.
  Emitting endpoints as articles invents two articles per range.

## Page folio and furniture (phantom articles)

A printed page number that survives extraction as its own line is accepted by the
bare-number article fallback. Measured: page N's trailing folio paired with page
N+1's masthead and became a phantom article.

Two independent detectors, both requiring the line to be nothing but a number:

1. **Page-index equality.** A standalone number sitting at the *end* of its page
   that equals the page's 1-based index. Measured 76 of 77 folios satisfy this
   exactly, which is why it is the strong signal.
2. **Letterhead lookahead.** The next non-empty line is Bulletin-Officiel
   masthead (`الجمهورية العربية السورية`, `المملكة المغربية`, `وزارة العدل`,
   `الصياغة الجزائية`, `النشرة التشريعية`, `الطابع الشريف`, `مديريّة`,
   `مجموعة القانون الجنائي`). No article body begins with a masthead.

Both are needed: the index rule misses a folio whose value drifted, the
letterhead rule misses a folio followed by body text. Also reject a header line
whose content *is* letterhead, after stripping any leading folio glued to it by
the run-on splitter (`3 الجمهورية العربية السورية`).

**Verify the loss is phantoms, not articles.** After adding a folio rule, list
the numbers it removed and grep the full text for each as a real header
(`الفصل <n>`). Folios have no header anywhere; real articles do.

## Suppressing the bare-number fallback

The bare-number fallback exists for documents that print headers *without* the
`المادة`/`الفصل` keyword. On a page whose headers **do** carry the keyword, a
standalone 1-2 digit line is a date fragment or an enumeration item, not an
article — the native layer breaks dates across lines (`22` ⏎ `أغسطس 2024`), and
one document grew 104 phantom nodes this way.

Gate it on the page's own convention: drop standalone 1-2 digit lines only when
that page has at least one keyword-prefixed header; leave pages without one
alone, because there the bare number is the only structural signal available.
Keep multi-digit bare lines (a 4-digit number is a year or an issue number, not
an article).

## Substring matching in a cross-reference guard

A citation guard that decides "is this line a cross-reference to another
instrument?" by matching instrument nouns **must word-bound** them. Measured: a
body line opening with `من` and containing `الطريق القانوني` matched `القانون`,
and `من عقد العزم بمفرده` matched the noun `عقد` — three genuine articles were
dropped as citations.

`\b` is necessary but not sufficient for a word that is both a noun and a verb.
`عقد` is "contract" (a citation) and "to form" (ordinary prose) as whole words,
so bound it further: a cited contract carries an identifier, so require `رقم` /
`المؤرخ` / `بتاريخ` after the noun alternative.

**A guard you cannot tighten safely may be the right trade.** One article was
still dropped by an unrelated *quote-mark* alternative in the same guard — a bare
header followed by a quote-starting line, which is a deliberate defence against
phantom articles from court-decision references. Loosening it to recover one
article risks corpus-wide phantoms. Document the limitation and the trade in the
code comment and the changelog; do not silently weaken the guard.

## Ref extraction: dotted values and extension stripping

A Moroccan reference is `\d{1,2}.\d{2}.\d{3}` — it **contains dots**. Any helper
that takes the last dot-segment as a file extension will mangle it:

```python
filename.rsplit(".", 1)[0]   # "ظهير شريف رقم 1.12.34_1729075979117" -> "1.12.34_1729..."
```

The ref then truncates at the first group (`1.12` instead of `1.12.34`). Strip the
crawler timestamp first and remove only a **real** extension:

```python
fname = _RE_TIMESTAMP.sub("", filename)
if re.search(r"\.(?:pdf|docx?|txt|html?)$", fname, re.I):
    fname = fname.rsplit(".", 1)[0]
```

Apply the same glued-digit trim on the filename path as on the title path — a
path that skips the trim returns a different value for the same input.

**How to find these:** run the extractor over a few hundred real corpus files
under both the old and new code and diff the outputs. A latent truncation shows
up as the new value being *more complete* than the old; a regression shows as the
new value being wrong or shorter. Measured on 470 documents: 293 identical, 177
more complete (all truncation fixes), zero regressions.

## Choosing between candidate texts: which source carries the headers

The native layer and the OCR route fail in **opposite** ways, which decides which
one you want for headers:

| signal | native layer | vision OCR |
|---|---|---|
| article headers (`الفصل 58`) | intact | drops/garbles on dense pages |
| compound headers (`الفصل 1-35`) | shredded across lines (4 of 137) | intact |
| lam-alef ligature (`لا` vs `اال`, `األ`) | corrupt (968 occurrences) | clean |
| word-level text | shredded | clean |

So: **native supplies header identity, OCR supplies body words.** Pick per page
(see `extraction-source-routing.md`), and never assume one source is globally
better — measure both on the document in hand.

Corollary: OCR also *skips* articles on pages it reads fine. Filling only the
pages an engine left **empty** is too conservative; an engine can return a full
page and still omit several articles from it.
