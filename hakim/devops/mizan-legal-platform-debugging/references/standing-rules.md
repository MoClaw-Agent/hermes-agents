---
title: Standing Rules and Conventions
description: Always-on rules for working with the Mizan legal platform — language, documentation, and workflow preferences.
---

# Standing Rules

## Language

- **All replies must be in English only.** The user cannot read Arabic, Chinese, or other non-English text in assistant responses. Arabic text appears only in file names, JSON keys, and code literals — never in explanation prose.

## Documentation

- After every code fix, check whether documentation (CHANGELOG.md, doc/, .md files, diagrams, README) needs updating and update it in the same commit.

## Workflow

- When the user says "retry", they want the same operation re-executed, not a different approach.
- When the user says "stop", they mean exactly that — terminate and wait for next instruction.
- When the user says "commit and push", they want the current changes committed to git and pushed to origin/main.
- When the user says "mark as failed", they want the parser state file updated so the file will be reprocessed on next --retry-failed run.
- When the user says "check quality", they want a systematic audit of all JSON files in the specified folder, including article count, bis count, errors, and content quality (short articles, cut-off articles, overlapping content).

## Quality Audit Workflow

1. Run `validate_document()` on each JSON file
2. Check for short articles (< 30 chars) — likely cut off
3. Check for overlapping content (first 50 chars)
4. Check for articles not ending with punctuation
5. Classify errors as "order-only" (acceptable) vs "content problems" (need reparse)
6. Mark files with content problems as failed in the parser state file
7. Files with order-only errors are acceptable — do not mark as failed

---

# From SKILL.md

## Standing user preferences

- **No monkeypatches — fix the real thing, at the real layer.** Explicitly corrected: "no fucking monkeypatches, SOTA only". A `getattr(settings, "FLAG", default)` around an undeclared field, a `_url_claims_other_name(...) or True`, or a shim that re-interprets a broken value is not a fix: it hides the defect and the feature behind it is unreachable. Declare the field, patch the function that owns the behaviour, and let the fix survive the next refactor. If a workaround seems unavoidable, say so and get agreement before shipping it.
- **Never run a destructive git command without explicit permission for that specific command.** `git checkout`, `restore`, `reset`, `clean` and `stash` on working-tree files are forbidden unless asked — including to undo your own bad edit. Uncommitted work is *only* in the working tree, so these are not "safe cleanup": `git checkout <file>` on a file you have been editing for hours silently reverts every uncommitted change in it. Fix the edit in place, or ask first and say what it costs. Commit working checkpoints so this class of loss cannot happen at all.
- **Do not present a defect you introduced as a pre-existing one, and do not let a green test hide an unreachable branch.** After adding config-as-a-getattr-fallback, the new tests all passed because they monkeypatched a `SimpleNamespace` — while the feature could never be enabled in production. Tests must run against the real settings object, and must assert the field is declared, or they validate a fiction.

