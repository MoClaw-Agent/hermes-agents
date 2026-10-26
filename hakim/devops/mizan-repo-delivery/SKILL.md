---
name: mizan-repo-delivery
description: "Use when committing or pushing Mizan changes."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [mizan, git, commit, push, ci, pre-commit, changelog]
    related_skills: [arabic-legal-structure-parser, mizan-legal-platform-debugging, github-pr-workflow]
---

# Mizan Repo Delivery

## When to Use

- The user says "commit and push", "push it", "ship it" for `/home/mohammed/Mizan`
- The user asks "what's left open", "what's outstanding", "is anything undelivered" — a delivery-completeness audit
- A commit was refused by a pre-commit hook
- A working tree mixes your change with the user's in-flight work and you must decide what goes in
- Documentation has to be updated as part of the push

## Pre-flight (before staging anything)

1. `git status --short` and `git branch -vv`. The tree is normally full of the user's in-flight work — dozens of modified files plus untracked tests, scripts and audit docs are routine here, not a sign something is wrong.
2. Check whether a parse/ingestion job is writing right now: `ps aux | grep "[f]etching.adala.parser"`. Corpus JSONs and caches are gitignored so a running job usually does not touch the commit, but `data/corpus/reference/corpus_index.json` IS tracked — commit it knowingly or leave it out, and never stop the job (stopping runs needs explicit permission).
3. `.env` is gitignored — confirm with `git check-ignore -v .env` and never stage it. Before adding untracked files, grep them for secret-like strings and READ the matches: config metadata (`"is_secret": false`), `os.environ.get("SOME_TOKEN", "")`, and a local variable named `token` all trip the grep and are all fine.
4. Size-check the untracked files (`du -h`); anything over a few hundred KB is usually not meant for git.

## The docs rule (standing user requirement)

Before every push to origin main, check whether documentation needs updating — `doc/`, the manuals (`doc/mizan-manual*.html`), every `.md`, diagrams, changelogs, README — and update it in the SAME commit. In practice here:

- `CHANGELOG.md` is the behavioural record. The TOP entry must be the latest versioned release (`## [vX.Y.Z]`, matching `pyproject.toml`) — a doc gate enforces this by name. When the tree holds only accumulated `[Unreleased]` sections, convert the top one into the versioned release entry: keep its prose under a `### <topic>` sub-heading and add a lead line noting it consolidates the work since the last versioned entry. Prose first, then a `Changed files:` bulleted list. State what changed, why, and the measured before/after numbers; name the other topics the same commit carries when they share a wave.
- Historical changelog and audit entries are records of their time — do not rewrite them to match current behaviour.
- `doc/MANUAL.md` carries per-arc versioned sections that doc gates check by name: a release-record section per arc (`## v1.109.5 – v1.109.9 — U-3 Chunk Marker Arc`) with a per-version table that references the scripts and Makefile targets it introduced, and a closeout section when an arc lands (`## v1.112.0 — X-1 closeout`). These are operator-facing records; a gate that checks them by name will fail on a missing header even when the substance exists elsewhere.
- Check the CLAIM, not just the file list: grep the docs for the behaviour you changed (e.g. `grep -rniE "num_articles_detected|flat_articles|chunk_kind" doc/ README.md`). Manuals that only describe user-facing behaviour often need nothing; say so explicitly when you concluded no doc change was needed.
- **The operator manual is GENERATED — edit the template, never the built HTML.** `doc/mizan-manual*.html` and `api/static/mizan-manual*.html` are built by `python doc/build_manual.py --all --deploy` from `doc/manual-template.html` / `-fr.html` / `-ar.html`. A hand edit to the built HTML is silently destroyed by the next build, and the version label comes from `pyproject.toml` at build time. Edit the template, then rebuild and deploy, then commit the templates AND the generated files together. The repo's pattern is a separate follow-up commit for the release label (e.g. `docs: release label v1.114.0, ...`).
- The `pip-audit` pre-commit hook fires on ANY `pyproject.toml` change, so a version bump alone triggers it. It audits the *requirement manifests*, not `pyproject.toml`; if the CVE set is pre-existing and the commit changes no dependency pin, the repo's documented bypass applies: `SKIP=pip-audit git commit ...` (the bypass is written in `.pre-commit-config.yaml`). Say so in the commit message and in the report — do not silently skip a security gate, and do NOT bundle a dependency upgrade into an unrelated wave.

## The workflow documents (doc/workflow/)

Six planning/tracking documents live in `doc/workflow/`, kept current as part of
the agent's workflow — not a one-off artifact:

| File | Carries |
|---|---|
| `PRD.md` | what Mizan is, for whom, the definition of done |
| `ARCHITECTURE.md` | stack, folders, data flow (consolidated — the old `doc/ARCHITECTURE.md` is now a pointer to it) |
| `DESIGN.md` | the design tokens read from `api/static/mizan_base.css` |
| `RULES.md` | coding style and what the agent must never do |
| `TASKS.md` | the open work, one small step per item |
| `PROGRESS.md` | what is done, what broke, what is next |

