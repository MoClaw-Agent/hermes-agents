---
name: mizan-pipeline-audit
description: "Audit a Mizan pipeline layer; deliver fixes in waves."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [mizan, audit, ingestion, parser, release, wave]
    related_skills: [mizan-repo-delivery, mizan-legal-platform-debugging, systematic-debugging]
---

# Mizan Pipeline Audit → Fix Waves

> The project's workflow docs live in `doc/workflow/` — `RULES.md` is the standing contract. Read them before changing code.

## When to Use

- "run a deep audit on \<layer\>", "audit the ingestion pipeline", "report back with findings"
- An audit report exists and its findings must now be fixed and delivered
- A pipeline layer is suspected of losing, duplicating or mislabelling data

## The shape of the work

One wave per **root cause**. A wave = one cause, one fix, one regression
test, one report section, one release. Never batch unrelated defects into a
wave, and never open a wave for a one-line change.

## When the user will rebuild the data from scratch

If the user says they will re-ingest or rebuild the index from scratch
once the fixes are done, the remaining work is **code only**: stop
treating the live index's stale state as a caveat, drop the data-cleanup
and re-ingestion items from the queue, and keep fixing the code. State
once, in the report, that the index is rebuilt rather than repaired in
place — then stop repeating it in chat. A queue that keeps re-listing
"the live index still holds X" reads as unfinished work when the work
that was asked for is finished.

## Read-only review mode

When the user asks for a **read-only review** (usually while a reingestion
or a rebuild is running), the deliverable is a FINDING REPORT, not a fix.
State the constraint up front and keep to it:

- No writes to `data/`, the SQLite databases, or Qdrant — not even a
  probe that opens them for reading if the job is mid-write. A read-only
  probe that reads the corpus is fine; one that writes is not.
- No commits, no pushes, no source edits. The user holds the go-ahead for
  every fix ("never start fixing without explicit permission").
- Findings are reported with the evidence and the reproduction, then you
  STOP and wait. Do not queue the fixes and do not apply them.
- Offer the ordering: which finding to fix first, and why the timing
  matters (a parser fix lands BEFORE the rebuild and is picked up by it;
  after, it needs a second pass).

The sweep catalogue for this mode is `references/ast-sweeps.md` — it finds
whole classes of defect in one pass without touching the data.

## The overview file is the user's map of the work

Long audit sessions produce a queue, and the queue is what the user reads
to see whether anything is left. Write it to a file in the repo
(`docs/STATUS.md`), commit it, and keep it current: the waves done, what
is open, and what to run next.

- **Commit it.** An uncommitted overview is one `git checkout` away from
  vanishing — and a vanished overview reads as "the work was never
  tracked". Commit it as its own docs commit so git is the backstop.
- **Its committed content is authoritative.** When the user says the file
  is the truth, do not rewrite a committed section to match your current
  understanding — state the disagreement and let the user decide. A
  status file that silently disagrees with itself is worse than no file.
- **Update it per wave**, not once at the end: the done-list grows, the
  open-list shrinks, and the "what to run next" section is what the next
  session starts from.

## Procedure

1. **Map the layer before theorising.** List the files, the entry points
   and the data each reads; diff a provider against its sibling to find the
   fork point. A defect in one provider is usually a defect in the shared
   base — fix the base and both providers inherit the fix.