- **Do not act on a config or process change the user did not authorise**, even when the standing goal implies it. Reversible-but-unrequested edits to `.env`, restarts, and deletions are the user's call; propose them, don't perform them.
- **Keep the running job and the diagnosis in the same breath.** If a batch is stopped, say plainly that it was stopped, what it left behind, and what remains unparsed. A user who believes a corpus is complete because a batch ran cleanly for hours is worse off than one told it was halted at 30/121.
- **Be concise and decision-forward.** Lead with current state, the blocker, options, and a recommendation. No filler, no restating, no narrating process. When the user gives a one-word answer ("oke", "yes", "Sup"), match the brevity — a one- or two-sentence status is often exactly right.
- **Never switch to another language mid-response without the user asking.** If the user writes in English, every line of the response stays in English. A multilingual output is not a courtesy — it's noise.
- **When asked for a verdict, give the verdict first, then the evidence.** Do not bury "QARI ran but was rejected" inside a long diagnostic narrative. State what happened, then show the log lines that prove it.
- **Report destructive side effects unprompted, in the same breath as the work.** A parse run that moved 25 PDFs out of `raw/` into quarantine, or a prior run that was a silent no-op, belongs in the report even though nobody asked. The user reads the corpus directory, not my process log — a number that moved without explanation reads as data loss.
- **A diagnosis ends with a recommendation and a choice, not an open question.** When a defect has two candidate fixes, state which is cheap/safe and which is the real work, then ask which to take. Do not patch shared code mid-investigation without that confirmation.
- **Once the next step is agreed, execute it — do not re-propose it.** The choice rule above governs *which* fix; this governs *when*. This session repeatedly ended a turn restating an approved plan and asking to proceed, and the reply was a one-word "execute" each time. Re-proposing settled work reads as stalling and spends the user's attention on nothing. Run the thing, then report what it produced. If a long run is warranted, start it and report its state; a proposal to start it is one round trip wasted. Reserve questions for genuinely ambiguous requirements, irreversible actions, and the choice between materially different approaches.
- **Audit a sample before claiming a defect is systemic.** One short file is a defect report; the same ratio across a corpus is a parser bug. Say which one it is, with the table.
- **Never recommend *against* a resource on an unprobed hypothesis — probe it first.** Logged 500s and healthy health-check endpoints look like a diagnosis and are not one. A migration away from a host (to a notebook, another box, a different model) chosen on that basis is the expensive version of this mistake, because it survives the evidence that would have refuted it: the fault is transient, clears, and you have already redirected the pipeline. Send one real request through the thing you are about to rule out, read the body, and only then say it is broken. If you cannot probe it, say the fault is unexplained rather than naming a cause. **This failure recurred: after naming OOM on the LAN host and recommending a notebook migration, a direct probe showed the host serving both transports with correct Arabic. The health-endpoints-are-not-a-diagnosis rule below was already in this skill and was still violated — logged 500s are a *reason to probe*, never a diagnosis to report.**
- **A heuristic screen's "clean" bucket is unverified, not passed.** A screen keyed on "no impossible-year signature" passes every pure-image scanned document, because a PDF with no extractable text has no years to be wrong. Always report three buckets — SCANNED (no text layer) / CORRUPT (text present, signatures wrong) / CANDIDATE (unverified) — and say plainly that the candidate bucket is untested.
- **Do not build a batch on a count you have not validated.** Triage first, report the buckets, let the user pick the scope, then parse. Deleting prior JSONs and relaunching on an unvalidated "clean N" wastes the whole run and destroys the evidence needed to explain the result.
- **Do not name a code defect, or a predicted failure count, without measuring it against runtime data.** Reading a nearby `except` handler, or assuming how a queue was enumerated, produces confident wrong claims — and a retracted bug sends the next session chasing a fix that was never needed. Sweep the real data, then report. If measurement contradicts an earlier claim, say so plainly and correct the record rather than quietly dropping it.
- **Treat the user's eyeball observations as probe triggers, not as claims to argue with.** On this corpus the user read a page and said "44 articles" while four successive automated probes reported 28, 25, 39 and a confident "shortfall of 3". They were right every time. A casual remark like "maybe first page is title of the book" should send you re-reading the actual pages — that one remark led to the title front matter, the `الفصل.1` period-header defect, and the TOC page structure, none of which the probes had found. Automated measurement on a corrupt text layer is a hypothesis generator; the rendered page is the evidence. When the two disagree, re-read the page before defending the number.
- **Correct the record in plain words when you were wrong, and do it early.** A retracted diagnosis costs the user more time than the error did. State "I was wrong about X", what the evidence actually showed, and what it cost — do not quietly drop it or bury it under the next finding. After a wrong call, re-derive the conclusion from the log before making the next one; repeating the same mistake twice in a row is the failure mode to guard against.
- **A wrong diagnosis is usually a wrong *kind* of evidence.** Nearly every bad call this class of work came from trusting an indirect signal (a progress bar, a CPU percentage, an open socket, a configured-but-unread flag) over the ground truth (the log, the rendered page, the actual settings object). Reach for the artifact that records what happened, not the one that shows the process is busy.
- **Verify the target still exists before carrying a conclusion forward.** A re-crawl replaces sources in place, so a verified finding can describe bytes that no longer exist. Re-stat the file and re-read the current article numbers before carrying a conclusion forward, and say plainly when earlier evidence no longer applies rather than quoting it as current.
- **Never remove a dependency because the code never imports it.** A library can probe for a package by metadata instead of importing it — `transformers.from_pretrained` calls `importlib.metadata.version("bitsandbytes")` as a capability check — so deleting an apparently-unused package breaks model loading with a `PackageNotFoundError` that names neither the notebook nor the removal. The test is "required at runtime, directly or via a dependency's capability probe", not "appears in the import list".
- **When a remote dependency is failing, verify the whole gate set resolves, not just the URL.** Flags like `ADALA_QARI_OCR_ENABLED` gate everything below them; a hand-edited `.env` can carry a correct base URL, model, style and key while the master switch stays off, so nothing is called and the config looks complete. Confirm the gate opens and make one real call through the adapter before reporting the switch done.
- **When the user says stop/kill, stop and report — do not take the next initiative step.** A request to stop a process is not a request to restart it, and not a cue to launch a replacement run, adjust config, or clean up. This has been corrected explicitly more than once. Stop it, verify nothing is left running, state the resulting state, and wait. Never treat "kill it" as "get it running again".
- **Do not kill a running batch on a progress-bar read.** See the stall-detection rule above; confirm with per-file completion lines first — and confirm the *failure counters* too, not just the completion lines.
- **Never open config or settings objects wholesale.** Printing a settings repr, dumping a dataclass, or `cat`-ing `.env` past the secret-file guard can spray API keys into the conversation transcript. Edit `.env` programmatically without reading it back, and never print a settings object — select the single field you need.
- **Verify extracted values against ground truth before proposing a fix that rewrites them.** When a diagnosis implies a change to shared extraction code, confirm the actual values first (render the page and read it). A confident fix built on an unverified theory is worse than no fix: it converts missing data into plausible-but-wrong data. If verification contradicts the theory, say so plainly and correct the record — do not build the fix anyway.



