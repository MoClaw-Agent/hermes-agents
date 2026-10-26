#!/usr/bin/env python
"""Compare the committed parser tree against the working tree, corpus-wide.

Same input, two code roots, one variable. Reports which provision numbers
the change removed and classifies each one:

  REAL      the document prints the number as a SPACED header ("الفصل 446")
            -> a real provision the change destroyed: BLOCKING
  artefact  the number only ever appears GLUED ("الفصل446")
            -> a native-layer shred artefact: removable

Usage (from the repo root):

    SC=<scratch>/headcheck && rm -rf $SC && mkdir -p $SC
    git archive HEAD | tar -x -C $SC
    venv/bin/python scripts/compare_parser_roots.py $SC .

The first argument is the CODE root, the second the CORPUS root. The corpus
is untracked, so it is not in `git archive`; it is passed explicitly because
`glob.glob(..., recursive=True)` does not descend into a symlinked directory.

The working tree, the caches and the JSON outputs are never written.
"""
from __future__ import annotations

import glob as _glob
import json
import os
import re
import sys
from pathlib import Path

SPACED = re.compile(r"^\s*(?:الفصل|فصل)\s+\d+\s*$")


def _walk(nodes, out=None):
    if out is None:
        out = []
    for n in nodes:
        out.append(n)
        _walk(n.get("children") or [], out)
    return out


def _numbers(tree):
    return {
        n.get("number")
        for n in _walk(tree)
        if n.get("type") in ("chapter", "article") and n.get("number") is not None
    }


def _spaced_numbers(pages):
    nums = set()
    for page in pages:
        for line in (page or "").split("\n"):
            if SPACED.match(line.strip()):
                for tok in re.findall(r"\d+", line):
                    nums.add(int(tok))
    return nums


def _select(code_root, pages, native):
    """Reproduce the provider's own page selection when it is importable."""
    try:
        sys.path.insert(0, code_root)
        from fetching.adala.parser.pipeline import _select_richer_pages

        return _select_richer_pages(pages, native, "ar")
    except Exception:
        return pages


def _collect(code_root, corpus_root):
    from fetching.pipeline_base.pdf_quality import extract_native
    from fetching.pipeline_base.structure import build_tree

    out = {}
    pattern = os.path.join(corpus_root, "data/corpus/adala/json/**/*.json")
    for q in sorted(_glob.glob(pattern, recursive=True)):
        try:
            d = json.load(open(q, encoding="utf-8"))
        except Exception:
            continue
        cache = d.get("structure_text_cache")
        if not cache or not os.path.exists(cache):
            continue
        try:
            c = json.load(open(cache, encoding="utf-8"))
        except Exception:
            continue
        pages = c.get("pages") or []
        if not pages:
            continue
        key = os.path.basename(q).replace(".json", "").split()[-1]
        pdfs = _glob.glob(
            os.path.join(corpus_root, "data/corpus/adala/raw/wrk/**/*%s*.pdf" % key),
            recursive=True,
        )
        native = []
        if pdfs:
            try:
                native = extract_native(Path(pdfs[0]), "ar")
            except Exception:
                native = []
        sel = _select(code_root, pages, native)
        tree = build_tree(sel, document_language="ar")
        out[os.path.basename(q)] = {
            "numbers": sorted(_numbers(tree)),
            "spaced": sorted(_spaced_numbers(pages)),
        }
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    code_root, corpus_root = sys.argv[1], sys.argv[2]
    before = _collect(code_root, corpus_root)
    after = _collect(os.getcwd(), corpus_root)
    print("documents: before=%d after=%d" % (len(before), len(after)))

    real_lost = artefact_lost = gained = 0
    examples = []
    for name in sorted(set(before) & set(after)):
        b = set(before[name]["numbers"])
        a = set(after[name]["numbers"])
        spaced = set(before[name]["spaced"])
        for num in b - a:
            if num in spaced:
                real_lost += 1
                examples.append((name, num, "REAL"))
            else:
                artefact_lost += 1
        gained += len(a - b)

    print()
    print("REAL provisions lost (blocking) : %d" % real_lost)
    print("artefacts removed (expected)    : %d" % artefact_lost)
    print("provisions gained                : %d" % gained)
    for name, num, kind in examples[:20]:
        print("   %-32s num=%-8s %s" % (name[:32], num, kind))
    return 1 if real_lost else 0


if __name__ == "__main__":
    raise SystemExit(main())
