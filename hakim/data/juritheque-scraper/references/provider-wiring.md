# Wiring a Provider into Mizan Ingestion

The full registration checklist for a provider whose parser emits the
ADALA document envelope. Every point below is a place a provider has been
found missing; a provider that is not in all of them is invisible to some
part of the system.

## 1. Settings fields

`core/settings/ingestion.py` — declare both, or pydantic's `extra="ignore"`
silently drops the `.env` key and the attribute does not exist:

```python
PARSER_PATH_<PROVIDER>: str = Field("./data/corpus/<provider>/raw/", ...)
INGEST_PATH_<PROVIDER>: str = Field("./data/corpus/<provider>/json", ...)
```

Then add both names to `_path_fields` in `core/settings/__init__.py` so
relative values resolve against `MIZAN_HOME`. **Add only your own names** —
adding a sibling's changes its existing resolution behaviour.

A path key present in `.env` but read by no code is *dead configuration*: it
looks wired and is not. Grep for the symbol before assuming a path is live.

## 2. Converter

`ingestion/pre_converters/<provider>.py` — subclass `LawConverter` when the
parser emits the ADALA envelope, overriding only:

```python
class XConverter(LawConverter):
    provider_name = "<provider>"
    def domain_map(self) -> dict: return X_DOMAIN_MAP
```

Register it in `ingestion/pre_converters/__init__.py` — **both** `CONVERTERS`
(schema-detection fallback) and `PROVIDER_CONVERTERS` (provider-keyed
dispatch) — and add its path fragment to `_PROVIDER_PATH_PATTERNS` in
`dispatch.py`. That pattern list is exact path components, never substrings, so
`/not-juritheque/` is not routed as JuriThèque.

## 3. The document must survive the converter

`LawConverter.convert` fails closed: `if not pages: return []`. Two fields
decide whether a document reaches it:

- **`pages` is mandatory.** Emit the segmented page list inline.
- **`source_file` must be ABSENT** when there is no extraction cache.
  `_load_pages_from_cache` branches on it: present → it looks for a hashed
  cache file and never falls back to inline `pages` (it ends at
  `page_texts_sample` handling and returns `[]`). Absent → it returns the
  inline `pages` directly.
- **`page_texts_sample` must be absent.** Its presence switches the converter to
  preview mode and truncates the indexed text.

So for a JSON-sourced provider: inline `pages`, no `source_file`, no
`page_texts_sample`, provenance in `file_name` + `source_url`.

`detect()` needs `file_name` plus (`pages` present, or `full_text_in_cache`, or
`source_provider == provider_name`, or `num_pages is not None`) — and must not
carry `sections` (that marks a bulletin).

## 4. Output-path helper

`{doc_type} {ref}.json` with ` (2)`/` (3)` collision suffixes. Shared helper:
`fetching/pipeline_base/paths.py::compute_output_path(doc_type, ref,
fallback_stem, existing_path=None)`. When a second provider needs the rule,
extract it to the base and have the existing provider **alias** the shared
function under its historical private name so its callers and tests do not
move. Check the god-file pin before adding lines to a pinned provider module —
replacing a body with an alias *shrinks* the file, which the gate allows.

## 5. Pipeline registration

- `fetching/pipeline.py` — add to `PROVIDERS`. Its loader imports
  `fetching.<name>.<name>_parser`, so a thin shim module is required; the
  canonical implementation lives in `fetching/<name>/parser/`.
- `run_provider` calls `run(..., only_html2json=...)`. **Accept that kwarg**
  (and `bulk`, `retry_from`) in your `run()` signature even if unused —
  otherwise the loader's `TypeError` fallback silently drops to the `main()`
  path, which behaves differently.
- `api/routes/ingest/providers_config.py` — add the entry to both
  `PROVIDER_SOURCE_PATHS` and `_PROVIDER_CONFIGS`.
- `api/routes/admin_config.py` — add the path rows so the admin surface can see
  them.

## 6. Logging volume

A shared extractor that logs one INFO line per rejected candidate will flood a
whole-corpus run. Check which logger it uses first — `logging.getLogger(...)`
has no effect on a **loguru** module (`from loguru import logger`). For loguru,
`logger.disable("<module>")` is the mechanism; confirm the module logs no
`warning`/`error` before disabling it, so you are not silencing failures.

## 7. The admin manifest is GENERATED — a Settings field alone is invisible

`api/routes/admin_config_manifest.json` is built by
`scripts/build_admin_config_manifest.py` from
`core/settings/_admin_field_whitelist.py`, **not** from
`Settings.model_fields`. Declaring the `Field(...)` alone leaves the field
invisible to the operator: it exists, the drift check passes, and the admin
UI never shows it.

