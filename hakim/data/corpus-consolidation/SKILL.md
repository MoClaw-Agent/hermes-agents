---
name: corpus-consolidation
description: "Merge overlapping raw corpora into one complete corpus."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [corpus, consolidation, dedup, manifest, ocr, provenance, mizan]
    related_skills: [corpus-quality-audit, legal-corpus-pipeline, ocr-and-documents]
---

# Corpus Consolidation

## Overview

Class of work: several providers each hold a partial, overlapping set of the same documents, and the deliverable is ONE corpus that is complete (no law missing) and deduplicated (no document twice). This is distinct from building a scraper (`legal-corpus-pipeline`) and from auditing/reparsing parsed JSON (`corpus-quality-audit`) — it operates on the **raw files** and produces the corpus those two skills later parse.

Trigger it when asked to consolidate, merge, or deduplicate document corpora; when a corpus must be shown to be complete; or when building an OCR/scanning handoff.

The governing asymmetry:

> **A duplicate costs disk. A missing law costs correctness — permanently and invisibly.**

Under a completeness objective, over-inclusion is the safe failure and under-inclusion is the dangerous one. Every decision below follows from that.

## Always-On Rules

1. **Verify each provider's actual artifact type before planning around it.** Do not assume a provider holds PDFs because it is a legal portal. Measure: count files by extension per provider, per subdirectory. A JSON-only provider with its text embedded in a metadata field cannot be merged as files — its text must be extracted first, and that extraction is itself a step with its own failure modes. Claiming a provider "has no data" from a top-level `ls` is the failure this rule prevents.

2. **Namespace every file before merging. Never flat-merge a corpus whose providers reuse basenames.** Measure distinct basenames vs file count per provider first. When they disagree, a flat merge silently overwrites with no error and no log. Arabic legal corpora are the known offender: one provider's 139 PDFs shared only 28 basenames, with `1.pdf`–`4.pdf` each appearing ~11 times across domain subfolders, so a flat merge destroys 111 of 139 documents. Namespace as `<source>__<domain>__<safe-stem>.<ext>` and keep a collision counter in the log even when it reads zero — zero is a measurement, not an assumption.

3. **Sanitise filenames for bidi controls and download stamps, and prove the sanitiser works before the full run.** Scraped legal filenames carry invisible directional marks (`‫ظهير‬‫شريف‬`) that make two visually identical names compare unequal, plus a trailing epoch-millisecond stamp (`_1737983838474`) that defeats basename matching. Strip the marks by codepoint range, not by guessing. Run the sanitiser over three or four real filenames and print the result before trusting it on 4,000 files.

4. **Pair each file with its sidecar metadata; do not consolidate files alone.** Crawler sidecars (`<stem>.meta.json`) carry the fields the binary cannot: `source_url`, scrape/download timestamps, `legal_domain`, `subject`, and a `content_hash` recorded at download time. Without them the output cannot answer "where did this come from" or "is this still the file we downloaded". Link them alongside under the same namespaced stem.

5. **A sidecar `content_hash` is an independent integrity witness — cross-check it, do not restate it.** It is a hash written by a different process at a different time. Comparing it against your own hash is a real test that catches in-place mutation, re-download, and truncation. Report the disagreement count; do not silently normalise it away.

6. **Screen text-layer health before choosing between copies, and screen the repair source too.** Classification by Arabic function-word frequency over the first pages of extracted text: `<50 Arabic chars` = image-only (needs OCR); `≥6` stopwords = clean; `2–5` = suspect; `0–1` = ciphered. Corruption propagates along the source chain — a second provider holding the same instrument is frequently ciphered identically, because both descend from one bad scan. A designated "clean reference" must be screened per document, not assumed.

7. **Distinguish a glyph-substitution cipher from a digit transposition before writing any detector.** Under a cipher the extracted text is real Arabic with letters permuted; the letters of a known phrase are absent as a multiset from the entire document. Test that explicitly — check whether the target phrase's letter multiset exists anywhere in the text — rather than inferring the defect from mojibake appearance. Digit-transposition detectors, which look for implausible year patterns, score such a document as clean.

