---
name: mizan-retrieval-benchmark
description: "One-question-at-a-time Mizan retrieval pipeline benchmark."
version: "1.0.0"
author: "Hermes Agent"
metadata:
  hermes:
    tags: [mizan, retrieval, benchmark, probe, evaluation]
    related_skills: [mizan-legal-platform-debugging, mizan-pipeline-audit]
license: MIT
tags: [mizan, retrieval, benchmark, probe, evaluation]
---

# Mizan Retrieval Benchmark

> The project's workflow docs live in `doc/workflow/` — `RULES.md` is the standing contract. Read them before changing code.

## When to Use
- One question at a time, through the public `/search` endpoint, testing the retrieval
  pipeline against the currently ingested corpus.
- The five-question set at `evaluation/retrieval_qa_ingested_corpus.json` is the
  canonical starting point (`expected_ref` / `expected_provision` / `answer_ar`).
- Verifying how a change to the query pipeline, retriever, or payload fields moves a
  result against a known provision.

## Always-on rules (standing user preferences for this task)
- **One question at a time.** Launch each question as its own background process and
  verify it before launching the next. Do not batch all questions into one call.
- **Clear the semantic cache before each question.** A cache hit returns the prior
  answer and masks whether the pipeline actually re-ran. Clear with
  `from core.semantic_cache import get_semantic_cache; get_semantic_cache().clear()`
  before each question.
- **Use a ≥5 minute client timeout.** The server is slow (semantic + RAG pipeline:
  QU/OCR-camel, dense + sparse, rerank, LLM reasoning, citation verify). Set the HTTP
  client timeout to 360 s and do not expect a single question to finish in <60 s.
- **Report only what actually ran.** Never claim the suite is green; report the numbers,
  not adjectives.
- **If the user signals frustration, answer in one short block first** — state the
  verdict and where the failure is, then the evidence. Do not deliver a monologue
  before the user can react.
- **Answers are from chunks, not PDFs.** The benchmark's expected answers were read
  from ingested chunks, so this tests retrieval, not re-extraction or re-parse.
- **The anonymous `/search` endpoint carries a small daily request cap** (verified
  5/day, later raised to 50/day by the user). Each `/search` poll counts against it;
  exceeding it returns HTTP 429 / `anonymous_quota_exceeded` and the window must fully
  reset. Budget the benchmark questions, do not re-run a failed query more than once,
  and don't expect the endpoint to reset mid-burst.
- **Never load the full LLM embedder inside a probe on this machine.** Instantiating
  the hybrid retriever and calling the dense leg loads the bge-m3 embedder (~1.7 GB)
  and stalls ~2.5 min on CPU with no output, burning the iteration budget before the
  first useful line. A probe may start from the **live `/search` response** (already
  run) or a **sparse-only (BM25) reproduction** — both finish immediately and need no
  embedding. Only if the sparse leg cannot separate the causes, trigger the dense leg
  under a hard timeout and read
  incrementally.

- **Stage-3 candidate pool is not deduplicated by `chunk_id`.** In the
  hierarchical retriever (`retrieval/hierarchical/stages.py`) the
  `mmr_rerank()` does not dedupe, and Stage-2 builds
  `MAX_LAWS × MAX_ARTICLES_PER_LAW` candidates without a `chunk_id` check,
  so the same chunk can be selected 3× (q1 returned `chunk_31` three
  times). Fix: dedupe Stage-2's candidate pool by `chunk_id` (keep
  first/highest-ranked copy) before the Stage-3 MMR cap. Verified this
  session: no `chunk_id` appears 3×, and the expected Art. 19 surfaced
  once.

## Environment and settings

- **Two copies of the per-plan tier config.** `billing/plans.py` defines
  the `Plan` dataclasses (for the billing API) — **changing its fields
  does not move retrieval**. The config that `get_context_limit()` and
  `get_context_chunk_limit()` actually read is `MODEL_TIERS` in
  `core/settings/system.py` (loaded by `core/settings/__init__.py`).
  When a retrieval number does not move after you change
  `billing/plans.py`, check `core/settings/system.py` and the `.env`
  load order in `run_server.py`.
- **The per-quota context limit drives the response, not the retrieval.**
  `get_context_limit(plan_id, quota_decision)` →
  `get_context_chunk_limit(plan_id, quota_downgrade)` reads
  `MODEL_TIERS[plan_id]["answer_generation"]["max_context_chunks"]`.
  That value flows into `_run_context_compression` and
  `_build_mizan_results(final_candidates, max_chunks)`, so
  `retrieved_docs` in the `/search` response is capped at that number.
  Raising it flows straight to the answer; changing pipeline candidates
  does not. Verify by re-reading the full response, not only the
  top-ranked chunk.
