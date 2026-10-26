"""Stage-2/Stage-3 instrumentation probe for q1 and q8 (writes to file).",
"""
import sys
MZ = "/home/mohammed/Mizan"
if MZ not in sys.path:
    sys.path.insert(0, MZ)

import json as _json
from core.query_preprocessor import preprocess_query
from retrieval.hierarchical.stages import (
    stage1_law_ranking,
    stage2_article_targeting,
    stage3_clause_retrieval,
    _rank_articles_for_law,
)
from retrieval.dense import DenseRetriever

OUT = "/home/mohammed/.hermes/profiles/hakim/cache/scratch/stage_diag_out.md"
f = open(OUT, "w", encoding="utf-8")

QA_PATH = "/home/mohammed/Mizan/evaluation/retrieval_qa_ingested_corpus.json"
QA2_PATH = "/home/mohammed/Mizan/evaluation/retrieval_qa_new_set.json"
QAS = __import__("json").load(open(QA_PATH, encoding="utf-8"))
QAS2 = __import__("json").load(open(QA2_PATH, encoding="utf-8"))
Q = {x["id"]: x for x in QAS["questions"]}
Q.update({x["id"]: x for x in QAS2["questions"]})
q8_text = Q["q8"]["question_ar"]


def trace(qid, qtext, lang="ar"):
    f.write("\n" + "#" * 78 + "\n")
    f.write("QUERY (q%s): %s\n" % (qid, qtext[:70]))
    pp = preprocess_query(qtext, lang=lang)
    f.write("expanded=%s\n" % pp.expanded_query[:100])
    f.write("legal_domains=%s art_refs=%s\n" % (pp.legal_domains, pp.article_refs))

    stage1 = stage1_law_ranking(pp.expanded_query, pp, filters=None)
    f.write("\n--- STAGE 1 (law candidates) -- count=%d ---\n" % len(stage1))
    for parent in stage1:
        payload = parent.get("payload") if isinstance(parent, dict) else {}
        m = parent.get("_hierarchical_retrieval_metrics", {}) or {}
        f.write("  doc_id=%s canonical_id=%s ref=%s title=%s\n" % (
            payload.get("doc_id") or parent.get("doc_id"),
            payload.get("canonical_id"), payload.get("ref"),
            str(payload.get("title") or parent.get("title"))[:60]))
        f.write("      stage1=%s sparse=%s fused=%s\n" % (
            m.get("stage1_dense_hits"), m.get("stage1_sparse_hits"),
            m.get("stage1_fused_hits")))

    for parent in stage1:
        payload = parent.get("payload") if isinstance(parent, dict) else {}
        doc_id = payload.get("doc_id") or parent.get("doc_id")
        if not doc_id:
            continue
        ref = payload.get("ref")
        f.write("\n--- STAGE 2 dense ranking doc_id=%s ref=%s top20 ---\n" % (doc_id, ref))
        try:
            ranked = _rank_articles_for_law(
                pp.expanded_query, doc_id, max_articles=20,
                dense_retriever=DenseRetriever())
            for i, c in enumerate(ranked[:20]):
                f.write("  [%d] ref=%s chunk=%s score=%s len=%d text=%s\n" % (
                    i, c.get("article_number"), c.get("chunk_id"),
                    c.get("rerank_score"),
                    len(str(c.get("text"))), str(c.get("text"))[:30]))
        except Exception as e:
            f.write("   dense_ranking errored: %s\n" % repr(e)[:100])

    stage2 = stage2_article_targeting(pp.expanded_query, pp, stage1, filters=None)
    f.write("\n--- STAGE 2 (capped) article candidates first20 ---\n")
    for c in stage2[:20]:
        f.write("  ref=%s chunk=%s rerank_score=%s text=%s\n" % (
            c.get("article_number"), c.get("chunk_id"),
            c.get("rerank_score"), str(c.get("text"))[:30]))
    f.write("  total stage2_articles=%d\n" % len(stage2))

    stage3 = stage3_clause_retrieval(pp.expanded_query, pp, stage2, hypothetical_doc=None)
    f.write("\n--- STAGE 3 (MMR) final top8 ---\n")
    for c in stage3.chunks[:8]:
        f.write("  ref=%s chunk=%s rerank_score=%s text=%s\n" % (
            c.get("article_number"), c.get("chunk_id"),
            c.get("rerank_score"), str(c.get("text"))[:30]))
    f.write("  stage_metrics=%s\n" % stage3.stage_metrics)


trace("q1", Q["q1"]["question_ar"])
trace("q8", q8_text)
f.close()
print("wrote %s" % OUT)