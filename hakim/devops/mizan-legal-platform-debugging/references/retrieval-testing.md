# Testing the retrieval pipeline against the ingested corpus

Class of work: the user wants to know whether retrieval actually returns the
right provision. The deliverable is a set of questions whose answers are
known BEFORE the query runs, plus the measured rank of the expected chunk.

## 1. What the ingested corpus actually looks like

The parsed corpus JSON is NOT a text source. Measured on the live store:

| fact | value |
|---|---|
| `data/mizan.db` tables | `documents`, `chunks`, `document_relations`, `citation_graph`, `citations`, `ingestion_checkpoints` |
| the documents row | `doc_id`, `ref`, `title`, `document_type`, `legal_rank`, `legal_domain`, `effective_date`, `is_amendment`, `amends_doc_ref`, `amendment_note`, `validity_status`, `source_authority` |
| the chunks row | `chunk_id`, `doc_id`, `chunk_index`, `token_count`, `text_segmented`, `text` — **no label** |

**The parsed JSON carries no `pages` field.** It holds `page_texts_sample`
(preview only) and `full_text_in_cache` (a pointer). The full page text lives
in the vision cache, so a corpus-impact measurement that reads page text
from the parsed JSON reads NOTHING and reports zero documents. Read page
text from the cache, or measure the decision on synthetic inputs and say
so.

**The chunk LABELS live in the Qdrant payload, not in SQLite.**

```python
from qdrant_client import QdrantClient
c = QdrantClient(url="http://localhost:6333", check_compatibility=False)
pts, offset = c.scroll(collection_name="mizan_law", limit=100, with_payload=True)
```

Useful payload fields: `short_name` (the instrument ref, e.g. `1.04.22`),
`provision_ref` (e.g. `Art. 19`, `Fasl. 267`), `section`, `text`,
`title`, `valid_from`, `validity_status`, `source_provider`,
`related_refs_v2`, `relationships`.

Pass `check_compatibility=False` — the pinned client is older than the
server and the version check raises.

## 2. The retrieval entry point (no LLM)

```python
from api.dependencies import get_qu_pipeline, get_hybrid_retriever
qu = get_qu_pipeline()
retriever = get_hybrid_retriever()
qr = qu.process(question, skip_hyde=True)
results = retriever.retrieve(qr.get("normalized_query", question))
```

This is the same path the benchmark runner uses
(`api/routes/benchmark/retrieval_benchmark.py::_run_retrieval_query`), so
a measurement taken this way is comparable to a benchmark run.

## 3. The first call is SLOW — budget for it

`get_hybrid_retriever()` loads the embedder and rebuilds the BM25S index.
The first `retrieve()` in a fresh process takes minutes, and a multi-query
run can exceed the tool's 420 s foreground cap (observed: a five-question
run timed out at 420 s with no output).

- Warm the pipeline ONCE, then run every question in the SAME process.
- Do not pipe the whole run through `tail`/`grep` — the pipe buffers and you
  see nothing until the process exits, so a slow run looks hung.
- Expect the first query to dominate the timing; report the per-phase
  timings so the next session knows which part is slow.

## 4. Writing the questions

Pick provisions that are SPECIFIC and verifiable — a number, a date, a
deadline, a named condition. A provision that states a general principle
makes a weak test because many chunks are plausibly relevant.

Good shapes: "what is the penalty for X when Y", "may Z do W", "within
how many days must V decide".

Ground each answer in the ingested chunk itself, and record the
`ref` + `provision_ref` as the expected hit. Then report the rank at which
the expected chunk appears — `NOT IN THE TOP 5` is a real result, not a
failure to hide.

## 5. The benchmark harness is ingest-then-query — do not reuse it as-is

`api/routes/benchmark/retrieval_benchmark.py` ingests the test set's OWN
documents, queries, then deletes them. It answers "does retrieval work on
documents it just wrote", not "does retrieval work on the ingested
corpus". For the ingested corpus, query the live store directly (§2) and
write the Q/A to a plain JSON file rather than a `set_*` directory.

The expected set shape, if you do need one:
`{"set_id", "domain", "documents": {<category>: [...]}, "questions":
[{"id", "question_fr"|"question_ar", "expected_topics"|
"expected_topics_ar", "expected_refs"}]}` under
`evaluation/test_sets/set_<id>/<id>.json`.

## 6. A probe that looks hung is usually memory-starved, not code-dead

Watch CPU, RSS and thread count on the probe over time in one shot (`ps -eo pid,etime,pcpu,rss,args --sort=-rss | head` shows the whole memory posture).

- **Flat ≈ 0 % CPU and flat RSS = memory/swap thrashing, not a deadlock.** That is the signature of a process paging out. Before concluding the code is hung, check the memory posture.
- **Suspects, biggest first:** the API server `run_server.py` (~6.5 GB), Qdrant (~3.7 GB), Ollama `serve` (~2.3 GB), then the new embedder load (~1.7 GB for `bge-m3`).
- **Free RAM, don't re-read code:** reduce the embedder's working set (smaller model or quantization) or lighten the heaviest consumer so the probe's own load fits. A hung embedder load cannot be fixed by commenting out a logger.
- **Baseline before you conclude:** a probe that prints ≈ 0 in BOTH CPU and RSS is looking at the wrong text source/tree, not an empty result. Trust the first non-zero reading as your baseline.
