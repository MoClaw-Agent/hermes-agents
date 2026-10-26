# Parser → Ingestion Contract

How the parser JSON, the extraction cache, and the vision cache relate — and the
places ingestion silently discards the parser's work.

## The gate order that discards structures

`ingestion/pre_converters/law.py::LawConverter.convert()`:

```python
pages = self._load_pages_from_cache(data)   # cache only
if not pages:
    return []                               # bails BEFORE reading structure
...
_structure = data.get("structure") or []    # ~50 lines later
flat_articles = self._flatten_structure(_structure, pages=pages)
```

`data["structure"]` is never reached when the cache lookup fails. A document
with a complete, expensive article tree in its JSON produces **0 ingested
items** if its extraction cache is missing.

Diagnostic: when ingestion yields nothing for a file, check whether the JSON's
`structure` is populated. If it is, the fault is the cache, not the parse.

## Cache key derivation (not the content hash)

The extraction cache filename is:

```
<pdf_stem>_<sha256(first 4096 bytes of the PDF).hexdigest()[:12]>.json
```

This is **not** `metadata.content_hash`, which is the full-file SHA-256.
Searching caches by the content-hash prefix finds nothing and produces a false
"cache missing" conclusion. Always derive the key by reading the PDF's first
4 KB. A legacy `<pdf_stem>.json` name is probed as well.

## Where the cache is looked up

`BaseConverter._cache_directories()` walks up from `source_file` looking for a
directory literally named `json` or `raw`, then takes its sibling `cache`.

**`cache_vision/` is never considered.** For a document whose parser JSON says
`structure_source == "vision"`, ingestion still joins the *native* cache pages
into `full_text`, while `flat_articles[].text` comes from the parser structure
that was built from *vision*. The result is two OCR passes inside one document
— the full text and the article text disagree, and the vision text the
structure was validated against is never indexed.

The parser records which text produced the tree in `structure_text_cache`.
That field, not the directory layout, is the authoritative source.

Both `structure_source` and `structure_text_cache` are **write-only**: all
three parsers emit them and no module reads them. Confirm with:

```bash
grep -rn "structure_text_cache\|structure_source" --include=*.py . | grep -v tests
```

Three writers, zero readers. The provenance the parser records for exactly
this purpose is dead metadata until ingestion is changed to consult it.

### Purged caches are unrecoverable from git

`data/corpus/*` is gitignored, so a cache directory that gets cleared cannot
be restored from history — and the legacy backup dir only holds whatever was
copied there. When caches are missing at scale the only fix is a re-parse,
which is blocked if the OCR backend is unreachable (the fallback is orders of
magnitude slower). Check cache presence across the corpus before promising a
re-ingest:

```python
# per JSON: derive the key from the PDF's first 4 KB and test for the file
```

## The completeness gate measures presence, not completeness

`_load_pages_from_cache` returns `[]` when the cache is absent, and `convert()`
treats that as fatal — but the gate never asks whether `page_texts_sample`
already covers the whole document. A short document whose sample covers
`num_pages` of `num_pages` is discarded identically to a long one whose sample
is a small preview.

The page-count test already used elsewhere (`len(pages) < expected_pages`) is
the right shape; applying it to the sample is what separates the two cases.
Changing this alters a deliberate fail-closed safety contract — confirm the
acceptance rule with the user before touching it.

## The parser's hierarchy lives on `position{}`

Every article node carries the parser's resolved place in the tree:

```json
"position": {"part": null, "book": null,
             "title": "الباب الأول: أحكام عامة",
             "chapter": null, "section": null}
```

`_position_hierarchy()` in `ingestion/pre_converters/helpers.py` reads it, and
`_flatten_adala_structure` prefers it for `path` / `chapter` / `section`,
falling back to the walker context and to the synthesised `Art.N`.

- `chapter` is legitimately `None` for documents nesting articles directly
  under الباب. That is the parser's correct answer, not a gap to fill.
- `section` falls back to `position.title` so a document with no القسم level
  still carries its nearest container instead of `Art.N`.
- The SGG branch already read `position.book` for its *text*; the hierarchy
  fields are the same idea applied to structure.

Do not re-derive hierarchy by regex-scanning page text when the parser already
computed it. The regex fallback exists only for JSONs that lack `position`.

## Which node types survive the flattener

`_flatten_adala_structure` emits a flat article for exactly two shapes:

1. every node with `type == "article"` — always;
2. childless nodes of type `title | book | part | section | preamble` carrying
   at least 20 chars of content.

`chapter` is **not** in the second list. A `chapter` node that holds provision
text in `content` and has no children — the shape `build_tree` produces for
الفل-numbered instruments, where each الفصل provision is its own node — is
discarded. The document then publishes `num_articles_detected: 0` and its
operative provisions never reach the chunker.

