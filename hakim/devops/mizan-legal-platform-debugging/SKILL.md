---
name: mizan-legal-platform-debugging
description: "Debug Mizan legal search, citation, and ingestion pipelines."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [mizan, debugging, qdrant, adala, citations, retrieval, ingestion]
    related_skills: [systematic-debugging, ocr-and-documents]
---

# Mizan Legal Platform Debugging

> The project's workflow docs live in `doc/workflow/` — `RULES.md` is the standing contract. Read them before changing code.

## References

- `references/pitfalls.md` — 26 hard-won defects, indexed by symptom
- `references/parser-and-ocr.md` — running a parse batch, the article-loss probe, OCR/QARI plumbing
- `references/standing-rules.md` — language, documentation and workflow conventions
- `references/retrieval-quality-audit.md` — retrieval pipeline quality audit findings (domain keywords, BM25 scale, Stage 3 granularity, instrument regex)

## When to Use

- Search replies show "unknown" sources/citations
- Dense retrieval returns 0 results for valid queries
- Parser marks documents as failed with "zero article nodes"
- Citation verification fails or strips valid citations
- User reports ingestion or search quality issues

## Architecture Overview

**Retrieval pipeline** (API endpoint → response):
```
History Resolver (query/history_resolver.py) → EntityFrame {law_ids, domain, context_summary}
  → QU Pipeline (query/pipeline.py) → domain detection (English short form, e.g. 'commercial')
  → HybridRetriever.retrieve() → _retrieve_law() → _dense_sparse_fuse()
    → domain policy (retrieval/hybrid/domain_policy.py): explicit keyword → hard filter,
      inferred → `_domain_boost` only, named instrument → inferred suppressed
    → Dense: DualCollectionManager.search() → Qdrant query_points
    → Sparse: BM25S disk index (no Qdrant filters)
    → RRF fusion → enrich_sparse_hits() (payload backfill for sparse-only hits)
  → Reranker → _build_mizan_results() (DocumentChunk with merged metadata)
  → LLM reasoning → _resolve_citation_metadata() → build_ref_label()
```

**Key files**:
- `retrieval/hybrid/filters.py` — `build_qdrant_filter` (hybrid path filter builder)
- `retrieval/hybrid/domain_policy.py` — the single gate for legal-domain decisions (explicit → hard filter, inferred → soft boost, named instrument → inferred suppressed)
- `retrieval/domain_boost.py` — the post-retrieval consumer of `_domain_boost`
- `retrieval/hybrid/hybrid_search.py` — `_retrieve_law`, `_retrieve_hybrid`
- `retrieval/hybrid/fusion.py` — `_dense_sparse_fuse` (dense+sparse RRF fusion)
- `fetching/pipeline_base/structure.py` — `build_tree`, `is_article_line`, `_is_french_article_line`
- `api/routes/search.py` — `/search` endpoint, hydrate_citations_from_results
- `api/routes/search_pipeline/` — coordinator, retrieval, reasoning, verification phases
- `ingestion/stages/chunk/_engine.py` — chunk payload builder (Qdrant payload population)
- `ontology/domain_map.json` — canonical domain map (French keys + qdnt_keys)
- `ontology/domain_normalizer.py` — normalize_domain(), canonical_to_qdnt()

**Citation rendering**:
- `reasoning/engine/helpers.py` — `build_ref_label`, `build_citation_meta_from_res`, `hydrate_citations_from_results`
- `reasoning/engine/engine.py` — `_build_prompt` (context header), `_resolve_citation_metadata`
- `reasoning/citation_gate.py` — citation gate marker stripping

**ADALA parser**:
- `fetching/adala/parser/pipeline.py` — main ADALA parsing pipeline
- `fetching/pipeline_base/structure.py` — `build_tree` (hierarchy), `is_article_line` (Arabic), `_is_french_article_line` (French)
- `ingestion/pre_converters/law.py` — law route converter

**Qdrant payload storage**:
- `retrieval/qdnt/manager.py` — QdrantManager, get_qdrant_manager
- `retrieval/dual_collection/manager.py` — DualCollectionManager (routes across 3 collections)
- `retrieval/hybrid/filters.py` — `fetch_missing_payloads` (payload backfill for sparse-only hits)

