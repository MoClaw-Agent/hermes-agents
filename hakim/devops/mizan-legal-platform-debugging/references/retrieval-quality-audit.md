# Retrieval pipeline quality audit (2026-10)

## French domain keywords missing from EXPLICIT_DOMAIN_MAPPINGS [FIXED 2026-10-25]

Fixed: added 11 French keyword→domain pairs (droit du travail, droit pénal,
droit fiscal, droit commercial, droit de la famille, droit constitutionnel,
code du travail, code penal, etc.). Verified:
`explicit_domain_from_query("droit du travail")` → `droit_du_travail`.

## `_INSTRUMENT_RE` false positives [FIXED 2026-10-25]

Fixed: tightened regex to require whitespace after keyword and a digit-starting
number of length ≥2. Verified: `names_instrument("قانوني 4")` → False (was True),
`names_instrument("قانون رقم 15.01")` → True.

## BM25 bonus scale [FIXED 2026-10-25]

Changed `BM25_FUSION_WEIGHT` from 0.5 → 1.0 in `core/settings/retrieval.py`.
Sparse hits now get up to 1.0× an RRF step bonus instead of 0.5×.

## Domain boost [FIXED 2026-10-25]

Increased from +0.1 → +0.15 in `retrieval/hybrid/fusion.py`. Domain-matching
chunks now get a 15% boost instead of 10%.

## `_normalize_article_ref` canonicalization [FIXED 2026-10-25]

Replaced `str.replace()` with regex using lookarounds `(?<![a-zA-Z\u0600-\u06FF])` /
`(?![a-zA-Z\u0600-\u06FF])`. Prevents "bis" from matching inside other words
while still handling digit-adjacent forms like "45bis". 6 normalize tests pass.

## `detect_source` missing provider [FIXED 2026-10-25]

Added "juritheque" to the provider lists in `ingestion/stages/common.py`.
Juritheque documents were being attributed to "adala" because their source_url
contains "adala.justice.gov.ma" and "juritheque" was not in the metadata check
list. Now `source_provider: "juritheque"` is read first and correctly returns
"juritheque".

## Stage 3 granularity limited to article-level

`stage3_clause_retrieval` treats article-level chunks as the retrieval
unit. Clause-level fetch is not yet implemented (comment: "can be added
later when CHILD_CHUNK_SIZE > 256"). Final results may be too
coarse-grained for precise citation.

## Hierarchical Stage 2 fallback to scroll order

When dense ranking fails for a law, `_rank_articles_for_law` falls back to
scroll order (arbitrary point-id order). Logged at WARNING but could
degrade silently. Monitor for this pattern.

## `expand_top_k` failure is logged at WARNING

If `expand_top_k` fails, the candidate pool shrinks. The exception is
caught broadly (9 types). Monitor `expand_top_k failed` in logs.

## Dense retrieval returns 0 is silent to the user

When dense returns 0 hits, a WARNING is logged but the pipeline continues
with sparse-only. The user sees degraded results without knowing why.

## `_resolve_payload` complexity in Stage 2

Wrapped/flat candidate handling could silently lose metadata if the
candidate shape doesn't match expectations. Test with both shapes.

## `fetch_missing_payloads` uses `scroll_all`

This could be slow for large result sets. Batch more aggressively.

## Juritheque provenance pattern (legal_domain_source)

For catch-all source folders (like `droit_administratif`), keep the folder
value as `legal_domain` but publish `legal_domain_source` indicating the
signal used: "site" (trusted folder), "site-catchall" (administrative
bucket), "tag" (site domain tag override), "classifier" (TF-IDF classifier
with confidence ≥ 0.4). This makes uncertainty visible rather than hiding it.