- **Update them in the same wave as the work they describe.** `PROGRESS.md` is the
  agent's changelog; a fix that is not recorded there is undocumented no matter
  how many commits carry it. Move a `TASKS.md` item to *Done* only when it is
  verified, and keep each item small enough to finish and check in one pass.
- **Do not create a second architecture document.** When a workflow set is
  introduced, put it in a dedicated folder and make any same-named existing file
  a pointer, rather than duplicating the name at the root.
- Full contract and the maintenance rules: `references/workflow-docs.md`.

## Standing delivery pattern (user-established)

After each fix wave: bump `pyproject.toml` version, consolidate CHANGELOG `[Unreleased]` sections into a versioned release entry, commit ALL, push. This is the default pattern — do it every time without being asked.

**A wave is not delivered until all four legs are done.** Committing the code is only one leg; the wave is incomplete while any of these is true, and each one is invisible in a `git status` that comes back clean:

1. **Unpushed commits** — `git log --oneline origin/main..HEAD` is non-empty.
2. **No versioned CHANGELOG entry for the wave** — the top of `CHANGELOG.md` is the release the wave belongs to. Grep the changelog for the wave's own date/topic marker; if the wave's work appears nowhere, it is undocumented no matter how many commits carry it.
3. **No version bump** — `pyproject.toml` still carries the previous release.
4. **No doc sync** — the docs still advertise the previous release label.

### Auditing delivery completeness

```bash
git log --oneline origin/main..HEAD          # leg 1 — unpushed
git stash list                                  # leftover stashes
grep -n "^## \[" CHANGELOG.md | head -5         # leg 2 — top release entry
grep -n "^version" pyproject.toml               # leg 3 — current version
cat VERSION                                     # leg 4 — repo release label
```

`VERSION`, `pyproject.toml`, and the release label quoted across `doc/MANUAL.md`, `doc/DOCUMENTATION_STATUS.md`, `doc/RAG_TEST_SUITE_MANUAL.md`, `doc/PIPELINE_V2_1_ROADMAP.md` and `doc/ROLLOUT_MASTER_PLAN.md` drift apart independently. The runtime version is derived from `pyproject.toml` via `core/settings/_version.py`; `VERSION` is the repository label and the docs quote it. When they diverge, every doc that quotes the label is stale — say so explicitly rather than quietly updating one file.

### The release label has a SOURCE — check the consumers, not just the value

A label can be correct while the machinery that consumes it is broken. A build that reads the version from a module that was moved or deleted resolves it to the **EMPTY STRING**, and every artifact it names carries that empty version — while the runtime reports the right version and every doc quotes the right label, so nothing surfaces it. Grep for the version's consumers (the Makefile, the packager, the manual build) and for the **old** source path, not just for the version string.

Two more rules for the same work: search for the label **phrasings** rather than the version string, so a document stating the CURRENT label is updated while a historical release reference is left alone; and pin the result with a gate test asserting label file == `pyproject.toml` == the newest changelog entry, and that every document quoting the label quotes the current one.

The consumer table, the current-vs-historical phrasing list and the gate-test shape: `references/release-label-consistency.md`.

### Leftover stashes are not free to drop

A stash is a snapshot of a work-in-progress tree, and it can be **partly superseded** — a later commit may already contain most of its content while a couple of hunks never landed. Before reporting a stash as redundant, diff it against HEAD file by file (`git diff stash@{n} HEAD -- <path>`); an empty diff for the files it touched means it is genuinely absorbed, while a non-empty diff means it still holds unmerged work (a typical case: a half-applied bare-except migration where the code change landed but the test change did not). Report the specific unmerged hunks; never drop a stash that still holds work.

## Reconciling another agent's work (branches + worktrees)

A second session works in this repo concurrently — through **branches** and
**git worktrees**, not only the working tree. Its files appear in `git status`
as ordinary modifications; its branches and worktrees are invisible in `git
status` entirely. The user's standing requirement here is **ONE branch**
(`main`), with the reconciliation done carefully and double-checked.

1. **Inventory before touching anything** — `git branch -vv`,
   `git worktree list`, `git log --oneline -1`, `git status -sb`. A worktree
   checked out at an OLD commit is normal here and is not by itself a
   problem to fix.
2. **Preserve first.** Its unpushed work is precious. Before deleting a branch
   or a worktree, confirm the commits it holds are reachable from `main`
   (step 3) — if they are, deleting loses nothing.
3. **Is its commit already in MY history?** This decides whether anything
   needs reconciling at all:
   ```bash
   git merge-base --is-ancestor <sha> HEAD && echo "already in history"
   git branch --contains <sha> -a
   git log --oneline <sha> | tail -3     # its actual BASE
   ```
   A worktree may sit on an old base, so **`git diff <my HEAD> <its tip>` is
   meaningless there** — it reports thousands of "deletions" that are just
   your later work (measured: 45,127 deletions for a worktree whose tip was
   139 commits behind). Diff against the two commits' real common base, or
   against `main`.
