#!/usr/bin/env python3
"""Diff two `pytest -q` logs and bucket the failures by error signature.

Usage:
    venv/bin/python scripts/diff_pytest_logs.py <log_a> <log_b>

Typical use: run the suite in the working tree and again in a `git archive HEAD`
copy, then diff the two logs to separate pre-existing failures from the ones the
change under test introduced.

Two traps this script exists to avoid:

  * The failures banner is `================= FAILURES =================`. A
    `startswith("=== FAILURES")` test matches nothing, the parser silently
    returns zero blocks, and the run looks clean.
  * Section headers are `____ Class.test_method ____`, but the short summary
    lists `FAILED path/to/test.py::Class::test_method - ...`. The two name forms
    never compare equal, so parse BOTH logs with this same parser and diff the
    header-name sets. Comparing header names against summary ids marks every
    failure as one-sided.

Reads the whole log, so give it a file, not a pipe.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict


def parse_blocks(path: str) -> list[tuple[str, str, list[str]]]:
    """Return [(test_name, "file.py:line", [error lines])] from a pytest -q log."""
    with open(path, errors="replace") as fh:
        lines = fh.read().splitlines()

    blocks: list[tuple[str, str, list[str]]] = []
    cur_name: str | None = None
    cur_lines: list[str] = []
    in_failures = False

    def flush() -> None:
        if cur_name is None:
            return
        loc = ""
        errs: list[str] = []
        for ln in cur_lines:
            m = re.match(r"^(tests/[^:]+:\d+): in ", ln)
            if m and not loc:
                loc = m.group(1)
            if ln.startswith("E "):
                errs.append(ln[2:].strip())
        blocks.append((cur_name, loc, errs))

    for ln in lines:
        if not in_failures and ln.startswith("=") and "FAILURES" in ln:
            in_failures = True
            continue
        if in_failures and ln.startswith("=") and "short test summary" in ln:
            flush()
            cur_name = None
            in_failures = False
            continue
        if in_failures and re.match(r"^_+\s+\S.*\s+_+$", ln):
            flush()
            cur_name = ln.strip("_ ").strip()
            cur_lines = []
            continue
        if in_failures and cur_name is not None:
            cur_lines.append(ln)
    flush()
    return blocks


def signature(errs: list[str]) -> str:
    """Collapse a block's error lines into a bucket key."""
    for e in errs:
        if "AssertionError" in e or e.startswith("assert"):
            return "assertion"
    for e in errs:
        m = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit))\b", e)
        if m:
            return m.group(1)
    for e in errs:
        if e:
            return e[:60]
    return "(no E-line)"


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    log_a, log_b = sys.argv[1], sys.argv[2]
    a_blocks, b_blocks = parse_blocks(log_a), parse_blocks(log_b)
    b_names = {n for n, _, _ in b_blocks}
    print(f"{log_a}: {len(a_blocks)} failures   {log_b}: {len(b_blocks)} failures\n")

    by_sig: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for name, loc, errs in a_blocks:
        by_sig[signature(errs)].append((name, loc, next((e for e in errs if e), "")))

    for sig, items in sorted(by_sig.items(), key=lambda kv: -len(kv[1])):
        pre = sum(1 for n, _, _ in items if n in b_names)
        print(f"=== {sig}  ({len(items)} in {log_a}, {pre} also in {log_b})")
        locs: Counter = Counter()
        for _, loc, _ in items:
            locs[loc.split(":")[0]] += 1
        for loc, cnt in locs.most_common(8):
            print(f"    {cnt:3d}x  {loc}")
        for name, _, msg in items[:3]:
            print(f"    e.g. {name[:70]:70s} | {msg[:90]}")
        print()

    only_a = [b for b in a_blocks if b[0] not in b_names]
    print(f"########## ONLY IN {log_a} ({len(only_a)}) — candidate regressions ##########")
    for name, loc, errs in sorted(only_a, key=lambda x: x[1]):
        msg = next((e for e in errs if e), "")
        print(f"  {name[:70]:70s} {loc.split('/')[-1]:34s} {msg[:70]}")

    a_names = {n for n, _, _ in a_blocks}
    only_b = [b for b in b_blocks if b[0] not in a_names]
    print(f"\n########## ONLY IN {log_b} ({len(only_b)}) — fixed by the change ##########")
    for name, loc, errs in sorted(only_b, key=lambda x: x[1]):
        msg = next((e for e in errs if e), "")
        print(f"  {name[:70]:70s} {loc.split('/')[-1]:34s} {msg[:70]}")


if __name__ == "__main__":
    main()
