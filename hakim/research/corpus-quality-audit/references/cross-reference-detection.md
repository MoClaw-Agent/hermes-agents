# Cross-Reference vs Primary-Content Detection

Diagnostic procedure for the "cross-reference mistaken for primary content" failure mode: the RAG retrieves a document that cites another instrument's article, and the LLM treats the citation as if it contained the referenced article's text.

## Symptom

A legal RAG answer builds its analysis around a document whose title indicates it is NOT the governing instrument, but rather a document that references the governing instrument. The answer contains legal-sounding citations but the central authority chain is wrong.

Classic example: a Moroccan labor-law overtime question retrieves `1.14.190` (ظهير شريف بتعويض حوادث الشغل — workplace accident compensation law). Article 75 of that law cites "المادة 202 من القانون بمثابة مدونة الشغل". The LLM treats this cross-reference as if it had Article 202's actual text, and builds the answer around the accident-compensation law rather than the Labor Code.

## Detection procedure

### Step 1 — Find every corpus file mentioning the target article/provision

Search the entire corpus JSON tree for the article number as a string. This includes article titles, article content, and full_text fields.

```bash
# Grep for article 202 across all corpus JSON (adjust article number as needed)
cd /home/mohammed/Mizan
grep -rn "المادة 202\|Article 202\|article 202" data/corpus/ --include="*.json" | head -20
```

For a programmatic version that also captures articles embedded in structure trees:

```python
import json, os

target_article = "202"  # or "75", "200", etc.
hits = []

for root, dirs, files in os.walk("data/corpus"):
    for f in files:
        if f.endswith(".json"):
            p = os.path.join(root, f)
            try:
                d = json.load(open(p))
                # Search title, ref, full_text, and entire structure tree
                blob = json.dumps(d, ensure_ascii=False)
                if target_article in blob:
                    hits.append({
                        "path": p,
                        "title": d.get("title", "")[:120],
                        "ref": d.get("ref", ""),
                        "doc_type": d.get("document_type", d.get("type", "")),
                    })
            except Exception:
                pass

print(f"Files mentioning article {target_article}: {len(hits)}")
for h in hits[:15]:
    print(f"  ref={h['ref']:15s} type={h['doc_type']:20s} title={h['title']}")
```

### Step 2 — Classify each hit by document type

For every hit, read the containing document's `title` and `document_type`. The key distinction:

| Document type | Is it primary content? |
|---|---|
| Law/code itself (e.g. "Code du travail", "مدونة الشغل") | YES — contains the article text |
| DAHIr "portant promulgation de la loi n° X" / "بتنفيذ القانون رقم X" | NO — cover letter only |
| Amendment law "modifiant et complétant la loi n° X" | NO — references articles, doesn't contain them |
| Implementation decree "pour l'application de l'article Y de la loi n° X" | NO — about a specific article, not the full code |
| Court decision referencing the article | NO — commentary, not the statute |
| Workplace accident law that CROSS-REFERENCES the labor code | NO — cites the article but is a different law |

### Step 3 — Confirm whether the primary law exists

Check whether any file in the corpus has the code law's name as its OWN title, not as a reference within another document's text.

```python
import json, os

# For مدونة الشغل / Code du travail (Law 65-99)
expected_titles = ["code du travail", "code_du_travail", "مدونة الشغل", "65-99"]
primary_hits = []

for root, dirs, files in os.walk("data/corpus"):
    for f in files:
        if f.endswith(".json"):
            p = os.path.join(root, f)
            try:
                d = json.load(open(p))
                title = (d.get("title") or "").lower()
                ref = d.get("ref", "")
                # Is THIS file the code itself (not a document about it)?
                is_primary = (
                    any(kw in title for kw in expected_titles)
                    and "portant" not in title
                    and "promulgation" not in title
                    and "modifiant" not in title
                    and "amending" not in title
                    and "application" not in title
                )
                if is_primary:
                    # Check if it actually has article content
                    s = d.get("structure", [])
                    art_count = sum(
                        1 for n in (s or [])
                        if isinstance(n, dict) and n.get("type") == "article"
                    )
                    primary_hits.append({
                        "path": p,
                        "title": d.get("title", "")[:120],
                        "ref": ref,
                        "articles": art_count,
                        "full_text_len": len(d.get("full_text", "") or ""),
                    })
            except Exception:
                pass

print(f"Primary law files found: {len(primary_hits)}")
for h in primary_hits:
    print(f"  ref={h['ref']:15s} articles={h['articles']:4d} full_text={h['full_text_len']:6d} chars")
    print(f"    title: {h['title']}")
```

### Interpretation

- **0 primary hits + N cross-reference hits** → corpus coverage gap. The primary law text is missing. Ingestion is the fix, not pipeline changes.
- **≥1 primary hit with articles > 0** → primary text IS present. The failure is in retrieval/ranking or in the LLM treating cross-references as primary content. Pipeline hardening is the fix.
- **Primary hit exists but has 0 articles** → the file is a promulgation notice mislabeled as the law, or a law file that failed to parse. Investigate the specific file.

## Why this matters for RAG

The semantic search matches on key terms that appear in the cross-referencing document. If "ساعات إضافية" (overtime) and "مادة 202" and "مدونة الشغل" all appear together in article 75 of law 1.14.190, that document scores highly for an overtime question — even though 1.14.190 is about workplace ACCIDENT compensation, not overtime rules.

The LLM then sees "المادة 202 من القانون بمثابة مدونة الشغل" and has two choices:
1. Recognize this is a cross-reference and say the actual article text is missing from context
2. Treat the citation as if it contained article 202's content

Without explicit training or prompting to distinguish these, the LLM typically does #2, because it is fluent in legal language and can produce a plausible answer from the citation alone.

## Prevention at the pipeline level

See `PIPELINE_V2_1_ROADMAP.md` V21-3b (cross-reference vs primary-content distinction) and V21-4 (authority validation). The fix requires:

1. **Chunk-level flag**: every chunk must carry whether it `has_primary_content` (contains the actual provision text) or `is_cross_reference_only` (points to another instrument).
2. **Evidence chain verification**: a claim backed only by a cross-reference is treated as `inference_level: inferred` and must carry `requires_verification: true`.
3. **Primary-document identification**: the pipeline must know which instrument is the governing source for a given query domain, and weight it above cross-referencing documents.

These are deferred items in the rollout plan. For now, the detection procedure above is the primary tool for diagnosing the failure mode during corpus audits and QA evaluation.

## Related

- `corpus-quality-audit` skill, rule #10 (always-on audit rule)
- `mizan-legal-platform-debugging` skill, new pitfall "Cross-Reference Mistaken for Primary Content"
- `doc/PIPELINE_V2_1_ROADMAP.md` V21-3, V21-3b, V21-4