8. **Exact-hash dedup first; defer fuzzy/near-duplicate dedup until the text is trustworthy.** The same instrument published by two providers is frequently a different scan: measured, two copies shared 319 of 513 exact long lines while rendering 0 of 170 pages pixel-identical (per-page Pearson r 0.05–0.16). Detecting that requires readable text on both sides. Running fuzzy matching against layers that are a third unreadable produces false "duplicate" verdicts that delete laws silently — the one failure a completeness objective forbids. Order: fetch → repair text → dedup → elect best copy → parse.

9. **Record dropped files in a manifest; never delete silently.** Every de-duplicated file gets a `duplicate_of` pointer in `duplicates.jsonl`. The source tree is untouched and the consolidated output is hardlinks, so removing the output cannot damage the originals.

10. **`ref` is not an identity.** Measured, 612 of 6,226 distinct refs in one legal corpus mapped to more than one record, in two classes: cross-type (one ministerial order and one supreme-court judgment share a number) and cross-record (four records of one law). Key on the composite `(instrument_type, number, issue_date)`; `(document_type, normalized_ref)` is the floor.

11. **Ref overlap overstates content overlap.** Ref-matching two corpora can report thousands of shared refs while a byte-level sample shows only about half are actually the same file. Measure content overlap (hash a random sample) before quoting a ref-keyed number as a duplicate count.

12. **Title matching fails in both directions — never use it as the sole dedup key.** Providers store short topic labels rather than legal titles (`الماء` = "water", `المقالع` = "the quarries"). Measured against 8,623 union titles: 0 exact, 61 substring, 78 "absent" — including laws demonstrably present. Expect false positives and false negatives in the same run.

13. **Rank remediation queues by document importance, not by severity of technical failure.** Severity optimises for data hygiene; importance optimises for the user. An unreadable circular is cheaper to leave broken than an unreadable constitution. Score on instrument class (dominant weight) + legal domain + log-scale page count + reference presence, and **emit the score breakdown per row** so a ranking can be audited or overridden rather than trusted. When the two orderings disagree, say so and let the human choose — the two answer different questions.

14. **Verify accounting closes.** `survivors + recorded_duplicates == discovered`, every batched path resolves on disk, and the queue set equals the batched set. A consolidation that cannot show its arithmetic is a folder, not a corpus.

15. **Report coverage honestly; distinguish measuring from certifying.** Two providers with no independent oracle cannot prove nothing is missing. Say which sources were excluded and what each would have contributed — a completeness claim is the deliverable, so its limits belong in the output artifact, not only in chat.

16. **Materialise with hardlinks, not copies, and verify with link count.** Consolidation of a multi-GB corpus should cost no extra disk. Confirm `st_nlink > 1` on a sample and that `du` matches the source.

17. **A fluent OCR result can still be uncitable — gate on numeric yield, not readability.** The most dangerous defect in this class is OCR that recovers the Arabic prose and silently drops every digit: `ظهير شريف رقم` survives, the number that followed it does not. Measured on one such document, 140 numeric tokens in the source text layer became 5 in the OCR output, and the prose read cleanly throughout. Nothing signals the loss, because a missing number is indistinguishable from prose that never needed one. A document whose `extraction_mode` is `ocr_forced` and whose text looks correct has been through exactly this path. Validate every OCR result on: numeric-token yield versus the source layer (fail below ~70%); `رقم` followed by whitespace then a non-digit; a reference matching `\d+\.\d+` present **in the OCR text** rather than inferred from a filename or an LLM pass; and the version marker (`صيغة محينة` vs original) decidable. See `references/citability-and-numeric-integrity.md`.

18. **Verify what a provider IS before asserting its authority or recommending a merge policy.** Provider identity is one grep away and was got wrong once here — a provider assumed to be Morocco's Official Journal publisher is in fact a justice-sector training institute that republishes texts without identity metadata. A recommendation built on the false identity inverted the correct decision. Read the crawler's own docstring before making any claim about what a source publishes or how authoritative it is.

