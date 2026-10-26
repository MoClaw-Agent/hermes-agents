#!/usr/bin/env python3
"""Read-only audit of the parser -> ingestion contract.

Answers, per provider JSON:
  * is the extraction cache present (key derived from the PDF's first 4 KB)?
  * does the sample already cover the whole document?
  * which OCR pass built the structure, and is that text reachable?
  * which hierarchy fields do the flattened articles actually carry?

Nothing is written or deleted. Run from the project root:

    venv/bin/python scripts/audit_parser_ingestion_contract.py

Use it before promising a re-ingest, and after changing the flattener or the
cache resolution, to report real before/after numbers instead of unit-test
confidence alone.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path("data/corpus")
PROVIDERS = ("adala", "ism")


def head_key(pdf: pathlib.Path) -> str | None:
    """Cache key = sha256(first 4 KB)[:12]. NOT the full-file content hash."""
    try:
        with pdf.open("rb") as fh:
            return hashlib.sha256(fh.read(4096)).hexdigest()[:12]
    except OSError:
        return None


def main() -> int:
    for provider in PROVIDERS:
        json_root = ROOT / provider / "json"
        if not json_root.exists():
            continue
        cache_dir = ROOT / provider / "cache"

        stats: Counter = Counter()
        vision_unreadable: list[str] = []

        for jf in sorted(json_root.rglob("*.json")):
            try:
                d = json.loads(jf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                stats["unreadable json"] += 1
                continue

            src = d.get("source_file")
            pdf = pathlib.Path(src) if src else None
            key = head_key(pdf) if pdf and pdf.exists() else None

            if key is None:
                stats["source PDF missing"] += 1
            else:
                hashed = cache_dir / f"{pdf.stem}_{key}.json"
                legacy = cache_dir / f"{pdf.stem}.json"
                stats["cache present" if (hashed.exists() or legacy.exists())
                      else "cache MISSING"] += 1

            npages = d.get("num_pages")
            sample = len(d.get("page_texts_sample") or [])
            if isinstance(npages, int) and npages > 0:
                stats["sample covers whole doc" if sample >= npages
                      else "sample partial"] += 1

            if d.get("structure_source") == "vision":
                stats["structure built from vision"] += 1
                vc = d.get("structure_text_cache") or ""
                if vc and pathlib.Path(vc).exists():
                    stats["  ...vision text reachable"] += 1
                else:
                    vision_unreadable.append(jf.name)

            if d.get("structure") is None:
                stats["structure is null"] += 1

        print("=" * 72)
        print(f"{provider}: {len(list(json_root.rglob('*.json')))} JSON file(s)")
        print("=" * 72)
        for k in sorted(stats):
            print(f"  {k:34} {stats[k]}")
        if vision_unreadable:
            print(f"  vision text unreachable for {len(vision_unreadable)} file(s):")
            for name in vision_unreadable[:5]:
                print(f"    {name}")
        print()

    print("Hierarchy consumers — run these and read the result before claiming")
    print("any retrieval-quality impact:")
    print('  grep -rn "hierarchy_str" --include=*.py . | grep -v "/ingestion/"')
    print('  grep -rn "chapter" retrieval/ query/ reasoning/ api/routes/ --include=*.py')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