- **`skill_view` can return "pruned" during context compression.** The
  debug-workflow skill was pruned and `skill_view` 504'd. When the
  skill body is unavailable, recover by reading the source files
  directly (`retrieval/hierarchical/stages.py`, `orchestrator.py`);
  do not trust a truncated body or invent its contents.
- **Anonymous `/search` rate limit.** Per-IP 10/min (HTTP 429 `anonymous_quota_exceeded`). The anonymous endpoint also carries a daily cap: the running server's `ANONYMOUS_DAILY_REQUESTS` (default 10, currently 20 in the live config) is enforced in `api/routes/search_billing.py` via `get_user_usage("anonymous")` → `usage_logs` in `data/auth.db`. A daily window resets at midnight UTC — budget questions, do not re-run a failed one, and do not expect the endpoint to recover mid-burst.

## Procedure
1. Pick the next question `q`; write its `expected_ref` and `expected_provision` to a
   scratch file.
2. Clear the semantic cache (`core.semantic_cache.get_semantic_cache().clear()`).
3. POST to `/search`:
   ```python
   import json, urllib.request
   body = json.dumps({
       "query": q["question_ar"], "role": "public", "language": "ar",
       "use_reranker": True, "mode": "rag",
   }).encode("utf-8")
   req = urllib.request.Request("http://localhost:8000/search", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
   with urllib.request.urlopen(req, timeout=360) as r:
       res = json.load(r)
   ```
4. Read `res["retrieved_docs"]` — each `chunk.metadata.ref` / `provision_ref` /
   `text` / `validity_status` / `source_provider`. Record `top1_ref`,
   `top1_provision`, `n_results`, `answer` (first ~200 chars), `timing_seconds`.
5. Classify the result:
   - **correct** — top1 ref + provision matches expected;
   - **wrong-article** — right law, wrong article (expected a different article of the
     same document);
   - **missing** — the expected document never appears in the top-k;
   - **api-failure** — HTTP error, timeout, or language mis-detected.
1. Append one JSONL line per question to `cache/scratch/retrieval_probe.jsonl`.