## Retrieval Quality Audit Findings (2026-10)

Audit of the search/retrieval pipeline identified these actionable items:

1. **French domain keywords missing** from `EXPLICIT_DOMAIN_MAPPINGS` — French queries rely on fuzzy inferred-domain path only.
2. **`_INSTRUMENT_RE` false positives** — matches any `قانون`/`ظهير`/`مرسوم`/`قرار` + digits, including instruction text.
3. **BM25 bonus scale too small** — `bm25_weight=0.5` gives only ~0.004 bonus. Test with 1.0.
4. **Domain boost +0.1 may be too small** — 10% on 0-1 scale may not overcome score gaps.
5. **Stage 3 granularity** — article-level only, no clause-level fetch yet.
6. **Stage 2 fallback to scroll order** — dense failure degrades silently to arbitrary order.
7. **`expand_top_k` failure** — logged at WARNING, candidate pool shrinks silently.
8. **Dense returns 0 is silent to user** — sparse-only results without user notification.

Full details: `references/retrieval-quality-audit.md`

## Followup Context Resolution (History Resolver)

The pipeline resolves followup queries against prior conversation context so that "et la procédure ?" retrieves within the referenced legal scope instead of standalone.

**Module**: `query/history_resolver.py`
- `EntityFrame` dataclass: `resolved_query`, `law_ids`, `domain`, `context_summary`
- `resolve_history(query, history)` → `EntityFrame`
- Deterministic regex-based extraction (no LLM call at this layer)

**Law number patterns** (French + Arabic):
- `n° 70.03`, `loi n° 70.03`, `loi 70.03`, `dahir 1-25-73`
- `قانون رقم 65-99`, `مرسوم رقم 2-26-14`, `قرار وزاري رقم 2288-08`
- Deduped preserving order

**Domain inference**: Keyword-based (`famille` → Family Law, `travail` → Labor Law, `pénal` → Criminal Law, etc.)

**Followup detection**: Pronoun patterns (`cette loi`, `ce code`, `cette dernière`, `هذا القانون`) or short queries (≤4 words, no digits).

**Integration points**:
- `api/routes/search_pipeline/retrieval.py:_run_query_understanding` — calls `resolve_history()` before QU, passes `entity_frame.resolved_query` to QU pipeline, attaches `_entity_frame` to qu_result
- `api/routes/search_pipeline/reasoning.py:_run_llm_reasoning` — injects `context_summary` as system message into enriched history for the LLM prompt

**Tests**: `tests/test_history_resolver.py` — 20 tests covering EntityFrame construction, law extraction, domain inference, pronoun resolution, Arabic Unicode, malformed history edge cases.

**SOTA behavior**: When history is present and law IDs are resolved, retrieval is scoped to the referenced legal context. When no history or no law IDs detected, the query passes through unchanged (backward compatible).

## Corpus QA Generation and 5-Query Audit

When evaluating retrieval quality, use this repeatable pattern:

1. **Generate Q&A pairs from ingested documents**: Read `sqlite3 mizan.db` for documents with non-null `title` and `ref`. Generate type-aware French questions based on `document_type` (dahir → "Que promulgue le Dahir...", loi → "Que contient la Loi...", décret → "Que contient le Décret...", arrêté → "Que stipule l'Arrêté..."). Write to `data/corpus/adala/french_qa_50.json`.

2. **Run audit script**: For each question, execute QU → retrieval → LLM reasoning in-process (skip reranker on CPU). Check whether the expected ref appears in citations or answer text. Pass criterion: `ref_in_citations OR (matched_title_tokens >= 3 AND ref_in_answer)`.

3. **Score**: Report pass/total. A pass rate < 50% indicates retrieval degradation, not Q&A generation failure.

The audit script template lives at `scripts/run_5query_audit.py` and can be regenerated for different domains or languages.

## Evaluating Statutory Condition Answers

When a question asks for statutory conditions (e.g., "what are the conditions for X?"), a single pass/fail check on the reference hit is insufficient. The answer must state every condition listed in the source article.

**Quality gate pattern** (add to any evaluation harness):