2. **Measure the live state first.** Query the real SQLite, the real
   Qdrant and the real corpus. Counts ("84 of 534 documents", "3,740 of
   15,936 chunks") are what make a finding actionable and what let a later
   wave prove the fix.
3. **Reproduce every finding by executing the real code.** A hypothesis
   that does not reproduce is reported as NOT REPRODUCED, never as a
   finding. Reject your own findings loudly and keep the rejected
   hypotheses in the report.
4. **Group by root cause, not by symptom.** One cause can produce three
   symptoms (a random document id produced duplicate documents, duplicate
   chunks and a colliding chunk index). Fixing the cause once is the point;
   fixing the symptoms is a patch.
5. **Fix structurally.** Deterministic identity, delete-before-write,
   adapter-authoritative chunking, one source of truth per field, a value
   normalised at the single write boundary. No monkeypatches, no
   per-document special cases, no silent fallbacks.
6. **Re-measure with the same probe** — before/after numbers in the report,
   not adjectives. A fix with no measured delta is not a fix.
7. **Write the regression test before releasing** — one that fails without
   the fix. Run the module-scoped subset that covers the change, then the
   repo's own gate files.
8. **Release the wave** (four legs, see `mizan-repo-delivery`): report
   section, changelog entry, version bump, label sync, manuals rebuilt,
   commit, push.
9. **Continue with the next wave.** Do not stop to report between waves — a chat report after a wave reads as "the work is finished" and the user has to say *continue* to get the next one. Report in chat only when the open-findings queue is exhausted, when a wave needs a decision the code cannot supply, or when the user asks. The report FILE is the deliverable that grows per wave; the chat message is not the progress channel.

## Pitfalls

- **A delegated audit agent can wreck the live index.** Concurrent audit
  workers each load an embedding model (~2.5 GB RSS) and the kernel
  OOM-kills Qdrant mid-run; they also leave scratch collections
  (`audit_*`, `tmp_*`) behind and may leave a stray point in a live
  collection. Give every delegate its own temp Qdrant collection and an
  isolated DB, and check `git status` plus `GET /collections` after the
  batch returns. The scratch collections are the DELEGATE's, and deleting a
  collection in a live Qdrant is destructive: list them and offer to clear
  them — do not delete unilaterally.
- **A delegate may leave an artefact in the repo root** — a harness
  written to the wrong path lands in the working tree. Check `git status`
  and delete it; never commit it.
- **Do not trust a delegated finding.** Re-verify the strongest claims
  yourself against the real code; sub-agents over-report and
  mis-attribute causes.
- **A stale table row will abort your release script** — match the rows by
  substring, and write each file only after all its edits succeed.
  **Validate EVERY anchor before the FIRST write**: a script that asserts
  per step leaves a half-released tree when it aborts midway (the report
  section written, the version bump, the changelog entry and the label sync
  not) — and the next wave then inherits a tree whose report says a wave
  landed that never shipped. Make the script re-runnable: it must
  succeed when re-run against a tree it already half-touched.
- **A per-page text heuristic is only safe when it is actually given pages.**
  Structure builders that take `str | list[str]` apply their guards
  (contents-page detection, trailing footnote block, page-folio guard,
  amendment-note gate) per element. Handed a whole document as one element,
  a length-based stop condition in a drop-gate never fires and the document is
  swallowed — measured, 337 of 346 lines dropped and a 41-article decree
  parsed to a single preamble and zero provisions, while the same text parsed
  correctly once segmented. The producer owns segmentation: recover real page
  boundaries from the source's own printed page numbers, cap a segment so a
  boundary-less text cannot present an instrument as one page, and re-derive
  `num_pages` from what the artifact actually has. Rule of thumb: prefer a
  producer change that segments over a shared-base change that widens a gate —
  the gate is calibrated for a page and a page is what it should be given.
- **An identity or resume check built on `path.exists()` silently overwrites,
  and a PATH snapshot does NOT fix the collision case.** When the output path is
  a pure function of identity, the second record to reach a given identity sees
  the first record's freshly written file, treats it as its own, and replaces it
  — the corpus ends up with fewer documents than records (measured: 6,855
  written, 6,800 on disk), and nothing is logged. Snapshotting the output tree
  before the first write stops the re-run FORK but not this: on a re-run both
  colliding records find the same path in that snapshot, so the second still
  overwrites the first. **Key the resume lookup by the RECORD, not by the path
  or the identity.** The record's own source path (the `raw_record` field) is
  the only key unique to it; the identity is not, because two records can
  legitimately share one — the same instrument filed under two domains, an
  Arabic original and its French translation. Build the index ONCE per run from
  the existing documents' record key, pass it to the per-record write, and take
  the next free ` (2)` slot when the record has no entry. Verify idempotency by
  re-running and comparing the sorted output path SET, never the written count.
- **The bare-except ratchet is a BUDGET, not a formality.** It counts
  `except Exception:` AND `except BaseException:` sites, and it fires on
  any increase. Prefer a narrow tuple; where you need the in-flight
  exception (a rollback that must hand the error to a context manager),
  do not catch it at all — take `sys.exc_info()` inside a `finally` and
  pass it to `__exit__`. A wave that adds a broad except to be "safe"
  spends budget the next wave will need.
- **A fix can break the repo's own gates.** The bare-except ratchet, the
  god-file gate and the per-PR pin files all count things; run the gate
  files after every wave, and re-run the suite after each source-changing
  wave. **A gate failure your own wave caused gets its own follow-up wave**
  — the code fix plus a release — and the report says so. Folding a
  regression into the next wave's diff hides that the next wave was
  measured against a broken baseline.
- **The executive table goes stale across a multi-wave session.** Write it
  last, but re-check it after EVERY wave: each row must carry what is
  fixed (with the section that fixes it), what is measured-but-open, and
  what stays open. A table written once at the end of a long session
  understates the progress, and correcting it later needs its own commit.
- **The chunked suite keeps the pre-edit result for files it already ran.**
  Re-run the files you touched, and treat a suite log as evidence about
  the code at the time that file ran.
- **A shared class flag whose TYPE changes breaks the tests that force it.**
  Keep the public shape and add precision alongside it (a per-key set
  next to the boolean) rather than replacing it.
- **A probe whose "before" number is zero is not measuring the defect.**
  Run the probe against the pre-fix code before trusting its "after": a
  probe that reports zero before AND after is looking at the wrong text
  source or the wrong corpus subtree, and the report must not claim a
  delta from it. The "before" must be non-zero and should agree with the
  audit's independent number — a mismatch means the two measured
  different things.
  **Two mechanisms produce a blind scan.** (1) The stored artefact's field
  NAME differs from the function's parameter name (`amends_document_ref` in
  the JSON, `amends_ref` in the code) — a scan keyed on the function's name
  reads nothing and reports zero. Verify the field against a REAL document
  before trusting the count. (2) A stored metadata value can be WRONG: a
  jurisprudence record carried Arabic text with `language: "fr"`, so an A/B
  that trusted the stored language ran the French path on Arabic text and
  produced 205 bogus "changes". Derive the language (and any other
  per-document discriminator) from the head itself, not from the stored
  field — the stored value is a claim, not a measurement.
