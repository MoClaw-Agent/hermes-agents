#!/usr/bin/env python3
"""Provision content-coverage probe for a parsed legal-corpus JSON.

Answers three questions that `num_articles_detected` structurally cannot:

  1. COVERAGE  - how many provision nodes carry no content at all?
  2. INTEGRITY - are provision numbers duplicated, or is more than one
                 provision merged into a single node's content?
  3. LOCATION  - for a provision whose body is missing from its own node, is
                 that body present SOMEWHERE in the tree (misplaced,
                 recoverable) or absent entirely (lost)?

Why this exists: `num_articles_detected` is computed from the same `structure`
tree it appears to describe, so agreement between the field and the node count
is a tautology. A document can report a self-consistent counter, resolve both
caches, carry `structure_degraded: false`, and still have most of its
provisions empty. Measured on one 207-page code: 700 declared provisions, 499
of them empty shells, 50 duplicated numbers.

Usage:
    python provision_text_coverage_probe.py <parsed.json> [--sample N]
                                            [--source-cache <cache.json>]

The source text is resolved from `structure_text_cache`, else from the
`cache_vision/` / `cache/` sibling of the corpus root. It is the text the
parser actually consumed, and the provenance line printed with it names which
one was graded against (never grade against a source you cannot name).

Exit code is always 0 - read the printed verdict.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

PROVISION_TYPES = ("chapter", "article")
KEYWORD = r"(?:\u0627\u0644\u0641\u0635\u0644|\u0641\u0635\u0644|\u0627\u0644\u0645\u0627\u062f\u0629|\u0645\u0627\u062f\u0629)"
PHANTOM_TITLE_RE = re.compile(r"^(?:\u0627\u0644\u0641\u0635\u0644|\u0641\u0635\u0644|\u0627\u0644\u0645\u0627\u062f\u0629)\d+$")
COMPOUND_RE = re.compile(KEYWORD + r"\s*\d{1,4}\s*[-\u2013]\s*\d{1,3}")
HEADER_RE = re.compile(KEYWORD + r"\s*(\d{1,4})")
# Body = the remainder of the line following the header number.
BODY_NEWLINE_RE = re.compile(KEYWORD + r"\s*(\d{1,4})[ \t]*\n[ \t]*(.{20,200})")
BODY_SPACE_RE = re.compile(KEYWORD + r"\s*(\d{1,4})[ \t]+(.{20,200})")
LONG_TITLE_CHARS = 100


def load_json(path):
    """Load a JSON file. An Arabic filename pasted from chat can differ from
    the on-disk name by Unicode normalization, so fall back to a basename glob
    rather than reporting the file as missing."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), path
    hits = sorted(glob.glob(os.path.join("**", os.path.basename(path)), recursive=True))
    if not hits:
        sys.exit("JSON not found: %s" % path)
    with open(hits[0], encoding="utf-8") as fh:
        return json.load(fh), hits[0]


def flatten(nodes, out):
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        out.append(n)
        flatten(n.get("children") or [], out)


