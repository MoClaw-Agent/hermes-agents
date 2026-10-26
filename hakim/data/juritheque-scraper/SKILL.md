---
name: juritheque-scraper
description: "Parse and audit the JuriThèque legal corpus."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [corpus, quality, audit, legal, arabic, adala, ocr, json]
    related_skills: [legal-corpus-pipeline, mizan-pipeline-audit, corpus-quality-audit]
---

# JuriThèque Corpus: Parse, Audit, Wire

## When to Use

- The JuriThèque corpus must be parsed, re-parsed, or audited
- `data/corpus/juritheque/` is mentioned, or its `json/` tree is empty
- A provider's `document_type`, `language`, `ref` or `legal_domain` fields
  look wrong, or its records carry no provisions
- Every document of a provider appears under ONE legal domain ("everything
  is Administrative Law") — that is a catch-all source folder being inherited,
  not a downstream bug
- A new provider must be wired into Mizan ingestion

Class of work: the JuriThèque provider for Mizan — parsing its corpus,
auditing its quality, wiring it into ingestion, and repairing defects found
there. Use `mizan-pipeline-audit` for the audit-and-fix-wave discipline and
`mizan-repo-delivery` for the release.

## Read this first: the raw tree is NOT what the docs say it is

`doc/JURITHEQUE_SCRAPER.md` describes a browser scraper. **The corpus on disk
was not produced by it.** `data/corpus/juritheque/raw/` is a Supabase REST
dump of the ADALA backend (`fetching/juritheque/fetch_api.py`), so the
scraper, `scrape_standalone.py` and `convert_to_adala.py` are all unrelated
to the data you will actually be handed:

| | browser scraper (`scrape.py`) | the real corpus |
|---|---|---|
| producer | `run_from_sitemap()` | `fetch_api.py` |
| fields | `full_text`, `reference`, `instrument_type`, `domain`, `external_links` | `content_ar`/`content_fr`, `_juritheque`, SEO projections, `views` |
| provenance | juritheque.com | `source_name: "Adala"` |

`convert_to_adala.py` reads fields that do not exist in this corpus; run
as-is it emits `document_type: loi`, `collection_title: Droit Général` and
`structure: []` for every record. **Verify which producer made the tree
before trusting any doc or converter.** The parser that owns the corpus now
is `fetching/juritheque/parser/`.

## The four record fields that are filing metadata, not legal facts

Every one of these must be re-derived, never trusted:

1. **`document_type`** — lowercased from `_juritheque.type`, i.e. the folder
the site filed the PDF under. 31 distinct values, including `bulletin officiel`
(a container, not an instrument) and the Arabic literal `مرسوم`. It carries no
normative rank.
2. **`language`** — the *site page* language. 1,125 records are filed `fr`
while `_juritheque.language` says `AR`; 20 records declare a language their own
text contradicts. Detect it from the text.
3. **`ref`** — `_juritheque.number`. Empty for 123 records (a circular, a royal
letter, a note — real instruments with no printed number), a title or a bare
year for 338 more. The filename `circulaire_.json` is a placeholder, not an
identity: 13 unrelated circulars collide on it.
4. **`legal_domain` (the subject matter)** — the folder is NOT the subject.
The site's `droit_administratif` folder is a **catch-all**: 4,514 of 7,037
records (64%) are filed there, but only **22%** of those are administrative law
by content — the rest are international conventions, education and health
decrees, banking laws, land and urban-planning arrêtés, military statutes.
Measured over the 4,142 records in that bucket carrying text: the site folder
says administrative for 100%, the content classifier says administrative for
22%, so 77.7% would be reassigned (labour 577, civil procedure 457, commercial
328, constitutional 283, fiscal 225, urban planning 202, civil 179, corporate
164). A parser that inherits the folder faithfully reproduces a catch-all —
and every consumer of `legal_domain` (domain filters, domain boosting, the
stats panel) then reports a corpus that is 65% administrative law.

**Before inheriting a source's classification, measure what share of that
bucket survives it — and establish that the COMPARATOR is reliable before you
read its disagreement as the signal's error.** Sample the bucket's own titles
and inspect them; then run the content classifier over the same records.

A low agreement rate means the two signals disagree. It does NOT mean the
source is wrong, and it does NOT license replacing the source with the
comparator. The comparator here is a **query** classifier
(`ingestion.pipeline.resolvers.detect_domain_from_content`, built for "what
domain is this QUESTION about?"), and a legal document cites the Constitution,
the finance law and the courts in its preamble — so bag-of-words matching
returns the CITATIONS, not the subject. Measured on documents whose subject is
legible from the title: **the folder was right 3 of 5, the text classifier 0
of 5, the title classifier 1 of 5.**

Do NOT replace the folder with content classification. The one signal worth
reading is the site's own **`tags`** field, which carries subject tags already
in the `LegalDomain` vocabulary (`القانون العقاري`, `القانون_التجاري`,
`القانون_المالي`) and is accurate where present — but it covers only ~13% of
the catch-all bucket (592 of 4,514 records), so it corrects a subset and
cannot replace anything.

Ship it as: **keep the folder value, and publish where it came from** —
`legal_domain_source` of `"site"` for the subject-named folders (verified
reliable by inspection), `"site-catchall"` for `droit_administratif`,
`"tag"` where a domain tag overrides the folder, and `"classifier"` where a
embedding classifier (multilingual sentence embeddings, trained on the 16 subject-named folders, threshold 0.4,
~81% out-of-fold accuracy, disk-cached) reclassifies with sufficient confidence. The
content-classifier prohibition below still applies to
`detect_domain_from_content` (the query classifier) — the TF-IDF classifier
is a separate, document-level model trained on the corpus's own labels.

## Procedure

1. **Measure before theorising.** Whole-corpus counts over every file —
language, type, ref validity, provision count, collision groups. Numbers, not
samples, for anything you will report as a corpus defect.
2. **Re-derive identity, in this measured priority order** (each step beaten
   against the others on a sampled corpus before it was adopted):
   - `ref`: the document's **own title** → the site's `number` → the body →
     `""`. Title vs site field agree on 999 of 1,051 sampled records and the
     title wins essentially every disagreement.
   - `document_type`: the instrument the **title opens with** → the site's
     label → the body classifier → `law`. The body is LAST: it reads an
     instrument word out of a citation.
   - `language`: detected from the text.
   - `legal_domain`: the source's folder is a **filing bucket, not a subject**
     for `droit_administratif` (verified catch-all), but the other 16 folders
     are reliable. Keep the folder value and publish `legal_domain_source`
     (`"site"` / `"site-catchall"` / `"tag"`) so the confidence is in the
     payload. Correct from the site's own domain `tags` where they exist. Do
     Do NOT substitute the QUERY classifier (`detect_domain_from_content`) for
     the folder — it classifies queries, not documents, and returns the document's
     CITATIONS. A separate embedding classifier (multilingual sentence embeddings,
           trained on the 16 subject-named folders, title + summary + tags) may be
           used for the administratif bucket with a confidence threshold (0.4) and
           provenance `"classifier"`.
3. **Rebuild the legal hierarchy with the shared grammar**
   (`fetching.pipeline_base.build_tree`) — see `references/parsing-the-flat-text-layer.md`
   for the page-segmentation requirement and the identity/collision traps.
4. **Fill `data/corpus/juritheque/json/`.** That is what
   `INGEST_PATH_JURITHEQUE` points at; the ingestion walk finds nothing until
   the tree exists.
5. **Wire ingestion — every registry, not just the converter.** Converter,
   dispatch, provider registry, settings fields, the parser route, the ingest
   trigger's category set, the bulk-ingestion maps, the corpus hierarchy roots,
   the log list, the generated admin manifest, and both panels. See
   `references/provider-wiring.md` for the table; a provider in some of them
   is not wired, and the generated manifest is the one that passes every check
   while staying invisible.
6. **Verify against the baseline** — zero-provision rate, empty-ref count,
   collision groups, output document count. A fix with no measured delta is
   not a fix. Then verify the wiring END-TO-END:
   `discover_documents(INGEST_PATH_<P>, provider=<p>)` must return the corpus —
   registry membership alone does not prove it.

## Pitfalls

- **A source's SUBJECT MATTER classification can be a catch-all, not a subject**
  — a folder named `droit_administratif` held 64% of the corpus, and 78% of that
  bucket is not administrative law (international conventions, education and
  health decrees, banking laws, land arrêtés, military statutes). The parser
  reproduced it faithfully and the defect surfaced downstream as "everything is
  Administrative Law". **But the fix is NOT to switch to the content
  classifier** — that classifier (`detect_domain_from_content`) is a query
  classifier and returns the document's CITATIONS (a family-fund law classified
  `droit_fiscal` because the preamble cites قانون المالية; a civil-status
  decree classified `droit_procedure_civile` because it mentions محكمة and
  تنفيذ). Keep the folder, label its reliability, and correct from the site's
  own domain tags where they exist. An embedding classifier (multilingual sentence embeddings, trained on the
 16 subject-named folders, title + summary + tags) may additionally reclassify
  administratif records with confidence >= 0.4 (provenance `"classifier"`),
  ~81% out-of-fold accuracy, ~18% coverage. See the rule in the section above.
- **Agreement with a comparator measures DISAGREEMENT, not error.** "The source
  signal and the classifier agree on only 19.5%" is not evidence that the
  source is 80% wrong — it is evidence the two disagree. Establish the
  comparator's reliability on documents you can identify by inspection before
  you use its disagreement to condemn a signal. Acting on the unproven
  inference cost a full implement–test–revert cycle: the replacement signal was
  measurably worse than the one it replaced.
- **`detect_source()` must know the provider, and the explicit provider key
  must OUTRANK a host match.** `ingestion/stages/common.py` enumerates the
  providers and matches `source_url` hosts; a provider missing from that list
  is not merely omitted — the host match then fires on whatever host the source
  uses. Measured: 83% of this corpus (5,867 of 7,037 records) was attributed to
  ADALA because the dump's `source_url` values point at
  `adala.justice.gov.ma` and at CDN paths containing `adala_documents`, plus
  147 to SGG, 11 to jurisprudence and 9 to BDJ — i.e. a wrong `source_authority`
  for 100% of the records. Register the provider AND order the checks so the
  document's own `source_provider` is read before the URL. When adding a new
  provider, add its name to all three lists (metadata, path, file_name) in
  `ingestion/stages/common.py`.
- **Passing a whole document to `build_tree` as one page loses it.** The
  per-page heuristics are calibrated for a page; a flat text layer has no
  page boundaries, and the amendment-note gate then swallows the document
  (measured: 337 of 346 lines dropped, leaving a single preamble and zero
  provisions). Segment first — see the references file.
- **Never set `source_file` on a parsed document.** It sends the ingestion
  pre-converter down its cache-lookup branch, which never falls back to the
  inline `pages` this parser emits — the document is silently dropped as having
  no text. Carry provenance in `file_name` + `source_url` instead.
- **Do not emit `page_texts_sample`.** Its presence switches the converter to
  preview mode and truncates the indexed text.
- **`pages` is mandatory.** The converter returns `[]` when it is absent, so
  a record with no text becomes no chunk at all. That is correct (fail
  closed) but must be counted and reported, not discovered later.
- **A bilingual dump's title field is usually the filing language, not the
  document's language.** The top-level `title` is typically the filing language
  (often French). For an Arabic document, prefer `title_ar` for display — but
  extract refs from the French title, which carries the instrument's own number.
  The Arabic title often names only the law the instrument implements ("مرسوم ...
  القانون رقم 37.99"), so extracting from it files the decree under the law's
  number. Measure: compare ref extraction from each title against the site's
  number field on a sample before choosing.

- **A title pattern must be ANCHORED at the start of the title.** A title
  names its own instrument first and cites others afterwards:
  `Décret n° 2-99-52 instituant une taxe…` (own) vs
  `Application du décret n° 2.04.403 du 29 Chaoual 1426…` (citation). An
  unanchored pattern filed the circular under the decree's number, creating a
  second document shadowing the real decree.
- **`detect_amendment` returns a raw capture that can be a word, not a ref**
  (measured: `amends_doc_ref` stored the Arabic word «تعديل» = "amendment").
  Validate the shape before publishing it, or it joins on nothing and reads as
  a citation.
- **A folder can be a container, not an instrument.** Bulletin officiel
  records carry no text at all; emitting them creates empty law documents.
  Skip them, count them, log them — never silently drop and never emit.
- **A ref must have ONE spelling across sources.** The site prints
  `2-20-371`, the title prints `2.20.371`; without folding `-` to `.` the
  Arabic original and its French translation never join.
- **Key the resume index by the RECORD, never by the identity or the path.**
  `_build_output_record_index()` maps `raw_record` → path and `process_file`
  takes it as `preexisting=`; a record with no entry takes the next free
  ` (2)` slot. The general rule, and why a path snapshot is NOT enough when two
  records share an identity, is in `mizan-pipeline-audit`. Verify idempotency
  by re-running and comparing the sorted output path set, not the written count.

## Running

```bash
# full parse (≈6 min for ~7k records; ~0.05 s/record)
./venv/bin/python -m fetching.juritheque.juritheque_parser --force
# smoke run
./venv/bin/python -m fetching.juritheque.juritheque_parser --limit 300 \
    --json-dir /tmp/jq_smoke
```

Run it in the **background** — a full parse is ~6 min, past the foreground call
limit, and a foreground attempt will be cut off mid-corpus. (That is the rule
for THIS job; the pytest suite is the opposite case — background suite runners
are SIGTERM'd, so it runs as bounded foreground slices. See
`mizan-repo-delivery`.)

## Tests

`tests/test_juritheque_provider.py` — real corpus records (read-only) plus
synthetic shapes: identity priority, page segmentation, the amendment-note
regression, output-path collisions, ingestion wiring, and the platform-wiring
contract mirrored from `tests/test_ism_platform_wiring.py`.

## References

- `references/parsing-the-flat-text-layer.md` — page segmentation, the
  amendment-note regression, identity priority and collision handling.
- `references/provider-wiring.md` — the ingestion contract and every
  registration point a new provider must touch.