```python
# core/settings/_admin_field_whitelist.py
("Paths", "PARSER_PATH_<PROVIDER>", "str", False, False),
("Paths", "INGEST_PATH_<PROVIDER>", "str", False, False),
```

Then regenerate, and confirm with the sync check:

```bash
./venv/bin/python scripts/build_admin_config_manifest.py
./venv/bin/python scripts/check_admin_manifest_in_sync.py
```

The drift check (`scripts/check_admin_field_drift.py`) only asserts that
whitelisted keys and `FIELD_META` keys **resolve** to canonical Settings — it
does NOT assert that every Settings field is whitelisted. So a field missing
from the whitelist is silent. The `api/routes/admin_config.py` `FIELD_META`
rows carry the description and the default string; the whitelist carries the
metadata.

## 8. The registries that enumerate providers

A provider parsed and converted but absent from these is half-wired. Each was
a real gap found by asking "where does this provider need to be reachable
from?":

| registry | file | failure when missing |
|---|---|---|
| parser route | `api/routes/parser.py` `_PARSER_PROVIDER_CONFIGS` | parser panel cannot run it |
| ingest trigger | `api/routes/ingest/trigger.py` `VALID_CATEGORIES` + the `all` run list | category rejected with HTTP 400, or silently skipped by "All Sources" |
| bulk ingestion | `run_ingestion.py` `BULK_SOURCES`, `CATEGORY_TO_RANK`, `CATEGORY_DEFAULTS` | cannot be ingested at all — no source path, no rank |
| provider registry | `api/routes/ingest/providers_config.py` `PROVIDER_SOURCE_PATHS`, `_PROVIDER_CONFIGS` | `/ingest/sources` omits it |
| corpus hierarchy | `core/legal_hierarchy/corpus.py` `_default_corpus_roots()` | the parent→child index does not scan the provider, so its chunks get no hierarchy boost |
| corpus domain filter | `api/routes/corpus.py` the `source`-field branch | stats panel falls back to `legal_domain` filtering |
| log list | `api/routes/logs.py` `LOG_FILES` | parser log not selectable |
| source attribution | `ingestion/stages/common.py` `detect_source()` | the payload's `source_authority` is wrong — see below |
| settings whitelist | `core/settings/_admin_field_whitelist.py` + generated manifest | see section 7 |
| admin fields | `api/routes/admin_config.py` `FIELD_META` | no description/default in the admin surface |
| ingestion panel | `api/static/panels/ingestion.html` + `js/panels/ingestion.js` | no dropdown option, no source-path row, no label map entry, no run-history category |
| logs panel | `api/static/js/panels/logs.js` | parser log renders as its raw key |

### Source attribution is the registry that mis-attributes rather than omits

`detect_source(file_path, metadata)` in `ingestion/stages/common.py` is called
by the document builder for `source_authority`. It enumerates the providers in
two places (a path-component scan and a `source_url` host scan) and **falls
through to a host match**. A provider missing from the enumeration is therefore
not skipped — it is mis-attributed to whatever provider's host the source's URL
happens to carry.

Measured on a corpus whose URLs point at a sibling's hosts: 83% of records were
attributed to the sibling (5,867 to ADALA), plus 147 to SGG, 11 to
jurisprudence and 9 to BDJ — a wrong `source_authority` for 100% of the records,
including the ones the host match got right by accident.

So register the provider **and** order the checks so the document's own
`source_provider` is read BEFORE the URL: the provider key is a statement about
the document, the host is a hint, and a CDN path can carry another provider's
name.

`corpus_scope.discover_documents()` is generic — it needs no per-provider entry,
which is exactly why it is the one place you do NOT have to register.

## 9. Frontend panels

The panels are static files under `api/static/`; there is no build step and no
i18n indirection for provider labels — they are hardcoded in the JS.

- `panels/ingestion.html` — one `<option>` per provider in the category
  `<select>`, plus one `.src-row` per provider in the Source Paths block.
- `js/panels/ingestion.js` — four places: the `labels` map, the
  `for (const key of [...])` list that rebuilds the dropdown, the run-history
  `catMap`, and the `el("src-<provider>", d.<provider>)` binding. Missing any
  one leaves the others showing `—` for a configured provider.
- `js/panels/logs.js` — a label map keyed by log-file id.

**Assert panel wiring by reading the files**, not by driving a browser: grep
the HTML for the option value and the `id="src-<provider>"` row, and the JS
for the key list, the label map and the binding. That is what
`tests/test_<provider>_platform_wiring.py` does.

**Deliberately do NOT add a crawler-panel entry unless the provider has a
crawler.** The crawler panel drives a subprocess that downloads source files
(`api/routes/crawler/_shared.py::_crawler_config_for`, which raises
`ValueError` for an unknown provider). A JSON-sourced provider with no
crawlable source would expose a button that cannot succeed. Pin the absence
with a test so it reads as a decision rather than an omission.
