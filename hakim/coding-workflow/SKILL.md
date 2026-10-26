---
name: coding-workflow
description: "Agentic coding workflow patterns."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [coding, workflow, agents, trust-gate, verification]
    related_skills: [superpowers:verification-before-completion, superpowers:test-driven-development, superpowers:dispatching-parallel-agents]
---

# Coding Workflow

## When to Use

- Starting any multi-step implementation, debugging, or review task
- Setting up agent definitions (`.agents/`) or skills (`.mimocode/skills/`) for a new project
- Need to verify `.agents/` directory trust before loading agent definitions
- Completing a task and need a structured completion summary + followup suggestions
- User asks to "adapt" or "rip" patterns from another tool/framework
- User asks to integrate external skills/tools (e.g. Qdrant Skills, freebuff patterns)

## Core Principles

1. **Specialize, don't monolith** — Different tasks need different agents:
   - `parser-debugger` — parser/output debugging
   - `corpus-auditor` — corpus quality auditing
   - `search-debugger` — search/retrieval debugging
   - `code-reviewer` — review changes before committing
   - `thinker` — complex analysis, multi-step planning

2. **Propose, then apply** — Never write directly to a file without proposing the edit first:
   - Use `str_replace` / `patch` for targeted edits
   - Use `write_file` only for new files
   - Show the exact diff before applying
   - Wait for user confirmation on non-trivial changes

3. **Track progress** — Use `todo` tool for multi-step tasks:
   - Break work into atomic steps
   - Mark complete only after verification
   - Don't skip steps

4. **Truncated-write guard** — Never complete a cut-off edit, and never patch a file your own edit just broke:
   - If a file write was interrupted, do NOT try to repair it by guessing the intended content
   - Re-read the file to see what was actually written
   - Re-do the edit from the current state
   - **A syntax check that fails immediately after YOUR edit means YOUR edit broke it.** Revert to the last known-good version and rewrite the whole file in one pass, rather than patching the breakage. Successive patches onto an already-invalid file compound: each targets text that has shifted, silently drops a needed token (a closing `})();`, a brace), and the next check reports a *different* error — so the sequence reads as a moving bug instead of one self-inflicted wound. The tell is a file that parsed before your first edit and reports a new error after each one; the exit is to stop patching, re-read the file end to end, and write it once.

5. **A shared working tree may hold another author's uncommitted work — touch only your own paths.** When another agent or session is editing the same repo, `git status` shows their modified files alongside yours and the instinct to "clean up" is the dangerous one. Rules: (a) commit with an explicit path list (`git add <yourfile>`), never `git add -A` / `git add .`, so their work is never staged into your commit; (b) a test failure caused by their edits is THEIR in-progress state, not a regression you introduced — verify your own change in isolation by stashing only their paths (`git stash push <their-files>` … `git stash pop`), and never revert or "fix" their files to get your suite green; (c) say plainly in the hand-off which failing checks belong to their uncommitted work so the user is not misled about your change's state; (d) when they edited a file you *also* edited, `git add <file>` is not enough — it stages their hunks too. Split the diff by hunk (`git diff -- <file>`), group hunks on a marker string unique to your change, write the diff header plus only your hunks to a patch file, then `git apply --cached <patch>` and confirm with `git diff --cached <file>` that only your hunks are staged. Keep any stash window short and never edit files while a stash is active: `git stash push -- <paths>` … `git stash pop` is not atomic against another writer, and a pop after their intervening write conflicts or silently drops work. The failure is silent and its symptom is confusing: when the other writer saves a tracked file during your window, the later `git stash pop` merges their newer content into the stash entry, so files you never touched come back modified and the pop can report success. Treat the window as a lock — start no edits, and run the whole push → test → pop sequence as ONE command so nothing intervenes. If the baseline run is long enough that you would want it in the background, do not stash at all: run the baseline first (or last) with no stash, or narrow the comparison to the specific test files your change touches. Never background a command that leaves the tree stashed while you keep working.

6. **Think deeply, then act** — For complex tasks:
   - Use `think_deeply` or write a plan first
   - Break the problem into sub-problems
   - Solve each sub-problem independently

7. **In a suite that already has failures, verify by diffing the failure SET against a stashed baseline — never by the summary line.** A pre-existing failure count tells you nothing about yours. Capture the set (`pytest -q 2>&1 | grep '^FAILED' | sed 's/FAILED //' | sort > mine.txt`), stash only your paths, capture again into `base.txt`, then `comm -23 mine.txt base.txt` for what you introduced and `comm -13` for what you fixed. **Equal totals are not proof** — one new failure can be masked by one flaky test that happened to pass, and vice versa; only the set diff is evidence. Re-run any single differing test in isolation to classify it as flaky vs real. Report the pre-existing count and the set diff in the hand-off, or a red suite reads as your regression.