4. **Reconcile the overlapping FILES, not the commits.** When both sessions
   touched the same file, decide which fix wins and re-run the affected tests
   against the merged tree. A second fix of the same defect class is usually a
   DUPLICATE, not a conflict — both can be in history with the later one
   authoritative; prove it with the tests rather than by reverting the earlier
   one.
5. **Consolidate to one branch.** Fast-forward `main` to the current commit
   (`git checkout main && git merge --ff-only origin/main`), then delete the
   extras with `-d` (git refuses unmerged branches, so `-d` is the safe proof
   they are merged) and `git worktree remove <path>` (check the worktree is
   clean first). Verify: `git branch -vv` shows exactly one branch tracking
   `origin/main`.
6. **Push to the branch that has the upstream.** A branch with no upstream
   fails with "upstream, see 'push.autoSetupRemote'". Push explicitly:
   `git push origin <branch>:main` when the working branch is not `main`.

## Commits

- Match the repo's granular style: `fix(<scope>): …`, `docs(...)`, `chore(...)`, lowercase scope (`adala`, `parser`, `ingestion`, `manual`). The subject should say what behaviour changed, not which file moved.
- **The co-author trailer is FIXED — do not invent an address.** Every commit ends with exactly:
  `Co-Authored-By: Hakim <mohammed.aqarad@gmail.com>`
  A made-up address (`mohammed@huquqai.ai`) was committed three times and had to be rewritten out of the history; the user corrected it twice. No other trailer variant, no bare name, no substituted address. Write the message with `-F <file>` so the trailer is not mangled.
- **Rewriting a trailer across pushed history** (the user asks to "replace that throughout"): back up first (`git branch backup-<purpose> HEAD`), then
  `FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --msg-filter <msg.sh> --tree-filter <tree.sh> -- <first-bad>^..HEAD`
  where `msg.sh` is a `sed` over the commit message and `tree.sh` the same `sed -i` over each commit's tracked files (a trailer also appears inside `CHANGELOG.md`). `--tree-filter` needs a CLEAN tree — `git stash push -- <unrelated modified file>` first and `git stash pop` after. Then `git push --force-with-lease origin main` (the lease makes it refuse if the remote moved). Verify by scanning every commit: `git log --format="%(trailers:key=Co-Authored-By,valueonly)"` plus a per-revision `git show <rev>:CHANGELOG.md | grep <old string>` loop. A force-push of `main` is a gated tool action — it will block for the user's approval; say so rather than retrying.
- **Never put a backtick in a double-quoted `git commit -m "…"`.** The shell command-substitutes it: `` `mark_failed` `` was executed as a command, the shell printed "command not found", and the word was silently dropped from the committed message. Use a quoted heredoc (`git commit -F - <<'MSG'`) — the single quotes stop every expansion — or write the message to a file and pass `-F <file>`.
- Split a mixed tree by LAYER when the topics separate cleanly (parser layer / ingestion layer / docs+data / tooling) — it matches the history and keeps reverts possible. When your change and the user's sit in the SAME file with adjacent hunks, do not hand-split hunks: keep them in one commit and say which is which in the body.
- Commit the user's WIP as they asked rather than quietly excluding files. If something looks like scratch (a probe script at the repo root), commit it and flag it so they can move it.
- When the user says "commit and push everything" / "EVERYTHING", they mean ALL files in the working tree — not just yours. Stage with `git add -A` unless they explicitly scoped the commit.
- When you commit a test that currently fails (an incomplete contract in their WIP), record that failure IN the commit message so it traces to the commit that introduced it, and repeat it in the handover.

## The gates — they will block you

`.pre-commit-config.yaml` runs on every commit: `dead-file-audit` (`venv/bin/python tools/find_dead_files.py --strict`), `admin-field-drift`, and `mypy` (zero-tolerance); pip-audit and the resolver check fire only on dependency manifests.

