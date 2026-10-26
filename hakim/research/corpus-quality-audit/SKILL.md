---
name: corpus-quality-audit
description: "Audit and repair ingested legal corpus JSON files."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [corpus, quality, audit, legal, arabic, adala, ocr, json]
    related_skills: [legal-corpus-pipeline, ocr-and-documents]
---

# Corpus Quality Audit & Repair

## Overview

Class of work: after a legal corpus has been ingested (scraped + parsed + stored as JSON), audit the JSON artifacts for quality defects and repair them in place. This is distinct from building the scraper (see `legal-corpus-pipeline`) — this is post-ingestion quality assurance.

Applies to: any ingested legal corpus stored as structured JSON (ADALA, SGG, DGSSI, JuriThèque, huquqai — any provider whose output is JSON documents with a `structure` tree and `page_texts_sample`).

## Always-On Rules

0. **The text layer is the suspect, not the evidence** — when a document's article count is in question, the text layer you would use to measure it is frequently the corrupted artifact. Never report an article-count discrepancy derived from text-layer extraction as fact. Say "the text layer claims N" and get the human's read of the rendered page before characterising a shortfall. See "Establishing Article-Count Ground Truth" below.
0j. **Execute to verify, but ASK before launching anything long, expensive, or hard to reverse.** Rule 0g requires that a claim be backed by execution; that is not permission to start work unilaterally. Ask first for: a corpus-wide parse or re-parse (minutes to hours per document on CPU-hosted VLM OCR), a live VLM/OCR endpoint request against a busy host, anything that mutates a remote service, and anything touching `.env`, systemd units, or remote hosts. A one-line statement of what will run, on what, and for how long is enough — do not wait for a green light on read-only inspection, which is how root cause gets found. When a run is already in flight and the answer is stop, stop it and report the resulting state rather than substituting a different run. This user sets the rule explicitly; assume it holds for the whole class of work.

0ja. **NEVER fix without explicit permission — always analyze and report first.** When a bug or defect is found during work, do NOT start fixing it. Analyze the problem, report findings back to the user, and wait for a go-ahead before making any changes. This applies to all bug fixes, parser changes, corpus repairs — anything that modifies code or data. The user wants to review the analysis and decide on the fix approach before any changes are made.

0k. **Restructuring a shared dispatch can silently reroute a live dependency other components rely on.** Before moving a gate, a branch, or an engine call in a shared module, list what consumes the old behaviour — a parser in another provider, a service config, a downstream index — and check each against the new path. A change that hoisted a routing gate also stopped consulting a remote OCR endpoint that the whole corpus depends on, and the breakage surfaced only when the endpoint refused connections. Proof by configuration diff is not proof: `git diff` shows what you changed, not what depended on it. State the blast radius before editing, and keep the change reversible until it has run green.

0l. **When ground truth exists, score the NUMBERS, never the text similarity — similarity ranks a digit-transposed layer as the better one.** Rules 0a and 0h say the suspect artifact cannot be the grading key. This is the sharper form, reached only when real ground truth is in hand (a `.txt` beside the `.pdf`, or the user's reading): measured against a correct reference text, the CMap-transposed native layer scored **recall 0.870 / precision 0.990** while every legal reference in it was wrong (`1.02.202` → `22.121.1`, `1423` → `2211`, `2002` → `0260`, issue `5029` → `8365`), and the OCR route that actually read the digits correctly scored 0.607. Character-level similarity is blind to transposition precisely because transposition preserves the character multiset — the layer is wrong in a way that bag-of-chars recall cannot see, and it will win every similarity comparison while pointing the citation index at the wrong instrument. **Report recall/precision only alongside a numeric-fidelity verdict; never let it stand as the quality claim.** Corollary A: probe the digit damage explicitly — list ground-truth reference tokens and assert each appears verbatim in the candidate, and assert the corrupted variants do **not** appear. Corollary B: do not attempt a single-permutation repair. Measured, it is not that one document mixed transposed (`1423`→`2211`) and half-shifted (`2002`→`0260`) forms so a partial table recovered some references and not others — the digit multiset is not preserved at all (see rule 0p and `references/corruption-invertibility.md`), so a partial recovery reading is the optimistic case that does not occur. A partial table applied to non-permuted input silently rewrites references that were correct. Corollary C: a quality gate can report `errors=0 warnings=0` on this document. Structure checks, article-marker counts and masthead patterns all pass while the citations are garbage, so a green gate verdict is not evidence about numbers.

0m. **Diacritics are a one-line detector for a VLM that regenerated the page instead of reading it.** Printed and OCR'd Arabic legal text is unvowelled; a generative model completing the page emits fully harakat-marked text. Measured against ground truth at 0.0000 harakat-per-letter, one OCR route returned 0.1342 — an unambiguous signal that it was composing plausible legal Arabic rather than transcribing, and it fabricated accordingly (invented a library stamp and a supplement absent from the source, and substituted a plausible-but-wrong ministry name). Compute `harakat / letters` for any suspect OCR output before reading a word of it: **any non-trivial ratio means the text is synthetic and must not be scored for fidelity**, because every character-level metric it produces is measuring the model's language prior. See `references/ocr-model-selection.md`.

0p. **Before designing a repair, test whether the corruption is invertible — and expect that it is not.** The reflex when digits come out wrong is "it's a glyph substitution, find the mapping and reverse it", which would repair a corpus for the cost of one table. That requires a **permutation**, and a permutation preserves the multiset of digit characters: compare per-digit counts against a trusted reference and it fails immediately. Measured: the native layer kept ~86% of characters while losing ~60% of digit characters, with digits both vanishing and appearing out of nowhere. **No substitution table exists, so no digit repair is available — plan for a re-OCR or a trusted reference from the start.** The test needs no alignment, which matters because the two methods that do need one both produce confident wrong verdicts: matching digit tokens by length pairs unrelated numbers, and `difflib` alignment on divergent texts yields too few pairs to conclude anything while still printing a confident table. **A verdict resting on fewer than ~30 aligned pairs is not a verdict.** See `references/corruption-invertibility.md`, which also records that the CMap detector handles letter substitution only and returned False on every document tested — so `errors=0` on such a document is not a clean bill.

0n. **Establish a reference file's PROVENANCE before calling it ground truth — a diff against an OCR product can invert your conclusion.** A `.txt` sitting beside a `.pdf` is not self-evidently an original; ask or read its metadata, because the answer changes which source is the outlier. Scored against a cloud-OCR `.txt`, a CMap-corrupt native layer looked like the *better* extraction (recall 0.870 vs 0.607) and the OCR engine looked like the failure — which is exactly backwards, because the OCR route read the digits correctly and the reference agreed with it on the law number while the native layer disagreed on every citation. Neither similarity nor "the file was there first" settles which reading is wrong. Two rules: (a) state the provenance of every reference you score against ("cloud OCR of the same PDF", "human transcription of page N") and downgrade your wording accordingly — a second OCR pass is a *strong reference*, not ground truth, and saying "ground truth" overstates what you have; (b) when three sources disagree on a reference value, the one that agrees with the other two is right, and the odd one out is the corrupt artifact — do not reason from which file you trust a priori. Corollary: a provenance correction from the user mid-analysis invalidates the verdict built on it; re-derive the ranking before reporting, don't patch one sentence of it.

0q. **A metric that does not move when you change the thing it measures is a memorisation signature, not a fix.** The reflex for an under-reading VLM is to raise the pixel budget, and it works partway: harakat-per-letter fell 0.4687 → 0.2068 as body text went 15.4px → 22.9px, and prose clearly improved. It did not make the output citable — digit recovery stayed at **40/70 tokens across both resolutions**, and the law number was right at both. A model that were reading would improve with legibility; one that is recalling cannot, because recall has no resolution dependence. **When you deliberately change a variable, assert the metric you are trying to move actually moved before claiming the variable was the cause.** For legal references the unmoved metric is memorised prior, and the real lever is an OCR-trained model, not resolution, temperature or prompt. Corollary: this is the measured form of rule 0m — diacritics detect *that* the model composed instead of reading; an insensitivity to resolution proves *it cannot be made to read* at that size class. See `references/ocr-model-selection.md`.

0r. **Read the fallback arm of a quality gate, not just its accept arm — a gate with no known-good destination leaves the defect as the default.** Measured: a vision route emitted zero recognised article markers, the gate correctly rejected it (`article coverage 0 < 70% of native layer's 7`), and the pipeline fell back to the native text layer — the corrupt artifact under investigation all along. The document indexed from the worse source while a log line explained the rejection, which reads like success. This is not a tuning bug: rejecting the better option without an alternative is equivalent to choosing the worse one. The rejection must name a destination that is also known-good; when none exists, report "no citable source for this document" rather than indexing the layer already proven wrong. The rejection path is the one that runs silently, so a gate is only as good as its else-branch. See `references/ocr-model-selection.md`.

0s. **"Stop" means terminate and report state — verify the kill actually took, and do not let the verification itself look like a restart.** A mid-flight `pkill` can return 0 while `pgrep` still matches, and a shell wrapper line containing the script name matches its own pattern; a subsequent `pkill -9` whose own command line matches can then be reported as `exit -9`, which reads as a crash rather than a completed kill. Sequence it as: send the signal, `sleep` briefly, then check with a pattern that cannot match the checking command — or read the process table and confirm the PID is gone. Report the resulting state plainly ("both test processes are gone; the only remaining match is my own `pgrep`"). Rule 0j already covers not substituting a different run; this covers making the stop itself verifiable.

0t. **Before SSHing anywhere to fix a service, check whether the address is this machine.** A host reported by address can be the box you are sitting on: `hostname -I` answers in one call, and an SSH attempt costs a failed auth, a password guess, and a wrong mental model of the topology. An auth rejection on the address you were told to use is a strong hint to run `hostname -I` before retrying rather than to ask the user for credentials again. Corollary: `ss -tlnp | grep <port>` on the local host settles "is it bound to loopback or all interfaces" in one call, so a LAN client's `connection refused` can be diagnosed without a remote login at all.

0u. **A closed port from the LAN does not mean the service is down — check the bind address.** A service listening only on `127.0.0.1` refuses every LAN connection while being perfectly healthy locally, which reads identically to "not running" and sends you hunting for a dead process. Probe loopback and the LAN address separately; ping/SSH success plus a closed app port is the signature of a loopback bind, not a failure. Corollary on the same class: assert the model store the service is configured to use actually exists (`OLLAMA_MODELS=/some/path` pointing at a missing directory makes the service start and report an empty model list), and check the unit state honestly — `activating` means the daemon has not finished coming up, so a `/api/tags` probe run too early is not evidence about models.

0v. **A service running as a different user cannot traverse a private home directory — test the WHOLE path as the service user, not the leaf.** Pointing a daemon's data directory at a store inside a `750` home (`/home/<user>/.cache/models` under a mode-750 `/home/<user>`) makes the store itself readable and the daemon still crash-looping, because the unit's `User=` cannot traverse the *parent*. The journal names the parent, not the store: `mkdir /home/<user>/...: permission denied` while `ls` on the store as that user succeeds from your shell. So a pre-flight that stats the configured directory is not a pre-flight — **walk every path element from the filesystem root with `sudo -u <service-user> test -x <dir>`**, and read the unit's `User=`/`Group=` from `systemctl cat` first, because a store that is `755` to you can be wholly unreachable to the account the daemon runs as. Corollary A: the minimum grant is `chmod o+x` on the *parent* — traverse without read, so the service reaches the store and still cannot list your home; verify with a paired probe (`test -x` passes, `ls` denied) rather than by assumption, since the grant that works is the one you meant to give. Corollary B: check the path the daemon is configured with, not the one you would choose. Repointing `OLLAMA_MODELS` at the store that actually holds the models is not optional when the configured path does not exist, and a user asking you to leave a value alone is asking about a value they believe is correct — surface the contradiction (configured path missing, real store elsewhere, service will report an empty model list) and get the ruling before restarting, because the restart itself is what breaks a previously-working loopback service. Corollary C: passing a sudo password by piping it (`echo pw | sudo -S`) is blocked as a brute-force pattern; write it to sudo's stdin from a subprocess instead (`subprocess.run([...], input=pw + "\n")`), which also keeps it out of argv and the journal — and have the script refuse to run unless the target path is owned by the user it is about to chmod.

0w. **A REGRESSION in extracted article count (was N, now M) is usually a change in the TEXT SOURCE, not the parser — establish which text produced the output before editing any parser code.** Rule 0h covers an initial shortfall; this is its regression twin and the trigger is different: something that used to work stopped, and the reflex is to blame the last parser edit. Measured: a document that had produced 197 articles came back with 40 while the parser was correct the whole time. The vision cache the parser reads had gone missing, so the run re-transcribed every page, the remote pass timed out, and the pipeline silently fell back to the fallback OCR engine (which drops Arabic header digits). Proof took one call — run the parse function on each candidate text source and compare: `build_tree(vision_pages)` → 197, `build_tree(fallback_pages)` → 40. So before touching the parser: (a) read the output's own provenance field (`structure_source` / `extraction_mode`) to see which text actually won, and (b) re-run the parse function against each candidate source and compare the counts. A parser fix written for a bug the parser does not have is the most expensive edit in this class — it degrades working code while chasing a phantom, and it is what makes an investigation run in circles. Corollary: an output field naming the winning text source is worth adding wherever the pipeline chooses between sources; without it this diagnosis must be reconstructed from logs. A third cause, distinct from a missing cache and a timeout: **a per-page OCR failure that escalated to document level.** One degenerate page raised out of the vision route, the caller abandoned the whole pass, and the fallback engine ran — 612 articles became 222. The text source changed because a single page failed, not because the cache or the network did; see the per-page isolation pitfall below.

0x. **When your own edits may have broken working functionality: stop editing, analyse the COMPLETE damage, and report before fixing anything.** A fix whose cleanest form removes or narrows an existing path is a degradation, not a fix — functionality is not degraded without explicit permission, so when the minimal fix would drop a working path, stop and get a ruling rather than shipping it. Sequence the recovery as: (1) diff the working tree against the last committed baseline to list every touched file; (2) for each, state what changed and whether it breaks the build or the behaviour; (3) report and wait — do not start repairing. Corollary A: when two consecutive patch attempts on the same file fail (syntax error, broken build), stop patching incrementally — restore the committed baseline for that file and re-attempt from known-good, because patches over a broken intermediate state compound the damage and lose track of what is original. Corollary B: analyse from committed history, not recollection — `git log` / `git diff` is the authority on what you changed, and "revert everything you broke" is answered by diffing the working tree against the last commit.

0y. **A module that fails to import with `re.error: unbalanced parenthesis` has a stray `)` in a regex string literal — and the reported position is often the wrong one.** Find every offending literal by AST-walking the file's `re.compile` calls and checking paren balance inside each string, then fix each to match the canonical sibling module. Measured: three literals in one shared module each carried a stray `)` (`...{0,60}?)?)` instead of `...{0,60}?)?`), so the whole facade — and every module importing it — was unimportable, while the error position pointed at a line that was correct. Diff the drifting module against its canonical sibling (near-duplicate `_shared.py` files exist per provider and drift) before hand-tracing the pattern.

0z. **A missing article number is not necessarily a defect — a contiguous run of them is a range label or a repealed block, not a parser failure.** Moroccan codes repeal provisions in place and print the block as a range: `الفصول 19 - 23` followed by `نسخت`, with a footnote naming the law the content moved to. Measured on a 207-page code: 47 "missing" numbers, of which a contiguous 8 were explicitly repealed and several more sat under range headings — none recoverable, and none a defect. **Render the page (rule 0f) and read it before characterising any shortfall.** The shape tells you which it is: a contiguous run is a label or a repeal; scattered singletons are the parser-failure signature. Corollary: a range heading is not an article header — reject the plural `الفصول`/`المواد` followed by a span, and never emit a range's endpoints as articles.

0ac. **Rank a text source by DISTINCT article identities, never by raw header matches.** Cross-references in body text (`وفقا للفصل 25`) match a header pattern, so a page that merely cites many articles outscores one that defines them. Measured: a per-page source choice driven by raw match counts selected the poorer page on 20 pages, silently discarding 54 compound provisions the other source carried. Count the *set* of `(number, label)` pairs a page contributes, so a repeated citation of one article counts once.

0ad. **A parser JSON is not self-contained — its page text lives in a sibling cache file, and `--force` does not rebuild that cache.** `full_text_in_cache: true` means the JSON carries only `page_texts_sample` (a diagnostic preview) while the real page list sits in `data/corpus/<provider>/cache/<stem>_<sha256(first 4096 bytes)[:12]>.json`. Two consequences. (a) **Ingestion fails closed when the cache is absent.** `[COMPLETE_INGESTION] Full extraction cache not found ... refusing to ingest page_texts_sample` means the cache is missing, not that ingestion is broken: the converter returns no pages rather than indexing the preview, so the document is silently un-indexable while its JSON reads as complete. (b) **`--force` is not a cache rebuild.** It clears parser state and deletes existing output JSONs, and `extract_pages()` takes no force argument at all — on a cache hit it returns the stored pages unchanged, so a force run re-derives the tree from the same text and re-pays nothing for OCR. Re-extraction requires deleting that document's cache file. Audit cache resolvability corpus-wide before blaming the parser or the indexer: derive the key exactly as the code does (the head hash — NOT the JSON's `metadata.content_hash`, which is a different value by design and will match nothing) and tally present-vs-missing per document. Correlating each JSON's `timestamp` against cache presence is what exposes a whole parse batch whose caches are gone: the corpus looks complete from the JSON side alone while every file from that batch is un-ingestable. See `references/cache-resolution-audit.md`.

