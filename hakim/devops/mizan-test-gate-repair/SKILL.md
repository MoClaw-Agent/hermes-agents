---
name: mizan-test-gate-repair
description: "Fix Mizan's red CI test gates."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [mizan, testing, ci, gates, bare-except, mypy]
    related_skills: [mizan-legal-platform-debugging, mizan-repo-delivery]
---

# Mizan Test-Gate Repair

> The project's workflow docs live in `doc/workflow/` — `RULES.md` is the standing contract. Read them before changing code.

## When to Use

- The red gates are **policy gates** (bare-except walker, god-file LOC, doc
  sections, CHANGELOG top entry, `.env` hygiene) rather than runtime bugs.
- Migrating bare `except Exception` to narrow tuples and the count pins must move.
- A suite is red and the task is to make it green by fixing causes, not mocking.

## Standing rules

- **Fix the real cause; re-pin the gate to measured truth.** Do not loosen a gate to
  make it pass. A gate that asserts a wrong number is updated to the correct
  measured number with a comment explaining the change — never deleted.
- **Prefer production fixes over test-only mocks** (the user's SOTA preference). A
  test that mocks heavy work is acceptable only when the test's intent is
  orthogonal to the failure.
- **Verify before claiming green.** Run the specific gate file, then the full
  suite, then mypy over the gate's scope. Report only what was executed.
- **Before trusting a harness's verdict, prove the harness can distinguish pass
  from fail.** A runner that reports a file FAILING when you watched that same
  file pass minutes earlier is measuring its own defect, not the code's.
  Sanity-check it against one case you verified by hand BEFORE quoting its
  totals — a harness bug reported as a suite failure costs an hour of phantom
  debugging and, worse, a wrong conclusion about the code. The failure mode
  that bites: a log filter that matches a substring of a PASSING run's output
  (a warm-up line containing the word "failed"), so every file is counted as
  failed and the real signal is buried under a large false count. A large,
  uniform failure count is a smell — check the harness before the code.
- **Two mypy scopes exist — know which one you are running.** The pre-commit
  hook covers the **core packages only** (`api core retrieval reasoning
  ingestion graph ontology query billing services`). The CI job
  (`.github/workflows/mypy.yml`) runs core PLUS `fetching scripts tools ner
  evaluation` — a materially larger file set. So a core-scope run coming back
  clean does NOT mean the CI gate is green, and a "mypy clean" claim in a
  CHANGELOG entry is only true of the scope it names. Before reporting a type
  error as in-scope or out-of-scope, reproduce it under the scope that actually
  gates: run the CI package list verbatim. Errors in `scripts/` or `tools/` fail
  CI even though the pre-commit hook never sees them — report them, do not
  treat them as out of scope.

## Workflow

1. Triage: run the full suite bucketed by file, separate real causes from noise,
   and identify which gates are policy gates vs runtime bugs.
2. For each policy gate, find the production cause (a missing wiring, a lost
   counter, a stale fixture, an oversized file) and fix it.
3. Re-pin every gate that encodes the old measurement — see **Pin ratcheting**.
4. Verify: the gate file, then the full suite, then mypy.

## Diagnosing a red CI gate (see references/ci-gate-diagnosis.md)

- **Establish whether the gate EVER passed** before blaming the current change:
  `gh run list --workflow="<workflow name>" --limit 100 --json conclusion,createdAt`
  then count conclusions. A workflow that has failed on every single run since
  it was created is a mis-configured gate, not a regression from your commit —
  and "the last run failed" is not evidence of anything about your change.
- **Read the job log, not the run summary.** `gh run view --log-failed` often
  returns empty. Use
  `gh api repos/<owner>/<repo>/actions/jobs/<job_id>/logs | strings` (get
  `<job_id>` from `gh api repos/<owner>/<repo>/actions/runs/<run_id>/jobs`).
  The `strings` step matters — the raw payload is binary-ish and a text filter
  on it reports "binary file matches" instead of showing the lines.
- **`pip install -e .` installs NO runtime dependencies** — `pyproject.toml`
  declares `dependencies = []` on purpose (runtime deps live in
  `requirements.txt`). Any CI workflow whose script imports `core.settings`
  therefore dies with `No module named 'pydantic'` and exit code 2
  ("load failure"), even though the same script passes locally. The fix is in
  the workflow: install `pydantic pydantic-settings` explicitly, or install the
  requirements variant the script needs. Verify the local equivalent passes
  first — a green local run plus a red CI run with a load-failure exit code is
  a workflow dependency bug, not a drift defect.
- **Distinguish exit code 1 (drift found) from exit code 2 (load failure) in
  the field-drift gate.** They mean different things: 1 is a real field gap to
  fix in `core/settings/*`, 2 is the gate not being able to load Settings at
  all and will pass as soon as its dependencies exist.

## Patterns (depth in references/test-gate-repair.md)

- **Bound a sync lookup in an async endpoint** with a daemon thread +
  `join(timeout)`. Never a `ThreadPoolExecutor` `with` block — its
  `shutdown(wait=True)` blocks on the abandoned lookup and defeats the
  timeout. **Caveat:** bounding is NOT enough when the abandoned work loads a
  shared resource the request path also needs (e.g. an ML model) — the
  abandoned thread still contends with the pipeline and the request stalls
  anyway. Check what the abandoned thread loads before reaching for a bound;
  the real fix is failing fast at the source so the heavy work never starts.
- **Narrow-tuple selection for bare-except migration**: include every exception
  type the message-based discriminator's callers/tests can raise, not just the
  production SDK exception.
- **Pin ratcheting**: migrating bare excepts changes the walker count; re-pin
  `BASELINE_COUNT`, `X1_BASELINE_FLOOR`, `WALKER_COUNT_PINS`, and every per-PR
  hard-coded count in one commit. The ripple is WIDE — after a count change,
  grep the old number across ALL of `tests/` (many `test_pr_*` files pin it,
  not just the walker file); the convention is to repin to current measured
  truth, never freeze a historical value. The walker counts **bare-baseclass**
  excepts (`except Exception`, `except:`), NOT all `except` handlers —
  counting every `ast.ExceptHandler` gives a wrong delta and sends you hunting
  phantom drift.
- **Module-global test pollution**: an autouse snapshot/restore fixture for
  `reload(core.settings)` singletons and module-level status dicts.
- **Isolating a request-path stall**: when an endpoint times out in a test env,
  disable the suspected component via its env/settings toggle and re-measure —
  this cleanly separates the component's cold-start cost from the request. A
  cache backend that lazily loads ML models in the request path is a classic
  stall; measure its standalone timing (and whether its backend is even up)
  before and after any bound.
- **Fixture/doc/env repairs**: real PNGs when production decodes with PIL; golden
  fixtures cover every item; god files pinned in `ALLOWLIST`; `.env` dead keys
  removed and paths matched to canonical suffix; `doc/MANUAL.md` versioned
  sections and a `vX.Y.Z` CHANGELOG top entry.
- **CI mypy: Qdrant `field_schema` type mismatches**: Qdrant's
  `create_payload_index` expects `qmodels` params objects
  (`IntegerIndexParams`, `FloatIndexParams`, `KeywordIndexParams`) — NOT
  string values like `"integer"` or `"keyword"`. Replace all string schemas
  with proper params objects. Check both `retrieval/qdrant/manager.py` and
  `retrieval/dual_collection/manager.py`.
- **CI mypy: stale script references**: When a symbol is renamed (e.g.
  `_qari_transcribe_png` → `_vision_transcribe_png`), every script that
  imports it breaks with `attr-defined`. Grep the old name across `scripts/`
  and update all references. Same for renamed settings
  (`QARI_OCR_BASE_URL` → `VISION_OCR_BASE_URL`, etc.).
- **CI mypy: missing library stubs**: Packages without PyPI type stubs
  (`limits`, `tiktoken`, `ollama`, `playwright`, `docling`, `PIL`,
  `pdf2image`, `slowapi`) cause `import-not-found` errors. Fix: add
  `# type: ignore[import-not-found]` to each import line. For multi-line
  parenthesized imports, place the comment after the closing `)`, not
  after the opening `(`. Grep the test tree for the package name first —
  there may be multiple import sites across api/, core/, retrieval/,
  ingestion/, and fetching/.

## References

- `references/test-gate-repair.md` — the full pattern set with code samples.
- `references/ci-gate-diagnosis.md` — per-workflow status sweep, “has this gate ever been green?”, reading a failing job's log, the two mypy scopes, and a table of common CI failure classes.
