#!/usr/bin/env python3
"""Find duplicate and at-risk (colliding) PDFs in a crawled corpus.

Two distinct defects, one scan:

1. DUPLICATE  — same bytes stored under two names (`N.pdf` + `N_<hash>.pdf`).
   Wasted disk, and the parser redoes the work because its output stem is
   keyed off the same basename.
2. COLLIDING  — same basename, DIFFERENT bytes. These are distinct documents
   that a name resolver may silently overwrite, because a collision test
   driven by crawler state has nothing to disambiguate against after a reset.
   No duplicate count will ever surface this; it is the one that loses data.

Usage:
    venv/bin/python scripts/duplicate_download_probe.py data/corpus/ism/raw/ar
    venv/bin/python scripts/duplicate_download_probe.py data/corpus/ism/raw/ar --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: str) -> dict:
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(".pdf"):
                continue
            total += 1
            folder = os.path.relpath(dirpath, root)
            stem, ext = os.path.splitext(name)
            base, sep, _suffix = stem.partition("_")
            groups[(folder, base + ext)].append(os.path.join(dirpath, name))

    duplicates, collisions = [], []
    for (folder, base), paths in groups.items():
        if len(paths) < 2:
            continue
        digests = {p: sha256(p) for p in sorted(paths)}
        unique = set(digests.values())
        entry = {
            "folder": folder,
            "basename": base,
            "files": [{"path": p, "sha256": digests[p][:12],
                       "bytes": os.path.getsize(p)} for p in sorted(digests)],
        }
        if len(unique) == 1:
            waste = entry["files"][0]["bytes"] * (len(paths) - 1)
            duplicates.append({**entry, "redundant_bytes": waste})
        else:
            collisions.append(entry)

    return {
        "root": root,
        "pdfs_scanned": total,
        "basename_groups": len(groups),
        "duplicate_groups": len(duplicates),
        "colliding_groups": len(collisions),
        "redundant_bytes": sum(d["redundant_bytes"] for d in duplicates),
        "duplicates": duplicates,
        "collisions": collisions,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="corpus root, e.g. data/corpus/ism/raw/ar")
    ap.add_argument("--json", action="store_true", help="emit full JSON")
    ap.add_argument("--limit", type=int, default=15, help="rows to print per section")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.root):
        print(f"not a directory: {args.root}", file=sys.stderr)
        return 2

    rep = scan(args.root)
    if args.json:
        json.dump(rep, sys.stdout, indent=2, ensure_ascii=False)
        return 0

    print(f"root              : {rep['root']}")
    print(f"pdfs scanned      : {rep['pdfs_scanned']}")
    print(f"basename groups   : {rep['basename_groups']}")
    print(f"duplicate groups  : {rep['duplicate_groups']} "
          f"({rep['redundant_bytes'] / 1e6:.1f} MB redundant)")
    print(f"COLLIDING groups  : {rep['colliding_groups']}  <- distinct docs, "
          f"risk of silent overwrite")

    print(f"\n--- duplicates (identical bytes) ---")
    for d in rep["duplicates"][:args.limit]:
        names = ", ".join(os.path.basename(f["path"]) for f in d["files"])
        print(f"  {d['folder']}/{d['basename']}: {names}")
    if len(rep["duplicates"]) > args.limit:
        print(f"  ... {len(rep['duplicates']) - args.limit} more")

    if rep["collisions"]:
        print(f"\n--- COLLISIONS (same name, different bytes) ---")
        for c in rep["collisions"][:args.limit]:
            print(f"  {c['folder']}/{c['basename']}:")
            for f in c["files"]:
                print(f"      {os.path.basename(f['path']):<28} {f['sha256']}")
        if len(rep["collisions"]) > args.limit:
            print(f"  ... {len(rep['collisions']) - args.limit} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