- The mypy hook entry is `venv/bin/python -m mypy api core retrieval reasoning ingestion graph ontology query billing services`. `fetching/` is not in that list but is type-checked transitively through `ingestion`, so parser errors surface as ingestion errors. Run that exact command to reproduce a blocked commit locally.
- CI runs the same mypy (`.github/workflows/mypy.yml`, on push) plus dead-files, dep-audit, admin-drift, i18n, document-quality and the U-3 backfill. `--no-verify` therefore does not buy a green build — it only moves the failure to CI. Fix the types, or ask.
- **pip-audit scans dependency manifests** (requirements.txt, requirements-cpu.txt, etc.) and can fail on pre-existing vulnerabilities that are NOT caused by the current change. When this happens: report the exact failure, state that the vulnerabilities pre-date the change, and ask the user whether to fix the dependencies (major upgrade, out of scope) or use `--no-verify`. Do not auto-use `--no-verify` without explicit permission. This pattern has now fired 4 consecutive sessions — if the user says "yes" to `--no-verify`, that authorization applies to the current commit only, not as a standing bypass.
- **A blocked version bump must not stall a functional fix.** `pyproject.toml` is what triggers the pip-audit hook, so a bump can block a commit that changes no dependency at all. When the CVEs are pre-existing and no bypass is authorized, REVERT the bump and commit the code fix cleanly; report the blocker and the un-bumped version. The version bump is a release-label concern, not a precondition for shipping a fix.
- Type errors that are not yours: report the exact errors plus the one-line fix for each and let the user choose (fix now / `--no-verify` / hold), then apply what they chose. Fixing someone's WIP without that choice is the same overreach as fixing a bug without permission.
- Recurring fixes in this codebase: an optional-import fallback (`logger = None`) → declare `logger: Any` before the try block; a `dict[str, object]` cache read → `cast(Any, …)` at the read; a variable assigned `""` then a `str | None` return → annotate the first assignment (`: str | None = ""`); a name re-annotated later in the same function scope → drop the annotation on the later declaration.

## Push and verify

```bash
git push origin main
git fetch -q origin && git status -sb     # "## main...origin/main" with no ahead/behind
git log --oneline -1 origin/main          # equals your HEAD
git log --oneline origin/main..HEAD       # empty
```

Report the push with the commit range (`813075ec..815ad5c6`) and the four verification lines above. `gh` may be absent or unauthenticated — then say plainly that CI status was NOT verified rather than implying it was.

**GitHub CLI auth in headless environments**: `gh auth login --web` fails with Chrome zygote "Broken pipe" errors. Use device flow instead: `gh auth login --hostname github.com --git-protocol https --with-token` (paste a PAT from github.com/settings/tokens with `repo` scope) or `gh auth login --hostname github.com --git-protocol https --web` (enter a code at github.com/login/device). Neither forks a browser.

## Running the suite here (the cgroup kills a single-process run)

A whole-suite `pytest` in one process is OOM-killed by the user memory cgroup
(`journalctl -k`: `Memory cgroup out of memory: Killed process <pid> (python) … anon-rss:4050100kB`).
**Run one test file per process** — `scripts/run_suite_chunked.py` in this skill does
that and is resumable, so a runner that is itself OOM-killed is simply started again.
**The runner lives in this skill's own `scripts/` directory, not in the repo** — invoke
it by absolute path (`skill_dir/scripts/run_suite_chunked.py`), or copy it to the scratch dir
first. Looking for it at the repo's `scripts/` fails, and that is not a reason to hand-roll a
replacement loop.

Full procedure, recovery steps, and how to report the total: `references/chunked-suite-run.md`.

The rules that matter most:

- **Run the suite as BOUNDED FOREGROUND slices, not as a background
  process.** A background runner is SIGTERM'd when its window closes (the
  notification arrives as `exit -15`), and `nohup`/`setsid` inside the
  command is refused by the tool. A foreground slice that is killed
  mid-way loses NOTHING, because the runner writes each completed file to
  its state file as it goes — so the "a foreground run that is killed
  loses the per-file state" worry is unfounded. The practical shape: a
  runner that takes `START`/`END`/`MAXFILES` environment variables and
  a resumable state file, invoked once per slice, each slice sized to
  finish inside the call's own timeout (the tool's foreground limit is
  420 s, so 30–40 files per slice is safe). Aggregate the per-file logs
  at the end and report the summed counts.
- The runner can be OOM-killed by a CONCURRENT session running the same heavy test file.
  Re-run it to resume. **Never kill the other session's process** to free the memory.
- **The full suite is a GATED operation — confirm before launching it.** The
  standing rule is to run it before CLAIMING the suite is green, but the user
  may hold it (a reingestion in flight, a rebuild they want to control), and an
  unprompted launch mid-delivery is a correction waiting to happen. Ask, or
  deliver the wave and say plainly that the suite has not run. Delivering the
  wave without it is fine when the user says so — the failure mode is claiming
  green, not omitting the run. A focused selection plus the repo's own gate
  files (label sync, god-file, bare-except ratchet) is what a wave needs before
  it ships; the full memory-bounded run is what makes the CLAIM true.
- A file reporting no summary line (pytest exit code 5) collected ZERO tests. Under the
  suite's marker filter that means the file's tests were ALL deselected — a
  DESELECTION, not a failure. Run those files separately WITHOUT the filter,
  against the live services, and count both passes in the final total. A file
  whose every test sits in a `main()` behind `if __name__ == "__main__"`, or
  behind a `check()` counter, ALSO exits 5 — and that one is a real defect:
  pytest collected nothing, so the file's checks never ran.
