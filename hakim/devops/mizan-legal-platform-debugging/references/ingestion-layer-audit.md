# Ingestion Layer Audit

How to audit a multi-stage ingestion pipeline end to end, produce findings that
survive scrutiny, and deliver the fixes as independently verifiable waves.

## Audit in the order the data flows

One layer per agent, in flow order — a defect in an early layer is invisible in
a later one, so a later layer audited alone will report "correct" while the
data never reached it.

| Layer | Typical files | The question that finds the defects |
|---|---|---|
| Discovery / scope | `run_ingestion.py`, `ingestion/pipeline/corpus_scope.py` | Which files are candidates? Is one legal instrument represented by two files? |
| Pre-converter / adapter | `ingestion/pre_converters/*`, `ingestion/adapters/*` | Which node types are emitted and which are dropped? Does the emitted item count match the corpus? |
| Chunk | `ingestion/stages/chunk/*`, `ingestion/chunker/*` | Is each document chunked once? Does every label match its text? |
| Metadata / identity | `ingestion/metadata_projection.py`, `ingestion/pipeline/builder.py` | How is a document identified? When the same field exists twice, which source wins — and does the loser reach the store? |
| Store | `ingestion/stages/store.py`, `ingestion/stages/embed.py`, `ingestion/metadata_store.py` | Is the write atomic and idempotent? Is a failed write visible, or reported as success? |
| Orchestration | `ingestion/pipeline/runner.py`, `ingestion/parallel_engine.py`, `ingestion/checkpoint_store.py` | Can a document be marked complete before its rows exist? Do the serial and the parallel path produce the same result? |

## The delegation brief

The brief is the whole instrument. These four clauses are what made the
results reproducible instead of plausible:

1. **READ-ONLY: report findings, do not fix anything.**
2. **Every finding MUST be reproduced by executing the real code against the
   real data** (the parsed corpus, the live SQLite, the live collections),
   quoting the exact command and its real output. **A hypothesis that does not
   reproduce must be reported as NOT REPRODUCED, not as a finding.**
3. **Report a ranked list**: severity, `file:line`, exact reproduction (command
   + real output), measured impact as **counts, not adjectives**, and the
   direction of a fix.
4. **Explicitly list what you checked and found CORRECT as well.**

Clause 2 is what keeps the report honest: on a real run it forced several
plausible hypotheses to be demoted to "NOT REPRODUCED" and it caught two
findings that were wrong (a duplicate-provenance explanation confounded by a
same-day reparse, and an "index expansion is context enrichment" reading that
was really double chunking). Clause 4 is what stops the next wave from
re-litigating what was already checked.

Also state in the brief: the real data locations, that the agent may not start
or stop any process, and that the live index and the corpus must be read
through the real code paths rather than through a re-implementation.

## A delegated audit can damage the live system

Delegated audits run concurrently, and they touch real services. Observed
damage in one batch: Qdrant OOM-killed by three agents each loading a ~2.5 GB
embedding model at the same time; a stray point written into a live collection
and then deleted by the agent that wrote it; four scratch collections left
behind in the live Qdrant; one file written into the repo root.

Rules that prevent it:

- The brief forbids writing to the live index, the live database, or the
  corpus. Probes use a **temporary collection** or a **copy** of the database
  (`shutil.copy2` of the `.db` for anything that writes).
- No agent loads an embedding model. If a layer needs embeddings, stub the
  transport and keep every other line of the real code.
- After the batch returns, the parent **verifies the live state itself**: the
  per-collection point counts, the document/chunk counts, and `git status` for
  stray files. A clean audit report is not evidence that the system is clean.
- Report the leftovers by name and let the user decide before deleting
  anything from the live index.

## Code fix, data cleanup, and re-ingestion are three different operations

Keep them apart in every report and every commit:

- **Code fix** — the defect in the code, with a regression test.
- **Data cleanup** — the artifacts the old code produced (duplicate rows,
  poisoned references, orphaned chunks). Never silently deleted.
- **Re-ingestion / index rebuild** — the operation that applies the fix to the
  existing data. It is a data operation and the user's to call.

A code fix does **not** change the live index. Say so explicitly: "the fix
makes the NEXT ingest clean; the live index still carries N duplicate
documents until it is rebuilt." Never let a report imply the live data
changed because a commit landed.

## Measuring

- Counts, never adjectives: "48/185 documents, 16,734 duplicated characters",
  not "some documents".
- Compare against a baseline captured the same way. A defect found in the
  live index is only actionable once you know what the corpus should produce.
- Reproduce against the **real** function, not a re-implementation of it. A
  re-implementation can be wrong in a way that manufactures the finding.
- Re-verify every finding against the current tree before writing it into the
  report — a concurrent session may have changed the code under you.

## Delivering the fixes

Fix in waves, each independently verifiable and independently revertable:

1. One root cause per wave, with a regression test that fails before it.
2. A focused verification run (the affected test files + the type checker),
   then the full suite in the chunked runner.
3. Release-label and changelog sync in the same wave — see the repo-delivery
   skill's four-leg rule.
4. The audit report gains a section per wave: the defect, its root cause, the
   measured before/after, and **what is explicitly not claimed**.