1. Extract the numbered conditions from the source article text (أ، ب، ج، د, etc. for Arabic; (1), (2), (3) for French).
2. Extract the conditions mentioned in the final answer (keyword match against condition text).
3. Compute `missing_conditions = conditions - mentioned` and `missing_rate = len(missing) / len(conditions)`.
4. If `missing_rate > 0`, penalize the score explicitly (e.g., via `blended_attribution` or `condition_completeness` fields). A correct-but-incomplete answer is not a pass.

**Why this matters:** The retriever can deliver the full article text correctly (dense/sparse fusion works), yet the generator or summarization layer drops a subparagraph. Tagging the failure to the wrong layer wastes time. Trace:
- Chunk 15 contains clauses ج and د → the retrieval delivered partial text
- The answer lists only 2 of 4 conditions → the generation layer is the likely blame
- But verify first: check if clauses أ and ب appear in other retrieved chunks

**Pitfall:** Do not label a failure as "retrieval failure" until you inspect the complete retrieved chunk set. A chunk that appears partial may be the only one carrying the missing clauses, or other chunks may partially cover them. Verify before assigning blame.

## Dense/Sparse Retrieval Mismatch Diagnostic

When dense retrieval returns 0 hits while sparse returns results, log and diagnose:

1. Check the dense retriever's log for embedder errors (`embedding failed`, `Qdrant query error`, etc.)
2. Check Qdrant collection state: `collection_exists()`, `get_collection_stats()`
3. Check embedder model is loaded: `DualCollectionManager` must have a loaded embedder
4. Return empty results from dense rather than propagating the failure upward — the error should be visible in logs, not silently swallowed

**Why this matters:** A silent dense failure masks the reason for empty results. The search appears to work (sparse returns 20 hits), but the ranking is degraded and the user sees a dense/sparse imbalance with no diagnostic trace.

## Citation Metadata Preference

When building citation labels for displayed results, prefer human-readable metadata over raw internal IDs:

1. **First choice:** `ref` field from payload metadata (human-readable citation string, e.g., "1.02.172 Art. 9")
2. **Second choice:** `title` field from payload metadata (law name)
3. **Fallback:** raw `doc_id` (Qdrant internal UUID) — this produces opaque "unknown document" displays

**Why this matters:** A citation that shows a UUID instead of a law reference breaks the user's ability to locate the source. `build_citation_meta_from_res()` must cascade through these fields, not stop at the first non-empty one.

## MAX_LAWS Tuning for Hierarchical Retrieval

The `MAX_LAWS` threshold controls how many laws the hierarchical retriever considers before applying stage-2 document dedup. For query-domain expansion (QDE) queries that match many laws:

1. **Default 7 is insufficient** for domain-expansion queries — the correct law was ranked 11th in the merge, outside the top 7
2. **Raise to 15** for queries that match multiple domains or legal categories
3. **Measure the rank distribution** of correct laws across q8-style queries before tuning this threshold
4. **Stage-2 dedup removes duplicates at the document level**, but does not raise the law-miss rate if MAX_LAWS excludes the correct law from the merge

**Why this matters:** A retrieval failure is not fixed by deduplication. The correct law must first reach the merge stage as a candidate. Raising MAX_LAWS increases the candidate pool, which stage-2 dedup then collapses to unique documents.

## Corpus QA Generation and 5-Query Audit

When assessing a website as a potential corpus source:

1. **Check robots.txt** — is scraping allowed for all user-agents?
2. **Check terms of use** — many sites have permissive robots.txt but explicitly prohibit automated extraction in their ToS. Example: `huquqai.ma` has `Allow: /` for all user-agents but its `/use-terms` page states:
   > يُحظر: (أ) الاستخراج الآلي (scraping) للخدمة دون إذن
   > ("Prohibited: Automated extraction (scraping) of the service without permission")
3. **Check for sitemap.xml** — exists on juritheque.com with 6,774 law URLs
4. **Check for PDF download patterns** — juritheque.com hosts PDFs at `pdfs.juritheque.com`; original SGG/ADALA source links may also be present
5. **Report both signals clearly** — robots.txt permissive + ToS prohibitive = seek permission via contact email, do not scrape.

### Supabase-Backed Sites

Many modern legal platforms use Supabase as their backend. The URL pattern is `https://<project-ref>.supabase.co`. To check for API access:

