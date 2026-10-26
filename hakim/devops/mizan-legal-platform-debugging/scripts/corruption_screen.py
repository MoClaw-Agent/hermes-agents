#!/usr/bin/env python3
"""Screen a PDF corpus for text-layer corruption BEFORE running a parse.

Two independent defects, deliberately reported separately because they need
different responses:

  1. DIGIT CORRUPTION - prose reads fine, article numbers are wrong.
     Signal: impossible Hijri/Gregorian year tokens (1444 -> 3222, 2022 -> 6666).
     Response: OCR/vision re-read of the numbers. The prose is salvageable.

  2. DEAD TEXT LAYER - the Arabic itself is scrambled at the word level.
     Signal: Arabic-letter ratio near zero.
     Response: nothing to preserve; needs OCR from scratch, or exclusion.
     No number-repair fixes this.

Both are invisible to the parser's own corruption gates, which inspect Arabic
text for defect 1 and so pass it cleanly. That is why a file can parse with
extraction_mode: native and full confidence while every article number is wrong.

Usage:
    MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \
      venv/bin/python scripts/corruption_screen.py data/corpus/ism/raw/ar

Output is RANKING, not verdict. Confirm the top hits by rendering the page
(article_loss_probe.py / digit_cmap_verify.py emit the crops) before acting.
"""
import argparse
import os
import re
import sys

import fitz

HIJRI_BAD = re.compile(r"\b3[01]\d\d\b")
GREG_BAD = re.compile(r"\b6666\b|\b3266\b|\b2255\b|\b6662\b")
ARABIC = re.compile(r"[\u0600-\u06FF]")

# Below this Arabic-letter ratio the text layer is scrambled, not merely wrong
# in its digits. Tuned by inspection, not derived - treat as a screen.
DEAD_LAYER_RATIO = 0.25


def analyse(path, max_pages=80):
    doc = fitz.open(path)
    n = len(doc)
    pages = [doc[i].get_text() for i in range(min(n, max_pages))]
    doc.close()
    txt = "\n".join(pages)

    years = HIJRI_BAD.findall(txt) + GREG_BAD.findall(txt)
    ratio = len(ARABIC.findall(txt)) / max(1, len(txt))

    return {
        "pages": n,
        "chars": len(txt),
        "years": years,
        "ratio": ratio,
        "dead_layer": ratio <= DEAD_LAYER_RATIO,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="corpus dir, e.g. data/corpus/ism/raw/ar")
    ap.add_argument("--max-pages", type=int, default=80)
    args = ap.parse_args()

    files = sorted(
        os.path.join(d, n)
        for d, _, ns in os.walk(args.root)
        for n in ns if n.lower().endswith(".pdf")
    )
    if not files:
        sys.exit(f"no PDFs under {args.root}")

    rows = []
    for p in files:
        try:
            rows.append((p, analyse(p, args.max_pages)))
        except Exception as e:
            rows.append((p, {"err": str(e)}))

    def rank(item):
        _, r = item
        if "err" in r:
            return (0, 0, 0)
        # dead layer outranks digit corruption: nothing salvageable at all
        return (r["dead_layer"], len(r["years"]), r["ratio"])

    rows.sort(key=rank, reverse=True)

    digit = [r for _, r in rows if "err" not in r and r["years"] and not r["dead_layer"]]
    dead = [r for _, r in rows if "err" not in r and r["dead_layer"]]
    ok = [r for _, r in rows if "err" not in r and not r["years"] and not r["dead_layer"]]
    errs = [r for _, r in rows if "err" in r]

    print(f"screened {len(files)} PDFs under {args.root}\n")
    print(f"  clean                 : {len(ok)}")
    print(f"  digit corruption      : {len(digit)}   (OCR the numbers, keep prose)")
    print(f"  dead text layer       : {len(dead)}   (OCR from scratch, or exclude)")
    if errs:
        print(f"  unreadable            : {len(errs)}")
    suspect = len(digit) + len(dead)
    print(f"\n  -> {len(ok)}/{len(files)} parseable as-is; "
          f"{suspect} would produce unreliable JSON\n")

    print(f"{'file':<46} {'yrs':>4} {'arab%':>7}  fault")
    print("-" * 78)
    for p, r in rows:
        if "err" in r:
            print(f"{os.path.relpath(p, args.root):<46} ERR  {r['err'][:22]}")
            continue
        fault = "DEAD-LAYER" if r["dead_layer"] else ("digits" if r["years"] else "")
        if not fault:
            continue
        toks = ",".join(sorted(set(r["years"]))[:5])
        print(f"{os.path.relpath(p, args.root):<46} {len(r['years']):>4} "
              f"{100*r['ratio']:>6.1f}%  {fault} {toks}")

    print("\nRanking only. Confirm the top hits by rendering the page before "
          "committing to a multi-hour parse.")


if __name__ == "__main__":
    main()
