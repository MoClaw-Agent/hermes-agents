#!/usr/bin/env python
"""Run the Mizan test suite ONE FILE PER PROCESS, resumable and memory-bounded.

Why: the whole suite in a single pytest process is OOM-killed by the user
memory cgroup (journalctl: "Memory cgroup out of memory: Killed process
<pid> (python) ... anon-rss:4050100kB").  One file per process keeps peak
RSS bounded.

Usage:
    venv/bin/python <this script> [logdir]        # resumable; safe to re-run

Behaviour:
  * Each test file runs in its own pytest process with a per-file timeout.
  * A state file records the files already run, so RE-RUNNING THE SCRIPT
    RESUMES instead of re-running everything.  The runner itself can be
    OOM-killed (a concurrent session running the same heavy file will do
    it) — just run it again; it picks up where it stopped.
  * Files listed in SKIP are excluded from the runner and must be run
    individually, in the foreground, when no other session is running the
    same file.  Do NOT kill another session's process to free the memory.
  * NO RLIMIT_AS is applied: an address-space cap breaks torch's shared
    library mmap ("ImportError: libtorch_cpu.so: failed to map segment")
    in the files that import torch, which produces FALSE failures.

Read-only with respect to the repository: it only runs pytest and writes
its logs to the log directory.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import time

REPO = os.environ.get("MIZAN_REPO", "/home/mohammed/Mizan")
PY = os.path.join(REPO, "venv/bin/python")
LOGDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/mizan_suite_chunks"
RUNLOG = os.path.join(LOGDIR, "run.log")
STATE = os.path.join(LOGDIR, "done.txt")

# Heavy files that OOM the cgroup when a concurrent session runs the same
# file.  Run them separately, in the foreground, when alone.
SKIP = {"tests/test_admin_profiles_endpoint.py"}

MARK = "not requires_server and not requires_qdrant and not requires_llm"
PER_FILE_TIMEOUT = 420

os.makedirs(LOGDIR, exist_ok=True)
os.chdir(REPO)

files = sorted(
    p for p in glob.glob("tests/**/*.py", recursive=True)
    if not p.endswith("__init__.py")
    and os.path.basename(p).startswith("test_")
    and p not in SKIP
)

done = set()
if os.path.exists(STATE):
    done = {l.strip() for l in open(STATE, encoding="utf-8") if l.strip()}

out_fh = open(RUNLOG, "a", encoding="utf-8")


def emit(msg: str) -> None:
    print(msg, flush=True)
    out_fh.write(msg + "\n")
    out_fh.flush()


emit("=== run started %s | files=%d already_done=%d ==="
     % (time.strftime("%H:%M:%S"), len(files), len(done)))

failures: list[tuple[str, int, str, str]] = []
for i, f in enumerate(files, 1):
    if f in done:
        continue
    log = os.path.join(LOGDIR, "%03d_%s.log" % (i, os.path.basename(f)[:-3]))
    t0 = time.time()
    try:
        r = subprocess.run(
            [PY, "-m", "pytest", f, "-q", "-p", "no:cacheprovider", "-m", MARK],
            capture_output=True, text=True, timeout=PER_FILE_TIMEOUT, cwd=REPO,
        )
        out = r.stdout + r.stderr
        rc = r.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "") + "\n[TIMEOUT %ds]" % PER_FILE_TIMEOUT
        rc = -9
    except Exception as e:  # runner-level failure, not a test failure
        out = "RUNNER ERROR: %r" % (e,)
        rc = -1
    dt = time.time() - t0
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(out)
    tail = [l for l in out.splitlines()
            if "passed" in l or "failed" in l or "error" in l]
    summary = tail[-1][:90] if tail else "(no summary line)"
    oom = "MemoryError" in out or "Cannot allocate memory" in out
    tag = "OOM" if oom else ("FAIL" if rc != 0 else "OK  ")
    if rc != 0:
        failures.append((f, rc, tag, summary))
    emit("[%3d/%d] %s %-50s %5.1fs  %s" % (i, len(files), tag, f[:50], dt, summary))
    with open(STATE, "a", encoding="utf-8") as fh:
        fh.write(f + "\n")

emit("")
emit("=" * 78)
emit("FILES WITH FAILURES: %d of %d" % (len(failures), len(files)))
for f, rc, tag, s in failures:
    emit("  %-4s exit=%-5s %-50s %s" % (tag, rc, f[:50], s))
emit("=" * 78)
emit("=== run finished %s ===" % time.strftime("%H:%M:%S"))
out_fh.close()