8. **When your own test fails, suspect the fixture before the production code — and prove it by rebuilding over a real artifact.** A synthetic fixture encodes assumptions about the code you are changing; when the code decides something *per document* (a median over collected values, a density vote, a dominant-keyword choice), a two-item fixture fails that decision and the test fails for a reason unrelated to your change. Before touching the production code, rebuild over a real cached input and check whether the behaviour is correct there. If it is, the defect is the fixture's shape: give it at least the handful of low-valued entries the real document has. Symptom to recognise: your new tests fail with *fewer* results than expected or a container classification instead of an article one, while an existing nearby test passes.

9. **Fix a generated artifact at its template, and verify by round-trip.** When a file is produced by a generator (a manual built from an HTML template, a lockfile, a compiled schema), editing the generated file is a change the next build discards. Fix the template, re-run the generator, and confirm the change survives a *second* run — a single build proves nothing about what the next one produces, so the round-trip is the actual test. Then regenerate every deployed copy in the same pass: a generated artifact usually exists in more than one place (a source dir and a served/deploy dir), and regenerating one leaves the other stale, so the two silently disagree — the source copy missing content the served copy still carries. The symptom that identifies this class: a diff against a file you never edited, whose only meaningful lines are content you added earlier, buried in date/version churn. Recover the intended content from the last commit that had it (`git show <commit>:<file>`) and re-apply it to the template rather than to the output.

11. **A new guard changes which code path a document takes — so it can expose a latent bug that the old path was masking.** Adding an early-out, a gate or a re-route is never behaviour-neutral for the inputs that now go elsewhere: they land on a path that has rarely or never run, and any bug there was previously unreachable. Measured: a gate that skipped the auto-derivative branch routed affected documents into the standard priority path, where an extension-strip (`filename.rsplit(".", 1)[0]`) silently truncated a dotted reference (`1.12.34` → `1.12`) — correct-looking output, wrong value, and the bug had been latent because the other branch always handled those documents first. So after adding any gate: **re-run the changed function over a broad sample of real inputs under BOTH the old and new code and diff the outputs.** Do not sample the inputs the gate targets — sample everything, because the new path is reached by exactly the inputs you were not thinking about. Classify every difference: a new value that is *more* complete or correct is the fix working; a new value that is shorter, wrong, or plausible-but-different is the latent bug surfacing. Quantify it ("293 identical, 177 more complete, 0 regressions") rather than asserting no regressions from the tests alone — the tests exercise the cases someone thought of, and the latent bug is by definition in the ones nobody did. A shared helper and the local code it replaces are rarely equivalent: one matches more than the other (a looser quantifier, an extra alternation), and a shared helper often carries a documented precondition its original callers satisfy and yours does not. Before substituting, run both against the real inputs and compare their captures, then read the shared helper's docstring for the conditions it assumes (a guard the caller must apply, an ordering requirement) and confirm your call site meets them. The failure is silent and returns a *plausible wrong value* rather than an error — a reference extractor that swapped its own strict pattern for a loose shared one returned the *cited* law's number instead of the instrument's own, which is precisely the defect its tests existed to catch. This is the characteristic failure of a prescribed "cleanup": it reads as mechanical, so it gets applied without running the tests. Run the tests before committing any recommendation you did not design yourself. **When a prescribed item contradicts a higher-priority test, the test wins.** An audit can be internally inconsistent — here a low-priority "cleanup" item (replace the local pattern with the shared one) directly contradicted the audit's own priority-1 test suite, which existed to catch exactly the regression the cleanup caused. Priority order is not a style preference: a suggestion filed as maintenance does not get to break a stated correctness requirement. When two items conflict, say so and follow the test.

12. **Validate a shared/global strategy change across the whole corpus, not one document — with a win/loss/equal tally and a second competing metric.** When a change alters how a *class* of inputs is handled (a per-page source choice, a fallback order, a threshold), one document proves nothing: by construction the change wins on some inputs and loses on others. Sample everything the change can affect, report the mean movement on the primary metric, and tally how many inputs improved / regressed / tied — a mean alone hides a strategy that wins big on a few and silently degrades many. Carry a second metric that catches what the primary one rewards: a rule tuned for "more items found" must also be watched for "more phantom or truncated items produced", or it trades precision for count. **When the signal is a count, count DISTINCT identities, not raw pattern matches** — citations and repeated mentions inflate raw counts, so a source that merely *references* many items outscores one that *defines* them and the selection inverts. And when one source structurally cannot represent something the other can (a text layer that shreds compound identifiers, a parser that lacks a concept), require it to beat the alternative by more than what it would lose, or it wins on a marginal count while silently discarding real content.

