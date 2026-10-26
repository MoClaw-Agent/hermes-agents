# Extraction-Cache Resolution: the JSON↔cache coupling

A parser JSON is a pointer, not a container. Auditing a corpus for completeness
means auditing two artifacts, and the second one goes missing silently.

## The contract

`pipeline_base.extract_pages()` writes the complete page list to:

```
data/corpus/<provider>/cache/<stem>_<sha256(first 4096 bytes)[:12]>.json
```

and the parser JSON deliberately stores only `page_texts_sample` (first two
pages plus the last, each truncated) to avoid holding whole documents in memory.
`full_text_in_cache: true` is the JSON declaring that its text lives elsewhere.

**The key is the head hash, not the JSON's `content_hash`.** `metadata.content_hash`
is the SHA-256 of the whole PDF; the cache filename uses the first 4 KB only.
The two are different values by design, so searching for the cache by the stored
content hash returns zero hits on a document whose cache is present. Derive the
key the way the code does or the audit produces pure false negatives.

A vision-layer cache sits alongside it as
`cache_vision/<stem>_<hash12>_vision.json`, keyed identically. It is a *different*
artifact: the extraction cache holds the native/legacy text, the vision cache the
OCR pass that may be what actually built the tree. Check both before concluding a
document has no cached text.

## Ingestion fails closed — and says so in one line

`ingestion/pre_converters/base.py` resolves the cache for ADALA and ISM (the
`_COMPLETE_CACHE_PROVIDERS` pair, matched by `source_provider` or by a provider
segment in `source_file`). Resolution tries the hashed name then the legacy
`<stem>.json`, across the candidate cache directories, and validates the page
count against `num_pages`.

When no candidate resolves, the converter logs:

```
[COMPLETE_INGESTION] Full extraction cache not found for <file>; refusing to ingest page_texts_sample
```

and returns `[]`. **This is the fail-closed contract working, not a bug.** The
alternative — indexing three preview pages as if they were the whole law — is the
worse outcome, so the message is a diagnosis to act on, not a defect to suppress.
Sibling messages in the same method mean different things and are worth
distinguishing: `Empty extraction cache` (file present, no pages),
`Incomplete cache: N/M pages` (present but short — the cache write was
truncated), and `full source path/cache is missing` (no `source_file` to resolve
from at all).

## Audit recipe: cache resolvability corpus-wide

```python
import json, hashlib
from pathlib import Path
from collections import defaultdict

json_root = Path("data/corpus/<provider>/json")
cache_dir = Path("data/corpus/<provider>/cache")

by_date = defaultdict(lambda: {"present": 0, "missing": 0})
for jf in json_root.rglob("*.json"):
    d = json.loads(jf.read_text(encoding="utf-8"))
    src = d.get("source_file")
    if not src:
        continue
    p = Path(src)
    has = False
    if p.exists():
        with p.open("rb") as f:
            h = hashlib.sha256(f.read(4096)).hexdigest()[:12]
        has = (cache_dir / f"{p.stem}_{h}.json").exists() \
            or (cache_dir / f"{p.stem}.json").exists()
    by_date[(d.get("timestamp") or "")[:10]]["present" if has else "missing"] += 1
```

Grouping by parse date rather than printing one total is what makes the finding
actionable: a per-date split separates "this corpus is half-cached" from "one
entire parse batch lost its caches", and the second is the case worth reporting.
Split by `language` as well — a batch that covered only one language directory
produces a clean-looking total with an entirely broken subset.

`rglob`, never `glob` — corpus JSONs live under nested domain subdirectories.

## Repairing a missing cache

Delete nothing else and re-parse the source PDF for the affected documents. Two
costs to state before starting:

- **The re-parse is the expensive step, not the deletion.** It re-runs whatever
the extraction route selects, which for an Arabic CMap-corrupt provider can be
minutes per page.
- **If the configured OCR route is unreachable, the run silently degrades** to
the fallback engine, which is documented as dropping Arabic article-header
digits. A re-parse is only a repair if it lands on the intended engine; confirm
the route before launching, and treat a fallback-produced cache as still needing
repair rather than as done.

Confirm the fix the way the ingestion code resolves it — re-run the audit
snippet above and check the count, then parse one document end-to-end and confirm
ingestion accepts it. A regenerated cache that the resolver still cannot find
(the name does not match the key derivation) looks identical to no fix at all.

## Pitfalls

- **Auditing completeness from the JSON side alone.** `num_pages`, a populated
  `structure`, and `full_text_in_cache: true` all coexist with an absent cache.
  The JSON cannot tell you its text is gone.
- **Keying the lookup on `content_hash`.** Whole-file hash vs 4 KB head hash —
  every present cache reads as missing.
- **Reading `--force` as a cache refresh.** It is a state/JSON-reset flag. The
  page-text caches survive it untouched.
- **Treating a short cache as a hit.** A cache whose page count is below
  `num_pages` is skipped by the resolver exactly like a missing one; a truncated
  write leaves the document un-ingestable while the file exists on disk.