- **A regression test that passes against the unfixed code is not a
  regression test.** Prove the discrimination with
  `scripts/ab_verify.py` (run the test against the pre-fix file, before
  the code commit — HEAD still holds it then). The usual cause of a
  non-discriminating test is that it marks the wrong content: a
  duplication of the paragraphs PRECEDING an over-long paragraph is not
  detected by a marker inside the over-long paragraph.
- **A fix that changes an identity or a label must be checked against the
  whole corpus, not a sample** — identity keys merge documents, and a
  false merge is silent data loss. Measure collisions and prove each one
  is a genuine duplicate. **And measure the fix's DELTA, not just its target:**
  a change that reads correct on the document you were handed can move an
  unrelated document's value from one wrong answer to another. Run the
  before/after comparison over every record and report the symmetric
  difference; an empty delta is the bar, and a non-empty one means the change
  overreached even when the target improved.
- **When a helper's own field is one of several signals, settle the priority by
  MEASURING the signals against each other — and re-measure after every rule
  change.** Changing one pattern (anchoring a title match, widening a
  classifier) changes which signal wins for thousands of unrelated records, so
  the "agreement rate" you measured before the change is no longer the
  agreement rate after it. Re-run the same sampled comparison against the new
  code before reporting the new ordering as an improvement; a count that moves
  the wrong way is the signal that the change cost more than it fixed.
