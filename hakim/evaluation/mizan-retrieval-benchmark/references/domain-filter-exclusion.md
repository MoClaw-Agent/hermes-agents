# Domain-filter exclusion: the provision exists, the retrieval is fine, the document was removed

A legal provision can fail to reach the model because an **inferred metadata filter**
removed its document from the candidate set before ranking. Every retrieval stage
reports success, the provision is present in the corpus, and the answer abstains for
want of it.

## The root-cause chain

`inject_domain_filter` turned a domain **inferred from the query's wording** into a
**hard** Qdrant `domain` payload filter:

1. `detect_explicit_domain` matched the instrument-reference regex
   (`قانون|ظهير|مرسوم|قرار` + number), then **stripped that reference** and asked
   the ontology to classify the text that remained.
2. For a long prompt that remainder is instruction boilerplate. A rule like
   «اربط كل ادعاء قانوني بمقطع محدد يدعمه، ولا تكتف بإحالة عامة إلى المادة 9» was
   classified `droit_general`.
3. `inject_domain_filter` set `filters["domain"]` — a hard filter. The corpus
   stores only a handful of chunks under that domain; the target law lives under a
   different one, so it never entered the candidate set.
4. Stage 1 ranked unrelated laws; the model abstained.

The failure is silent: the filter is applied inside the retriever, never logged at
the pipeline level, and no stage reports "I excluded the instrument you named".

## The policy that fixes it — one gate, three rules

`retrieval/hybrid/domain_policy.py` is the single gate; every retrieval entry point
delegates to it.

| signal | may do |
|---|---|
| domain the query names **explicitly** (مدونة الشغل, القانون الجنائي, الدستور, …) | constrain recall → hard `domain` filter |
| domain **inferred** from the query's wording | ranking hint only → `_domain_boost`, never a filter |
| query names an **instrument** (قانون رقم 15.01, ظهير رقم 1.02.172) | the instrument *is* the domain signal → suppress the inferred domain entirely |

Rationale: the corpus's `domain` metadata is coarse (a handful of stored values, and
family law folded into `droit_civil`), so a fuzzy classifier must never gate recall.
Explicit keywords are high-confidence; inferred categories are not.

**Wire the boost to a real consumer.** A `_domain_boost` key that no ranking stage
reads is worse than no signal — it implies behaviour that does not occur.
`retrieval/domain_boost.py` is that consumer, following the `retrieval.frame_boost`
contract: runs after retrieval, copies candidate dicts, applies a bounded boost, and
composes with the frame boost. Apply it at the end of the retrieval phase.

**Unify the copies.** `retrieval/dense/_engine.py` used to carry its own
`_inject_domain_filter` without the ref-regex branch, so the two legs answered
different questions for the same query. Two implementations of one policy is how a
bug survives: one copy gets the fix, the other does not.

## The classifier must match Arabic as whole words

`ontology/expander.py` matched Arabic terms as **raw substrings**, so `عام` matched
`عامة` ("general") and `قانون` matched `قانوني` ("legal") — the false positive
that classified instruction boilerplate as "public law".

`arabic_term_present(term, text)` requires a whole-word match: the term may be
preceded by a connector prefix (و ف ب ل ك س) or the definite article الـ (separate
morphemes), but **nothing may follow it**. Verify both directions before trusting a
classifier change:

```python
from ontology.expander import QueryExpander
assert QueryExpander().detect_domain("قانوني عامة") is None      # was: droit_general
assert QueryExpander().detect_domain("قانون عام") == "droit_general"
assert QueryExpander().detect_domain("القانون العام") == "droit_general"
```

## Corpus domain vocabulary (measure, do not assume)

The corpus's `domain` field stores **French canonical keys**, not the Arabic
`LegalDomain` enum spelling. Read the real values with `facet` — scrolling the
collection is slow and times out:

```python
res = mgr.client.facet(collection_name=settings.QDRANT_LAW_COLLECTION,
                      key="domain", limit=100)
{hit.value for hit in res.hits}
```

Only a handful of domains are actually populated. A hard filter naming any other
value is guaranteed to match nothing — the same zero-candidate failure as the
kafala bug. A mapping whose target is not yet stored is a **corpus coverage gap**,
not a code defect: every explicit mapping target is a domain the ingestion can
assign. Pin the gap in a test so growing the corpus is a deliberate change.

## Diagnostic order when the target is absent from stage-1 candidates

Run these in order; each one is cheap and rules out a whole family.

1. **Corpus presence.** Filter Qdrant on `doc_id` / `doc_ref` and grep the chunk
   payloads (both `text` and `parent_text`) for the distinctive phrase. If it is
   absent, the problem is ingestion, not retrieval.
2. **Plain dense retrieval.** `hybrid_retriever.dense.retrieve_parallel(query, filters=None)`.
   If the target is present here, the failure is downstream of the raw search.
3. **The injected filter.** `hybrid_retriever._retrieve_raw_parallel(query, {})` and
   read the returned `effective_filters`. A `domain` key that the target's own
   payload does not carry is the cause — confirm by neutralising the injection in a
   probe (monkeypatch `_inject_domain_filter` to pass the filters through) and
   re-running stage 1. If the target reappears at rank 0, the filter was it.
4. **Stage-by-stage.** Only after the filter is cleared: stage-1 law ranking,
   stage-2 article targeting, stage-3 clause selection.

Do not change the embedding model or the reranker before step 3. A hard filter that
removes the document makes every downstream ranking number meaningless.

## Normalisation round-trip to know about

`canonical_to_qdrant` returns the Arabic enum spelling; the payload stores the French
key; `normalize_domain` folds one back to the other. The round-trip was repaired once
and a test pins it — but the policy now names the stored key directly, so there is no
second vocabulary to drift. When you touch domain values, run
`tests/test_domain_filter_reaches_stored_key.py` and
`tests/test_domain_filter_stored_keys.py`.