## Creating a new 5-question benchmark set
When a new set (e.g. `set_new20261024`) is requested for a run, write it to
`evaluation/retrieval_qa_<setname>.json` with this shape:
```json
{
  "set_id": "set_new20261024",
  "purpose": "short description of the domains under test",
  "corpus": "data/mizan.db (SQLite: 8,231 chunks, 187 documents) + Qdrant mizan_law (1 point per chunk_id)",
  "questions": [
    {"id": "q11", "question_ar": "...", "expected_ref": "1.05.185",
     "expected_provision": "المادة 1", "answer_ar": "...", "source": "ظهير 1.05.185"}
  ]
}
```
- `expected_ref` must exist as a `documents.ref` in `data/mizan.db` (verify via SQLite join on `doc_id`).
- Verify the expected provision text is present in `chunks.text` for that ref before writing the question.
- Save the answer text from the source document (the provision's `text` field), not a paraphrase.
- Run the set with a probe that imports the set file and POSTs each question through `/search`, one per background process, with a 12s sleep between questions to respect the anonymous rate limit. The probe must classify each question (correct / wrong-article / missing / api-failure) and report `chunk_id` duplicate counts.

## When a question fails — which stage first lost the gold answer?
The stage-by-stage debug workflow lives in the parent skill, `mizan-legal-platform-debugging`
(freeze the case, confirm evidence exists in SQLite first, then walk query-side →
dense/sparse retrieval → fusion/rerank). Reaching the `mizan-retrieval-benchmark`
pitfalls below (the memory/swap-thrash signature, the payload-field probe, the stale
semantic cache) should come BEFORE re-running the stage-by-stage debug, because a
probes that never really load the embedder will report a wrong-article result that
looks like a retrieval defect.

**Reproduce fast, before anything else.** Order:

1. **Sparse-only (BM25) reproduction.** From a fresh process run
   `retriever.sparse.retrieve(query, top_k=20)` (no embedding). If BM25 already
   returns the right article, the dense/engineering leg is the suspect.
2. **Live `/search` response.** Read `top1_ref`, `top1_provision`, and the count of
   duplicate `chunk_id`s in `retrieved_docs`. Duplicates of the *same* chunk at
   ranks 1–3 point to a fusion/retrieval re-listing bug, not a payload or ingest bug.
   Classify the defect family before touching code — a duplicate-chunk signature is a
   re-listing bug ONLY while duplicates exist:
   - **dupes present** → retrieval re-listing / duplicate bug (e.g. `chunk_id` not
     deduplicated in the hierarchical stage-2 candidate pool, so MMR selects the same
     chunk 3×). Fix at the candidate pool, not the payload.
   - **no dupes + same law, wrong article** → genuine ranking defect within one law
     (dense/sparse rank or MMR rerank). q1's Art. 18-over-Art. 19 is this family.
   - **no dupes + wrong law** → law-targeting or fusion defect, or the expected
     instrument is superseded (old decree vs current law). q8's `1.75.243`→`1.19.116`/
     `1.02.125` is this family.
   - **no dupes + expected never in top-k** → corpus gap *or* a dense/sparse failure to
     retrieve the right provision; confirm the chunk exists in SQLite before blaming
     the index.
   - **no dupes + expected never in top-k + an inferred domain filter is active** →
     **metadata-filter exclusion**. The provision is in the corpus and plain dense
     retrieval finds it, but a hard `domain` filter removed the document before
     ranking. Check the injected filter (`hybrid_retriever._retrieve_raw_parallel(query, {})`
     → `effective_filters`) **before** any ranking diagnosis — a filter that excludes
     the named instrument makes every downstream ranking number meaningless.
     Depth, the root-cause chain, and the three-rule fix policy:
     `references/domain-filter-exclusion.md`.

3. **Sparse leg from the live corpus.** Via `retrieval/sparse/retriever.py` directly
   (no embedder). Confirm the right chunk exists in the corpus and is findable by
   BM25. If it is, the defect is in the dense/engineering leg or fusion.
4. Only then, deep-run the dense leg under a hard timeout (bge-m3 embedder on this
   CPU is slow) and read output incrementally.

**Cap-clipping obfuscation — a capped per-law candidate pool can masquerade as a
ranking defect.** A within-law question that shows no duplicates (same law, wrong
article, no dupes) is classified as a "genuine ranking defect", but verify FIRST
whether the expected article simply sits *just outside* the `MAX_ARTICLES_PER_LAW`
cap. In q1 the expected Art. 19 ranked dense #4 of ~20 (score 0.508, within 0.6% of
rank-3 Art. 16) but a per-law budget of 3 clipped it out of Stage-3 entirely, so the
MMR reranker never saw it. Fix the cap before re-tuning scores. Do not assume the
ranking defect is semantic until you have read the per-article dense rank of the
expected article inside the target law.

**Law-targeted-but-right-article-missing.** When Stage-1 correctly includes the
expected law but the article never appears in its capped candidate pool (family:
"no dupes + expected never in top-k"), do NOT blame the index before confirming the
chunk actually exists in SQLite under that doc_id. In q8 the expected `1.75.243` was
targeted correctly, yet its Stage-2 dense top articles were `الفصل 51-xx`
breakdown-chapter text (score 0.576) rather than the registration-purpose article —
the dense leg itself leaked the wrong content, so a corpus check alone cannot
distinguish this defect from a genuine retrieval failure.

## When a question fails — live the stage-by-stage diagram (q1/q8 probe)

For a failing within-law or law-targeted result, run the reproducible stage
instrumentation in `scripts/retrieval_stage_diag.py` (works in the repo venv). It
prints, per question: Stage-1 law candidates with their `stage1_dense/sparse/fused`
counts; Stage-2 per-article dense rank (top 20) for every targeted law, so you read
exactly where the expected article falls relative to the cap; and Stage-2 capped
candidates followed by Stage-3 MMR output. Use that ordered output to decide whether
the fault is cap-clipping, semantic-density, or fusion before changing code.

## Findings discipline (this session's lesson)

- Record findings to a file (`cache/scratch/retrieval_probe_findings.md`), NOT to
  long-term memory (memory has a ~2,200-char entry limit; an over-large add is
  silently rejected, so log there instead).
- Never present a test, number, or legal reference as verified unless you ran it and
  saw the output. If you did not run it this session, it is a hypothesis, not a
  result — rerun it before reporting.
- When the user signals frustration (`stop`, `wtf`, `don't explain`), answer in one
  short block first (verdict + stage), then the evidence.

## Reference
`references/run-recipe.md` — the ready-to-copy form of the one-question background run,
the payload fields, and the environment facts for the currently ingested corpus.
`references/domain-filter-exclusion.md` — why a provision that is present in the corpus
can still never reach the model: the inferred-domain hard filter, the three-rule policy
that fixes it, the Arabic whole-word classifier fix, the corpus domain vocabulary, and
the ordered diagnostic when the target is absent from stage-1 candidates.