0ae. **A counter computed FROM the tree cannot validate the tree — audit per-provision CONTENT COVERAGE instead.** `num_articles_detected` is derived from the same `structure` it appears to describe, so agreement between the field and the node count is a tautology: it holds identically on a sound document and on one whose provisions are mostly empty shells. Measured on a 207-page code: `num_articles_detected: 700` matched the tree exactly while **499 of those 700 provisions (71%) carried no content at all**, 50 numbers were duplicated (`الفصل 1` in 29 separate nodes), and 48 nodes held merged multi-provision text. Metadata was clean, both caches resolved, `structure_degraded` was false, and the document was unusable for article-level retrieval. So: (a) never read counter/tree agreement as a quality signal — it is a self-check, not a measurement; (b) count provision nodes whose content is empty AND which have no children; (c) **decide LOST vs MISPLACED before proposing any repair** — search the concatenation of every node's `content` for a distinctive ~40-char slice of the provision's body taken from the source text: present means misplaced (recoverable), absent means lost. A high retention ratio beside a high empty-shell count is itself the proof that the defect is placement, not loss. `scripts/provision_text_coverage_probe.py <parsed.json>` runs all of it; depth in `references/provision-coverage-audit.md`. Corollary: zero change after a re-parse is the stale-text signature, not a failed fix — compare the JSON's `timestamp` against the cache file's mtime (rule 0ad).

