#!/usr/bin/env python
"""Measure the VIOLATION RATE of every retrieval filter.

A filter that reaches one retrieval leg and not the other is not a
filter: the user asked for a domain, a document or a validity window
and the other leg answered with everything else.  This probe runs a
real search with each filter and counts the returned chunks that do
NOT satisfy it, which is the only measurement that shows the defect.

Usage:

    venv/bin/python <this script> [field=value ...]

With no arguments it runs the default set.  Each argument overrides
one case, e.g. `doc_ref=1.08.60` or `domain=droit_civil`.

Exit status: 0 when every filter holds, 1 when any filter violates.
The rates are printed as a table so a before/after pair can be
diffed.
"""
from __future__ import annotations

import sys
from collections import Counter

REPO = "/home/mohammed/Mizan"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# The default cases.  Each is (field, filter value, the value the
# returned chunk's payload field must have).  A LIST means the chunk
# may carry any one of them.
DEFAULT_CASES = [
    ("legal_rank", {"legal_rank": "قانون"}, "قانون"),
    ("language", {"language": "ar"}, "ar"),
    ("status", {"status": "active"}, "active"),
    ("doc_ref", {"doc_ref": "1.08.60"}, "1.08.60"),
    ("validity_status", {"validity_status": "IN_FORCE"}, "IN_FORCE"),
    ("domain", {"domain": "droit_du_travail"}, "droit_du_travail"),
]

QUERY = "droits et obligations du contrat de travail"


def _cases_from_args(argv):
    if not argv:
        return list(DEFAULT_CASES)
    cases = []
    for arg in argv:
        if "=" not in arg:
            print("bad argument %r (expected field=value)" % arg)
            raise SystemExit(2)
        field, value = arg.split("=", 1)
        cases.append((field, {field: value}, value))
    return cases


def main(argv):
    from retrieval.hybrid.retriever import HybridRetriever

    retriever = HybridRetriever()
    cases = _cases_from_args(argv)

    print("%-18s %9s %11s %8s" % ("the filter", "the results",
                                   "the violations", "the rate"))
    worst = 0.0
    for field, filters, expected in cases:
        try:
            results = retriever.retrieve(QUERY, filters=filters)
        except TypeError:
            results = retriever.retrieve(QUERY, **{field: expected})
        except Exception as exc:
            print("%-18s raised %s: %s" % (field, type(exc).__name__,
                                            str(exc)[:70]))
            worst = 1.0
            continue

        total = violations = 0
        seen = Counter()
        for result in results or []:
            payload = result.get("payload") if isinstance(result, dict) else None
            if not isinstance(payload, dict):
                continue
            total += 1
            value = payload.get(field)
            seen[value] += 1
            ok = value in expected if isinstance(expected, list) \
                else value == expected
            if not ok:
                violations += 1
        rate = (100.0 * violations / total) if total else 0.0
        worst = max(worst, rate / 100.0)
        print("%-18s %9d %11d %7.1f %%" % (field, total, violations, rate))
        if violations:
            print("       the values it returned: %s"
                  % dict(seen.most_common(4)))

    if worst:
        print()
        print("AT LEAST ONE FILTER DOES NOT FILTER — the results contain "
              "chunks the user did not ask for.")
    return 1 if worst else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