19. **Separate "usable" from "citable"; OCR is the gate between them, and it is gated by rule 17.** A document can be perfect retrieval content and unusable as a citation, and the distinction is whether it resolves to which law, which version, as of when. Text-layer corruption is fixable and metadata gaps are fillable, so neither alone makes a document uncitable — what makes it uncitable is having no anchor at all: no reference recoverable from any layer, no date, and the one signal that would identify the version locked inside the cipher. Keep such documents, mark them `source_authority: republication, citable: false`, and let them answer retrieval without ever being quoted.

20. **A complete document corpus is not a complete legal corpus.** Delivering every file once, with nothing missing, satisfies coverage and still leaves the corpus unable to answer "what does article N say today" — a later consolidated version of a law is a different and more correct object than the promulgated text, not a duplicate of it. Government publishers (Legifrance, EUR-Lex/CELLAR) model this as an instrument plus a version list plus an amendment graph, addressing articles by `(instrument, as_of)` rather than "current". Say plainly that a static corpus gets the date-applicable version wrong, and treat the version layer as a separate deliverable. Do not let "the corpus is complete" imply "the corpus is legally sufficient".

## Workflow

### Phase 1 — Measure before planning

For each provider: count files by extension, per directory; count distinct basenames vs file count; locate sidecars and check they pair 1:1 with their binaries; measure text-layer health on a sample. Run the provider-pair overlap twice — by normalised reference and by content (hash a random sample of one side against the other). Report both. Any of these can invalidate the plan; discovering that after building is wasted work.

### Phase 2 — Namespace

Build `<source>__<domain>__<safe-stem>.<ext>`. Derive domain from the parent directory, which is the provider's own legal-area grouping. Sanitise: strip bidi/zero-width codepoints, strip the epoch-stamp suffix, replace filesystem-unsafe characters, collapse whitespace to underscores, truncate to leave room for the namespace. Emit a collision counter.

### Phase 3 — Manifest

One row per file, and let the manifest BE the interface — a directory of files cannot be reasoned about. Columns: `rel_path`, `sidecar_rel_path`, `source`, `domain`, `sha256`, `bytes`, `pages`, `content_health`, `declared_ref`, `declared_title`, `language`, `source_url`, `scraped_at`, `bo_number`, `doc_date`, `legal_rank`, `legal_domain`, `effective_date`, `is_amendment`, `subject`, `has_sidecar`, `sidecar_content_hash`, `content_hash_agrees`, `duplicate_count`, `origin_path`.

Report the population rate of every column. All-zero provenance columns are a finding — they tell you what post-parse extraction must derive rather than inherit.

### Phase 4 — Exact-hash dedup

Group by SHA-256. Keep one survivor per group (prefer healthier text layer, then shorter path, then lexicographic for determinism); record the rest in `duplicates.jsonl` with `duplicate_of`. State the yield plainly even when it is near-zero — a stage that removes 3 files from 4,229 is a measurement, not a main event, and dressing it up misleads the reader about what dedup achieved.

### Phase 5 — Remediation queue

Select the files that need work, rank by importance, batch, and emit per-document `sha256` and page counts so the consumer can verify what it received. Emit a summary with per-tier and per-batch document and page volumes. Verify: queue set equals batched set, all paths resolve, score sequence non-increasing in both queue and batches.

### Phase 6 — Handoff

Emit a flat, uniquely-named drop plus a machine-readable batch list. Re-verify checksums on a sample of the handoff before declaring it ready.