0a. **Never grade one extractor against the suspect artifact.** Rule 0's corollary, and the single most expensive mistake in this class of work: when OCR output and the native text layer disagree on a legal reference, do NOT treat the native layer's reading as the correct answer to score the OCR against. The native layer is under suspicion for exactly the defect in dispute, so using it as the key makes every correct OCR result look like a failure — and the conclusion inverts. Get the true value from the rendered page (human or vision) first. A session spent reporting "OCR mangles digits, e.g. 141.192 → 192.141" was in fact observing that the native layer reverses digits, while OCR was correct on every count. Two independent extractors agreeing against a third is a signal that the third is the outlier.
0b. **No monkeypatches, no threshold-tuned heuristics — root-cause fixes only.** The user's standing requirement for this codebase. A fix that special-cases one document, pads a regex until it hits a target count, or wraps around a broken function instead of correcting it is rejected even when the symptom disappears. If the honest fix is "this cannot be detected reliably", document the limitation and gate on something that can be — do not ship a detector that appears to work. Corollary: when a fix requires guessing which node is wrong, ask the user rather than tune until the number matches.
0c. **Never run destructive git commands without explicit permission.** `git checkout <file>`, `git restore`, `git reset`, `git clean` and `git stash` all discard uncommitted working-tree state. Parser fixes live uncommitted until committed, so on this class of work one of these is indistinguishable from deleting the fix: it cannot be recovered from history and must be reconstructed from scratch. Undo a bad edit by correcting the text, or ask. If a destructive command genuinely seems warranted, state what it costs and wait for a yes. Corollary A: commit verified fixes as soon as their test passes, so recovery is a checkout rather than a reconstruction. Corollary B: **`git stash push <exact paths>` scoped to files that are NOT yours, popped in the same breath, is the safe carve-out** — it isolates another author's uncommitted edits so you can re-run a test selection against your own change alone, and it is reversible by construction. A bare `git stash` (everything) stays forbidden, and so does popping without checking what came back. When another agent is editing the same tree, stage and commit only your own paths (`git add <yourfile>`; the pre-commit hook stashes and restores the rest itself) and leave their files untouched — never revert or repair their work to make your suite green. The regression-diff procedure below also uses `git stash`; scope it the same way, or diff against a committed baseline.
0e. **A corrupt text layer destroys STRUCTURE, not just digits — which puts a hard ceiling on parser work and invalidates the obvious measurement.** Digit corruption is the visible half; the damaging half is that header markers can vanish entirely. On a 76-page code the printed page 35 carries articles 109-114 while the text layer of that same page reports "articles" 27-31, and the boundary marker between two adjacent articles does not exist anywhere in the extracted text — one article's opening words run straight into its predecessor's closing words. **Consequence 1:** no parser rule can recover an article whose header is absent from the input; there is nothing to anchor a split on. Say so plainly rather than continuing to tune the detector. **Consequence 2 (the expensive one):** re-parsing the stored JSON's article text to measure whether a parser fix helped is NOT a valid measurement — that text is the corrupt artifact, so the count moves for reasons unrelated to the fix, in either direction. A fix can look like a regression because it correctly dropped a misnumbered phantom, or like a triumph because it recovered numbers the layer invented. Only a re-parse from a real OCR pass, scored against a human count, measures anything.
0f. **When the human cites a specific page and quotes specific words, render that exact page and read it — do not reason from the text layer.** This is the fastest route to a root cause and the one most often skipped. If the user says article 114 begins `يتعرض والي الجهة` on page 35, and your extraction does not contain it, the answer is one page-render away: render, then read the headers visually with a vision tool, and compare against what the text layer claims for the same page. Disagreement between printed page and extracted page is the finding. Rounds spent theorising from the text layer — and rounds spent fixing the parser — would all have been avoided by that single render.
0g. **Never hand over code you have not executed.** `ast.parse` passing, `syntax OK` printing, and a green pre-commit are not verification — the defect only surfaces when the code runs, and the user is the one running it. This is the user's most emphatic standing requirement: ship only what you have actually executed. Corollary A: when the artifact cannot be executed where it lives (a Colab notebook, a remote runtime, a hosted service), build a harness that executes it locally with the environment stubbed rather than asking the user to run it and report back. See `references/artifact-execution-harness.md`. Corollary B: **a stub that stands in for the thing under test will hide the defect it was written to expose** — if the harness pre-binds a global that production code is supposed to bind, the early-return path never runs against real code. Fake the environment, never the subject. Corollary C: do not ship test scaffolding. Smoke tests, `PASTE_KEY_HERE` placeholders, commented-out usage prompts and TODO markers are removed before hand-off, and a check in the harness asserts they cannot reappear.
0h. **Measure the ingestion engine's fidelity BEFORE writing any parser fix.** The costliest ordering mistake in this class: a full day of parser work was spent making `structure.py` recover articles that the OCR backend had already destroyed. On one page, PP-OCRv5 read printed articles 109-114 as `المادة9`, `المادة11`, `المادة114` — digit dropped, two articles absent — so the parser was handed text it could not possibly segment, and every fix it appeared to need was downstream of a fault it could not reach. **Before touching the parser: take one page with known ground truth, run the configured extraction backend on it, and diff the article markers.** Ten minutes there replaces a day of tuning. Score by **numeric yield against the source text layer** (`len(re.findall(r"\d+", ocr))` vs `len(re.findall(r"\d+", native))`), not by prose quality: PP-OCRv5 emits fluent, well-formed Arabic while silently dropping article digits, so a readable page can be missing a third of its references. `رقم` followed by no digits is the tell. Corollary A: a parser improvement measured against its own corpus's stored text measures nothing (rule 0e, Consequence 2) — you cannot tell the fix from the artifact it reads. Corollary B: when the parser looks like it is losing articles, check whether the loss happened at the OCR layer before assuming it happened at parse time; the two produce identical symptoms and opposite remedies. Corollary C: "wrong number" and "right number in an unexpected spelling order" are different faults with different costs — the first is corruption, the second is formatting, and only formatting is recoverable downstream.
0i. **OCR routing is three orthogonal settings, and a gate is only real if every branch reaches it.** Deciding *whether* OCR runs despite a usable text layer (`OCR_FIRST` + `OCR_FIRST_PROVIDERS`), *which engine* it uses (`VISION_OCR_ENABLED` / `OCR_FIRST_ENGINE`), and *whether a Paddle backend may load at all* (`OCR_PARSER_USE_PADDLE_VL` / `OCR_PARSER_USE_PP_OCRV5`, independent booleans — both true is valid) are three different questions, and conflating them produces a config that reads correct and behaves otherwise. Two failure modes, both invisible: (a) a key written in `.env` but never declared as a Settings Field makes `getattr` return its default forever, so the code silently takes the other branch — assert the effective value through the settings object, never by grepping `.env`, and register the key in `core/settings/_admin_field_whitelist.py` **and** `api/routes/admin_config.py` `FIELD_META` or the pre-commit admin-field-drift hook fails; (b) a gate placed inside one arm of a dispatch cascade is unreachable from the arms above it. Measured: the OCR_FIRST gate sat in the final `else` of `extract_pages()` while 299 of 300 real ADALA Arabic PDFs take the `cid_fonts` arm, and the `scanned` arm hardcoded a backend call with no engine selection at all — so the setting governed no branch the corpus actually used. Before trusting any gate, classify a real sample with `_classify_pdf()` and count which arm it reaches; then put engine selection in ONE shared function that every arm calls, and grep to confirm no backend is still invoked directly beside it. See `references/ocr-routing-config.md`.
1. **Audit before repair** — always run a full statistical audit of the corpus BEFORE writing any repair code. Know the scope: total files, document type distribution, extraction mode distribution, article count distribution, empty section count, phantom title count, empty chapter count, citation lead-in count. Repair without audit leads to wrong fixes.
2. **Distinguish defects from legitimate variation** — not every "0 articles" file is broken. Draft finance laws (مشروع قانون المالية) organized by parts/titles/books, and organizational decrees without numbered articles, are structurally valid without article nodes. Audit the FILE CONTENT before classifying as defect.
3. **Repair in place, preserve provenance** — fix the existing JSON files directly. Do NOT rebuild from raw PDFs unless the raw PDF itself is corrupt. The parsed JSON carries metadata (timestamp, extraction_mode, source_url) that would be lost on re-parse.
4. **Garbled OCR headers are a masthead issue, not a content issue** — when the official journal masthead (`الجريدة الرسمية العدد NNNN`) is garbled but the body text is clean, the fix is a targeted masthead repair, NOT a full re-OCR. Re-OCR of a document with clean body text wastes compute and risks introducing new errors.
5. **Empty sections are a parser tree issue, not missing content** — when sections have titles but no content, the content is usually in an adjacent sibling. The fix is tree surgery (merge title into next sibling's content), not data recovery.
6. **Add metadata flags, don't just fix** — when repairing, also add explicit flags (e.g. `has_article_structure`) so downstream consumers (search, RAG) know what to expect. A flag is better than implicit behavior.
7. **Work from the JSON, not the PDF** — the JSON is the parsed artifact. When auditing quality, work from the JSON files in `data/corpus/<provider>/json/<lang>/`. The raw PDFs in `data/corpus/<provider>/raw/` are the source; only revisit them if the JSON defect traces to PDF-level corruption.
8. **When fixing a parser bug, patch the parser AND re-parse** — in-place JSON repair fixes the current corpus, but a future re-parse re-introduces the defect. For a complete valid corpus, fix both: (a) the JSON files in place, and (b) the parser code so re-parses produce clean output. Then re-parse. If only the current corpus needs to be clean, in-place repair suffices.
9. **Verify after repair** — run the same audit metrics after repair to confirm the fix worked. Zero defects should be verified, not assumed.
10. **Check for missing primary law text** — when auditing a corpus for a code law (e.g. مدونة الشغل / Code du travail), confirm the ACTUAL law text with article content is present, not just DAHIR promulgation notices and cross-reference documents. **A DAHIr notice is USUALLY a cover letter** — it contains the promulgation metadata but NOT the law's article text. **Exception (JurThèque pattern):** some JurThèque DAHIr files embed the full consolidated code text inside a `preamble` node (e.g. `dahir_1-03-194.json` contains the entire Code du travail with 50 article nodes and a 14,000-char preamble starting "CODE DU TRAVAIL / Version consolidée..."). **Always check the actual content, not just the file's type label**: a file labeled `dahir`/`promulgation` may carry the full law, and a file labeled `loi` may be an amendment that references but does not contain the articles. The detection procedure below handles both cases by inspecting content rather than labels.

## Establishing Article-Count Ground Truth

`num_articles_detected` is a parser claim, not a measurement. Before saying a document is missing articles, establish ground truth by one of the two routes below — in this order.

**Route 1 — ask the human.** The user's read of the rendered page is authoritative and is the only reliable ground truth on a corpus with CMap corruption. This is cheap: ask for the chapter and article count for one file. Do not substitute your own extraction for it, and do not report a number you derived from the text layer as if it were the truth.

**Route 2 — count rendered pages.** Render the document to images and read the headers visually (or with a vision tool). Note the vision tool's own rate limit and batch the renders so you are not cut off mid-audit. Ask specifically for the article numbers present on the page and for the opening words of any article the user has quoted; comparing the printed list against what the text layer reports for the same page is what exposes a layer that renumbers articles wholesale.

**When the human has already given you a page and a quote, render that page first** — it is the whole investigation compressed into one step (see rule 0f).

### Three ways counting from the text layer goes wrong

All three were hit on a single 16-page ISM code in one session; each produced a confidently wrong number.

1. **Counting UNIQUE article numbers.** Moroccan codes restart article numbering per chapter, so `المادة 41` legitimately appears under الفصل 3, 4, 5 and 8 of the same law. Deduping by number collapses real articles: 44 printed articles collapsed to 25 distinct numbers, and a "shortfall of 3" was reported when the true shortfall was 19. **Article number is not an identity — `(scope, number, inserted)` is.**
2. **Anchoring the header regex to end-of-line.** Chapter headers carry a title suffix (`الفصل الخامس :النظام الجمركي`), so a pattern ending in `$` after the number matches zero chapters and the document looks chapter-less. Allow an optional colon and trailing title: `^\s*(الماد[ةه]|الفصل)\s*([\u0660-\u0669\u0600-\u06FF0-9]+)\s*(?::|：)?\s*(.*)$`.
3. **Screening on the wrong signal.** A screen keyed on "no impossible-year signature" passes every pure-image scanned document, because a PDF with no extractable text has no years to be wrong. A file can be classified clean and contain zero articles. **Absence of a detected defect is not evidence of integrity — treat every screen as a floor, not a boundary.**

### Triage into three states, not two

Classify the whole corpus as SCANNED (no usable text layer → needs OCR) / CORRUPT (text present, signatures wrong) / CANDIDATE (unverified). A "clean" result from a heuristic screen is a candidate, never a pass. Report the three counts and say plainly that the candidate bucket is unverified.

## Patch the Parser When Fixes Must Survive Re-Parse

In-place JSON repair fixes the existing corpus, but a future re-parse will re-introduce the defect if the parser itself is not fixed. For a complete valid corpus, fix BOTH:

1. **Fix the JSON in place** — repair the existing files.
2. **Fix the parser** — so any future re-parse produces clean output:
   - **CMap ToUnicode repair:** add the CMap auto-repair hook to `fetching/pipeline_base/extraction.py` (extraction-time path that re-extracts from the repaired PDF in the same run) AND a CMap repair gate to each parser's `pipeline.py` (post-extraction path that repairs the source PDF for the next run). The shared implementation lives in `fetching/pipeline_base/repair.py` and is imported by all parsers. Both hooks are opt-in via `CMAP_REPAIR_ENABLED` setting and require `mutool`. See `references/pdf-cmap-repair.md` for the full algorithm, integration pattern, and pitfalls.
   - **Masthead repair:** add the masthead repair as a post-extraction step in each parser's pipeline (after pages are extracted, before `build_tree`). Use the shared `repair_extracted_pages()` from `pipeline_base/repair.py` instead of duplicating the regex inline. The masthead repair is always-on (no setting needed) — it is a cheap string scan. See `references/ocr-masthead-repair.md` for the pattern variants.
   - **Empty section merging:** add the merge logic to `build_tree()` in `structure.py` so it runs during every parse.
   - **Metadata flag:** add `has_article_structure` to the output dict in `pipeline.py` so downstream search/RAG knows whether article-level chunking is available.
   - **False-positive container detection:** tighten `_container_hit()` so body text that merely mentions a section keyword is not promoted to a container node.
3. **Re-parse the corpus** with the fixed parser to produce a clean corpus from source.

**Decision rule:** if the user wants a complete valid corpus with no errors, fix the parser AND re-parse. If the user only needs the current corpus clean, in-place JSON repair is sufficient.

**Choosing a text source is a separate decision from repairing a defect.** Some corpora ship a broken RTL ToUnicode CMap that transposes digit glyphs while leaving prose clean, so the text layer's legal references are wrong and OCR is the correct source. Route OCR per provider via the declared `OCR_FIRST` / `OCR_FIRST_PROVIDERS` settings — never as a global switch, because `pipeline_base/extraction.py` is shared across all providers. Establish the correct digits from the rendered page before routing, never by comparing two extractors against each other. See `references/extraction-source-routing.md`. Choosing *which* OCR model, and scoring candidates against a reference OCR so invented legal references are the decisive metric, is `references/ocr-model-selection.md`. Serving one as an endpoint a corpus pipeline consumes — pixel budget, output validation, decoding, HTTP framing, and the resident-memory leaks that kill a long run — is `references/vlm-ocr-endpoint.md`.

**Parser fleet integration rule:** when a repair function is written, integrate it into ALL parsers that handle the affected document type — not just the parser you were debugging. A change to `fetching/pipeline_base/structure.py` affects every provider (ISM, ADALA, SGG, DGSSI, BDJ, JurThèque), so treat any edit there as fleet-wide and regression-test accordingly.

**Dedup keys must carry their scope.** `build_tree()`'s cross-reference dedup rejects a repeated article header as an in-body citation. Its key must include the enclosing hierarchy — `(part, book, chapter)` plus `(number, inserted qualifier)` — not the bare number. A document-global key silently deletes real articles in any code that restarts numbering per chapter, while the code comment right above it describes per-scope behaviour. When a comment specifies a scoping contract, check that the key actually implements it. Keep the `inserted` qualifier inside the scope: `المادة 14` and `المادة 14 مكرر` are distinct operative units (audit 2026-09-21).

**In a code, identity is also COMPOUND: `الفصل <provision>-<code>`.** `الفصل 1-35` is provision 1 of code 35, so a header regex that captures only the leading integer collapses every provision of every code onto the same small numbers and collides with the real articles 1..14 — measured, 85 duplicated numbers and 118 phantom nodes from one document. Carry the full label as the node's identity and put it in the dedup key, or distinct provisions that share a leading number dedup into each other.

**Every consumer of article identity must key on the parser's tuple.** Measured: a duplicate detector keyed on `(chapter, number, bis)` while the parser scoped on `(part, book, chapter, number, inserted)` and used `(number, title)` for the container — so four distinct `الجزء الأول` parts, all numbered 1, collapsed into one scope and produced 6 phantom duplicates, and a newly-emitted compound label the validator had never heard of made distinct provisions read as duplicates. When you widen what counts as identity in the parser, grep for the validator, the chunker and the dedup and widen them in the same change. A validator whose docstring claims it "mirrors the parser" is the tell to check it actually does. See `references/article-header-detection.md`. A repair that lives only in `scripts/` or only in one parser's pipeline will miss other parsers that process the same corruption class. The `corpus-quality-audit` skill's repair functions should live in `fetching/pipeline_base/repair.py` and be imported by every parser (ISM, ADALA, SGG, DGSSI, BDJ) that needs them.

## Corpus Comparison, Deduplication & Merging

When two ingested legal corpora (JSON) cover overlapping laws, compare them to find duplicates, then either deduplicate (keep one copy) or merge (combine best parts of both).

**`ref` alone is NOT an identity — do not key the merge on it.** Measured on the JuriThèque corpus: 612 of 6,226 distinct refs map to more than one record, 1,300 records involved, and the collisions are of two different kinds. Cross-type: `3202.24` is both an `Arrêté ministériel` and a `Décision de la Cour de cassation`. Cross-record: one PPP law appears as four separate `law` records under the same ref. A ref-keyed merge therefore silently fuses a ministerial order with a court judgment. Use the composite `(instrument_type, number, issue_date)`; where issue_date is unavailable, at minimum `(document_type, normalized_ref)`.

**Ref overlap also overstates coverage.** Ref-matching ADALA against JuriThèque reports 3,092 shared refs, but downloading a random sample and comparing SHA-256 against the ADALA raw files shows only ~52% byte-identical — the other ~48% are distinct documents that a ref-only pass would discard as duplicates on title similarity. Measure the *content* overlap before trusting a ref-keyed number as a duplicate count.

**Merge requires trustworthy text on both sides.** Every technique below — field-level best-of, structure-aware article merge, "keep the version with longer content" — silently picks the worse copy when one side's text layer is corrupt. Screen both corpora for extraction health *before* merging, not after. And when repair is needed, repair first: you cannot choose the better of two documents you cannot read.

See `references/corpus-merge-dedup.md` for full code recipes, and `corpus-consolidation` for the raw-file (PDF) level: namespacing, manifests, completeness accounting, and OCR handoff.

### Index Both Corpora by `ref`

Build a `ref → path` dict for each corpus:

```python
adala_index = {}
for jf in ADALA_DIR.rglob("*.json"):
    d = json.loads(jf.read_text(encoding="utf-8"))
    ref = d.get("ref", "")
    if ref:
        adala_index[ref] = jf

jur_index = {}
for jf in JURITHEQUE_DIR.rglob("*.json"):
    d = json.loads(jf.read_text(encoding="utf-8"))
    ref = d.get("ref", "")
    if ref:
        jur_index[ref] = jf
```

Then compute the overlap sets:

```python
common_refs = set(adala_index) & set(jur_index)
adala_only = set(adala_index) - set(jur_index)
jur_only = set(jur_index) - set(adala_index)
```

Note: `set(dict)` returns the set of keys. Both `adala_index` and `jur_index` are dicts — use `set(adala_index)` to get the set of refs.

### Deduplication (Pick One, Flag/Delete the Other)

For each overlapping `ref`:
- Load both JSONs
- Pick the better one by a metric (content length, extraction quality, structure completeness, or simply the one with more articles)
- Write the chosen one to the output (or keep in place)
- Flag the other with `"is_duplicate": true` and the `ref` of the chosen one, or move to a duplicates directory

Deduplication does NOT merge fields or fix errors — it only selects one version to keep.

### SOTA Merge: Field-Level Best-of + Structure-Aware Article Merge

For each overlapping `ref`, produce one merged JSON combining the best of both copies.

**Phase 1 — Field-level best-of merge (metadata):**
For each non-structure field, pick the better value:
- `ref` — same on both, take either
- `title` — take the longer/cleaner one
- `extraction_mode` — prefer "native" over "ocr"
- `full_text_in_cache` — true if either has it
- `num_articles_detected` — take the max
- `has_article_structure` — true if either has it
- `source_file`, `source_provider`, `source_url` — from the better-quality copy
- `parsed_at`, `effective_date`, `timestamp` — from the better copy
- List fields (`tables`, `references`, `relationships`, `camel_entities`, `related_refs`) — merge both with dedup via JSON canonicalization (`json.dumps(sort_keys=True)`)

**Phase 2 — Structure-aware article merge:**
Both copies have a `structure` tree. Flatten both trees to get all articles by number, then:
- **Articles in both trees:** keep the version with longer content
- **Articles only in tree A:** add to merged tree
- **Articles only in tree B:** add to merged tree
- Pick the tree with more articles as the base, replace its articles with the merged set, and attach any remaining articles from the other tree

**Phase 3 — Apply parser fixes to merged output:**
- Masthead repair on `page_texts_sample` and `full_text` (same regex as the parser)
- Set `has_article_structure` based on actual merged structure
- Recompute `num_articles_detected` from actual tree
- Recompute `content_hash`

**Phase 4 — Copy non-overlapping files:**
Copy ADALA-only and JurThèque-only files through with the same parser fixes applied (masthead repair, flag setting, hash recompute). Do NOT skip these — they need the same fixes as merged files.

### CLI Pattern

The merge script should accept CLI args for output and source directories:

```bash
python scripts/merge_ar_corpora.py \
  --output /path/to/merged \
  --adala /path/to/adala/json/backup/ar \
  --jurtheque /path/to/juritheque
```

Default values should match the project's standard paths so the script runs with no arguments.

### Verification

After merge:
- Total files = len(common_refs) + len(adala_only) + len(jur_only)
- All files have `content_hash`
- All files have `has_article_structure` (True/False, not missing)
- No garbled mastheads remain (scan `page_texts_sample` for known patterns)
- Sample check: pick 3-5 merged overlap files and verify structure integrity

See `references/corpus-merge-dedup.md` for full code recipes.

See also: `references/corpus-merge-dedup.md` for full code recipes, a verification checklist, and a ready-to-use argparse CLI skeleton.

## When NOT to Repair

- **0-article files that are draft finance laws (مشروع قانون المالية) or organizational decrees** — these are structurally valid without numbered articles. Check `full_text_in_cache` and structure content before classifying.
- **Documents where the body text is also garbled** — masthead repair alone is insufficient; full re-OCR is needed.
- **Empty sections that are genuinely empty by design** — investigate before merging.

## Workflow

### Phase 1 — Full Corpus Audit

Audit the entire corpus statistically before targeting specific files. Use `scripts/adala_ar_audit.py` for the ADALA Arabic corpus — it performs all checks below and prints a summary table.

```python
import json
from pathlib import Path
from collections import Counter

corpus_dir = Path("/home/mohammed/Mizan/data/corpus/adala/json/ar")

total_files = 0
doc_type_counter = Counter()
extraction_mode_counter = Counter()
articles_counter = Counter()
empty_sections = 0

for json_file in corpus_dir.rglob("*.json"):
    total_files += 1
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    doc_type_counter[data.get('document_type', 'unknown')] += 1
    extraction_mode_counter[data.get('extraction_mode', 'unknown')] += 1
    
    num_articles = data.get('num_articles_detected')
    if num_articles is not None:
        articles_counter[num_articles] += 1
    
    structure = data.get('structure', [])
    if structure:
        for item in structure:
            if item.get('type') == 'section':
                content = item.get('content', '')
                if not content or not content.strip():
                    empty_sections += 1

print(f"Total: {total_files}")
print(f"Doc types: {doc_type_counter.most_common()}")
print(f"Extraction modes: {extraction_mode_counter.most_common()}")
print(f"Article distribution (top 10): {articles_counter.most_common(10)}")
print(f"Empty sections: {empty_sections}")
```

### Phase 2 — Targeted Defect Investigation

After the statistical audit, investigate each defect category.

**Garbled OCR headers:** Sample the `page_texts_sample` of files where the first page text contains known garbled patterns. For Arabic ADALA, the pattern is `((NN (مسيد` or `بمسيد` in the masthead.

**0-article files:** Check whether these files have `full_text_in_cache: true` and substantial content in their structure (preamble, titles, parts, books). If yes, they are legitimate non-article documents. If no, they are parser failures.

**Empty sections:** For each file with empty sections, examine the surrounding structure to understand if the content is in a sibling or truly missing.

### Phase 3 — Repair

#### Repair 1: Garbled OCR Masthead

Write a targeted repair script that:
1. Detects the garbled masthead pattern via regex
2. Extracts the issue number from the garbled text
3. Replaces the garbled masthead with a clean version: `الجريدة الرسمية العدد NNNN`

```python
import re

GARBLED_PATTERNS = [
    re.compile(r'\(\(\d+\s*\(مسيد.*?عدد\s*(\d+)\s*الجريدة\s*الرسمية', re.DOTALL),
    re.compile(r'\(\(\d+\s*\(1\s*بمسيد.*?عدد\s*(\d+)\s*الجريدة\s*الرسمية', re.DOTALL),
    re.compile(r'\(\(\d+\s*\(مسيد.*?عدد\s*(\d+).*?\n\s*الجريدة\s*الرسمية', re.DOTALL),
]

def repair_masthead(text: str) -> tuple[str, bool]:
    for pattern in GARBLED_PATTERNS:
        m = pattern.search(text)
        if m:
            issue_number = m.group(1)
            clean_masthead = f"الجريدة الرسمية العدد {issue_number}"
            replacement = re.compile(r'\(\(\d+[^ن]*?عدد\s*\d+\s*(?:الجريدة\s*الرسمية|[^\n]*?\n\s*الجريدة\s*الرسمية)', re.DOTALL)
            cleaned = replacement.sub(clean_masthead, text, count=1)
            if cleaned != text:
                return cleaned, True
    
    if 'الجريدة الرسمية' in text and 'مسيد' in text:
        fixed = re.sub(r'^الجريدة\s*الرسمية\s+(\d+)', r'الجريدة الرسمية العدد \1', text, count=1)
        fixed = re.sub(r'\n\(\(\d+[^\n]*?\n', '\n', fixed, count=1)
        if fixed != text:
            return fixed, True
    
    return text, False
```

#### Repair 2: Add Metadata Flags

Add `has_article_structure` flag to every JSON file. This tells downstream search/RAG whether article-level chunking is available:

```python
def has_articles(structure) -> bool:
    if not structure:
        return False
    for item in structure:
        if item.get("type") == "article":
            return True
        if item.get("children"):
            if has_articles(item["children"]):
                return True
    return False

data["has_article_structure"] = has_articles(data.get("structure", []))
```

Also add the flag to the parser output dict in `pipeline.py` so it's set on every future parse:

```python
"has_article_structure": bool(structure_node_count({"type": "article"}, root, tree=True)),
```

The `structure_node_count` helper (in `pipeline_base/structure.py`) counts nodes of a given type recursively in the tree.

#### Repair 3: Fix Empty Sections

Merge empty section titles into the next sibling with content:

```python
def fix_empty_sections(structure) -> tuple[list, int]:
    if not structure:
        return structure, 0
    
    fixed = []
    pending_empty_title = None
    num_fixed = 0
    
    for item in structure:
        if item.get("type") == "section":
            content = item.get("content", "")
            if not content or not content.strip():
                title = item.get("title", "")
                if title:
                    pending_empty_title = f"{pending_empty_title} — {title}" if pending_empty_title else title
                continue
            else:
                if pending_empty_title:
                    existing = item.get("content", "")
                    item["content"] = f"{pending_empty_title}: {existing}"
                    pending_empty_title = None
                    num_fixed += 1
                
                if item.get("children"):
                    fixed_children, child_fixes = fix_empty_sections(item["children"])
                    item["children"] = fixed_children
                    num_fixed += child_fixes
                
                fixed.append(item)
        else:
            if pending_empty_title:
                pending_empty_title = None
            
            if item.get("children"):
                fixed_children, child_fixes = fix_empty_sections(item["children"])
                item["children"] = fixed_children
                num_fixed += child_fixes
            
            fixed.append(item)
    
    return fixed, num_fixed
```

### Phase 4 — Verify

Re-run the same audit metrics after repair. Confirm:
- Garbled files: 0
- Empty sections: 0
- All files have `has_article_structure` flag

### Phase 5 — Test

Run the relevant test suite to confirm no regressions:

```bash
cd /home/mohammed/Mizan
/home/mohammed/Mizan/venv/bin/pytest tests/test_adala_metadata_defects.py tests/test_adala_vision_structure.py tests/test_adala_relationships.py -v --tb=short
```

## VLM OCR Routing

When the VLM produces out-of-order articles within a page (common on
multi-column Arabic legal layouts), use the hybrid routing pattern:
full-page VLM first (fast), then layout-guided re-run only for pages
with detected ordering issues. See `references/vlm-ocr-routing.md` for
the full pattern, the ordering-detection function, and the settings.

## Post-Ingestion Verification

After ingestion, run the verification suite: ingestion logs, quality sweep,
Qdrant provision counts vs JSON, hierarchy paths, footnote counts, ref spot-checks.
See `references/ingestion-verification.md` for the full workflow and the known
`ref` field location issue.

## Pitfalls

- **Chasing a parser bug the parser does not have.** An article-count regression reads as a parser defect and usually is not one — the text source changed underneath it (a missing vision cache, a timed-out remote pass, a silent fallback to the weaker engine). Editing the parser to recover articles the input never contained degrades working code and produces the run-in-circles pattern. Confirm which text won (the output's provenance field) and re-run the parse function against each candidate source before touching the parser; see rule 0w.
- **Degrading a working path to make a fix clean.** A fix whose minimal form removes or narrows an existing capability is a degradation, not a fix, and it is not shipped without explicit permission even when the user asked for a fix. When the cleanest fix would drop a working path, stop and get a ruling; when edits may already have broken working functionality, analyse the full damage (diff the working tree against the last commit) and report before repairing anything. See rule 0x.
- **Verifying with a fake that stands in for the thing under test.** A test that monkeypatches `_classify_pdf`, `extract_native` and the OCR backend to drive a cascade can report green while the real code path fails — and the extraction cache makes it worse, because a first run writes entries a later run reads back, so a re-run after an edit can pass on cached output produced before the edit. Assert on real artifacts from a real corpus instead, or clear the cache between runs. If the only way to test a path is to stub it out, that is itself evidence the path is hard to verify.
- **Starting work because the request sounded like a go-ahead.** "parse these now" reads as authorisation and is not, and a fix described as verification is not permission to run a corpus-scale job. State the plan and the cost, then wait. Starting the run first and asking afterwards reads as ignoring the answer; when a run is already in flight and the answer is stop, stop it and report the resulting state rather than substituting a different run.
- **Treating a passing local check as end-to-end proof.** Config assertions, compile checks and import checks all pass while the real route has never executed. Say plainly which links of the chain are verified and which are not — a pipeline whose OCR route has never been exercised on a real PDF is unverified end to end no matter how green the unit checks are.
- **Re-OCRing documents with clean body text** — wastes compute and risks new errors. Targeted masthead repair is the correct fix for garbled headers with clean body.
- **Classifying draft laws as defects** — مشروع قانون المالية (draft finance laws) organized by parts/titles are structurally valid without numbered articles. Check `full_text_in_cache` and structure content before classifying.
- **Regex too strict on garbled patterns** — OCR garbling is not consistent. Start with flexible patterns (.*?) and tighten only if false positives appear. The 2016 variant had the masthead on a separate line BEFORE the garbled text — handle that case explicitly.
- **Structure audits must walk `children` recursively AND detect preamble-collapse** — a flat top-level scan of `structure` misses articles nested inside `title`/`section`/`book` `children` arrays, and reports false "0 articles" for documents that actually have dozens of nested article blocks. But recursing alone is still not enough: some documents have the structure parser collapse ALL content into a single `preamble` block with `num_articles_detected: 0` — there are no nested children to find, the parser simply failed to identify article boundaries. For these, the structure tree is uninformative; check `full_text_in_cache` and the cache directory to determine whether content actually exists. A doc with 0 structure articles but `full_text_in_cache: true` and substantial cache text has a parser decomposition failure, not missing content. Audit both layers: walk `children` recursively for nested articles, then fall back to cache content when the tree is a single flat block.
- **Fixing without verifying** — always re-run the audit after repair. A fix that doesn't change the metric is not a fix.
- **Vision cache staleness produces false phantom-title reports.** When auditing phantom titles (keyword+digits, no space), the JSON may have been parsed from an older vision OCR pass while `cache_vision/` has since been refreshed. Signs: every phantom title reports "not found in vision cache". This does NOT mean the regex is broken — test the regex directly against known text patterns. To verify a fix on the corpus, delete the vision cache file and re-OCR before re-parsing; a re-parse against stale cache text reproduces the old defect regardless of parser fixes.
- **Proving a fix introduced no regressions** — an absolute pass/fail count after a shared-code change proves nothing: the suite may already have been red. Stash the change, re-run the same selection, and diff the two failure lists. Identical lists means zero regressions attributable to the change. Use `git stash push <file> -m wip` then `git stash pop`.
- **A user naming a LAN address is not telling you it is remote — resolve it before designing an access path.** The address may be this machine, and the reverse of rule 0t costs the same: a failed SSH, a password guess, a rejected credential and a wrong topology model, all before any work starts. `hostname -I` settles it in one call, and the fact that you already have SSH on the box proves nothing about which box the user means. Corollary: when a service runs on the host you are sitting on, "reach it" means `curl http://127.0.0.1:<port>` — an SSH tunnel to yourself is noise, and offering one signals you have not established the topology. Corollary: the user's "it's local" is a correction of your access model, not a detail to work around; re-derive the plan around local access rather than retrying the remote one.
- **A regression test that has never failed** — a test written after the fix and only ever run green does not prove it guards anything. Always run the new test against the reverted code and confirm the relevant cases go red, then restore. Pair every guard case (behaviour that must NOT change) and every bug case; the bug cases should fail without the fix and the guards should pass either way.
- **Losing metadata on re-parsing** — when fixing in place, the JSON's timestamp, extraction_mode, source_url are preserved. Re-parsing from PDF loses these.
- **Only fixing the JSON, not the parser** — in-place repair fixes the current corpus but a future re-parse re-introduces the defect. When the user wants a complete valid corpus, fix the parser too and re-parse. When only the current corpus needs cleaning, in-place repair is enough.
- **Async generator consumed twice** — when adding masthead repair to `pipeline.py`, the `pages` value from `extract_pages()` is an async generator. Collect it into a list first (`pages_list = [p or "" for p in pages]`), then run the masthead repair loop on the list. Iterating the generator to build `sample_text` and then again for repair fails because the generator is already exhausted.
- **Container detection too loose** — `_container_hit()` with a fuzzy position window (pos ≤ 25) catches body text that merely mentions a section keyword (e.g. `-كلغ 200 من القسم الأول...`). Tighten to anchored regex first, then fuzzy fallback with pos ≤ 5 only. Test with the specific false-positive lines from the corpus before widening.
- **OCR text that arrives as one line per page** — when page text has zero newlines, any header detector anchored at line start finds nothing and the document reports zero articles even though the markers are present mid-sentence. Diagnose by counting newlines in the cached page text before touching the parser. Prompt changes do not fix it: variants including an explicit instruction to emit one line per printed line all returned zero newlines with output similarity above 0.9, and independent benchmarks put the frontier ceiling for structure at roughly 65 percent. Split run-on text at header markers on the parser side, excluding citations.
- **Citation back-references promoted to articles** — a pointer such as article-20-above is not a new operative unit, and becomes a phantom article when it lands at the start of a line. Reject when the marker (above/below, in Arabic script) immediately follows the number; a real article opens with its operative verb or noun, so the marker can never begin one. Same class as container cross-references, where the damaging case is a citation carrying a real-looking number that shadows a genuine chapter and re-scopes its articles.
- **Simple prepositions before keywords create phantom articles** — `في المادة 6` ("in Article 6") is a cross-reference, not a header. The citation lead-in regex must match single prepositions (`في`, `من`, `على`, `إلى`, `عن`, `ب`, `ل`) as well as compound ones (`بناء على`, `بحسب على`). Do NOT generalize to any Arabic word — that breaks real headers after plain text mid-line. Also check variant spellings of pointer words (`أعلاه` vs `أعاله`).
- **A contents page whose structure was stripped** — line statistics detect a contents page only when dot leaders and line breaks survive extraction, and OCR frequently returns the page as one line with the leaders dropped entirely, leaving bare page numbers. Such a page is re-parsed as real chapters and silently duplicates the whole document hierarchy. Add a second, leader-independent signal (explicit contents marker plus a dense run of sibling container headers) evaluated on flattened text, and test it against the actual extracted string — a hand-built reconstruction can appear to pass and hide the bug.
- **Merge preserves parser tree defects** — the merge script combines the best structure from each copy, but empty containers (sections with titles but no body text) from the parser's `build_tree` survive the merge. The merge's structure merge does NOT apply the `_pending_empty_titles` cleanup from `structure.py`. To fully clean empty containers, either re-parse the merged PDFs with the fixed parser, or port the `_pending_empty_titles` logic into the merge script's structure merge.
- **Garbled masthead variants** — the masthead repair regex matches one OCR garble variant but not all. When merging two corpora, the JurThèque copy's pages 2+ may have a slightly different garble pattern than the ADALA copy (e.g., `عدد الجريدة الرسمية` without a space between the issue number and `الجريدة الرسمية`). Test the repair regex against actual garbled pages from BOTH corpora. If some pages survive with garble, expand the regex to cover the additional variant.
- **Python `nonlocal` scoping in nested functions** — when a nested function reassigns a variable from the enclosing scope (e.g., `count += 1` inside a `walk()` nested in `count_nonempty_containers()`), Python treats the variable as local in the nested function unless declared `nonlocal count`. Without `nonlocal`, you get `UnboundLocalError: cannot access local variable 'count' where it is not associated with a value`. Always declare `nonlocal` for enclosing-scope variables that are reassigned inside nested functions.
- **Variable name typos in f-strings** — a typo like `ada_only_count` vs `adala_only_count` in an f-string produces a `NameError` that crashes the script at runtime. The typo is invisible in review because both names look similar. Always run `python -m py_compile script.py` before executing a new script to catch syntax and name errors early.
- **JurThèque files may carry French subtrees** — when merging Arabic corpora, JurThèque JSON files can contain structure nodes whose `language` field is `"fr"` (French sections). These must be stripped before merging so the merged output is purely Arabic. Use a recursive `_prune_fr_subtrees(tree)` helper that deep-copies the tree and removes any node with `language == "fr"` (and all its descendants) before flattening articles or merging structures. Without pruning, French articles leak into the Arabic merged corpus.
- **Post-merge empty container stripping** — the merge's structure merge does NOT apply the parser's `_pending_empty_titles` cleanup from `structure.py`. Empty containers (sections/chapters/titles/books/parts with no content and no children) survive the merge. Add a separate post-merge `_strip_empty(tree)` pass that walks the merged tree, drops empty container nodes, and drains their titles into the next non-empty sibling's content. Run this AFTER `merge_structures` returns, before writing the output.

- **Tree strip functions must re-check emptiness AFTER recursing into children** — a `_strip_empty` pass that recurses into a container's children and strips them may leave the container itself empty (no content, no children). If the function appends the container to the cleaned list before checking this, the empty container survives. After recursing into a child's children and stripping them, re-check: if the child is now an empty leaf (no content, no children), drain its title into the pending accumulator and skip appending it. Apply this check in BOTH the merge path (`merge_structures._strip_empty`) and the copy path (`copy_and_fix._strip_empty_single`). Without it, files like 1.24.65 (finance law with nested empty tariff containers) retain dozens of empty containers after the strip pass.

- **`copy_and_fix` must run the same empty-container stripping as the merge path** — ADALA-only and JurThèque-only files go through `copy_and_fix`, not `merge_structures`. If `copy_and_fix` only applies masthead repair and flag-setting but skips empty-container stripping, single-copy files retain parser tree defects that the merged files don't have. The `_strip_empty_single` helper in `copy_and_fix` must use the same bottom-up stripping logic as the merge's `_strip_empty`, and must mutate the tree in place (assign back to `d["structure"]`). Without this, 1.24.65 retained 25 empty containers after merge while the merged overlap files were clean.

- **Return-type consistency when changing a function's signature** — when patching a function to return a tuple (e.g. `(structure, warn_count)`), audit ALL return statements in that function. Early-return paths (`if not base: return ...`, `if not other: return ...`) that still return a single value will crash the call site with `TypeError: too many values to unpack`. Run `python -m py_compile script.py` before executing to catch name errors and return mismatches at compile time.
- **A code claim you did not execute is not a finding** — this skill's audits are read-then-verify, in that order. Report nothing about existing code that you have not run or read in full context. Three separate defects were reported from truncated file windows and misattributed lines: one claimed a wrong error code was emitted (it was correct all along), one read a bare digit line as a bare-digit regex match (the character class excluded only Arabic-Indic digits, not ASCII), and one wrote a keyword as a character class `[الفصلالبابالقسم]` instead of an alternation, which matched stray `ا`/`ل` characters and "proved" 92% of headers were missed — pure noise. Print the surrounding lines with enough context to be unambiguous, or better, execute the function and print its return value. When a window is too narrow to be sure, widen it before concluding, and add a self-test to any probe before trusting its output.
- **"syntax OK" is not verification** — a patch that parses can still be wrong, and a subtle wrongness is worse than a crash. Before accepting any fix, run it and assert the behaviour, and cover BOTH directions of a conditional. A cache-hit fix that returned the cached value was correct for the hit path but would serve content validation had just rejected on the invalidation path. Prove the hit returns, the invalidated case falls through, and the corrupt case is handled.
- **A test fixture written to the wrong key tests nothing** — cache and state files are keyed by a derived name (`{stem}_{hash}.json`), not the name you choose. Writing a fixture to `hit.json` when the code reads `27_<hash>.json` makes the fixture invisible: the code silently takes the re-extract path, the test appears to fail, and you chase a phantom bug in the code you just fixed. Derive the real key the way the code does, print it, and confirm the fixture was the file actually read. Related: a synthetic fixture must satisfy the same validity gates real data does (an OCR-mode cache entry needs its own `رقم N` reference or it is correctly invalidated), otherwise you are testing the validator, not the cache.
- **A corrupt sibling source can invert a well-founded fix** — when auditing `digit reversal`, note that a swapped dotted reference (`19.94` → `49.91`) is locally UNDETECTABLE: both orientations are well-formed legal references, so no plausibility test separates them without a corpus of real references. A detector keyed on bare 4-digit years works (`4149` is implausible, `1439` is real) but silently cannot see the dominant form. State that limit in the docstring and assert it as a test case, so nobody later reads `False` as proof the layer is sound. Where a gate depends on such a detector, prefer scoping by provider (verified) over gating on an incomplete detector (blinds the exact files it protects).
- **Partial page loss must be visible** — an OCR stage that drops pages and returns the rest produces a document that looks complete. Log the transcribed/total ratio, record failed page numbers in the document metadata, and treat a shortfall as a parse failure rather than emitting a shorter document. A document missing an eighth of its pages is worse than one that failed: it indexes silently.
- **Degenerate output is also invisible, and a 200 says nothing about it** — the mirror of page loss: the stage returns a full result that is worthless. A greedy VLM on a dense Arabic page produced 4336 characters across 3 distinct lines, 15 identical, returned as HTTP 200 and stored as text. Validate the *content*, not just its presence — measure the share of output lines that are not repeats, and on degeneracy retry once at a lower pixel budget (too-small-to-read is the other common cause) then **raise**, recording the page lost. Returning the least-bad sample is precisely the failure being guarded against. Size the threshold to the domain: statutory text repeats legitimately, so a ratio that condemns ordinary boilerplate rejects good pages. See `references/vlm-ocr-endpoint.md`.
- **A per-page OCR failure must be handled per page — escalation to the batch turns one bad page into a whole-document fallback.** The degeneracy guard is per-page and correctly refuses a looped page, but the raise is only as good as the caller that catches it. Measured: a `RuntimeError` raised on the polling path was outside the caller's caught exception tuple, so it propagated out of the per-page loop and through the document-level extractor, and the caller discarded the ENTIRE 207-page vision pass — falling back to the weaker engine, which drops Arabic header digits, turning 612 articles into 222. Two independent defects, both required for the loss: the raised type was missing from the `except` tuple, and the loop had no per-page isolation. When a stage iterates items and one item's failure is meant to be recorded rather than fatal, wrap the per-item call in its own `try/except`, append the failure to a failed-items list, and return the partial result — and assert the exception tuple actually contains the type the callee raises (grep the callee for `raise`, do not assume). Corollary: a deterministic failure must not be retried — degenerate transcription is a property of the page's pixels, so retrying it from the caller burns the whole retry budget on a 200-page document for nothing; fail the page on the first degenerate verdict, since the endpoint already retried internally at a second pixel budget. **Before changing input granularity to fix a failure (splitting a large PDF into chunks), establish whether the guard is per-page or per-document.** If it is per-page, chunking the input changes nothing: the failing page is still exactly one page inside one of the chunks and produces the same verdict. Read the guard's own scope first — the reflex "the document is too big" is wrong whenever the failure is computed per item, and the fix that helps is per-item failure handling, not smaller inputs.
- **A vision tower allocates super-linearly in image area, so an unbounded pixel budget is a guaranteed OOM** — `MAX_PIXELS = 0` means "no limit" and one A4 page at 200 DPI (~3.9 Mpx) tried to allocate 13.74 GiB against a 14.56 GiB card while the model sat resident. Budget from measured headroom (total − resident − other tenants), expressed as `N * 28 * 28`, and cap on both the client that renders and the service that receives. Resolution and legibility trade against each other: too small and the model cannot resolve the glyphs, which surfaces as §2's degeneration rather than as an error.
- **`.env` duplicates resolve last-wins, silently** — appending a key you have since edited elsewhere leaves both, and the later value wins with no warning. After any `.env` edit, assert the effective value through the settings object (`Settings().FLAG`) rather than grepping the file, and assert the key appears exactly once. A user change that appears configured while behaving the opposite way is almost always a duplicate key.
- **Per-page OCR failure is often image-specific, not size-related** — when an OCR backend drops specific pages, sweep every page individually and record status and pixel dimensions before theorising. All pages of an A4 render to identical dimensions, so a size/OOM explanation is refuted when a small payload fails and a large one succeeds; the real signature was a backend runner crash (`model runner has unexpectedly stopped`), reproducible on the same pages. Do not "fix" it by lowering the resolution budget on a size theory without the per-page table.
- **A quarantine flag that parks documents instead of OCRing them** — `OCR_QUARANTINE_ENABLED` makes the pipeline MOVE an image-only PDF aside rather than OCR it, immediately after logging "falling back to OCR"; the fallback never runs. That policy predates a working OCR backend, and it costs documents: the file leaves `raw/` entirely and becomes invisible to the parser, with no trace in the output to say so. Check the flag before concluding a corpus is short of documents, and restore anything already parked — quarantine is `shutil.move`, not copy, so recovery means moving the file back.
- **A quarantine path that duplicates the language segment** — building the destination as `ocr/<lang>` and then taking the relative path from *after* `raw` repeats `<lang>`, yielding `ocr/ar/ar/<domain>/...`. Check the produced path against the function's own docstring examples rather than assuming the shape; the doubling is silent and mis-files every quarantined document for every provider.
- **A running parser that looks hung** — tqdm writes carriage returns to stderr while log lines interleave, so an actively progressing run reads as a frozen line in a terminal, then appears to stall again through a slow CPU-side model init. Confirm by watching elapsed time climb in `ps`, and run the user-facing command with `python -u ... 2>&1 | tee <log>` so output is unbuffered and tail-able. Do not kill a parser on the basis of a progress display.
- **`rglob` for corpus traversal, not `glob`** — `Path.glob("*.json")` is non-recursive and only finds files in the top-level directory. A corpus with subdirectories (e.g. `data/corpus/adala/json/ar/المادة الأسرية/*.json`) will appear empty under `glob`. Always use `rglob("*.json")` for corpus scans. Verify the glob result count against `os.walk` or a known file count before trusting it. Related and recurring: **an Arabic path pasted into a command can raise `FileNotFoundError` although the file exists** — the pasted string and the on-disk name differ in Unicode normalization. Resolve it by basename glob (`glob.glob(f"**/{os.path.basename(path)}", recursive=True)`) rather than concluding the file is missing; a literal path is a guess about normalization, a basename glob is a lookup.
- **R2-A gate decision workflow** — when the rollout plan calls for an enforcement-gate decision (R2-A for Arabic, R2-F for French), the evidence is a corpus-wide quality audit, not a single-file result. Run a full statistical audit across all files, report clean rate by extraction mode (native vs ocr_forced), and decide: flip the enforcement flag only if the clean rate meets the acceptance threshold AND the known corruption classes (hallucination markers, garbled headers, split keywords) are at zero corpus-wide. A single-file pass (R1) is necessary but not sufficient for R2-A — the gate decision needs corpus-scale evidence. Record the exact numbers in the rollout plan section for the gate.
- **Evaluate corpus, not test artifacts, for gate decisions** — when auditing for an enforcement gate (R2-A, R2-F), run the statistical audit against the actual corpus files. A QA/test artifact (e.g. `french_qa_50.json`) may be contaminated with wrong-language metadata (Arabic doc_type/domain fields in a French audit set) while the underlying corpus is clean. The test artifact is a separate concern from the corpus — do not let a broken test artifact block a clean corpus from passing its gate. Audit the corpus files directly with `rglob("*.json")`, not the QA set. If the QA set is contaminated, note it as a follow-up (regenerate the QA set) but do not block the gate flip on it.
- **R2-S triage before documenting decisions** — when the rollout plan lists shared-policy items (R2-S: OCR quarantine, footnote separation, article-count manifest, quarantine visibility), check each item against the actual codebase before treating it as open. Items already implemented in code (`footnote` cleaning in `structure.py`, `quarantine_failed()` in `extract.py`, `expected_article_count` reading in `quality_validation.py`) are not open decisions — they are documentation gaps. The OCR quarantine toggle (`OCR_QUARANTINE_ENABLED` in `.env`) was a real decision point and has been resolved: it is now `false`, so image-only PDFs are OCRed inline rather than parked. Update the rollout plan to reflect what is implemented vs what is genuinely undecided, rather than documenting all four as open.

- **Extract test fixtures from real corpus text programmatically — never hand-type Arabic into a test file.** Hand-written RTL strings are mangled repeatedly and silently: a letter drops, a combining mark is lost, and the fixture stops resembling the defect it guards. The resulting false failure sends the investigation into the parser instead of the test rig, which is how a correct fix gets reverted on the evidence of a broken probe. Generate the fixture with a small script that reads the actual corpus file and writes the test file, embedding the extracted string as a literal. Two sessions' worth of misdiagnosis trace to this one practice.
- **Provider-specific metadata gaps** — when a field like `num_chapters_detected` is missing from one provider's output but present in others, check whether that provider's pipeline actually sets it. The ADALA pipeline never imported `count_chapters` or wrote `num_chapters_detected` to its output dict, while parser_base and ISM did. Grep all provider pipelines for the field name to find which ones are missing it. `build_tree(str)` and `build_tree([str])` took different branches: the string branch was a bare `split("\n")` while the page-list branch ran the run-on header splitter, so the same document parsed two ways produced two different trees and an embedded header survived one path but not the other. When a splitter, filter or normaliser is required for correctness, assert it runs on **every** entry point, and add a test that both forms of the same input yield the same tree.
- **A repair that reorders tokens must be checked for placement, not just presence.** An RTL digit-first handler built its candidate by appending the number at the end (`keyword + rest + number`), producing a string with no number after the keyword — the code looked like it handled the case and silently matched nothing. Assert the candidate actually resolves to the expected number, and count the records reachable only through that path so the size of the blind spot is measured rather than assumed.
- **Arabic diacritics and tatweel inside the header keyword hide whole articles** — OCR emits `المادَة 21` (U+064E FATHA) and `المـادة 7` (U+0640 TATWEEL) inside otherwise-correct words. `الماده` (ha) is accepted by the header matcher but these are not, so the header never resolves and the article's text is absorbed into its predecessor. On one 76-page code this made articles 21 and 23 invisible; a sibling node was carrying the entire text of article 21. Strip the marks in `_header_candidates()` alongside the existing ligature/hamza repair candidates — and **delete them, do not substitute a space**: replacing U+0640 with `" "` splits the keyword (`المـادة` → `الم ادة`) and still fails. Identify the actual codepoint (`unicodedata.name`) instead of guessing; a mark described as "tatweel" that is really a fatha sends the fix nowhere. When a header variant is rejected, count the numbers reachable only through it — that count is the measured size of the blind spot.
- **The node count and the distinct-number count are different questions, and both overcount** — rule 1 above warns that deduping by bare number collapses real articles. The mirror error inflates: counting parsed nodes (255) and calling it "≈231 real articles" when the distinct article numbers present were 166 against a human count of 256. State both figures and name which is which, or the reader takes the larger as the shortfall.
- **A node beginning `المادة N من هذا القانون` is a repeal citation, not an article** — it collides with the real article N and is the entire cause of apparent duplicate numbering. It is self-verifying: match on the number in the opening phrase equalling the node's own declared number (zero false positives across the corpus). Do NOT simply drop these nodes — many run long and contain a real article's full text after the citation, and dropping them deletes content. Split them instead, and confirm the surviving content is accounted for.
- **An OpenAI-compatible service and an `ollama`-style client differ by one path** — pointing an `ollama` transport at a server exposing `/v1` POSTs to `/api/generate` and 404s on every request. Change base URL and API style **together**; a URL that serves `/healthz` proves the process is alive and says nothing about which routes exist. Probe the actual method+path (`GET /healthz` vs `POST /api/generate` vs `POST /v1/chat/completions`) before pointing a client at it. A GET-only check passes while every real POST fails.
- **A quality scorer must accept every spelling the engine actually emits, or it manufactures false failures.** The same page read correctly by one engine and reported as `MISSING all 6` by a scorer that only matched `المادة 109`, because the engine emitted the RTL visual form `109 المادة`. Before declaring a model missed something, widen the pattern to both orders and re-score — a scorer that reports zero recoveries on output you can see is scoring itself, not the model. Print the matched spans, not just the count, so the mismatch is visible.
- **An enabled OCR setting does not prove which engine ran.** The OCR-first branch called one backend unconditionally, so `OCR_FIRST=true` plus any per-backend flag still routed every document through that hardcoded engine, and the run wrote `mode: native` for a document explicitly opted into OCR. Trust the artifact, not the config: assert on the cache entry's `mode`/`source` field and on a log line naming the engine, and treat a config value that contradicts the artifact as a routing bug to trace rather than a stale cache.
- **A gate that infers a provider from the filesystem path fails silently on the layout you actually have.** The consolidated layout carries the provider in a *filename* prefix (`corpus_consolidated/ar/ism__name.pdf`) with no provider directory, so the path lookup found nothing and the gate skipped with no warning. Every provider parser already knows its own name, so thread an explicit `provider` argument to the shared function instead of re-deriving it — and pin the path-form limitation in a test so the fix cannot regress unnoticed.
- **Prove a regression diff with a method that can fail.** `git stash` on a clean tree is a no-op, so the "before" run is really the "after" run and the comparison proves nothing; and a worktree lacks the corpus data the suite reads, so its failure count is confounded by missing fixtures rather than by your change. To compare in place, copy the file aside, write the previous revision over it, run the same selection, then restore — and keep the baseline list from the same machine and same data, because a quoted failure count from an earlier session is itself stale.

- **A plan's task boundaries can be wrong in a way that silently breaks the tree between commits.** When planning a rename spanning code and config, the unit of atomicity is the *deployable* state, not the source file — a task boundary that splits `X.py` from `X.env` leaves the old key unread at the intermediate commit, which is self-inflicted rule 18. The tell is a plan whose later task depends on a name an earlier task has not yet introduced: applying that later task's names "early" in an earlier task yields phantom failures that look like code bugs. Resolve the coupling when writing the plan, and record the deviation in the execution ledger when reality forces it anyway — the ruling is the deliverable, not the plan. Corollary: assert values the *code* defines, never values read off the live config file; a default and a live setting routinely differ, and a test written from the live file fails against the code. See `references/refactor-planning.md`.

### ISM Corpus: Stem Collisions, CMap Gaps, and Re-Parse Recovery

ISM (ism.ma) PDFs share short numeric filenames (`1.pdf`, `2.pdf`, … `7.pdf`) across different legal-domain subfolders — `droit_civil/7.pdf`, `droit_penal/7.pdf`, `droit_sante/7.pdf` are three distinct laws. This creates two failure modes during repair:

**Stem collision during re-parse.** When a repair script deletes a garbled JSON and re-parses the PDF, `process_file()` writes to `JSON_DIR/<lang>/<domain>/<stem>.json`. If the script processes one domain's stems at a time but the stem is shared with another domain that also needs re-parsing, the second parse overwrites the first. Fix: full wipe-and-reparse — delete ALL JSONs in `data/corpus/ism/json/ar/`, then parse every raw PDF in `data/corpus/ism/raw/ar/` in domain-sorted order so each stem lands in its correct folder exactly once. For ISM specifically, use the **`scripts/ism_repair_screen_then_parse.py`** helper — it wipes the JSON dir, screens every raw PDF for CMap garbling (standard detector + supplemental ISM check), then parses clean docs with `force=False` and only forces OCR on garbled ones. This avoids the 12s LLM-OCR rate-limit on every doc and turns a 30+ min full-force re-parse into ~12-15 min. Never cherry-pick individual stems for ISM re-parse — the short numeric filenames (`1.pdf`–`7.pdf`) are shared across domain subfolders and cause stem collisions. Always wipe-all-then-repair.

**CMap detection false negatives on ISM.** `is_arabic_cmap_corrupt()` in `fetching.pipeline_base.pdf_quality` has a vocabulary early-out: if ≥8 of 16 common Moroccan legal words (وزارة, المملكة, المغرب, ظهير, مرسوم, …) appear, the document is treated as clean. ISM garbled text often retains 1-3 of these words by chance while the rest is mojibake — the early-out fires and the doc gets a flat single-`preamble` structure with `num_articles_detected: 0`. Supplemental detection rule: if a JSON has >3000 Arabic chars in its structure but ≤2 of these 9 specific legal-structure keywords (مادة, قانون, وزارة, مرسوم, ظهير, المغرب, المملكة, الباب, الفصل), treat it as garbled even if `is_arabic_cmap_corrupt()` returns False.

**Fast re-parse: screen before forcing.** The full parser pipeline runs LLM OCR normalization with a 12s rate-limit between chunks, making garbled-doc re-parses take 200-400s each. For a corpus with 15+ garbled docs this is too slow. Screen first: extract each raw PDF's text layer via `extract_pages()`, run `is_arabic_cmap_corrupt()` AND the vocabulary check, then parse with `force=False` for clean docs (skip LLM norm, ~10s) and `force=True` only for flagged ones (~40-60s). Sample: 62 ISM PDFs with 5 garbled completes in ~12-15 min vs. 30+ min if all are force-parsed.

**When a human's reading contradicts the extraction, probe the page before theorising.** Run **`scripts/page_ground_truth_probe.py <pdf> <page>`**. It renders the page for vision reading, lists the article markers the text layer claims for that page, and with `--from-json <parsed.json>` flags artifact articles whose body contains a further article marker — the signature of a destroyed boundary. One run replaces several rounds of reasoning from the suspect artifact, and the printed-vs-extracted disagreement is itself the diagnosis.

**Over-deletion guard.** When deleting garbled JSONs for re-parse, check whether the JSON has ANY article blocks before deleting. A doc like `droit_environnement/7.json` with 6 article blocks but ≤2 common vocabulary words is garbled but retains parseable structure — deleting it loses the article decomposition. Only delete when: (a) 0 article blocks AND (b) garbled (low common vocabulary + high Arabic char count). For docs with articles already detected, call `process_file(..., force=True)` to re-extract in place without deleting first.

### Isolated Subprocess Re-Parse (When In-Process Hangs or OOMs)

The `scripts/ism_repair_screen_then_parse.py` helper runs the full batch in one process. That is the normal path. When it is not viable — a garbled doc hangs the docling OCR path for hours, or a docling crash takes down the whole batch — isolate each doc into its own subprocess so one bad doc cannot kill the batch.

**Working invocation pattern:**

```python
import subprocess, os
from pathlib import Path

VENV = "/home/mohammed/Mizan/venv/bin/python"
env = {**os.environ, "PYTHONPATH": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}

code = (
    "import sys, os; sys.path.insert(0,'/home/mohammed/Mizan'); "
    "os.environ['PYTHONPATH']=''; "
    "from pathlib import Path; "
    "from fetching.ism.parser.pipeline import process_file; "
    f"process_file(Path('{pdf_path}'), 'ar', force={force})"
)
r = subprocess.run(
    [VENV, "-c", code],
    capture_output=True, text=True, timeout=<PER_DOC_TIMEOUT>,
    env=env, cwd="/home/mohammed/Mizan",
)
ok = r.returncode == 0
```

**Required env vars:** `PYTHONPATH=""` (clears the kernel's broken `sys.path` that pulls in a broken pydantic_core), `OMP_NUM_THREADS="1"`, `MKL_NUM_THREADS="1"` (caps thread-count memory). Without `PYTHONPATH=""`, the subprocess inherits the kernel's `sys.path` and imports a mismatching pydantic_core that raises `ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'`.

**Per-doc timeouts (calibrated on this hardware, 2026-09):**
- Clean doc, `force=False`: ~76s (LLM metadata extraction dominates; text extraction is fast)
- Garbled doc, `force=True`: 200-400s (LLM OCR normalization with 12s rate-limit between chunks)
- Docling OCR path on CUDA < 7.5 hardware: OOM/crash, do not use — fall through to PP-OCRv5 or native
- Docling OCR engine on old CUDA (pre-7.5) hardware: causes OOM or persistent crashes during `force=True` re-parses. Symptoms: docling process hangs for hours, or crashes the parent process. The pipeline's docling path is triggered by `force=True` in the ISM parser. On affected hardware, fall through to PP-OCRv5 or the native text-layer path instead. If a subprocess batch is already running with `force=True` and a docling call hangs, the per-doc isolation pattern (below) lets you kill the stuck doc without losing the rest of the batch.

**Batch strategy:** parse clean docs first (fast, ~76s each, no OCR), then garbled docs (slow, ~5 min each, OCR). This gives early wins and lets the batch produce good JSONs before hitting the slow path. Expect ~7-10 docs per hour in a 15-garbled + 124-clean batch on this hardware.

**Do not re-run the in-process script as a fallback after a subprocess batch.** If the subprocess batch completes, the corpus is done. If it does not (time/resource constraints), report the remaining count and stop — do not switch strategies mid-task and re-run the in-process script, which will re-introduce the same hang/OOM risk.

### When All Repair Strategies Threaten to Break Working Output

Prefer a clean full re-parse over complex salvage when salvage has already caused collateral damage (wrong-domain JSONs, deleted good files). If an attempted repair has corrupted files that were previously fine, stop the salvage attempt and re-parse from raw PDFs with a strategy that does not touch files that are already correct — domain-aware JSON existence check (`JSON_DIR / pdf.parent.name / f"{pdf.stem}.json"`) before each parse, skip if OK.
