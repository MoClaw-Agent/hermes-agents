# Verification gate — never hand over unexecuted code

Ship nothing you have not run. Every defect that reached the user as a runtime
traceback was one a local execution would have caught first: a name imported as
a module then called as a function, a cell that ran before the cell defining its
server, a `global` declared but never assigned. The user found all of them; each
cost a round trip.

Order of verification, cheapest first:

1. **Static name check** — every free name a unit reads is bound by an earlier
   unit, a local binding, or a builtin. Catches ordering bugs with no execution.
   `scripts/notebook_local_harness.py <nb> --deps` does this for notebooks;
   `--all` then execs every cell into ONE shared namespace, which is the only
   way a cross-cell dependency is actually exercised.
2. **Execute it** — run the real code, not a description of it.
3. **Integration** — drive the real entry point (real HTTP server, real
   filesystem), stubbing only what is genuinely external.

Establishing the baseline:

- **Compare by swapping the file in place and re-running in the repo root.** A
  `git worktree` copy carries no corpus data, so it reports a pile of spurious
  errors and a failure count that looks like a regression when it is setup.
  Swap with `cp` to a side path plus `git show <rev>:<path> > <path>`, run, then
  `cp` back — this also respects a standing ban on destructive git commands.
- **Re-measure the baseline when it is quoted.** A remembered "90 failures"
  baseline drifts as commits land and turns into phantom regressions. If the
  failure count moves, swap the file and re-run rather than reasoning about the
  delta.
- **A detector's first hits are not findings.** Validate it against content you
  know is good before reporting what it flagged. A year-shaped heuristic fired
  on Journal Officiel issue numbers (`الجريدة الرسمية عدد 5997`) and page cites
  (`ص 1456`), which are legitimately large; every hit was noise. Retract it.

Rules:

- **A fake that stands in for the thing under test hides the defect it was
  written to find.** Faking a module a function binds internally lets the real
  "never assigned" bug pass green. Fake the *dependency*; assert the *wiring*.
- **Every widened filter needs a negative case.** Broadening a citation
  matcher to a bare demonstrative rejected real articles whose body opened with
  the same word; only a test asserting the legitimate sibling saved it. A test
  that checks only the happy path will happily ratify an over-broad rule.
- **Two real defects stack.** Fixing the visible one did not unblock the user
  because another sat underneath. When a fix does not change the observed
  symptom, keep digging rather than declaring victory.
- **Never report a test as passing without its output in hand.**
- **Set `global x` and then assign it on every path**, including early returns.
  Binding it only after an early `return` leaves it `None` for the process
  lifetime, and it only surfaces once a cached/already-loaded branch is hit.

## Ingestion failure modes worth encoding

- **Blocked or absent model output must raise, not return.** Greedy decoding on
  a dense page can loop; the service returns HTTP 200 with the loop. Measure the
  share of output lines that are not repeats; below a threshold retry once at a
  lower budget, then raise so the page is recorded lost.
- **Repetition penalty, not n-gram blocking**, for legal text: Arabic legal
  prose legitimately repeats formulas and citation phrases, and banning n-grams
  corrupts real citations.
- **A generation budget of 0 is a landmine.** "No limit" surfaced as a CUDA OOM
  later at full resolution. Reject a non-positive cap explicitly.
- **Classify reference text before ingesting it.** A repeal citation
  (`المادة N من هذا القانون`) whose N equals its own declared article number is
  a cross-reference, not an article. Article numbers legitimately repeat across
  chapters, so dedup must be container-scoped.
- **Strip diacritics and tatweel before header matching.** OCR emits
  `المادَة`/`المـادة`; the keyword then fails to match and the whole provision
  is absorbed into its neighbour. Delete the marks, never replace them with a
  space, which splits the word.
- **Digit classes must span every range OCR emits.** `[٠-٩0-9]` silently
  ignores the Persian forms U+06F0-06F9, so a fully Persian-digit header reads
  as having no number. When narrowing or widening a class, assert both ranges
  explicitly and re-check that ASCII digits still match.
- **When repairing RTL token order, place tokens where they belong.** A
  digit-first header (`21 المادة ينتخب`) must become `المادة 21 ينتخب`; putting
  the digits at the end yields a line with no number after the keyword and
  discards every such header. On one 76-page legal document that single
  misplacement cost 114 of 255 article nodes — and the symptom looked like a
  regression from an unrelated filter.
- **Separate a citation marker from a legal one by its noun, not its particle.**
  `من هذا القانون` is a cross-reference; `من هذا التاريخ تبدأ` is a real
  article opening. Only the instrument noun separates them, so match on that
  rather than on the demonstrative alone.
- **Persist the text the parse actually used.** If a richer OCR pass overrides a
  cheaper one for the structure but is not written down, the corpus cannot be
  audited or reproduced, and the cache flag points at the wrong text.

## Artifact expectations

- Page text must live on disk in the shape the consumer reads, and the consumer
  must prefer it over fresh inference. OCR once, parse later — this makes a
  stalled backend a non-event and the parse reproducible.
- Empty and failed pages must be recorded, not skipped: an absent file and a
  failed page look identical otherwise, and a resume loop re-attempts forever
  without them.
- Provenance in the output: which route produced the structure, and where its
  text is cached.