- **Read the pushed commit message back.** A heredoc body can lose a
  word to shell expansion (a backticked identifier was eaten from a
  pushed message and the sentence landed broken). Write the message to a
  file and use `git commit -F <file>`, avoid backticks, and read the
  message back from `git log` before moving on.
- **A test file that is a SCRIPT collects ZERO tests.** A file whose
  checks live in a `check()` counter, or inside `main()` behind
  `if __name__ == "__main__"`, has no `test_` function and no `Test`
  class: pytest collects nothing, exits **5**, and the file's checks
  never reach the suite's results. It looks green because the file is
  "not failing". Scan for it whenever a file exits 5 or contributes no
  count (`ast`: a `test_`-prefixed function or a `Test`-prefixed class
  must exist). Once converted, the checks often FAIL — the taxonomy
  file's 19 checks failed 18 times on the day it became a real test,
  because its expectations were the pre-v1.113 English rank values while
  `LegalRank` is Arabic by project rule. Assert the enum's MEMBER NAME
  (its identity), never its value (a presentation choice that has
  already been migrated once).
- **pytest exit 5 means "no tests ran", and under a marker filter that
  is a DESELECTION, not a failure.** The suite's default filter drops
  `requires_qdrant` / `requires_server` / `requires_llm`, so a file whose
  every test carries one of those markers is deselected wholesale. Run
  those files separately WITHOUT the filter, against the live services,
  and count both passes in the final total. A runner that reports exit 5
  as FAIL overstates the failures.
- **Never count a Qdrant collection by scrolling its payloads** — the facet
  API returns byte-identical counts where a full-payload scroll takes 289 s
  on 13,092 points versus 0.01 s. Call shape and the one-field fallback:
  `references/debugging-recipes.md`.
- **The god-file pin counts PHYSICAL lines (the `wc -l` metric).** The
  gate reads the file in binary and counts newlines, so `split("\n")` is
  off by one. Re-measure with the gate's own method, or the pin will
  disagree with the gate by one line in either direction.
- **A background process launched for a long suite gets SIGTERM'd.**
  The tool's background runner is killed when its window closes (a
  notification arrives as `exit -15`), and `nohup`/`setsid` inside the
  command is refused. Run the suite as **bounded foreground slices**
  (each under the call's own timeout) against a resumable state file,
  and aggregate the per-file logs at the end. A slice that is killed
  mid-way loses nothing, because the state file records each file as it
  completes.
- **The camel `TypeError` is a test-isolation defect, not a production
  one** — import the heavy stack at MODULE level in the test file, outside
  every `sys.modules` patch window. Mechanism and fix:
  `references/debugging-recipes.md`.
- **A logger that owns handlers must not also have an ancestor that owns
  handlers** — put the handlers on the NAMESPACE ROOT and let the module
  loggers propagate to it, or every record is written twice (measured: one
  `logger.info()` printed twice and landed twice in each log file). The
  `NOTSET` level rule and the `caplog` consequence:
  `references/debugging-recipes.md`.
- **A filter derived from a FUZZY classifier must never gate recall.** When a
  filter's value comes from inference — a topic classifier, a domain guess, a
  confidence-scored label — rather than from the user or a high-confidence
  keyword, a hard Qdrant filter can exclude the very document the query names,
  and every retrieval stage reports success while the answer abstains. Measure
  the filter's COVERAGE against the corpus before applying it (a `facet` on the
  field, not a scroll): if the value matches a handful of chunks, the filter is
  a recall killer. Reserve hard filters for user-supplied or high-confidence
  constraints; make inferred categories a post-retrieval score boost that can
  reorder but never remove. The full policy and the diagnostic live in the
  `mizan-retrieval-benchmark` skill, under its domain-filter exclusion reference.

