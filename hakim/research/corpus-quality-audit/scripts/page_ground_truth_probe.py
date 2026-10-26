#!/usr/bin/env python3
"""Probe one PDF page: what the page PRINTED vs what the text layer CLAIMS.

Use this the moment a human's reading of a document contradicts your
extraction -- especially when they name a page or quote opening words. One run
of this replaces several rounds of theorising from the text layer.

The printed/extracted disagreement IS the finding. A text layer that renumbers
articles, or drops the marker between two adjacent articles outright, puts a
ceiling on every parser-side fix: there is no anchor left to split on, and no
count taken from that layer measures anything.

Usage:
    python scripts/page_ground_truth_probe.py <pdf> <page> [--out DIR]
    python scripts/page_ground_truth_probe.py <pdf> <page> --from-json <parsed.json>

Then read the rendered PNG with a vision tool and ask specifically: which
article numbers appear on this page, and what is the opening of <N>?

The --from-json mode reports whether each artifact article body contains a
further article marker; a run of articles with none between them means the
boundary is unrecoverable from that text.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    sys.exit("PyMuPDF is required: pip install pymupdf")

# Arabic + ASCII-Indic + extended-Arabic (Persian) digits.
ARTICLE_HEAD = re.compile(
    r"(?:\u0627\u0644\u0645\u0627\u062f[\u064b-\u065f]?[\u0629\u0647]?"
    r"|\u0627\u0644\u0641\u0635\u0644|\u0627\u0644\u0628\u0627\u0628|\u0627\u0644\u0643\u062a\u0627\u0628"
    r"|\u0627\u0644\u0642\u0633\u0645|\u0627\u0644\u062c\u0632\u0621)"
    r"\s*([0-9\u0660-\u0669\u06f0-\u06f9]{1,4})"
)


def render(pdf: Path, page: int, out_dir: Path, dpi: int) -> Path:
    doc = fitz.open(pdf)
    try:
        if not 1 <= page <= len(doc):
            sys.exit("page %d out of range; document has %d pages"
                     % (page, len(doc)))
        pix = doc[page - 1].get_pixmap(dpi=dpi, alpha=False)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / ("%s_p%03d.png" % (pdf.stem, page))
        pix.save(path)
        return path
    finally:
        doc.close()


def text_layer(pdf: Path, page: int) -> str:
    doc = fitz.open(pdf)
    try:
        return doc[page - 1].get_text()
    finally:
        doc.close()


def parsed_articles(artifact: Path) -> list:
    data = json.loads(artifact.read_text(encoding="utf-8"))
    out = []

    def walk(nodes):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            if n.get("type") == "article":
                out.append(n)
            walk(n.get("children"))

    walk(data.get("structure"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("page", type=int)
    ap.add_argument("--out", type=Path, default=Path("/tmp/page_probe"))
    ap.add_argument("--dpi", type=int, default=140)
    ap.add_argument("--from-json", type=Path, default=None,
                    help="parsed artifact to cross-check against")
    args = ap.parse_args()

    png = render(args.pdf, args.page, args.out, args.dpi)
    text = text_layer(args.pdf, args.page)
    nums = [m.group(1) for m in ARTICLE_HEAD.finditer(text)]

    print("=" * 72)
    print("%s  page %d" % (args.pdf.name, args.page))
    print("=" * 72)
    print("rendered  : %s" % png)
    print("text layer: %d chars" % len(text))
    print("article markers the TEXT LAYER reports here: %d" % len(nums))
    if nums:
        print("  %s" % nums)
    else:
        print("  (none -- if the printed page has articles, the layer lost them)")

    if text.strip():
        print()
        print("--- text layer, first 600 chars (may be visibly corrupt) ---")
        print(text.strip()[:600])

    if args.from_json:
        arts = parsed_articles(args.from_json)
        print()
        print("=" * 72)
        print("cross-check against %s" % args.from_json.name)
        print("=" * 72)
        print("  articles in artifact : %d" % len(arts))

        merged = []
        for a in arts:
            body = a.get("content") or a.get("text") or ""
            tail = body.split("\n", 1)[1] if "\n" in body else ""
            if ARTICLE_HEAD.search(tail):
                merged.append(a.get("number"))
        if merged:
            print("  bodies containing a further article marker: %d"
                  % len(merged))
            print("  %s" % merged[:20])
            print("  (merged-boundary candidates: the next article's opening sits")
            print("   inside this one with no separator -- unrecoverable by split)")
        else:
            print("  no article body contains a further article marker")

        print()
        print("NEXT: read the PNG with a vision tool; ask which article numbers are")
        print("       printed on this page. Disagreement with the list above is the")
        print("       root-cause finding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())