13. **"Missing data" may be correctly missing — verify against the source before treating absence as a bug.** A report that N items are absent from parsed output is a claim about the source, not proof of a defect: some are legitimately not there (repealed provisions, range headings that only reference the numbers, items on genuinely blank pages). Resolve each absent item against the source itself — and **read the source, do not infer it from the surrounding text**. Neighbouring-item arithmetic ("the item before is 18, the one after is 24, so 19–23 must be missing") is exactly the reasoning that produces a wrong fix: those numbers can exist only as a range reference. Classify the absent items (provably-absent vs genuinely-dropped) and report the split, because a fix aimed at the whole set spends effort on items that must stay absent, and "restoring" them injects content the document does not contain. Corollary: when the source cannot supply an item, saying so is the correct result — never synthesise it from neighbours. **Same family: an exclusion you did not expect may be a deliberate invariant, not a defect — grep the test tree for the behaviour before reporting it as a bug.** Measured: a search path that filtered pinned rows out of its query looked like a serious retrieval bug (rows present in the index, query returning nothing) and was reported to the user as one; the project's own suite had a test asserting exactly that exclusion, because pinned items are injected on every turn instead of being searched. One grep of the tests would have prevented a false defect claim. Before escalating a surprising behaviour, look for the test that encodes it — a deliberate filter is usually documented where it is enforced.

14. **A test that fakes the entry point proves nothing about the entry point — check what the test actually invokes before trusting a green suite.** A monkeypatched `parse_args`, a stubbed `main()`, a direct call to an inner handler: each bypasses the wiring where the real bug lives. Measured: an argparse CLI whose `main()` passed a hardcoded empty argv list never read `sys.argv` and never dispatched a single subcommand — and the suite was green, because the tests replaced `parse_args` with a fake namespace carrying a stub handler, and asserted a condition that the broken behaviour satisfied (`"not wired yet" in out or out.strip() == ""` — the empty output took the second branch). A second test file called `build_parser().parse_args(argv)` directly and never touched `main()` at all. So: **for any entry point (CLI main, HTTP route, plugin `register`, job runner), run it for real at least once and assert on the observed effect**, and when reading a test, ask what it would still pass if the production code were deleted. A disjunctive assertion with a permissive fallback branch (`X in out or out == ""`) is a tell — it was written to accommodate the broken state. Prefer invoking the real entry with real arguments (`python -m pkg.cmd status`, `capsys` on actual stdout) over asserting on a hand-built namespace.

15. **A status document is a claim, not evidence — re-derive every "done / wired / tested" line against the code before building on it.** Design docs and READMEs drift out of step with the code, and they drift in both directions: a README can say "Phase 1 not started, nothing runnable" in one section and "Phase 1 store, schema and CLI are present" in another, while the guide claims a feature is implemented and unit-tested that is in fact silently inert. Before planning work from such a document, spot-check its load-bearing claims with the cheapest real command: run the tests it cites, run the entry point it describes, grep for the config keys it documents (a key that is read and logged but never enforced is unimplemented — say so). Report the discrepancies as findings rather than silently working around them, and fix the document in the same pass as the code. Corollary: when a doc and the code disagree, the code wins and the doc is the bug. **Budget for the document being a map of the code's INTENT, not its state** — a spec or review doc is still the right source for requirements and invariants, so read it early rather than after implementing: reading the design doc *after* writing the code turns each stated guarantee into rework, whereas reading it first makes the same document a checklist. The cheap ordering is: read the design doc → spot-check its claims against the code → then implement.

16. **A green suite is not evidence the behaviour is right — tests that pass over a defect were written around it, so expect them to fail when you fix it and read each failure as a claim about the old behaviour.** Measured repeatedly inside one pass: a dedupe test asserted a non-`None` result for a message that matched no memory, so it passed only because an empty context block was injected unconditionally; three extraction tests passed a throwaway current turn and silently relied on the bug that ignored it; an evidence fixture's quoted span existed only *inside* the candidate, which is precisely the hole being closed; and a CLI test replaced `parse_args` with a fake namespace and asserted a disjunction whose empty branch the broken output satisfied (principle 14). Rules: before trusting a suite over code you have just proven broken, **enumerate the tests touching the changed behaviour and ask what each would still pass if the defect were still present**. When one fails after the fix, do not reach for the assertion first — decide whether the *test's intent* is still valid. If it is, fix the fixture so it exercises the real path; if it is not, the test was asserting the bug and must be rewritten. Tells that a test is complicit: a disjunctive assertion with a permissive fallback (`X in out or out == ""`), a fixture value that could not survive the invariant you just added, and an input chosen to avoid the code path under test. **Also grep the test tree for duplicate test function names** (`ruff --select F811`, or group names and look for repeats): a later definition silently shadows the earlier one, so the earlier test never runs at all. A real defect found this way was a durability assertion that had never executed since it was written, sitting directly above its own shadow — the suite reported it as passing the whole time.

