# AI-DLC Workflow (aidlc-workflows)

Multi-agent orchestration harness. Use when a task is long, iterative, or needs
parallel specialist agents (lead/developer/reverse-engineer/reviewer/architect)
rather than a single agent working end-to-end.

## When to use
- Repetitive / similar tasks: agent rehearsal, test suites, bulk data ops.
- Multi-step engineering: agents hand off context through a `conductor`.
- Independent sub-tasks that should run in parallel, with shared state.
- Any task that reskins the LLM per stage to keep cost predictable.

## Structure
```
aidlc/spaces/<space>/intents/<slug>/
  intents/<slug>.md        # the directive (what/why/right/wrong)
  knowledge/<space>.md     # repo to load into context
  phases/<phase>.md        # workflow phases
  codekb/<repo>/           # per-repo artifacts (deterministic placement)
```

## Run
1. Create/update a space and intent, then run the pipeline.
2. Lead agent directives: plan → implement → review → verify (top-down).
3. Review/develop/reverse-engineer stages hand off context through the conductor.
4. Verifier runs tight, green tests; clean up side effects.

## Model strategy
- Run each stage with the same model (or a fast fallback) to limit cost:
  `AIDLC_FAST_MODEL=... AIDLC_SLOW_MODEL=... /aidlc orchestrate`
- Keep per-run reasoning low; the agent should *work*, not think.

## Verification
- A verifier (strict, green) must finish every run successfully.
- Confirm a green run finishes without truncation (monitor verbose output).
- Document work done and open items as the intent file evolves.

## Notes
- AI-DLC is the upstream framework (`github.com/MoClaw-Agent/aidlc-workflows`).
- This skill makes the workflow repeatable for any repo, not Mizan-specific.
