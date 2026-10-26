#!/usr/bin/env python3
"""Run a command against the pre-fix code and against the fixed code.

    python scripts/ab_verify.py ingestion/stages/store.py -- \
        ./venv/bin/python -m pytest tests/test_x.py -q

Swaps the named files for their COMMITTED (HEAD) versions, runs the
command, restores the working-tree versions, then runs the command
again.  Both outputs and exit codes are printed, and the script exits
non-zero when the command PASSES without the fix and fails with it —
the shape of a regression test that does not discriminate.

Run this BEFORE committing the wave's code: HEAD still holds the
pre-fix code, and after the code commit the "before" side is gone.

Only the named files are ever swapped; the working-tree copies are kept
in a temp directory and restored even when the command fails, so a
concurrent session's work in other files is never touched.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/home/mohammed/Mizan")
TAIL_LINES = 40


def _run(command):
    proc = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, "\n".join(output.splitlines()[-TAIL_LINES:])


def main(argv):
    if "--" not in argv:
        print(__doc__)
        return 2
    split = argv.index("--")
    files = argv[:split]
    command = argv[split + 1:]
    if not files or not command:
        print(__doc__)
        return 2

    saved = Path(tempfile.mkdtemp(prefix="ab_verify_"))
    try:
        for rel in files:
            src = ROOT / rel
            if not src.exists():
                print("missing file: %s" % rel)
                return 2
            shutil.copy2(src, saved / rel.replace("/", "__"))

        # the pre-fix side: the committed versions
        for rel in files:
            committed = subprocess.run(
                ["git", "show", "HEAD:%s" % rel],
                cwd=ROOT, capture_output=True, text=True,
            )
            if committed.returncode != 0:
                print("no committed version of %s" % rel)
                return 2
            (ROOT / rel).write_text(committed.stdout, encoding="utf-8")

        before_code, before_out = _run(command)

        # the fixed side: the working-tree versions
        for rel in files:
            shutil.copy2(saved / rel.replace("/", "__"), ROOT / rel)
        after_code, after_out = _run(command)
    finally:
        for rel in files:
            backup = saved / rel.replace("/", "__")
            if backup.exists():
                shutil.copy2(backup, ROOT / rel)
        shutil.rmtree(saved, ignore_errors=True)

    print("=== BEFORE the fix (exit %d) ===" % before_code)
    print(before_out)
    print("=== AFTER the fix (exit %d) ===" % after_code)
    print(after_out)

    if before_code == 0 and after_code != 0:
        print(
            "the command PASSES without the fix — it does not discriminate; "
            "the test must fail against the pre-fix code"
        )
        return 1
    if before_code == 0 and after_code == 0:
        print(
            "the command passes BOTH ways — it does not discriminate; the "
            "test must fail against the pre-fix code"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