- **A bilingual dump's title field is usually the filing language, not the
   document's language.** When a dump carries both `title_ar` and `title_fr`
   in a sidecar, the top-level `title` is typically the filing language (often
   French). For an Arabic document, prefer `title_ar` for display — but extract
   refs from the French title, which carries the instrument's own number. The
   Arabic title often names only the law the instrument implements ("مرسوم ...
   القانون رقم 37.99"), so extracting from it files the decree under the law's
   number. Measure: compare ref extraction from each title against the site's
   number field on a sample before choosing.

- **`_extract_refs_from_structure` must walk ALL nesting levels, not just top-level + one child.** A recursive walk is required because references can appear in deeply nested structure nodes. A 2-level traversal silently misses references in deeper nodes. Use a recursive `_walk(nodes)` helper that visits `node.get("children")` at every level.

- **When adding a new provider, update `detect_source` in `ingestion/stages/common.py`.**
  The function checks metadata, path components, file names, and URLs against a
  list of provider names. If the new provider is not in the list, its documents
  are mis-attributed to whatever provider's URL pattern matches (e.g. juritheque
  URLs containing "adala.justice.gov.ma" were classified as "adala"). Add the
  provider name to all three lists: metadata, path, file_name.

- **A content classifier is a QUERY classifier, not a document classifier.**
  When a folder is a catch-all (e.g. `droit_administratif`), do NOT replace
  it with `detect_domain_from_content` — that function matches citations in
  the preamble ("قانون المالية" in a family-law decree → fiscal). Instead:
  (1) keep the folder value, (2) record `legal_domain_source` provenance,
  (3) correct from the source's own subject tags where they exist (accurate
  but sparse), (4) use a TF-IDF classifier trained on the reliable folders
  with a confidence threshold (0.4 → ~81% accuracy, ~18% coverage). Never
  apply the classifier below the threshold — a 34% error rate is worse than
  keeping the catch-all label.
- **A filter that reaches one retrieval leg and not the other is not a
  filter.** Measure the violation rate of EVERY filter: run a search
  with the filter and count the returned chunks that do not satisfy it.
  In this codebase the dense leg took the whole Qdrant filter while the
  sparse leg took only the collection, so `doc_ref` and `validity_status`
  violated 82 % of the time ("show me law X" returned 41 chunks of other
  laws). The sparse leg's `weight_mask` is already a per-chunk 0/1
  array, so the general fix is to give it CONSTRAINTS named by the
  PAYLOAD field they mirror, built from the store.
- **Two stores that hold the same fact must be written together.** The
  validity job updated the Qdrant payload's `validity_status` and
  nothing else, so the store kept `status='active'` for a repealed
  document — and the sparse leg's mask is built from the store, so the
  filter could not be enforced there. When a job writes a fact to one
  store, write it to the other in the same call, and add the column
  through the repo's established `ALTER TABLE` migration list.
- **A payload field that is HARDCODED is a defect waiting for the data
  to change.** `"validity_status": "IN_FORCE"` was written for every
  chunk while the same payload derived its `valid_until` from the
  document's status. Derive the status from the same field that decides
  the temporal end, and extract the rule into a NAMED function so the
  payload sites agree by construction and the rule is testable alone.
- **A payload built by a SECOND code path drifts from the first.** The
  table payloads (the summary and the rows) were built separately and
  carried none of the main payload's temporal fields: measured, 380 of
  13,092 points had no `valid_from`, and the 380 missing ones were
  exactly the table chunks, so any temporal filter excluded every one.
  Compare the payload key sets of every construction site, not just the
  main one.
- **A name assigned inside a nested function shadows the parameter and
  fails SILENTLY.** `constraints = dict(constraints or {})` inside a
  nested builder made the name local, raised `UnboundLocalError`, and
  the repo's error cascade swallowed it — leaving the retrieval leg
  UNSCOPED, so every filter was ignored and the measured violation
  rates went UP (0 % to 72 %). When a helper logs a warning and
  continues, the behaviour it guards is GONE, not degraded: read the
  warning as a failure and fix the shadowing.