17. **Before any command that discards working-tree state, make the work recoverable — and treat an unversioned project as the first thing to fix.** `git checkout -- <file>` restores from the index, so it deletes uncommitted work in that file with no prompt and no undo; reached for mid-sweep to undo a bad scripted edit, it silently destroyed a verified batch of fixes that had to be redone from scratch. Rules: (a) if the project is not a repo, `git init` plus one baseline commit **before** touching anything — that single step is what makes every later mistake revertable; (b) commit after each verified batch rather than sweeping many files and committing once, so the blast radius of any mistake is one batch; (c) to undo an edit prefer `git stash` (recoverable) or a copy of the file, never `git checkout --`, and read what you are about to discard (`git diff <file>`) first; (d) snapshot the files to a scratch directory before a bulk edit is about to run across them — the copy is far cheaper than the rework. Corollary: a repo tracking build artefacts (bytecode, local databases) makes `git add -A` stage noise; add the ignore file in the same first commit.

18. **Audit code against its own spec by reading for missing writes, not just broken logic — an unimplemented guarantee leaves no trace in the diff.** When a project ships a design/review document, the expensive defects are not the ones that crash; they are the guarantees the document states and the code never implements. Those are invisible to a test run (nothing fails) and to a lint pass (nothing is wrong), so they survive indefinitely. The productive method is a targeted read: **enumerate the state changes the spec requires and grep for the write that would perform each one.** Measured in one pass: a table whose schema had permitted `create`/`update`/`pin`/`unpin` audit actions since an early migration, where nothing ever wrote them — only archive/restore/delete did; a cap the spec said must be *enforced* ("reject beyond N with a clear message") that only bound the *render* path, so the store accepted unlimited pins and silently dropped the overflow later; and a config key read into a config dict, documented in two places, and acted on nowhere, so the feature it protected ran with no rollback point. Each was found by asking "where is this value written or enforced?" and getting no hit. Tells: a config key with an accessor but no call site; a column or enum value that appears in the schema and in no `INSERT`/`UPDATE`; a limit applied when reading but not when writing; a `dry_run`/`--confirm` flag that changes an output string but not a code path. Report each as a spec-vs-code discrepancy, and implement the missing write in the same pass as the fix — a safeguard that is documented but not enforced is worse than an absent one, because it is trusted.

19. **Verify a claimed safeguard against the attack it names — a guard can be present, plausible, and check the wrong thing.** A security or integrity check that runs is not a check that works. Read what it actually compares, then construct the input it is supposed to reject and confirm it rejects it. Measured: an evidence-verification guard for model-extracted claims checked the quoted span against **the candidate's own content** rather than the source text, so a fabricated claim that quoted itself as proof passed — the guard existed, was documented, and validated the one input that could never fail. The same audit found a trust field read as `item.get("source", default)`, letting the untrusted producer set its own trust level and promote an assistant turn to user-attributed. Rules: (a) for each safeguard, name the specific bad input and probe it — do not accept "the check exists" as evidence; (b) beware any comparison where both sides originate from the untrusted side; (c) beware `dict.get("field", safe_default)` on values from the untrusted producer — the default only applies when the field is *absent*, and the producer supplies it present; (d) a safeguard written against a trust boundary must be enforced at the boundary, not by the producer's cooperation. **A probe that returns the *safe* outcome for the wrong reason is not a pass — confirm the guard fired, not merely that nothing bad was returned.** A rejected probe is ambiguous by construction: when a target has more than one guard, the one you are testing may not be the one that fired, so isolate it (disable the others, or choose an input only your guard rejects) before concluding the safeguard works. Equally, a probe that *passes* may be passing on a stale or unrepresentative fixture — re-run it against the real artefact before trusting it.

20. **A cached config/env loader makes "change the setting and retry" a silent no-op — verify the setting can actually be re-read before you tell the user to change it.** A loader that reads its file once, copies the values into the process environment, and then refuses to overwrite them will ignore every later edit to keys it already loaded; only brand-new keys appear. Measured: a backend selector edited from `manual` to `heuristic` kept returning `manual` even after an explicit forced reload. The user-visible symptom is the worst kind — the setting looks applied, the feature silently keeps its old behaviour, and nothing errors. Rules: (a) detect file changes (mtime + size is enough) and re-read when they differ, so a call costs a few `stat()`s and no parsing; (b) when re-reading, replace only the values *this loader injected* — track ownership by the **exact value injected**, not by key name. Tracking by name is the subtle bug: a genuine process-environment value set *after* a file load looks like "ours" and gets clobbered, silently inverting the documented precedence. The check is `os.environ.get(k) != injected[k]` → something else owns it, leave it alone; (c) unset keys that were removed from the file, under the same ownership test, or a deleted setting lingers forever; (d) make the switch reachable from the entry point users actually run — a runtime toggle only helps if the long-lived process re-reads it per operation, so rebuild the derived object at call time rather than at registration/import. Two corollaries that bite in the same pass: **a refresh that re-reads config will override an explicitly injected dependency** — anything set programmatically (a test double, a host-provided backend) needs a "pinned" flag the refresh respects, or the refresh silently discards it; and **tests must be isolated from the developer's real config/env file**, because once the loader re-reads per call, a local `.env` changes test outcomes. Point the loader at a non-existent path in a suite-wide fixture and reset its caches, rather than fixing it per test.

