# Parsing a Flat Text Layer (no page boundaries)

Depth for the JuriThèque parser and for any provider whose source is a flat
text blob rather than a PDF. The general lesson — **a per-page heuristic is
only safe when it is actually given pages** — applies to any parser handed a
concatenated text.

## The failure: one document, one page

`build_tree(text_or_pages, ...)` takes either a bare string or a list of page
strings. Given a list, it applies per-page heuristics to each element:
contents-page detection, the trailing footnote block, the page-folio guard,
the markdown-table block and the **amendment-note gate**.

Feed it a whole document as a single element and the amendment-note gate
swallows the document:

```
_amendment_note_block(page_lines)
  marker gate: from a line matching _AMEND_MARKER_RE, drop the marker line and
  every following line until a LONG, non-citing line.
```

The stop condition is `len(s) > 120 and not _NOTE_CITE_RE.search(s)` — a
length heuristic, not a structural one. A text layer whose lines are short
(≤120 chars, common in legal PDFs) never satisfies it, so the walk runs to the
end of the stream.

Measured on a real decree whose text opened with «كما تم تعديله بـ:»
("as amended by"): **337 of 346 lines dropped**, the tree collapsed to a single
`preamble` node, and a 41-article decree parsed to zero provisions.

Note this is a shared-base weakness (a genuinely long PDF page could trigger it
too), but the *producer* is what must change: `build_tree`'s contract is pages.

## The fix: segment before building

```python
_FOLIO_LINE_RE = re.compile(r"^\s*[-–—]\s*\d{1,4}\s*[-–—]\s*$")
MAX_LINES_PER_PAGE = 60

def split_pages(text, max_lines=MAX_LINES_PER_PAGE) -> list[str]:
    pages, current = [], []
    for line in text.split("\n"):
        if _FOLIO_LINE_RE.match(line):        # the source's own page number
            if current:
                pages.append("\n".join(current)); current = []
            continue                          # folio line is page furniture
        current.append(line)
        if len(current) >= max_lines:         # bound when folios are absent
            pages.append("\n".join(current)); current = []
    if current:
        pages.append("\n".join(current))
    return [p for p in pages if p.strip()]
```

Two rules, both evidence-based:

- **Split at the source's own printed page numbers.** Measured: 3,880 of 6,527
  text-bearing records carry them, and 2,395 of those run sequentially from 1
  — they are the PDF's real page numbers, which is what makes them a
  defensible boundary. It also keeps a trailing footnote block at the end of
  the page it belongs to, and lets `_is_page_folio_line`'s page-index check
  work. The remaining 1,485 are non-sequential (missing cover folio, OCR noise)
  but still bound a segment, which is all that is needed.
- **Cap each segment.** Without a cap, a document whose text layer lost its
  folios presents a whole instrument as one page and the gate fires again.

Report the consequence honestly: `num_pages` then counts the pages **this
artifact** has, not pages the source PDF has. Do not silently emit a
`num_pages` you cannot support.

## Identity priority, and why the body is last

Each ordering below was settled by measuring the two signals against each
other on a sampled corpus. Do not re-litigate it by intuition.

**Ref:** title → site field → body → `""`.

- The title is the document's own name and won essentially every disagreement
  with the site's `number` field (999 of 1,051 sampled records agree; of the
  74 that disagreed under the unanchored patterns, the title was right in 9 of
  the 10 inspected).
- The site's `number` is NOT the instrument's own number in general. Measured:
  a decree record carried `37.99` — the number of the **law it implements** —
  while its title read `Décret n° 2-99-665`. The title also wins.
- The body extractor is last because it reads an instrument word out of a
  citation. `Décret d'application de la loi n° 39.09` must not become `loi`.

**Document type:** the instrument the title **opens with** → the site's label
→ the shared body classifier → `law`.

- Distinguish "the title says Loi" from "the classifier fell through to its
  default": `detect_doc_type` answers `law` for both, so a title naming no
  instrument must return `""` and let the site's label decide. Only a title
  that actually carries a law word (`loi`, `code`, `charte`, `قانون`, …) may
  return `law`.

**Anchoring is the whole point of the title pattern.** Match `Décret n° …`
anywhere in a title and a circular applying a decree is filed under the
decree's number, producing a second document shadowing the real one:

```
Décret n° 2-99-52 instituant une taxe parafiscale …     ← own instrument
Application du décret n° 2.04.403 du 29 Chaoual 1426 …  ← citation
```

This is the same contract the shared extractor's `_explicit_instrument_ref`
applies to a title. (Known shared-base gap: that function matches only the
**Arabic** instrument kinds — `ظهير|مرسوم|قرار` — so a French title or filename
such as `Loi n° 131-13 …` falls through to the page scan and returns a cited
instrument instead. Fixing it changes every PDF provider's refs, so it needs a
corpus-wide measurement first.)

## Collisions: rewrite in place, or number them — never overwrite

The output path is a pure function of `(language, domain, document_type, ref)`,
which gives idempotent re-runs and deterministic collision numbering. The trap
is the resume check:

```python
# WRONG — the second record to reach an identity sees the first record's file
existing_path = base if base.exists() else None

# RIGHT — only paths that existed when the RUN BEGAN are this record's own
preexisting = {p for p in out_root.rglob("*.json")} if out_root.exists() else set()
existing_path = base if base in preexisting else None
```

With `path.exists()` the second record takes the first record's fresh file as
its own and silently overwrites it. Snapshot the output tree **before**
anything is written and pass that set down; compute it once per run so the
walk is O(N) rather than per record.

Then classify what the collisions are, because they are not all the same:

- **ar/fr pairs** — the Arabic original and its French translation. Separate
  documents, by the same convention the ADALA output tree uses. Keep both.
- **cross-domain** — the same instrument filed under two domain folders. Keeps
  the domain context; duplicates retrieval. Report the count, do not silently
  merge (which domain is right is not decidable from the data).
- **same (lang, type, ref, domain)** — a genuine duplicate. Inspect one before
  deciding; it may instead be a title-extraction error (see the anchoring rule
  above), which is a different fix.

## Zero-provision documents are not automatically a defect

After the segmentation fix the rate fell from 55 % to ~9 %, and inspecting the
remainder showed they are legitimately article-free: covering letters
(«إلى السيدات والسادة المديرون… أحيل عليكم رفقته نموذجا»), administrative
decisions, journal issues, tables of contents, and text layers whose OCR
replaced digits with look-alikes so no marker survives.

**Prove it by sampling the residue** rather than assuming the parser is still
failing. A zero-provision count is a finding about the *source* until you have
read some of them.