- **Instrument the real call; do not reason about the code.** The
  highest-yield defect finders come from executing the path and
  COUNTING what it does, not from reading it. Two patterns paid off:
  patch the client's methods at the CLASS level — so every instance
  counts, not just the one a module-level accessor returns — and dump
  the call sequence; and run the path with a filter and count the
  results that VIOLATE it. The filter probe found a defect where 82 %
  of the results were wrong, and the call-sequence probe found every
  log line being written twice. Neither was visible in the source.
  `scripts/measure_filter_violations.py` is the filter probe, ready to
  run.
- **An optional component that cannot be loaded must DEGRADE, not 500
  the request.** A model whose load fails (the embedder, a reranker, an
  NLI scorer) must fall back to the path that does not need it, and the
  failure must be logged as non-fatal. The pattern that recurs: one leg of
  a fused pipeline is guarded and its sibling is not, so the unguarded leg
  turns an optional failure into a 500 for every request. Sweep the
  sibling call sites — a fix applied to the dense leg of one retrieval path
  and not the other leaves the default path broken. Remember the exception
  hierarchy: `NotImplementedError` is a `RuntimeError`, so a tuple that
  catches `RuntimeError` already covers it.
- **Quantify the EXPOSURE before calling a defect an emergency.** A real
  code defect can be latent: measure how many real corpus documents it
  can hit, then report the number. A degenerate identity key that
  collapses two documents into one `doc_id` looked like data loss until the
  corpus was counted — 24,025 parsed documents, **6** with the missing
  fields, and none of them a legal document. That is a latent robustness
  gap to fix cheaply, not an active loss, and the user's reingestion is not
  at risk from it. Say which it is; the two have different urgency and a
  wrong urgency costs the user's trust.
- **A request field the route never reads is a silent contract break.**
  The API advertises a capability (`workspace_ids`, `folder_ids`, a filter)
  and the client cannot tell it was ignored. Find it with the
  ignored-request-fields sweep; fix at the choke point so every caller is
  protected, and keep the ownership condition in the filter so a scope can
  never widen the search beyond the caller's own documents.