21. **A pipeline that runs, returns success, and processes a fraction of its input: check the plumbing before the logic.** Two shapes recur, and neither is a crash, a lint error, or a test failure — the function is called, returns a valid result, and the result is empty or partial for a reason nobody logged.

    **(a) A parameter accepted and never forwarded.** The signature promises an input, the body ignores it, and the caller cannot tell. The tell is a conditional whose branches are identical — `for item in history if context is None else history` — which is a placeholder someone meant to differentiate and never did. The parameter is still *syntactically used*, so no linter flags it. Measured: a turn being processed was never passed to the extractor, so extraction ran over the conversation history instead; and separately, a hook declared `recent_turns`, a name the host never sends, so a `None` fell through to a fallback list that was initialised empty and never appended to. Rule: for every parameter of a function that produces output, confirm it reaches the thing that consumes it — grep the body for the name, and when a default or fallback exists, ask what fills it. A fallback that is never populated is worse than a required parameter, because it converts a wiring bug into silently degraded behaviour.

    **(b) A dedupe/idempotency key coarser than the unit of work.** A reprocessing guard keyed on the *container* rather than the *item* latches after the first item and silently discards every later one. Measured: an extraction guard keyed on `(namespace, session_id, extractor_version)` was written on the first call, so a session's second and third turns returned nothing at all while the first worked — a feature that appears to function if you test it once. Rules: the key's granularity must match what you are deduplicating (add a content/turn fingerprint, not just the container id); the check and the write must happen under one lock or two concurrent callers both pass; and a guard that suppresses work must **log at debug what it suppressed** — a silent early-return is indistinguishable from "nothing to do". Test the guard with a *second distinct item in the same container*, which is exactly the case a session-scoped key passes over.

    Corollary: when a function both filters input and forwards it, assert the forwarding, not just the filtering. `assert result == []` passes for a pipeline that correctly rejected bad input *and* for one that dropped everything, so a rejection test needs a paired positive case that proves a good input survives the same path.

22. **A derived value can be well-formed and mean the OPPOSITE of its source — probe a polarity pair, because a coverage count cannot see an inversion.** For any step that labels, normalises or rewrites a value, presence is not correctness. Measured: a preference extractor matched `prefer|always|never` in **one** capture group and prefixed every match with `"user prefers "`, so `never push to master` was stored as `user prefers push to master` — a prohibition recorded as its own opposite. The coverage table was 16/16 correct and every output was a plausible sentence; only feeding a positive and a negative form side by side exposes it. Rules: (a) when a pattern has alternation, confirm the output distinguishes the alternatives — a single capture group discards the token that carries the meaning, and a fixed prefix applied to all of them flattens them; (b) assert the derived value *preserves* the source's polarity (`"prefers" not in out` for a negative input), not merely that something was produced; (c) this class is worst in memory, policy, permission and summary paths, where the wrong value is quietly authoritative and steers later behaviour — an inverted rule is more dangerous than a missing one, which at least fails visibly. See probe 6 in `scripts/probe_invariants.py`.

23. **A command surface needs a structural guard, not just per-command tests — the command nobody tests is where the undefined-argument bug hides.** A handler that reads an argument its parser never defines raises on *every* invocation, and no per-command test exists for the command you did not think about. Measured: a subcommand read three arguments its subparser never declared, so it crashed unconditionally — and it was the audit/preview path the spec explicitly required, which nothing exercised. Rules: (a) walk the parser's choices and, for each, parse with placeholder values and assert every `args.X` the handler's source references exists on the resulting namespace; (b) **placeholder values must satisfy each positional's type** — an `int` argument needs `"1"`, not `"id"`, or the guard fails on your own test rather than on the bug; (c) the same structural shape applies to any registry of entry points (HTTP routes, tool registrations, job handlers): assert each registered name is reachable and its declared inputs are supplied. This is coverage of the *surface*, which enumerating the commands you changed can never give you.