- **Classify each per-file result by pytest's EXIT CODE, never by grepping its output for a word.** The suite's loguru warmup lines contain the literal text `warmup failed (non-fatal; …)`, so `grep -q "failed"` over combined output marks every file that emitted a warmup warning as failed — measured: 296 of 296 files reported failed, including a file that had passed 77 tests in the command immediately before. Capture stdout only (`2>/dev/null`), take the last line for the summary, and branch on `rc`: 0 passed, 1 failed, 5 collected nothing. **A result that contradicts a run you watched pass is measuring your harness, not the suite** — discard it, rebuild the detector, and re-run before reporting any number.
- **Keep each shell call to one purpose.** A long compound command (a for-loop over a
  dozen pytest files, wrapped in pipes) hits the command parser's approval gate, and a
  gated call that times out returns NO output at all — you lose the run and learn
  nothing. Split it into short single-purpose calls, and put the long loops in a
  script file.
- Re-run any file you edited after the runner started it; the chunked log holds the
  pre-edit result.
- Under an `RLIMIT_AS` cap torch/libtorch mmap fails, so torch-dependent tests must run
  WITHOUT the cap.

**Report the number you measured, and state how.** The total is the sum of the per-file
summaries in the chunked log plus the files run individually. When the total conflicts
with a total published by an earlier wave, **diff the per-file counts** before
concluding anything: identical per-file counts mean the difference is in the
aggregation, not in the suite, and saying so is the honest report. Never quietly
restate the earlier figure.

**Count each test file ONCE — the log's index must be the file's index in the FULL
list, not the slice's.** The chunked runner runs slices, and a log named by the
slice-local index lets the same file be logged under two names (counted twice when
the logs are summed) and lets one slice's log overwrite another's file with the same
index. A published total was inflated by exactly this. Deduplicate by the file's
NAME (the most recent log wins), and add the tests the marker filter excluded
separately — the live-service run executes the whole file WITHOUT the filter, so its
unmarked tests are already counted in the main run and only the DESELECTED ones are
additional.

## Triage a red suite before believing any of it

`pytest` here has been red for months (95 failures at the time of writing, most pre-existing). Classify every failure before touching anything:

1. Diff the failure set against a `git archive HEAD` copy of the same tree (same technique as the baseline rule above). Anything that fails in both is not yours.
2. Bucket the rest by error signature and by file. In this repo the recurring classes are: AST/source ratchet gates pinned to line numbers or counts, endpoint 500s, DB migrations missing from the test path, `.env`-driven expectations, and content gates that demand a specific line of code exist.
3. For anything that passes in isolation but fails in a full run, do NOT hunt by bisecting files — write a tiny pytest plugin (`-p <name>` with `PYTHONPATH=/tmp`) whose `pytest_runtest_teardown` snapshots `id()` of the suspects (`core.settings.settings`, `sys.modules['core.db']`, `sys.modules['ingestion.metadata_store']`) and prints the test after which one changes. One 4-minute run names the culprit exactly.
4. `reload(core.settings)` in a test is a global-state landmine: it rebinds the settings singleton, so every module imported earlier keeps the old instance while `patch.object(settings, ...)` hits the new one. Observed blast radius: 13 failures across 5 files from one test, only in full-suite order. Assert `Settings.model_fields["FIELD"].default` instead of reloading to read a "default" — and never assert an effective value that a developer `.env` can override.
5. Patch where the code under test reads: `patch.object(ingestion.metadata_store.settings, "DB_PATH", ...)`, not `patch.object(core.settings.settings, ...)`. Same object normally, but it survives a re-import.
6. Prefer content anchors over line pins when re-anchoring a gate: locate an except-site by owning function (walk AST parents) or by "the file has >= N narrow-tuple sites", never by absolute line number or a line band. Say in the docstring why the pin was replaced.
7. Module-global mutation is the other cross-test pollution shape: a test that assigns a module-level status dict or cache without restoring it breaks every later test that reads it — same signature as the `reload()` landmine above (green in isolation, red in full-suite order). Fix it in the polluting module with an autouse fixture that snapshots the global before each test and restores it after.

## Re-pinning the bare-except ratchet

`tests/test_no_bare_except.py` holds the gate; the number is `BASELINE_COUNT` (a ceiling with slack, not the measured count) plus `X1_BASELINE_FLOOR`, a `WALKER_COUNT_PINS` ledger, and per-PR gates in `tests/test_pr_b2/b5/b6/c1/c3/d5_*.py` that each pin their own historical count. When the measured walker count exceeds the ceiling: measure with `_bare_except_sites_from_ast()` (180 sites / 614 files at the 2026-10-17 re-pin), update every one of those constants, add a ledger entry whose description contains the word **ratchet** (the monotonic invariant allows a rise only for a declared ratchet), and state in the commit that the sites are recorded as debt rather than migrated. Verify the ledger's commit and version fields both resolve with `git rev-parse --verify` — using a date as the version field fails `test_walker_pin_commit_hashes_resolve`.