- **A second code path that builds the same artefact drifts from the
  first.** A request scope, a payload, a filter — wherever two functions
  build it, compare them. The retrieval's dense and sparse legs each built
  their own ownership filter; one got the user scope and the other did not.
  Compare the sibling implementations by DIFFING them, and treat a
  deliberate divergence (a sibling's docstring explains why it differs) as
  the fix that the other copy never received.
  **COUNT the copies before calling it a two-provider divergence.** Grep
  the SYMBOL across the whole tree, not the two files you were handed: a
  gate lived in `parser_base`, `ism` AND `adala`, and only the third had
  drifted — a two-file diff would have reported a divergence that was
  really a three-way split with two copies already fixed.
  **SHARE the implementation; do not copy the refined rule into the stale
  copy.** Extract it to the LOWER layer (the package the others import
  from, and which imports nothing back), have every provider import it,
  and prove they are the IDENTICAL function object — then the divergence
  cannot recur. Copying leaves the class in place and the next drift
  undetected. Alias the import to the existing PRIVATE name
  (`from x import shared as _private_name`) so the call sites and the
  tests that import it do not move. The full recipe, including the
  layering check and the gate consequences:
  `references/shared-helper-extraction.md`.
- **A failing test may ENCODE the defect.** Before adjusting a fix to
  satisfy a red test, re-read the test's PREMISE. A test whose input the
  real pipeline never produces — a hand-crafted title that leads with the
  law ref, where the pipeline extracts the other instrument's line — can
  be pinning the bug as correct, and it fails the moment the fix lands.
  Ask whether the test's expectation is the behaviour you just removed.
  If it is, correct the test and say why in the wave; do not weaken the
  fix to keep a test green. The same test file usually already carries the
  REAL guard under a better name, so check the sibling cases before
  rewriting anything.
- **The doc and the converter may describe a DIFFERENT producer than the one
  that made the data.** A provider's `doc/<PROVIDER>.md` and its converter can
  document a browser scraper while the corpus on disk is a REST/API dump: the
  field names do not overlap at all, and running the converter as-is emits a
  constant `document_type`, a constant collection and an empty `structure` for
  every record. Before trusting any doc, converter or field list for a
  provider, **establish which producer wrote the tree** — match the record's
  actual keys and provenance field against each candidate producer's output,
  then verify the doc against that. A stale doc is worse than none: it reads as
  authoritative and sends the next session to fix a converter that was never
  in the path.
- **A record's own `language`/`document_type`/`ref`/`legal_domain` can be FILING metadata, not facts.** When a source files documents into folders, the folder name, the page language, a free-text number field and the SUBJECT-MATTER folder are all claims about *where it was filed*, not about the instrument. Measured on one provider: the type field carried 31 values including a container and an Arabic literal, 1,125 records were filed under the wrong language, the number field was empty for 123 and held a title or a bare year for 338 more, and the domain folder was a catch-all — 64% of the corpus filed under `droit_administratif`, of which only 22% is administrative law by content (78% would be reassigned to labour, civil procedure, commercial, constitutional, fiscal, urban planning, civil, corporate). **Derive each from the document's own evidence and record which source won**, then measure the sources against each other on a sample before fixing an order — do not pick the priority by intuition. The document's own title is usually the strongest identity signal; a free-text body classifier is usually the weakest, because it reads an instrument word out of a citation.
- **Before inheriting a source's CLASSIFICATION, measure what share of that bucket survives it — and establish the COMPARATOR's reliability before reading its disagreement as the source's defect.** "Every document is <one label>" is usually the source's bucket being reproduced, not a downstream bug: the parser that inherits the folder faithfully looks correct and the bad value surfaces in every consumer. Measure by sampling the bucket's own titles (they name the real subject) and running the content classifier over the same records. **A low agreement rate means the two signals DISAGREE — it does not mean the source is wrong.** The content classifier is a QUERY classifier, and a legal document cites the Constitution, the finance law and the courts in its preamble, so bag-of-words matching returns the CITATIONS, not the subject: on documents identifiable by inspection the folder was right 3 of 5 and the text classifier 0 of 5. So do NOT stop emitting the inherited value in favour of the classifier — that replaces a good signal with a worse one, and the replacement looks authoritative while being wrong. Keep the value, record which source produced it, and correct it from the source's own subject tags where they exist (accurate where present, but sparse). Do not "fix" it by widening the producer's rule either (see the guard-vs-producer rule above).
- **Prefer narrowing a GUARD over widening a PRODUCER's rule.** When a
  guard reads a value another layer computes and that value is wrong, the
  minimal fix is the guard's CONDITION — veto only on a POSITIVE
  disagreement, not on the absence of agreement — not the producer's
  general rule. Widening the producer (making a title extractor take the
  earliest match across every pattern) fixed its target and simultaneously
  moved an unrelated document's value from one wrong value to another;
  the corpus-wide symmetric difference is the bar, and it was not empty,
  so the change was reverted. Narrowing the guard fixed the target with an
  EMPTY delta. Measure the producer change over the whole corpus before
  believing it is free.
- **The suite is a defect finder, not a gate you pass.** The fresh
  memory-bounded run over the final HEAD found three defects that no
  amount of reading had: a fresh database missing a column the code
  named, a process abort from a logging handler writing to a closed
  stream, and a breach of the bare-except ratchet by the wave's own
  code. Run the suite EARLY and OFTEN — after each source-changing
  wave, not once at the end — because each of those three was
  introduced by a wave that had already passed every focused test. A
  focused suite that passes proves only that the files you ran are
  consistent with themselves.

- **An A/B whose "before" is your own fix proves nothing.** `git archive HEAD`
  materialises the CURRENT commit, so once the fix is committed the baseline
  is the fix and the comparison reports agreement. Use the commit BEFORE the
  fix (`HEAD~1`, or the revision the wave's diff was measured against) and
  state which revision the "before" came from. The trap is silent: the run
  succeeds, the numbers look plausible, and the conclusion is backwards.
  **The archive is only half of it — the probe must also IMPORT from the
  baseline tree.** A probe that hardcodes `sys.path.insert(0, "<repo>")`
  loads the CURRENT code no matter which tree it runs in, so it reports the
  fixed result against itself and the A/B agrees perfectly. Parameterise the
  root (`os.environ.get("MZ_ROOT", "<repo>")`) and assert the loaded
  module's `__file__` is under the tree you meant to measure — a one-line
  guard that turns a silent wrong answer into a loud one. Both layers fail
  the same way: a plausible-looking run whose conclusion is backwards.
- **A fix that moves an unrelated document is not a fix — revert it.** A
  broad change (making a title extractor take the earliest match across all
  patterns) fixed its target and simultaneously moved one unrelated
  document's value from one wrong value to another. Neither value was the
  document's own, so the change had no defensible benefit and a real
  behavioural cost. Measure the change over the WHOLE corpus, not the target
  document; an empty symmetric difference is the bar. Reverting a change that
  overreached is the correct outcome, not a failure.
- **An identity fallback that is a CONSTANT is silent data loss.** The store
  deletes by `doc_id` before it writes, so two documents that share an id
  means the second replaces the first and the first's chunks are gone —
  unrecoverable and logged nowhere. Every branch of an identity key must
  carry the document TYPE, and the last fallback must be the document's own
  content hash (stable for a given file, never mistaken for a different one).
  A constant fallback is exactly what the exposure measurement rules out:
  measure how many real documents can hit it, then fix it anyway, because the
  failure is silent.

- **A finding's stated cause may already be resolved by a sibling fix.**
  Re-reproduce against the CURRENT tree before implementing anything. When a
  defect is caused by a value that a DIFFERENT finding already corrects,
  fixing that other finding removes it with no change of its own — verify the
  consequence and report it as fixed-by-sibling, not as a second fix. A
  document was stored as an amendment of itself because the self-reference
  filter compared `amends_ref` against the STORED ref, and the stored ref was
  wrong for an unrelated reason; fixing the stored ref made the comparison
  land and the self-edge disappeared, with no change to the amendment logic
  at all. Shipping a duplicate fix for a cause that no longer exists is a
  patch, and it hides that the real fix was elsewhere.
- **A guard that clears a flag must clear the fields that assert what the
  flag now denies.** Dropping a self-amendment cleared `is_amendment` and
  `amends_ref` but left `amendment_note` behind, so the stored metadata read
  `is_amendment=false` next to `amendment_note='تعديل'` — asserting an
  amendment it no longer claimed. When a guard removes a fact, sweep the
  sibling fields that carry the same fact and clear them together; a
  half-cleared record is worse than an uncleared one, because it looks
  authoritative.

## References

- `references/debugging-recipes.md` — the mechanisms behind three rules
  above: the logger handler hierarchy, counting a Qdrant collection, and
  the camel/numpy test-isolation defect.
- The wave template (report section shape, release-script shape, the
  per-wave checklist): `references/audit-wave-template.md`.
- `scripts/ab_verify.py` — runs a command against the pre-fix code and
  against the fixed code (swap the named files for their committed
  versions, run, restore), and fails when the command does not
  discriminate. Use it to prove a regression test and a probe's "before"
  before the code commit.
- `scripts/measure_filter_violations.py` — runs a real search with each
  filter and counts the returned chunks that VIOLATE it. The probe that
  found the 82 % violation rate; run it whenever a retrieval, payload or
  store change touches a filter.