24. **A long-lived process keeps running the code it loaded at startup — a missing log line means stale code, not a broken change.** Editing files does not reload a running gateway, desktop app or CLI session: it called the registration/import path once and executes that version until restarted. The symptom is an *absent* line, never an error, so the instinct to debug the feature is exactly wrong — it was never loaded. Rules: (a) before claiming a runtime change is live, compare the newest registration/log line's timestamp against the process start time (`ps -o lstart= -p <pid>`); a process started before the edit is running the old code regardless of what is on disk; (b) an absent registration line across **every** boot in the log means no process has ever loaded that version; (c) state the distinction explicitly — "verified offline and through the installed shim, not yet running in the live process" — because an offline probe reported as a live success is a false claim the user will immediately test against; (d) restarting the user's running session is a destructive action needing permission, not a cleanup step. This applies to any supervised/daemonised component (plugin hosts, workers, servers), not just the one that exposed it. **Corollary — do not read your own output back as evidence:** an agent that probes a hook by printing its result has that output captured into the session transcript, so a later grep of the log finds the marker string and reads it as proof the hook fired. Before citing a log hit, ask whether your own session wrote it. Log a content-free fire marker in the code instead (counts and ids, never content), placed before any early return so "fired and returned early" is distinguishable from "never fired".

25. **Never invent a mechanism for a failure you have not diagnosed, and never assert an action you did not take.** Both read as findings but are fabrications, and both cost more trust than the original failure.

    - **An invented cause.** When the real cause is not yet known, saying so is the correct answer. A plausible-sounding mechanism ("the test pointed at a stale database", "the environment did not match the worktree") is worse than "I do not know yet": the user may act on it, and it delays the actual diagnosis. Diagnose with a probe, or report the observed state and stop. If you cannot name the evidence for a claim, it is a guess — label it as one or drop it.
    - **An action you did not perform.** "I restarted it" when the restart was blocked, timed out, or never ran is a false claim the user will immediately test. Report what the tool actually returned. A blocked or timed-out command is a result to state, not a step to narrate as done.

    Reporting a blocker honestly always beats a confident invention, and the cost of the invention is not just the wrong answer — it is that every later claim from the same session gets re-checked.

26. **A blanket destructive operation over a set the user described as uniform — verify it IS uniform before executing.** "Reject/delete/close all N of them" is a statement about a count, not about the members, and a review queue, candidate list or batch of flagged rows is rarely homogeneous. Measured: 41 of 44 queued candidates were junk fragments of the agent's own prose, but 3 were a genuine standing instruction the user had stated — executing the request literally would have destroyed a real rule. Rules: (a) group the set by provenance/trust/source and read the small group before acting on the large one; (b) when a genuine minority exists, keep it and say so, rather than reporting "rejected all N" — the instruction was aimed at the noise, not at the user's own words; (c) prefer the reversible operation (mark rejected, never hard-delete) and confirm the store's policy permits undo.

27. **A pre-commit hook is the same gate CI runs — run its exact command before committing, and fix the failure instead of bypassing it.** The hook's `entry:` is the gate; a hand-rolled `mypy <changed_files>` is not. Measured: the hook ran `mypy api core retrieval reasoning ingestion …` — a fixed package list — while the changed code lived in a package (`fetching/`) the hook reaches only transitively through another package's imports, so a targeted check passed and the commit still failed. Rules: (a) read `entry:` in `.pre-commit-config.yaml` and run that command verbatim once before staging; (b) a blocked hook means NO commit — pre-commit stashes and restores the tree around the hook, so confirm with `git log -1` rather than assuming the commit landed; (c) the gate checks the whole working tree, not your diff, so its errors are often another author's uncommitted work — report them with file:line and the minimal edit for each and let the user choose, never fix their code silently; (d) never `--no-verify` or `SKIP=<hook>` a gate that CI re-runs (`grep -rl <hook> .github/workflows/`): that converts a local red into a pushed red and hides the decision from the user. Corollary: when the gate fails on something unrelated to your change, the honest hand-off names the errors, their location, and the one-line fix each needs — and a user asked "fix them and push?" answers a question they can act on, where "the commit is blocked" does not.

See `references/behaviour-diff-old-vs-new.md` for the concrete recipe that produces the old-vs-new evidence principles 11 and 12 require, `references/safe-bulk-edits.md` for running a mechanical rewrite across many files without corrupting them, and `scripts/probe_invariants.py` for the probe shapes that establish whether a pipeline actually enforces its stated guarantees (principles 18 and 19).

## Implementation Workflow

### Phase 1: Understand

```
1. Read the relevant source files (read_file, search_files)
2. Understand the architecture before changing anything
3. Trace symbols to their definitions and usages
4. Identify the root cause, not just the symptom
```

### Phase 2: Plan

```
1. Use todo_list to break work into atomic steps
2. For complex tasks, write a plan to .hermes/plans/ or docs/plans/
3. Identify which files need changes
4. Identify which tests need updating
5. Check if documentation needs updating
```

### Phase 3: Implement

```
1. Make minimal changes — fix root cause, not symptoms
2. Use str_replace/patch for targeted edits
3. Match existing code style and conventions
4. Add imports/dependencies only if needed
5. No drive-by refactors or renames
```