def corpus_root(json_path):
    """Walk up from the JSON until a directory holding a cache sibling."""
    d = os.path.dirname(os.path.abspath(json_path))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "cache_vision")) or os.path.isdir(os.path.join(d, "cache")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def resolve_source(doc, json_path, explicit):
    """Return (pages, provenance) for the text the parser consumed."""
    candidates = []
    if explicit:
        candidates.append(explicit)
    if doc.get("structure_text_cache"):
        candidates.append(doc["structure_text_cache"])
    stem = os.path.basename(doc.get("source_file") or doc.get("file_name") or "").rsplit(".", 1)[0]
    root = corpus_root(json_path)
    if stem and root:
        candidates += sorted(glob.glob(os.path.join(root, "cache_vision", stem + "_*_vision.json")))
        candidates += sorted(glob.glob(os.path.join(root, "cache", stem + "_*.json")))
    for cand in candidates:
        if not cand or not os.path.exists(cand):
            continue
        try:
            with open(cand, encoding="utf-8") as fh:
                cd = json.load(fh)
        except Exception:
            continue
        pages = cd.get("pages")
        if pages:
            provenance = "%s (mode=%s source=%s)" % (cand, cd.get("mode", "?"), cd.get("source", "?"))
            return [p or "" for p in pages], provenance
    return None, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("--sample", type=int, default=200,
                    help="max source provisions to score for location (default 200)")
    ap.add_argument("--source-cache", default=None,
                    help="explicit page-text cache to grade against")
    args = ap.parse_args()

    doc, resolved = load_json(args.json_path)
    nodes = []
    flatten(doc.get("structure") or [], nodes)
    provs = [n for n in nodes if n.get("type") in PROVISION_TYPES]

    n_chapter = sum(1 for n in provs if n.get("type") == "chapter")
    n_article = sum(1 for n in provs if n.get("type") == "article")
    empty_leaf = [n for n in provs
                  if not (n.get("content") or "").strip()
                  and not (n.get("children") or [])]
    merged = [n for n in nodes
              if len(set(HEADER_RE.findall(n.get("content") or ""))) > 1]
    numbers = Counter(n.get("number") for n in provs if n.get("number") is not None)
    dups = {k: v for k, v in numbers.items() if v > 1}
    compound = [n for n in nodes
                if COMPOUND_RE.search((n.get("title") or "") + " " + (n.get("content") or "")[:200])]
    phantom = [n for n in provs if PHANTOM_TITLE_RE.match((n.get("title") or "").strip())]
    long_titles = [n for n in nodes if len(n.get("title") or "") > LONG_TITLE_CHARS]

    print("JSON:        %s" % resolved)
    print("ref:         %r  type=%r  lang=%r" % (doc.get("ref"), doc.get("document_type"), doc.get("language")))
    print("declared:    num_articles_detected=%s  num_chapters_detected=%s"
          % (doc.get("num_articles_detected"), doc.get("num_chapters_detected")))
    print("tree:        %d provisions (%d chapter + %d article) in %d nodes"
          % (len(provs), n_chapter, n_article, len(nodes)))
    print("provenance:  structure_source=%r degraded=%r"
          % (doc.get("structure_source"), doc.get("structure_degraded")))
    print()
    print("--- COVERAGE ---")
    ratio = (len(empty_leaf) / len(provs)) if provs else 0.0
    print("empty-shell provisions (no content, no children): %d / %d  (%.1f%%)"
          % (len(empty_leaf), len(provs), ratio * 100))
    print()
    print("--- INTEGRITY ---")
    print("merged nodes (content holds >1 provision header): %d" % len(merged))
    for n in sorted(merged, key=lambda x: -len(x.get("content") or ""))[:5]:
        print("    num=%s title=%r len=%d headers=%s"
              % (n.get("number"), (n.get("title") or "")[:40],
                 len(n.get("content") or ""),
                 sorted(set(HEADER_RE.findall(n.get("content") or "")))[:12]))
    print("duplicated provision numbers: %d" % len(dups))
    for k in sorted(dups, key=lambda x: -dups[x])[:5]:
        print("    %s: %d nodes" % (k, dups[k]))
    print("nodes touching a compound header (N-M): %d" % len(compound))
    print("phantom titles (keyword+digits, no space): %d" % len(phantom))
    for n in phantom[:5]:
        print("    %r" % (n.get("title"),))
    print("titles longer than %d chars: %d" % (LONG_TITLE_CHARS, len(long_titles)))
    print()

    print("--- LOCATION (lost vs misplaced) ---")
    pages, provenance = resolve_source(doc, resolved, args.source_cache)
    if not pages:
        print("no source page text resolved - cannot score location.")
        print("pass --source-cache <cache.json>, or confirm the cache still exists.")
    else:
        print("graded against: %s" % provenance)
        full = "\n".join(pages)
        pairs = BODY_NEWLINE_RE.findall(full)
        if len(pairs) < 10:
            pairs = BODY_SPACE_RE.findall(full)
        pairs = pairs[: args.sample]
        hits = misses = 0
        missing_examples = []
        tree_text = "\n".join(n.get("content") or "" for n in nodes)
        for num, body in pairs:
            probe = body.strip()[:40]
            if len(probe) < 20:
                continue
            if probe in tree_text:
                hits += 1
            else:
                misses += 1
                if len(missing_examples) < 5:
                    missing_examples.append((num, probe))
        total = hits + misses
        if total:
            print("source provisions scored: %d" % total)
            print("  body present in tree (MISPLACED, recoverable): %d" % hits)
            print("  body absent from tree  (LOST):                 %d" % misses)
            print("  retention: %.1f%%" % (100.0 * hits / total))
            for num, probe in missing_examples:
                print("    lost example: provision %s -> %r" % (num, probe))
        else:
            print("no scorable provision bodies found in the source text.")
    print()

    print("--- VERDICT ---")
    if not provs:
        print("no provision nodes - check whether this document has numbered provisions at all.")
    elif ratio > 0.25:
        print("STRUCTURE DEFECTIVE: %.0f%% of provisions are empty shells." % (ratio * 100))
        print("  A high retention ratio beside this means the text is MISPLACED, not lost.")
        print("  Check duplicated numbers and merged nodes above for the collision that caused it.")
    elif empty_leaf:
        print("PARTIAL: %d empty-shell provisions (%.0f%%)." % (len(empty_leaf), ratio * 100))
    else:
        print("COVERAGE OK: every provision node carries content or children.")
    if dups:
        print("  note: %d duplicated provision numbers - identity collision, not a duplicate article." % len(dups))


if __name__ == "__main__":
    main()
