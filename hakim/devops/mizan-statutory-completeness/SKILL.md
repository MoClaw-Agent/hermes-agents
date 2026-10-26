---
name: mizan-statutory-completeness
description: "Use when an answer omits or adds statutory content."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [mizan, retrieval, reasoning, citations, arabic, completeness, qdrant]
    related_skills: [mizan-legal-platform-debugging, mizan-retrieval-benchmark, corpus-quality-audit]
---

# Mizan Statutory Completeness

> The project's workflow docs live in `doc/workflow/` — `RULES.md` is the standing contract. Read them before changing code.

## When to Use

- An answer to "ما هي الشروط المقررة لـ…" lists fewer conditions than the statute has
- An answer drops a qualifier the source contains (e.g. `الاجتماعية` from `صالحين للكفالة أخلاقياً واجتماعياً`)
- An answer adds eligibility wording the source does not have (e.g. `مجتمعين أو منفردين`)
- A legal-review table of "remaining issues" in an answer needs verifying against the source

## The decisive test — read BOTH payload fields

A legal article's numbered subparagraphs are routinely split across sibling chunks.
Article 9 of 1.02.172 spans `chunk_14` (الفقرتان أ وب) and `chunk_15` (ج ود + البندان 2 و3);
both share one `parent_text` (1809 chars) carrying the whole article, while each chunk's
`text` carries only its own slice (965 / 843 chars).

Dump the retrieved chunk's payload and grep BOTH fields BEFORE blaming retrieval,
chunking, or the model:

- `payload['text']` — the chunk-local slice (what the generator used to receive)
- `payload['parent_text']` — the full parent article

If the missing conditions are present in `parent_text` but absent from `text`, the
failure is the context builder, not retrieval and not the model.

Probe shape (Qdrant scroll on `doc_id` / `chunk_id`, then compare markers):

```python
flt = qm.Filter(must=[qm.FieldCondition(key="chunk_id", match=qm.MatchValue(value=cid))])
pts, _ = mgr.client.scroll(collection_name=settings.QDRANT_LAW_COLLECTION,
                           scroll_filter=flt, limit=5, with_payload=True, with_vectors=False)
pl = (pts[0].payload or {})
for label, blob in (("text", pl.get("text", "")), ("parent_text", pl.get("parent_text", ""))):
    print(label, {m: (m in blob) for m in MARKERS})
```

## The rule

The reasoning layer must build its context from `parent_text or text`
(`api/routes/search_pipeline/reasoning.py::_build_mizan_results`), matching the dense
retriever (`retrieval/dense/_engine.py`). Measured on the live corpus: before the fix
the context held 2 of 4 conditions (أ and ب missing); after, all four.

## Second, independent cause: corpus OCR defect

A model faithfully following a corrupted corpus repeats the corruption. The ADALA text
of Article 9 reads `مرض مع` (official: `مرض معدي`), `الوسائل المالية` (official:
`الوسائل المادية`) and `وتشجيعهم للتنشئة إسلامية` (official: `وتنشيئتهم تنشئة إسلامية`).

Cross-check a suspect clause against a second copy of the law (the official gazette, or
any independent transcription) before calling the answer wrong. A generation fix alone
does not close the gap when the corpus is the source of the error.

**Where the SOURCE page text actually lives.** ADALA/ISM keeps it in
`data/corpus/<provider>/cache_vision/<doc>_vision.json` (the structure text cache). The
parsed JSON has NO `pages` field — a probe that reads `pages` finds ZERO documents, so
verify a clause against the vision cache (or the official gazette), never against the
parsed tree. Reading the parsed JSON and reporting "the source says X" when you never
read the page text is a fabricated verification.

## The gate

`evaluation/claim_scorer.py::_check_statutory_conditions` is a two-sided
**statutory-fidelity** gate:

- **Recall** — parses the numbered subparagraphs (أ، ب، ج، د…) of the retrieved
  article and requires each to be addressed in the answer. Exposes
  `missing_conditions` / `missing_condition_rate`; a dropped condition depresses
  `blended_attribution`.
- **Precision** — lexical grounding: which of the answer's content terms (and the
  2-grams containing them) are unattested in the source, plus the sentences with
  no source support. Exposes `unsupported_terms`, `unsupported_phrases`,
  `unsupported_claims`, `novelty_rate`, `grounding_ratio`.

Two implementation pitfalls that silently broke this gate — both were live bugs:

- `_parse_article_conditions` must return the subparagraph **text**, not the bare
  label. A bare label has no words to match on, so every condition reads as
  missing and a complete article scores 0%.
- `_extract_condition_keywords` must strip only the leading label (`أ) `). A
  character class spanning the whole Arabic alphabet strips the alif from every
  word and leaves nothing to match on.

Lexical grounding cannot separate a legitimate paraphrase from a real addition
(«السجل العدلي» for «سبق الحكم … بجريمة» is unattested too), so the unattested
lists are **review candidates, not verdicts**, and the penalty only bites past
`NOVELTY_TOLERANCE` (0.70). A faithful-but-paraphrased answer measures novelty
≈ 0.62 — recalibrate from a real answer before tightening the threshold.

### The grounding normalizer must fold the definite article الـ

`_normalize_for_grounding` folds hamza / ya / ta-marbuta, but **not** the definite
article الـ. So the answer's `النزاع` and the source's `نزاع` are different tokens, and
`النزاع` / `القضائي` / `الكفالة` are reported **unsupported** while the source carries
them — a false positive that inflates `novelty_rate` and makes the unsupported lists
unusable as a verdict.

Check this before trusting any `unsupported_terms` output:

```python
from evaluation.claim_scorer import _normalize_for_grounding, _content_tokens
src = "نزاع قضائي أو خلاف عائلي"
ans = "النزاع القضائي يسقط الكفالة"
print(_content_tokens(src))   # ['نزاع', 'قضايي', ...]
print(_content_tokens(ans))   # ['النزاع', 'القضايي', ...]  <- should match, does not
```

Strip الـ on both sides (as `ontology/domain_normalizer._normalise_domain_name`
already does) before comparing. A grounding signal that fires on orthography is a
false-positive generator, not a gate.

### The gate is two-sided; it does not label WHY a claim is unsupported

`unsupported_claims` conflates three different things — a legitimate inference, an
added rationale, and an asserted authority/evidentiary requirement. It catches the
sentence but not the reason, so a reviewer cannot act on it. When a review asks for
the distinction, the deterministic part is a marker set (evidentiary requirements
«إلا إذا ثبت» / «ما لم يثبت», authority claims «الاجتهاد القضائي» / «سلطة تقديرية»),
flagged **only when the source does not carry the same requirement**. Separating a
true inference from an unsupported one reliably needs semantic verification (the NLI
path), not lexical overlap — do not present a marker set as a complete answer.

## Classify before fixing

| symptom | likely layer |
|---|---|
| phrase absent from the corpus entirely (e.g. `مجتمعين أو منفردين`) | generation |
| qualifier the corpus itself lost (e.g. `معدي`) | corpus OCR |
| qualifier the corpus HAS but the answer dropped (e.g. `الاجتماعية`) | generation |
| conditions present in `parent_text`, absent from `text` | context builder |
| provision is in the corpus but never enters the candidate set | metadata filter |

The last row is a different failure from every other one: the provision exists, the
retrieval is fine, and the document was **excluded before ranking**. Confirm the
injected Qdrant filter first — an inferred domain turned into a hard `domain`
filter will silently remove the named instrument while every retrieval stage
reports success. The ordered diagnostic and the three-rule fix policy live in
the `mizan-retrieval-benchmark` skill, under its domain-filter exclusion reference.

Never report a condition as verified without having read the source text yourself.