### Phase 4: Verify

```
1. Run relevant tests: pytest tests/test_<area>.py -v
2. If the suite already has failures, diff the failure SET against a stashed baseline (principle 7) — never trust the summary count
3. Run the repo's OWN gate command, not a hand-rolled one — read `entry:` in
   .pre-commit-config.yaml and run it verbatim (principle 27)
4. Run linting: ruff check <changed_files>
- Verify the actual runtime behavior
6. Fix any issues found

## Verification Gate

```text
1. Run relevant tests: pytest tests/test_<area>.py -v
2. If the suite already has failures, diff the failure SET against a stashed
   baseline (principle 7) — never trust the summary count
3. Run the repo's OWN gate command, not a hand-rolled one — read `entry:` in
   .pre-commit-config.yaml and run it verbatim (principle 27)
4. Run linting: ruff check <changed_files>
5. Verify the actual runtime behavior
6. If a UI or dashboard component changed, open the real page in a browser and
   read what it rendered — do not rely on the plugin discovery listing or on a
   console error being absent as evidence
7. Fix any issues found
```

### The render gate (new rule)

A "discovered in the plugin list", "API reachable (401 for anonymous curl)",
"green suite", or "no console error" is not proof the UI paints anything:

(a) For every dashboard/UI component you touched, open the real URL in a browser
    and read `document.getElementById('root').childElementCount` and the visible
    text — a tab that renders zero children with zero console errors is a null
    dereference or a silently-aborting render, not a success.
(b) The error may be invisible: some hosts (and a `useState(null)` initial value
    driving a JSX tree) abort a subtree without surfacing anything to the
    console. When the DOM is empty and no error appeared, treat "empty body" as
    the failure itself, not the symptom.
(c) Never hand-wave a negative as a positive. A claim like "discovered + API
    reachable" that later fails on-render must be reported as failed, with the
    render observation as the reason — not as a partial success.
(d) One blank page can have TWO independent causes, so a fix is not proof the
    tab now paints: re-run the render check after every fix. A null dereference
    and a third-party component-contract mismatch produce the identical symptom
    (zero children, empty console) and the second only becomes visible once the
    first is gone — so "I fixed the crash" and "it renders" are separate claims,
    and only the second one is the deliverable.
(e) When a sibling component renders and yours does not, the fault is yours —
    use a working peer as the control. Then capture the real exception with an
    error trap installed BEFORE app code runs (a `console.error`/`error`
    listener, or CDP `Page.addScriptToEvaluateOnNewDocument`), because React
    swallows a render throw and an empty console is not evidence of success. An
    exception naming the HOST's own bundle means a component-contract problem,
    not your logic — check the host's component source and whether the host's own
    pages even use that component before assuming a familiar prop shape.

### The test suite is a claim, not evidence of correctness

(14/16 above) A green suite over a defect that was written around is not evidence
the behaviour is correct, and not a prescient guard. Before trusting a suite
over code you have just proven broken, enumerate the tests touching the changed
behaviour and ask what each would still pass if the defect were still present.
If one fails after the fix, do not reach for the assertion first: decide whether
the test's *intent* is still valid. If it is, fix the fixture so it exercises the
real path; if it is not, the test was asserting the bug and must be rewritten.

### The test suite can encode a deliberate rule you misreported as a bug

(13 above) An exclusion you did not expect may be a deliberate invariant, not a
defect. Before escalating surprising behaviour, grep the test tree for the rule
that encodes it — "missing data may be correctly missing" and "pinned rows are
excluded from search" are exactly this shape. One grep of the tests prevents a
false-defect claim.
```

### Phase 5: Document

```
1. Update CHANGELOG.md under [Unreleased]
2. Update affected docs (diagrams, manuals, README)
3. Update tests if behavior changed
4. Commit with clear conventional message
5. Stage by layer and commit in focused commits (`git add <paths>`, never
   `git add -A`) — match the repo's own commit history; one mega-commit mixes a
   parser change, an ingestion fix and doc edits into an unreviewable diff
6. Name a known-failing test in the commit body when you commit it deliberately,
   so the next reader knows it was a decision rather than an oversight
7. After pushing, verify the push landed: `git log -1 origin/main` equals HEAD
   and `git log origin/main..HEAD` is empty — a rejected or hook-blocked push
   otherwise reads as success
```

## Agent Definitions (`.agents/` TypeScript)

Adapted from freebuff's `AgentDefinition` interface. These are reusable across projects.

### Agent Definition Pattern

Each agent is a TypeScript file exporting an `AgentDefinition` with:
- `id` — kebab-case identifier (e.g. `parser-debugger`)
- `displayName` — human-readable name
- `model` — OpenRouter model ID
- `toolNames` — subset of built-in tools the agent can use
- `spawnerPrompt` — when/why to spawn this agent (used by parent agents)
- `instructionsPrompt` — inserted after each user input (shapes behavior)
- `systemPrompt` — background context
- `reasoningOptions` — `{ effort: 'high' | 'medium' | 'low' }`