21. **Design the output layout for its consumers, not for tidiness — then re-check it after every restructure.** A consolidated tree is read by code that inspects **path structure**, not just filenames. Measured couplings: a language router that returns `None` unless a path part is exactly `ar` or `fr`; a provider gate that reads `parts.index("corpus")` and takes the next segment as the provider. A flat or differently-named layout silently disables both — no error, just the fallback path and a wrong `extraction_mode`. Before declaring a layout final, read the consumers: who enumerates the tree, what they key on, and whether a missing key fails loudly or quietly. When the layout changes afterwards, re-run those consumers against the new tree — a namespace that was correct when written can become wrong after a move, and the failure looks like a bug in the gate rather than a stale convention. Keeping a provider directory (`<root>/<lang>/<provider>/…`) satisfies path-derived consumers without loosening them; do not weaken a matcher to accommodate a naming choice you made.

## Pitfalls

- **Reporting a stage by its potential instead of its measured yield.** Exact-hash dedup removed 3 files from 4,229. Quoting the 48% net-new figure from a different corpus's sample as if it were this pipeline's dedup rate inverts the reader's estimate of what dedup does here.
- **Collapsing two metadata fields into one to fit a schema.** Writing `declared_ref or declared_title` into a single `declared_title` column silently destroys the reference, and a later consumer that needs "does this document have a citable number" cannot recover it. Carry fields separately and read from the authoritative source, not from a derived queue.
- **A verification probe that compares strings where numbers are meant.** A score written to CSV reads back as a string; lexicographic comparison reported "ordering violated" on a correctly sorted file. Cast before comparing, and re-check any surprising negative — it is more often the probe than the data.
- **Comparing a provider's own sidecar title field to the corpus title field and treating a mismatch as a defect.** Both were read from the same file; a difference means one path normalised and the other did not.
- **Assuming a repair pipeline writes back consistently.** One corpus held 16 repaired PDFs in a parallel `repaired/` directory while only one had been applied back into `raw/`. Diff the two trees and ask which is canonical before consolidating either.
- **Treating a mutation detected by the hash cross-check as damage without reading the file.** The single disagreeing file had been overwritten by a CMap repair; its extracted text went from unreadable to clean and it dropped out of the remediation queue. Report what changed and whether it improved.
- **Letting the excluded-source argument run past one statement.** When a human excludes a source, state the measured cost of exclusion once, in one or two sentences, then proceed without it. Re-arguing an excluded source reads as not listening and costs more time than the coverage was worth.
- **Reading a clean-looking OCR result as a pass.** Fluent Arabic with the digits excised produces no error, no exception, and a full HTTP 200. The tell is comparative, not absolute: count numeric tokens in the OCR output against the source text layer. A document that reads perfectly and yields 4% of its numbers is worse than one that reads badly and yields all of them, because the bad one gets queued and the fluent one does not.
- **Letting a derived field stand in for a source field.** A reference recovered from a filename or produced by an LLM metadata pass is not the same as one read from the document text, and only the second survives a re-scan. Record provenance per field; a citation assembled from inferred identity inherits the inference's errors silently.
- **Offering an engine already measured to be wrong as a live option.** When a provider has no usable text layer, the fallback engine is not a degraded option — it is the *only* reader, so its measured defect becomes the corpus's defect with nothing behind it. Presenting "leave it, it's faster" beside the correct choice inverts the trade-off: the real trade-off is correctness against throughput, and the throughput figure is known. State the cost, recommend, and ask.
- **Inheriting a recommendation from a fact never checked.** "This provider is the authoritative publisher" is a claim about the world, not about the code. One grep of the crawler's docstring settles it, and getting it wrong silently inverts the policy that follows from it.

## References

- `references/raw-corpus-consolidation.md` — the measured figures behind these rules: per-provider artefact census, overlap measurements, the cipher-vs-transposition test, sidecar schema, and the manifest column rationale.
- `references/citability-and-numeric-integrity.md` — the digit-dropping OCR failure, the validation gate, what makes a document citable versus merely usable, and why a complete file corpus is not a complete legal corpus.
- `scripts/` — `consolidate_corpus.py` (namespace → manifest → exact-hash dedup → hardlink), `build_ocr_queue.py` (health-tier queue), `rank_ocr_by_importance.py` (importance scoring with per-row breakdown). All take `--out` and write nothing into the source tree.