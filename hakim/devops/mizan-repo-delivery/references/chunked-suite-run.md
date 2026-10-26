# Running the Mizan test suite under the memory cgroup

The whole suite in one pytest process is OOM-killed by the user memory cgroup
(`journalctl -k`: `Memory cgroup out of memory: Killed process <pid> (python) … anon-rss:4050100kB`).
The fix is to run **one test file per process**. `scripts/run_suite_chunked.py` in this
skill does exactly that and is resumable.

```bash
venv/bin/python <skill>/scripts/run_suite_chunked.py /tmp/mizan_suite_chunks
```

## Procedure, in order

1. **Start the chunked runner in the BACKGROUND** with a long timeout and a notify — a
   full run takes tens of minutes. Never run it in the foreground: the tool call times
   out long before the suite finishes, and a foreground run that is killed loses the
   per-file state.
2. **The runner itself can be OOM-killed.** A concurrent session running the same heavy
   test file will do it. The runner writes a state file, so **just run it again** — it
   resumes at the first file it had not completed. Confirm it was an OOM kill and not a
   crash in your code: `journalctl -k --since "-15 min" | grep "killed process"`.
3. **When the runner keeps dying on the same file, exclude it and run it alone.** One
   endpoint test file (`tests/test_admin_profiles_endpoint.py`) grows past the cgroup
   limit when a concurrent session runs the same file; the runner skips it, and you run
   it separately in the foreground when it is alone. **Never kill the other session's
   process** to free the memory — that needs explicit permission.
4. **Run the files the runner never reached individually**, in the foreground, and add
   their counts to the tally. A file that reports no summary line (pytest exit code 5)
   collected ZERO tests — every test in it is deselected by the marker filter
   `-m "not requires_server and not requires_qdrant and not requires_llm"`. That is not
   a failure.
5. **Re-run any file you edited after the runner started it.** The chunked log holds the
   result from before your edit; a stale log is how a fixed failure gets reported as
   still broken.

## Two traps this avoids

- A detached run reports the LAUNCHER's exit code, so a green exit code can hide a
  killed pytest — read the log, not the exit code.
- Under an `RLIMIT_AS` cap, torch/libtorch mmap fails
  (`ImportError: libtorch_cpu.so: failed to map segment`), so torch-dependent tests must
  run WITHOUT the cap. The script applies no address-space limit for this reason.

## Reporting the total

The total is the sum of the per-file summaries in the chunked log plus the files run
individually — say so in the report.

**Parse the summary line for EVERY pytest format.** A regex that assumes
`N passed` silently miscounts the failure cases, because pytest prints a
DIFFERENT shape when a file has no passing tests:

| pytest printed | meaning |
|---|---|
| `15 passed, 3 warnings in 3.91s` | all green |
| `1 failed, 10 passed, 3 warnings in 6.53s` | some failed |
| `1 failed, 4 warnings in 4.80s` | ALL failed — there is no "passed" count to find |
| `27 deselected, 3 warnings in 6.35s` | 0 collected — not a failure |

A tally that requires "N passed" reads the third row as "no summary line" and
files it under "deselected", which reports a red file as a non-failure. Match
`passed`, `failed`, `skipped`, `deselected` and `error` INDEPENDENTLY, and take
the LAST summary-looking line in the file.

**The runner's log name is `NNN_<basename>.log` — strip the prefix, and beware
the collision.** The runner numbers the files and uses the BASENAME only, so
`tests/test_foo.py` becomes `012_test_foo.log`. Match on the basename, not on
the repo-relative path, or every file looks like it is missing.

## The runner dies near the end of the alphabet

In this repo the runner reliably reaches ~**242 of 267** files before the
cgroup kills it, and the files it never reaches are the TAIL of the alphabet
(`test_state_schema` onward). Resuming it re-runs the same tail and dies
again at the same point — the resume does not help, because the memory
pressure is caused by the concurrent session, not by the runner's own
position.

So after the SECOND OOM kill, do not keep resuming: switch to step 4 and run
the remaining files individually in the foreground, where each gets a fresh
process. Report the total as the sum of the completed files PLUS the
individually-run ones, and say plainly that the tail was run separately.

## Classifying the failures

The suite has been red for a long time and most failures are pre-existing. Diff the
failure set against a `git archive HEAD` copy of the same tree (see the delivery
skill's baseline rule): anything that fails in both is not yours. A file whose summary
is `1 failed, N passed` needs the failure itself classified — in this repo the recurring
pre-existing classes are the god-file LOC gate, the camel-lemmatize `TypeError` (a
`patch.dict(sys.modules, ...)` eviction of numpy's `_NoValue` singleton — see the
test-gate skill), the flaky SQLite-load checkpoint test, and the "all tests
deselected" files.

**A shared service dying mid-run is not a test failure.** Qdrant runs locally
(Mizan/qdrant/qdrant, data in Mizan/qdrant/storage/, started by
Mizan/start_qdrant.sh) and gets OOM-killed when the swap fills — the symptom
is `ResponseHandlingException: Server disconnected without loading a response`
and an empty `curl` to :6333. Re-probe it before classifying the affected
tests; the user may have restarted it.
