# Mizan retrieval benchmark — run recipe

Ready-to-copy form for running ONE background question. Write this probe as a `.py`
under `cache/scratch/` and launch it with the repo venv python in the background;
it appends one JSONL line per question to a single results file.

## Environment facts (verified, currently ingested corpus)
- SQLite `data/mizan.db`: **187 documents, 8,231 chunks, 217 document_relations,
  3,627 citation_graph entries, 780 citations**, all `language: ar`.
- Qdrant `localhost:6333` live: `mizan_law`, `mizan_case`, `mizan_bo`,
  `mizan_semantic_cache`. Client `1.14.2` vs server `1.19.0` → use
  `check_compatibility=False`.
- API healthy on `:8000` (`/health` returns 200).
- Payload carries `short_name` (the ref), `provision_ref` (e.g. `Art. 19`),
  `section`, `text`, `valid_from`, `validity_status`, `source_provider`.
- `api.dependencies` lazy singletons: `get_qu_pipeline()`, `get_hybrid_retriever()`,
  `get_embedder()`.
- The embedder is `BAAI/bge-m3` (1024d); first use loads it on CPU and takes
  >420 s. The QU pipeline's `HyDEGenerator` also creates an LLM provider —
  pass `skip_hyde=True` to avoid an Ollama/OpenRouter call.

## Probe pattern (copy, then edit `qa_path`, `out_path`, and the question index)
```python
import json, os, sys, time, warnings

warnings.filterwarnings('ignore')
MZ_ROOT = os.environ.get('MZ_ROOT', '/home/mohammed/Mizan')
if MZ_ROOT not in sys.path:
    sys.path.insert(0, MZ_ROOT)

QA_PATH = os.path.join(MZ_ROOT, 'evaluation', 'retrieval_qa_ingested_corpus.json')
OUT_PATH = os.path.join(MZ_ROOT, '.hermes', 'profiles', 'hakim', 'cache', 'scratch', 'retrieval_probe.jsonl')

from api.dependencies import get_qu_pipeline, get_hybrid_retriever

with open(QA_PATH, encoding='utf-8') as f:
    qas = json.load(f)

# Run ONE question per process (one-question-at-a-time). Edit this index.
q = qas['questions'][0]

# Warm the models once (embedder + BM25S) before the first real question.
t0 = time.time()
qu = get_qu_pipeline()
retriever = get_hybrid_retriever()
print(f'[warmup] loaded in {time.time() - t0:.1f}s', flush=True)

qr = qu.process(q['question_ar'], skip_hyde=True)
norm = qr.get('normalized_query')
print(f'[query] normalized: {norm!r}', flush=True)

t1 = time.time()
results = retriever.retrieve(norm)
dt = time.time() - t1
print(f'[retrieve] {len(results)} chunks in {dt:.1f}s', flush=True)

top1 = results[0] if results else {}
print(f'EXPECTED ref={q["expected_ref"]} provision={q["expected_provision"]}')
print(f'TOP-1: ref={top1.get("short_name")} provision={top1.get("provision_ref")}')
print(f'        text: {(top1.get("text") or "")[:160]}')
print(f'        validity_status={top1.get("validity_status")} source_provider={top1.get("source_provider")}')

entry = {
    'id': q['id'],
    'question_ar': q['question_ar'],
    'expected_ref': q['expected_ref'],
    'expected_provision': q['expected_provision'],
    'top1_ref': top1.get('short_name'),
    'top1_provision': top1.get('provision_ref'),
    'top1_text_head': (top1.get('text') or '')[:200],
    'validity_status': top1.get('validity_status'),
    'source_provider': top1.get('source_provider'),
    'retrieval_seconds': dt,
    'n_results': len(results),
}
with open(OUT_PATH, 'a', encoding='utf-8') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
```

## Launch
```bash
cd /home/mohammed/Mizan
nohup /home/mohammed/Mizan/venv/bin/python /home/mohammed/Mizan/cache/scratch/retrieval_probe_q1.py > run_q1.log 2>&1 &
```

## Aggregate
```bash
python3 -c "import json; rows=[json.loads(l) for l in open('.hermes/profiles/hakim/cache/scratch/retrieval_probe.jsonl')]; print([(r['id'], r['top1_ref'], r['top1_provision'], round(r['retrieval_seconds'],1)) for r in rows])"
```

## Pitfalls (already in `mizan-retrieval-benchmark` SKILL.md)
- **System python fails to import.** `ModuleNotFoundError: slowapi` means you are not using the repo venv — re-run with `/home/mohammed/Mizan/venv/bin/python`.
- **Hardcoded `sys.path` reads the live tree.** Pass `MZ_ROOT` and print the imported `__file__`; a baseline probe that ignores this reports the fixed result against itself.
- **Baseline must be pre-fix.** `git archive HEAD` is the current commit; measure against `HEAD~1`/the wave's base SHA and parameterise `MZ_ROOT`.
- **Language detection from the head, not the stored `language` field**, for jurisprudence records tagged `fr` but carrying Arabic.