Do not read that as "chapters are never flattened": a `chapter` node WITH
children is a container and its content survives through its children. Only the
childless provision-shaped chapter is lost.

### A non-empty `flat_articles` suppresses every fallback

Two safety nets exist and both are gated on emptiness:

- `ingestion/adapters/law_adapter.py` uses `metadata["flat_articles"]` whenever
  it is non-empty and skips the Arabic text-based article extractor. That
  extractor does not recognise الفصل headings anyway, so no recovery there.
- `ingestion/stages/chunk/_engine.py::chunk_from_structured` iterates
  `flat_articles`; its regex/full-text fallback and the `MZ-E-CHUNK-001`
  silent-degradation alarm fire ONLY when `flat_articles` is empty.

One surviving preamble item is therefore enough to suppress both nets and raise
no metric. The document's text still arrives as `full_text`, so it stays
findable as a blob; what is lost is provision-level chunking, `provision_ref`
and article-level retrieval. Never accept "it produced a chunk" as evidence the
structure survived.

### Quantify with the retention ratio

`kept` = characters carried by the flattened items, `src` = characters of the
text named by `structure_text_cache`. Report `kept / src` per document — it is
what distinguishes a real loss from a cosmetic count change. Measured on the
ADALA Arabic set: 9 of 31 reparsed documents (every الفصل-numbered instrument)
retained 8-47%, while the 21 المادة-numbered documents retained 87-99%.

`arabic-legal-structure-parser` → `scripts/audit_parsed_structure.py` prints
this table for a whole JSON directory.

## Trace every consumer before claiming a quality impact

Preserving or changing a payload field only matters if something reads it.
Grep for consumers FIRST, then state the impact from what you found — never
assert that a field improves or degrades corpus quality from what its name
suggests. A confident warning about a regression that the code cannot produce
costs the user a decision round and damages trust in the next claim.

Measured consumers for the hierarchy fields:

| Field | Reaches | Readers outside `ingestion/` |
|---|---|---|
| `hierarchy_str` / `hierarchy_path` | Qdrant payload | **none** |
| `section_path` | `hierarchy_str` | none |
| `chapter` | `structural_metadata.chapter` | 2 — citation string, provision API |
| `section` | `structural_metadata.section` | 1 — provision API |

```bash
grep -rn "hierarchy_str" --include=*.py . | grep -v "/ingestion/"
grep -rn "chapter" retrieval/ query/ reasoning/ api/routes/ --include=*.py
```

The only live consumer of the hierarchy is `reasoning/engine/helpers.py`,
which appends `chapter` to a citation string (`Art. 5, الفصل الثاني`). So
preserving `position{}` fixes citations and makes the JSON and the indexed
chunks agree, but it will NOT move retrieval quality until `hierarchy_str`
gains a reader. Report that distinction plainly instead of implying a win.

### Additive fallbacks cannot regress

A fallback written as `new_value or old_value` is strictly additive: a field
changes only when the new source supplies something the old path lacked, so no
field can lose its previous value. When layering parser-derived values over
existing fallbacks, prefer that shape and say it is provably non-regressive —
rather than warning about a regression the code cannot produce. Read the
patched lines back before describing their effect.

## Verifying an ingestion change against real corpus data

A unit test is not sufficient — the divergence only appears on real documents.

`scripts/audit_parser_ingestion_contract.py` runs the whole corpus audit
read-only: cache presence per JSON, whether the sample covers `num_pages`,
which OCR pass built each structure and whether that text is reachable, and
how many structures are null. Run it before promising a re-ingest and after
changing the flattener or cache resolution.

```bash
venv/bin/python scripts/audit_parser_ingestion_contract.py
```

Single-document recipe:

```python
import hashlib, json, pathlib
from ingestion.pre_converters.helpers import _flatten_adala_structure

d = json.loads(pathlib.Path(json_path).read_text())
pdf = pathlib.Path(d["source_file"])
with pdf.open("rb") as fh:
    head = hashlib.sha256(fh.read(4096)).hexdigest()[:12]
pages = json.loads(
    pathlib.Path(f"data/corpus/adala/cache/{pdf.stem}_{head}.json").read_text()
)["pages"]

flat = _flatten_adala_structure(d["structure"], pages=pages)
```

Report **before/after counts**, not just that it ran: how many flat articles
gained a `path` or a real `section`, and whether `flat_articles[].text` and
`full_text` now originate from the same OCR pass.

Unit coverage for the position-aware flattener lives in
`tests/test_ingestion_position_hierarchy.py` — it pins path/chapter/section
derivation plus the no-position, empty-position and malformed-position cases.
It is necessary but not sufficient; the divergence only shows on real docs.