1. **Find the project ref** — look in page source or JS bundles for `https://<ref>.supabase.co`
2. **Check for anon key** — Supabase anon keys are JWTs (`eyJ...`). They may be in:
   - Inline `<script>` tags with `supabase` in the src
   - JS bundles (search for `eyJ[A-Za-z0-9_=]+\.[A-Za-z0-9_=]+\.[A-Za-z0-9_-]+`)
   - Build-time env vars (not in static files — requires runtime interception)
3. **Test the REST API** — `curl https://<ref>.supabase.co/rest/v1/ -H "apikey: <key>"` — if the key works, you get JSON responses instead of HTML
4. **If no key found** — fall back to browser-based scraping (same pattern as JuriThèque)

### JuriThèque (juritheque.com)

Moroccan legal database with 7,000+ texts across 17 domains. Backend: Supabase (`bmargdbbcnhkrjeidmvh.supabase.co`).

**URL structure:**
- `/base` — database with filters (type, domain, status, language)
- `/domaine/<slug>` — domain pages (e.g. `/domaine/droit-civil`)
- `/loi/<slug>` — individual law pages (e.g. `/loi/loi-66-23-organisation-profession-avocat`)

**Page content:** Bilingual title, reference, date, domain, article count, source (SGG/BO), AI summary (FR+AR), "Articles clés" excerpts, full text viewer.

**Scraping assessment:** robots.txt allows all public pages. Legal texts are public domain. No explicit scraping prohibition in mentions-legales. Anon key not in static bundle (build-time env injection) — browser scraping required.

**Advantage over other sources:** Structured text pages (not PDF-only), domain classification, bilingual on same page, article-level excerpts.

## Corpus QA 5-Query Audit

When evaluating retrieval quality:

1. **Generate Q&A from ingested docs**: Query `sqlite3 mizan.db` for documents with non-null `title` and `ref`. Generate type-aware French questions (dahir → "Que promulgue...", loi → "Que contient la Loi...", etc.). Write to `data/corpus/adala/french_qa_50.json`.

2. **Run audit**: Execute QU → retrieval → LLM reasoning in-process. Check whether the expected ref appears in citations or answer text.

3. **Pass criterion**: `ref_in_citations OR (matched_title_tokens >= 3 AND ref_in_answer)`

If the LLM reasoning step is unavailable (quota exceeded or local model too slow), the retrieval-only check is still valid: verify the expected ref appears in the top-3 candidates from BM25S sparse retrieval.

The audit script template lives at `scripts/run_5query_audit.py`.

## Read-Only Audit Tool

When asked to trace or audit behavior without changing code, use this pattern in `execute_code`:

```python
import sys
sys.path.insert(0, '/repo/path')
sys.path.insert(0, '/repo/path/venv/lib/python3.11/site-packages')

from retrieval.qdrant import get_qdrant_manager
qm = get_qdrant_manager()

# Direct Qdrant scroll — bypasses all filters and pipeline logic
records, _ = qm.client.scroll(
    collection_name='mizan_law',
    scroll_filter=...,
    limit=N,
    with_payload=True,
    with_vectors=False,
)
for rec in records:
    print(rec.payload)
```

This verifies ground-truth Qdrant payloads without touching the retrieval pipeline.

## Log Files

- `data/logs/mizan.log` — main server log (pipeline stages, timers)
- `data/logs/mizn.json.log` — structured JSON log (if configured)
- `data/logs/adala_parser.log` — ADALA parser log (article counts, failures)
- `data/logs/adala_parser_failed.jsonl` — failure records
- `data/logs/adala_crawler.log` — crawler log
- `data/logs/adala_parser_state.json` — parser state
- `data/index/bm25s/corpus.jsonl` — BM25S index corpus IDs

## Environment Notes

- Python: 3.12.3 (use python3, not python)
- venv: `venv/lib/python3.11/site-packages`
- Qdrant: DualIndex mode (mizan_law, mizan_case, mizan_bo collections)
- LLM: Configured via .env (liquid/lfm-2.5-2.6b:free observed)
- Shell: PROMPT_COMMAND hook may break terminal calls — use execute_code
- Freebuff: CodebuffAI CLI (`npx freebuff`), sessions in `~/.config/manicode/`