The same machinery runs in reverse when you MIGRATE sites instead of ratcheting: the count drops, and every pinned copy of the old number must move in the same commit or the gate files stay red against each other. Procedure: `grep -rn "<old count>" tests/*.py` FIRST — the per-PR files pin the number independently (`POST_PR_*_WALKER`, `EXPECTED_WALKER_POST` / `EXPECTED_BASELINE`, and regex assertions that parse `BASELINE_COUNT` out of `test_no_bare_except.py` itself). Update each constant to the measured post-migration count with a comment naming what was migrated, add the `WALKER_COUNT_PINS` entry describing the migration, then re-run all the gate files together. A drop needs no "ratchet" keyword — the monotonic invariant only demands it for rises — but the ledger description must still say what changed and why.

- The walker counts **bare-baseclass** handlers only (`except:`, `except Exception:`, tuples containing Exception) — NOT every except clause. Counting all `ast.ExceptHandler` nodes to compute a migration delta over-counts (a narrow tuple is still an except handler) and makes the arithmetic look wrong; always derive the delta from `_bare_except_sites_from_ast()` before and after.
- The gate ALSO counts `except BaseException:` — it is a bare-baseclass handler under the same rule, and a rollback that must catch everything spends ratchet budget it does not have. Write it with NO except clause at all: put the cleanup in a `finally` and hand the in-flight exception to the context manager with `sys.exc_info()` (`conn_ctx.__exit__(*sys.exc_info())`) — the manager sees the exception and rolls the transaction back exactly as before, and the ratchet count does not move. A guard around an optional import wants the narrowest tuple that can actually fail (`except ImportError`), not `except Exception`.
- A rise in the count fails the gate with a delta against `BASELINE_COUNT`; the fix is to remove the site, not to re-pin the number. Re-pinning is the sanctioned path only for a declared, ledgered ratchet.

## Pitfalls

