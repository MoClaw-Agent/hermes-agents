# Auditing the ingestion pipeline against the live index

Class of work: the parser has produced corpus JSON; now find out what the
ingestion pipeline actually put into the index, and whether a legal document
that is missing, doubled or mis-identified is missing from the corpus or lost
at the ingestion boundary.

Neighbouring files, do not duplicate them:

| File | Covers |
|---|---|
| `references/ingestion-output-audit.md` | one parsed document vs a ground-truth count |
| `references/parser-ingestion-contract.md` | the JSON → converter → chunker contract |
| `references/quality-validation.md` | the per-document quality gate |
| `references/measurement-discipline.md` | counting traps, probe hygiene |

## Step 1: read the live index before reading the code

The index is the artefact; the code only explains it afterwards. Probe it
first, so every later claim is a measurement rather than a reading.

* SQLite `data/mizan.db`: `documents`, `chunks`, `citation_graph`,
  `citations`, `ingestion_checkpoints`, `ingestion_logs`.
* Qdrant: `mizan_law`, `mizan_case`, `mizan_bo`, `mizan_semantic_cache`.

Reconcile first — the sum of Qdrant point counts must equal
`SELECT COUNT(*) FROM chunks`. A mismatch localises the write path
immediately and costs one query.

Then check the four orphan classes, because they are cheap and each one
proves a different layer is broken: documents with no chunks; documents
whose chunks are missing from Qdrant; Qdrant points whose document is absent
from SQLite; graph edges whose source document is absent.

## Step 2: find duplicates by grouping, never by eye

One duplicated document found by hand is one document. The *class* comes from
grouping the index on the identity the user sees:

```sql
SELECT title, ref, COUNT(*) FROM documents GROUP BY title, ref HAVING COUNT(*) > 1;
```

Then weight it. Sum the chunk counts of the duplicated documents and report
the share of the whole index — "42 documents" reads as trivia, "42 documents
holding 23.5 % of all chunks" is the finding.

Group on `source_url` and on `ref` alone as well: a ref shared by two
documents with *different* titles is a different defect (a mis-identified
document), not a duplicate.

## Step 3: prove the mechanism by hash-matching the candidates

`content_hash` on a document row is the hash of the **source file**, not of
the stored text (`runner.py`: `file_hash = content_hash(file_path)`). So the
stored hash identifies *which file* produced the row. To establish provenance,
hash the candidate files and match:

```python
for p in glob.glob(corpus_root + "/**/*", recursive=True):
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if h == stored_hash:
        print(p)
```

Two rules this technique gives you:

* **A hash that matches no candidate on disk is not a dead end.** It means
  the source was a file that has since been moved, renamed or replaced (a PDF
  rather than a JSON; a backup tree that was renamed in place). Say that —
  do not report it as a defect.
* **Hash equality is not document identity.** The same legal document
  ingested from a PDF and from a JSON has two different hashes and
  byte-identical chunk text. Any design that dedups on `content_hash`
  cannot see that duplicate, and a hash comparison across two runs proves
  nothing about duplication.

## Step 4: the three guards that let a duplicate through

Check all three; each is independently sufficient to hide a re-ingest:

1. **Identity** — `builder.py`: `doc_id = str(uuid.uuid4())`. Nothing links a
   document to the file it came from, so a second copy cannot be recognised
   as the same document. (The BO path already uses a deterministic
   `DNS_NAMESPACE` id — that asymmetry is the tell.)
2. **The skip guard is run-scoped** — the document-level checkpoint is keyed
   by `(run_id, content_hash)` and the runner's resume skip is explicitly a
   resume of the *same* `run_id`. A new `run_id` re-processes everything.
   Count the distinct `run_id`s in `ingestion_checkpoints` — more than one
   means the corpus was ingested more than once.
3. **The hash covers the file, not the content** — see Step 3.

The rule: identity must be derived from the canonical source (deterministic
UUID v5 over the source path), the skip must be content-based *across* runs,
and the stored hash must cover the content that is stored.

## Step 5: the scan root must be the parsed corpus, not the provider directory

`api/routes/ingest/providers_config.py` sets `corpus_root` to
`data/corpus/<provider>`, and `ingestion/pipeline/runner.py::run_directory`
scans it with `rglob` for `.pdf/.json/.txt` and **no exclusion of the
derived subtrees**. A provider tree holds derived artefacts beside the
corpus — `backup/`, `repaired/`, `cache*/`, `llm_meta_cache/`, and the raw
PDFs. Every copy of a document that sits in that tree is ingested as another
document.

Measure it: count how many of the indexed documents' `content_hash` values
match a file in a `backup/` or `repaired/` subtree. That number is the
wasted population.

Fix direction: point the scan at the parsed corpus directory
(`data/corpus/<provider>/json/`), or exclude the derived subtrees. The
inverse rule — never *write* derived artefacts into a directory enumerated as
source — is in SKILL.md; this is its read-side twin.

## Step 6: a module with tests can still be dead code in the pipeline

`ingestion/ingest_cross_references.py` is the component that builds the
document-level relationship graph, and it is a two-phase CLI:

```
python3 -m ingestion.ingest_cross_references          # stage  -> cross_reference_staging
python3 -m ingestion.ingest_cross_references resolve  # resolve -> citation_graph
```

Nothing under `ingestion/pipeline/` calls it, and it is hard-wired to the
juritheque corpus. Its staging table is **absent** from the live database, so
phase 1 never ran: `documents.amends` / `amended_by` are empty and
`citation_graph` holds only intra-document edges (4885 `article` rows whose
`target_id` is an *article number*, plus 15 `cross_reference` rows whose
target is a phrase).

So when auditing "the graph is missing", do not stop at "the module exists
and has tests". Prove it is wired in:

```bash
grep -rn "ingest_cross_references\|stage_cross_references" --include=*.py .
```

and check that the table it writes actually exists in the live DB. A payload
field carrying the relationships is not a graph — nothing traverses it.

## Step 7: measure retention at every layer, and read the ratio

Measure three stages per document, not two: source page text → flat
provisions → indexed chunk text.

A ratio **above 100 % at the index stage is context enrichment, not
duplication** — the chunker prepends the hierarchical context to each chunk.
Reporting that as inflation is a false positive; report the per-layer ratios
and name the layer where the loss actually happens.

## Step 8: a missing field is a defect only if a consumer reads it

An empty `article_id` in the Qdrant payload looks like a broken contract
against a changelog entry. It is not a defect if retrieval filters on
`article_number` and `chunk_kind` instead — grep the consumer before
reporting the field. Same discipline for an empty `legal_domain`: it is a
real finding only once you have counted the documents it blanks and shown
that a scoped-retrieval path reads it.

## Step 9: reproduce with the arguments the call site passes

An audit probe that calls a production function with a *different* argument
than the call site passes manufactures findings. Passing the parsed JSON's
filename where the pipeline passes the raw PDF's name turned one real
reference defect into four. Derive the argument from the call site, not from
the artefact you happen to have open.

## Step 10: report shape

The deliverable is a written report plus a reply — not a fix. Unless the
user asks for fixes, the audit changes nothing.

Per finding: severity, the measured impact in counts, the root cause with
`file:line`, the reproduction command and its real output, and the direction
of a fix. Then, in the same document:

* **the rejected hypotheses**, named, so the next session does not re-derive
  them;
* **what was checked and found CORRECT**, with its numbers — otherwise the
  next session re-tests it.

Correct a probe's artefact in the report itself when the probe was wrong
(Step 9). A retraction that lives only in the chat transcript is a retraction
the report still contradicts.