### Generic Agents

| Agent | Spawn when | Tools |
|-------|-----------|-------|
| `parser-debugger` | Parser JSON output malformed, containers not splitting, metadata wrong, OCR garbled | read_files, write_file, str_replace, run_terminal_command, code_search, find_files, web_search |
| `corpus-auditor` | Auditing corpus quality, checking JSON validity, verifying metadata completeness | read_files, run_terminal_command, code_search, find_files, web_search |
| `search-debugger` | Search returns no results, citations wrong, dense/sparse retrieval fails | read_files, write_file, str_replace, run_terminal_command, code_search, find_files, web_search |
| `code-reviewer` | Reviewing changes before commit, checking security issues, verifying code quality | read_files, code_search, find_files |
| `thinker` | Complex multi-step task, architectural decision needed, multiple approaches possible | read_files, code_search, think_deeply |

### Project-Specific Agents

When creating agents for a specific project:
1. Copy the generic agent pattern
2. Replace `instructionsPrompt` with project-specific file paths, commands, and conventions
3. Keep `spawnerPrompt` generic (it describes WHEN to spawn, not project specifics)
4. Remove any hardcoded paths from the agent definition — reference them indirectly

See `references/agent-definitions.md` for full agent definition templates.

Before loading ANY `.agents/` definition from a directory, verify that the directory is trusted.

### Trust Store

Location: `~/.config/agents/trusted-agent-dirs.json`

```json
{
  "_schema_version": 1,
  "trusted_agent_dirs": {
    "/home/user/project": "2026-10-12"
  }
}
```

### Gate Procedure

```
1. Resolve the target directory to an absolute path (realpath, no symlink tricks).
2. Read ~/.config/agents/trusted-agent-dirs.json.
3. If the directory is present under "trusted_agent_dirs" -> proceed to load.
4. If absent:
   a. If a TTY is attached -> prompt the user:
        "Load .agents/ definitions from <path>? This directory is not in the trust
         store. (y/N)"
      - On "y": record { "<path>": "<today YYYY-MM-DD>" } in the store, then load.
      - On anything else: skip the directory, continue the task.
   b. If NO TTY (CI, piped stdin, non-interactive shell) -> SKIP with a warning:
        "WARN: untrusted .agents/ dir <path> — skipping (no TTY to confirm)."
      Never auto-trust in a non-interactive context.
5. Trust is per-directory and sticky: once trusted, later runs skip the prompt.
   Re-prompt only if the directory changes owner or the store entry is removed.
```

## Task Completed Signal

When a multi-step task finishes, emit a structured completion summary:

```
## Task Completed

**Accomplished**
- <outcome 1 — what changed, in plain language>

**Files Changed**
- `path/to/file.ext` — <one-line description of the change>

**Verification**
- `<command run>` → <result, e.g. "12 passed", "exit 0", "clean">

**Known Limitations / Follow-ups**
- <what is NOT done, edge cases, deferred work>

**Next Steps**
- <the single most useful next action, if applicable>
```

## Suggest Followups

After delivering the completion summary, proactively suggest 2–3 related followup actions.

| Task type | Common followups |
|---|---|
| Bug fix | Add a regression test; search for the same bug pattern elsewhere; update CHANGELOG |
| New feature | Write/expand tests; add docs; wire into CLI/API surface; add a usage example |
| Refactor | Run full suite; benchmark for perf regressions; update architecture docs |
| Parser / ingestion change | Re-run the affected corpus sample; validate output schema; check downstream consumers |
| Search / retrieval change | Re-run retrieval eval; spot-check ranking quality; measure latency |
| Docs-only | Verify links render; check code snippets still run; sync translated copies |
| Config / infra | Validate on a clean checkout; document the new knob; add a smoke test |

## Common Anti-Patterns

1. **Don't monkeypatch** — Fix root causes only
2. **Don't break working paths** — Minimal diff, test before/after
3. **Don't skip verification** — Run tests after every change
4. **Don't commit blindly** — Review the diff first
5. **Don't ignore type errors** — Run mypy before committing
6. **Don't forget docs** — Update CHANGELOG and affected docs

## Verification Checklist

Before handing over any change:

- [ ] Code compiles (python -m py_compile)
- [ ] Tests pass (pytest)
- [ ] Type checks pass (mypy)
- [ ] No linting issues (ruff)
- [ ] CHANGELOG.md updated
- [ ] Affected docs updated (including HTML manuals, .env.example, admin config manifest)
- [ ] No debugging print statements left
- [ ] No unused imports
- [ ] Commit message follows convention