- **A release script that asserts on an exact report/doc string aborts the whole wave — and it aborts AFTER the report was already prepared.** Match the rows it must update by SUBSTRING or line prefix, never by exact text: a table row's wording drifts as the report is edited, and one `assert text.count(old) == 1` then kills the script before the version bump, the changelog and the label sync, leaving the tree half-released. Make the script write each file only after all its edits have succeeded, so a failure leaves nothing behind. Two refinements that recur across waves: the "already noted" guard must be **section-specific** (`"FIXED in § N" not in line`), because a generic `"FIXED in §" not in line` silently skips a row that already carries an EARLIER wave's note and the new note is lost — the row keeps saying "open"; and the old version must be **derived from `pyproject.toml`**, never remembered, because a remembered one is stale the moment the previous wave ships and the assert then fires mid-script.
- **`pytest` is not a gate you can trust here.** The suite has been red for a long time (order of a hundred failures, many of them pre-existing ratchet gates that assert on source line numbers or pinned counts, plus endpoint 500s, DB migrations missing from the test path, and `.env`-driven failures). Never report "tests pass"; run the module-scoped subset that covers your change, diff a full run against a `git archive HEAD` copy, and classify every working-tree-only failure (gitignored `.env` values, data the archive does not carry, new untracked tests) before claiming the change is clean.
- **Do not edit source files while the suite is running.** A test that asserts on `inspect.getsource(...)` fails with a nonsense message when a line table goes stale mid-run; freeze the edits, re-run, and only then diff failure sets. The same applies to the RUNNER: a file whose result you need must not be edited after the runner started it — re-run that file alone.
- **A `NameError` in a test that exercises a provider module directly usually means the module grew a new module-level dependency the test does not provide.** Some suites exec a provider module's source in a SANDBOX with a hand-written prelude of stubs instead of importing it, so a new import in the module is invisible to the test and surfaces as `NameError: name 'x' is not defined` far from the change. When you add a module-level import to a provider module, grep the test tree for that module name and declare the new dependency in the test's sandbox prelude — or move the call to a local import.
- **A multi-operation edit batch can apply PART of its operations and still report failure.** Read the file back after any partially-failed batch and verify each intended change is present; do not assume the first operation landed, and do not re-apply one that did.
- **Do not `git stash`/`checkout` in this repo to build a baseline.** Copy the packages into the session scratch dir and `git show <rev>:<path> > <scratch>/<path>` instead — the working tree, caches and corpus JSONs stay untouched.
- **A push is not "done" until origin is verified.** `git push` output alone does not prove the remote moved; re-check `origin/main` against HEAD and that nothing is left unpushed.
- **The working tree is the user's, not yours.** Leave unrelated modifications alone, never revert or reformat them, and never commit a config change (`.env`, settings) to make a test pass.
- **"Write them" is not "run them."** When the user asks for an ARTIFACT — a question set, a report, a plan, a probe script — writing it IS the deliverable, and executing it (a retrieval pass, a test run, a benchmark, a reparse) is a separate step that needs its own permission. Corrected twice in one session: "dont run the suite yet", then "i didnt ask you to run the test, just write them" — the second came after a 420 s retrieval run was launched against a request that only asked for the questions. Deliver the artifact, state plainly that nothing was executed, and stop. The same rule covers the suite: the standing guidance is to run it before CLAIMING green, but the user may hold it, and an unprompted launch mid-delivery is a correction waiting to happen.
- **Another agent may be working in the SAME repo at the same time.** Its files appear in `git status` as ordinary modifications, indistinguishable from yours. Diff each unstaged file to decide ownership: a file your wave never touched is not yours to stage, revert, or reformat. Stage your wave's files BY NAME (an explicit `git add <paths>`), never `git add -A` — under concurrency a blanket add sweeps the other agent's half-finished work into your commit, and a later `git stash`/`git checkout` to isolate a baseline can destroy it.  The "commit everything" rule above is for the USER's WIP in a solo session; when a second session is live, its files are not "everything" — they are someone else's work in progress.
- **`git commit -- <paths>` commits ONLY those paths, ignoring what else is staged.** When the index already holds another agent's `M ` entries (or the user's), `git add <your paths>` followed by a bare `git commit` would sweep ALL of it in. `git commit -F <msg> -- <explicit paths>` takes the working-tree content of exactly those paths and nothing from the index, so the other session's staged work is untouched and still staged afterwards. Use it whenever the tree is shared; verify with `git show --name-only --format="" HEAD` and grep the file list for anything you did not write.
- **Never kill another session's process to free memory or a port** — not even a pytest run that is OOM-thrashing. Report the contention and let the owner decide. If the other session restarts a shared dependency (Qdrant, a model server), re-probe it before concluding it is down: a stale connection error is not the same as a stopped service.
- **Build a baseline WITHOUT `git stash` when another session is live.** `git stash push` hides the other agent's work for the duration of the measurement, and a concurrent edit landing in that window is lost when the stash pops. Copy the tree instead: `git archive HEAD | tar -x -C <scratch>/` and run the baseline there — the working tree, caches and corpus JSONs stay untouched. **`HEAD` is the CURRENT commit**, so once your own fix is committed this copies the FIX; for a pre-fix baseline archive the revision the change was measured against (`HEAD~1`, or the wave's base SHA) and say which revision you used.
- **A clean working tree is not a delivered wave.** `git status` reports only what is uncommitted. Committed-but-unpushed work, a missing CHANGELOG entry, an unbumped version, and stale release labels all live outside `git status` — check all four legs explicitly before telling the user a wave is done.
- **A file another process is writing can silently lose your patch.** When a source file is edited concurrently (the user, another agent, or a running parser), the patch tool may return success while the content is absent, or fail with "was modified since you last read it" / "Failed to write file". Never trust the success flag alone: **read the file back and grep for the marker you added before reporting the fix as applied.** If the write keeps failing, apply it with a direct file read/write instead of the patch tool, then re-verify. Re-patching the same file without a read-back wastes turns and makes the user think the fix is stuck.
- **The `documents` schema is declared TWICE — a new column needs BOTH.**
  `ingestion/metadata_store.py` has its own `ALTER TABLE documents ADD
  COLUMN ...` list (the runtime schema, applied by `_init_db`), and
  `scripts/migrate_db.py` is the CLI mirror of the same list.  Adding a
  column to only one leaves a FRESH database (every test's tmp DB, every
  new deployment) without it, and the first INSERT that names it fails
  with "table documents has no column named ...".  A test that saves a
  document is the canary: `tests/test_p6_source_authority.py` caught it.
- **Two changelog files, one release record.** `CHANGELOG.md` at the repo root and `doc/CHANGELOG.md` are separate files and they diverge. The root file is the one the release-entry gate checks by name. When you consolidate a release, check whether the doc copy still carries the same release, and do not assume the two are mirrors.
- **The defect classes and their fixes are single-sourced in
  `mizan-pipeline-audit`** — the logging handler hierarchy, a filter
  that reaches one retrieval leg and not the other, a hardcoded payload
  field, a payload built by a second code path, two stores holding the
  same fact, a shadowed name that fails silently, and counting a
  collection by scrolling its payloads.  Read that skill before
  reviewing a diff that touches those areas; do not re-derive the rules
  here.
