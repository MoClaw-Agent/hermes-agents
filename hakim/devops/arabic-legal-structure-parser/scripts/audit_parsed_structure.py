#!/usr/bin/env python3
"""Audit parsed legal-structure JSONs: article counts + ingestion retention.

Usage (from the repo root, with the project interpreter):

    ./venv/bin/python <skill_dir>/scripts/audit_parsed_structure.py \\
        [json_dir] [--repo ROOT] [--threshold 0.5]

For every *.json under json_dir it prints one row:

    arts   num_articles_detected, read from the JSON (not recomputed)
    chaps  num_chapters_detected, read from the JSON
    flat   items ingestion's flattener produces from the on-disk structure
    kept   characters those flat items carry
    src    characters of the text that built the tree (structure_text_cache)
    ratio  kept / src

Rows are flagged when arts == 0, ratio < threshold, structure_degraded is set,
or the text cache named by structure_text_cache is missing. Those documents
lose their provisions at ingestion -- see SKILL.md, sections "Ingestion
Chain" and "Auditing a reparse".
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def _pages_from_cache(path: str | None) -> list[str] | None:
    """Return the page strings from a structure_text_cache file, or None."""
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out: list[str] = []
    for page in data.get("pages") or []:
        out.append(page if isinstance(page, str) else (page.get("text") or ""))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("json_dir", nargs="?", default="data/corpus/adala/json")
    ap.add_argument("--repo", default=os.getcwd(), help="repo root to import from")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    sys.path.insert(0, os.path.abspath(args.repo))
    from ingestion.pre_converters.helpers import _flatten_adala_structure

    files = sorted(
        glob.glob(os.path.join(args.json_dir, "**", "*.json"), recursive=True)
    )
    if not files:
        print(f"no JSON files under {args.json_dir}", file=sys.stderr)
        return 2

    header = (
        f"{'file':44s} {'arts':>5s} {'chaps':>5s} {'flat':>5s} "
        f"{'kept':>7s} {'src':>7s} {'ratio':>6s}  flags"
    )
    print(header)
    print("-" * len(header))

    flagged = 0
    for path in files:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        structure = doc.get("structure") or []
        if not isinstance(structure, list):
            structure = []
        flat = _flatten_adala_structure(structure, None)
        kept = sum(len(item.get("text") or "") for item in flat)
        pages = _pages_from_cache(doc.get("structure_text_cache"))
        src = sum(len(p) for p in pages) if pages is not None else -1
        ratio = (kept / src) if src > 0 else None

        flags: list[str] = []
        if doc.get("num_articles_detected") == 0:
            flags.append("ZERO-ARTICLES")
        if ratio is not None and ratio < args.threshold:
            flags.append("TEXT-LOSS")
        if doc.get("structure_degraded"):
            flags.append("DEGRADED")
        if src < 0:
            flags.append("NO-TEXT-CACHE")
        if flags:
            flagged += 1

        ratio_str = f"{ratio:.3f}" if ratio is not None else "n/a"
        print(
            f"{os.path.relpath(path, args.json_dir)[:44]:44s} "
            f"{str(doc.get('num_articles_detected')):>5s} "
            f"{str(doc.get('num_chapters_detected')):>5s} "
            f"{len(flat):>5d} {kept:>7d} {src:>7d} {ratio_str:>6s}  "
            f"{','.join(flags)}"
        )

    print()
    print(
        f"{flagged} of {len(files)} documents flagged "
        "(zero articles, text loss, degraded, or missing text cache)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