- **Planning docs are tracking docs, not evidence.** `doc/TODO.md`, `doc/ROLLOUT_MASTER_PLAN.md` and `doc/TECHNICAL_DEBT.md` drift from the code and from each other. A debt item whose fix already landed in the tree is not debt — verify each item against the source before reporting it, and treat two trackers disagreeing about the same item (e.g. a gate recorded as open in one and closed in another) as a doc bug to report, not as a decision to make.
- **The `.env` undeclared-key gate sees `model_fields` only.** It diffs `.env` keys against `set(Settings.model_fields)`, but pydantic `validation_alias=AliasChoices(...)` names are declared input surfaces too — legacy renames like `VISION_OCR_ENABLED` (alias of `OCR_ENGINE`) are real configuration, and the gate false-positives on them. Extend the declared set with `field.validation_alias.choices` before diffing.
- **`tests/test_no_god_files.py` bans non-test files over 1000 LOC** unless pinned in its `ALLOWLIST` (path → LOC at pin time). Organic growth routinely pushes files over; the gate-sanctioned remedy is to pin each offender at its measured LOC with a comment recording that the canonical split is forward-path debt. A pin blocks growth — a file that grows past its pin fails the gate until it is shrunk.
- **An endpoint test that builds a bare `FastAPI()` and includes a router must wire `app.state.limiter = <the global limiter>`.** The rate-limit dependency reads `request.app.state.limiter`; without it every request 500s with "State object has no attribute 'limiter'". Mirror the production wiring (`api/server.py`) in the fixture — the app under test must be wired like the app under production.
- **When narrowing a Qdrant call site's bare except**, import `qdrant_client.http.exceptions.ResponseHandlingException` (base `ApiException`) and catch that explicitly — the client wraps server-side errors (413 payload limits, timeouts) in it, and that is the type split/retry logic must see. Don't leave a message-based check testing a type it can no longer receive.
- **Full-payload Python client scroll OOMs on large collections.** The Python Qdrant client's `scroll(with_payload=True)` exhausts memory on collections with thousands of points. Use batched curl against the REST API (`POST /collections/<name>/points/scroll`) with small `limit` (200) and `--max-time` per request. For field-level checks, use filter queries (small result sets) instead of full-collection pulls. Count endpoints (`GET /collections/<name>`) are O(1) and always safe.
- **A log message can be pinned by a test.** Some suites assert on the exact text of a guard message as a source-level check — `tests/test_dense_degrades_to_sparse.py` pins `"Dense search failed (non-fatal)"` and `"Dense retrieval failed (non-fatal)"`. Rewriting the message to add the exception type breaks the test even though the guard still works. Grep the test tree for the string before changing a log message: `grep -rn "<message fragment>" tests/`. Keep the pinned phrase in the new message and add the detail around it.
- **A source-inspection test that pins an exception tuple needs whitespace-normalised matching.** These gates read the file and assert a literal tuple string is present. The tuple is almost always written multi-line with a trailing comma, so `assert "(ImportError, AttributeError, ...)" in src` fails on the real code — and the failure message shows the whole file, which reads like a broken gate rather than a formatting mismatch. Normalise first (`src = "".join(path.read_text().split())`) and drop the parentheses from the needle. When the pinned SITE MOVES (a refactor relocates the guard to a new module), update the test to the new path and say so in its docstring — the guard did not disappear, its home did.
- **The `mypy` hook can fail on another agent's file, and that is not your defect.** Run the hook's exact scope first (`venv/bin/python -m mypy api core retrieval reasoning ingestion graph ontology query billing services`), then confirm your own files are clean by checking whether every reported error is in a file your wave never touched. When it is, use the documented bypass `SKIP=mypy,pip-audit,pip-resolver git commit ...` and name the skipped hooks and the reason in the commit message and the report — do not silently skip, and do not "fix" someone else's WIP types to make the hook pass.
- **A codebase-wide rename in this repo keeps backwards-compat aliases.** Rename the public name, the user-facing label and the comments, but keep the legacy settings and engine aliases working — the settings layer already maps `QARI_OCR_*` → `VISION_OCR_*`, and the OCR engine selector accepts `qwen`/`qari` as legacy aliases for `vision`. Dropping an alias silently degrades a deployment configured under the old name (it falls back to the fast engine). Do NOT rename real model identifiers (a HuggingFace repo name), real filesystem paths, or historical notes about what older deployments ran — those are not part of the rename.
- **When production decodes a fixture payload with PIL**, a header-only stub raises `UnidentifiedImageError` before anything is posted. Build fixtures with a real tiny image: PIL's PNG re-encode of a small RGB image is byte-identical, so base64 constants asserted in the test still match. Pin env-driven settings explicitly in tests that claim to exercise a default — the operator's `.env` leaks in otherwise.
- **A mode-bit flip can masquerade as a content change.** A `chmod` (often from a curator/backup tool) turns every file 100644 → 100755, and `git diff --stat` then shows hundreds of files changed with zero insertions. Before committing, revert modes to the committed state (`find . -path ./.git -prune -o -type f -exec chmod 644 {} +`), then restore the executable bit only on files originally tracked as 100755 (`git ls-files -s | awk '$1==100755{print $4}' | while read f; do chmod +x "$f"; done`). Verify `git diff --summary | grep "mode change"` is empty before staging.
- **Git identity may be unset in a fresh environment.** `git commit` fails with "Author identity unknown". Do not guess an address; reuse the existing commit author (`git log -1 --format='%an <%ae>'`) and set it locally with `git config user.name` / `user.email`.
