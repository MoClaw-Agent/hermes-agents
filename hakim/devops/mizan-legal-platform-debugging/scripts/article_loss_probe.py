#!/usr/bin/env python3
"""Diagnose where legal articles are lost between PDF text and parsed JSON.

Answers four separate questions that `num_articles_detected` alone conflates:

  1. how many unique article NUMBERS the source text layer actually contains
  2. how many of those the detector recognises, and what the other hits are
  3. how many were recognised and then DISCARDED by build_tree's seen_articles
     dedup -- the drop that makes a parse look short while looking healthy
  4. whether the emitted articles are in order (order breaks citations even
     when the count is perfect)

Run with the project venv (the Hermes kernel python has no fitz):

    MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \\
      venv/bin/python scripts/article_loss_probe.py <pdf> [<pdf> ...]

    ... --json-dir data/corpus/ism/json/ar     # sweep every parsed file

COUNTING RULE -- read this before trusting any comparison
-------------------------------------------------------
Four different numbers describe one document and only one is comparable to
`num_articles_detected`. On a 16-page code that emitted 25 articles:

    JSON emitted                        25   <- the target
    unique article NUMBERS from source  28   <- TRUE source count, comparable
    lines matching exact "المادة N"     47   <- inflated: restarted codes
    is_article_line hits                81   <- inflated: chapters + digits
    total occurrences of "المادة"       68   <- inflated: cross-references

Report the unique-number figure. A header-line comparison manufactures a
phantom shortfall of 15+ where the real loss is 3. The detector also accepts
two non-article shapes -- bare-digit lines and `الفصل` (chapter) headers,
which are numbered 1..N exactly like articles and so collide in any set
comparison -- hence the per-kind breakdown below.

`true_article_count` here is the unique set taken from EXACT `المادة N` whole
lines only, which is the defensible definition. A figure computed over all
detector hits is numerically close but not equivalent, because bare-digit
lines contribute page numbers as if they were articles. If the two disagree,
trust the exact-only number and look at the breakdown for why.

IMPORTANT: a count shortfall is not the whole story. A file can report a
healthy-looking article count while every number in it is wrong, because a
broken digit-font ToUnicode CMap silently substitutes glyphs and the
pipeline's text-corruption gates do not see it. The DIGIT CORRUPTION block
below screens for that. Treat any non-clean verdict as "the numbers need
visual verification", not as "N articles are missing".

Also: a `QUALITY BLOCKED` verdict does NOT mean the JSON was removed. The
ISM pipeline writes JSON before calling validate_document, so rejected
output is still on disk. Check the gate verdict per file, never the
presence of its JSON.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

import fitz

sys.path.insert(0, "/home/mohammed/Mizan")

from fetching.pipeline_base.structure import (  # noqa: E402
    _article_header_info,
    is_article_line,
)

# Whole line is exactly an article header -> a real article, not a mention.
EXACT_AR = re.compile(r"^\s*الماد[ةه]\s*[\u0660-\u0669\u066b-\u0669\u06f0-\u06f90-9]+\s*$")
AR_HEADER = re.compile(r"(?m)^\s*الماد[ةه]\s*[\u0660-\u0669\u066b-\u0669\u06f0-\u06f90-9]+")
FR_HEADER = re.compile(r"(?mi)^\s*article\s+\d+")
# Chapters. Numbered 1..N like articles, so they must be excluded from any
# source count or set comparison.
CHAPTER_AR = re.compile(r"^\s*الفصل\b")
BARE_DIGIT = re.compile(r"^\d+$")

# Digit-font CMap corruption also mangles dates, and impossible years are
# greppable: Hijri 1444 renders as 3222/3232/3242, Gregorian 2022 as
# 6666/3266. Presence of these means the text layer's digits cannot be
# trusted for article numbers at all.
HIJRI_BAD = re.compile(r"\b3[12]\d\d\b")
GREG_BAD = re.compile(r"\b6666\b|\b3266\b|\b2255\b")


def digit_corruption(text: str) -> tuple[int, int]:
    return len(HIJRI_BAD.findall(text)), len(GREG_BAD.findall(text))


def read_pages(pdf: str) -> list[str]:
    doc = fitz.open(pdf)
    try:
        return [doc[i].get_text() for i in range(len(doc))]
    finally:
        doc.close()


def classify_hits(pages: list[str]) -> dict:
    """Split detector hits by line shape. Only exact article headers count."""
    kinds = {"exact": 0, "chapter": 0, "bare_digit": 0, "other": 0}
    unique_nums: set = set()
    for page in pages:
        for line in page.split("\n"):
            s = line.strip()
            if not s or not is_article_line(s)[0]:
                continue
            if CHAPTER_AR.match(s):
                kinds["chapter"] += 1
                continue
            if EXACT_AR.match(s):
                kinds["exact"] += 1
                # ONLY exact article headers contribute to the true count.
                # Bare-digit lines are page markers / years and "other"
                # matches are inline mentions -- both would inject phantom
                # article numbers into the comparable figure.
                _, num, _ = _article_header_info(s)
                if num is not None:
                    unique_nums.add(num)
            elif BARE_DIGIT.match(s):
                kinds["bare_digit"] += 1
            else:
                kinds["other"] += 1
    kinds["total_hits"] = sum(kinds[k] for k in ("exact", "chapter", "bare_digit", "other"))
    kinds["unique_numbers"] = len(unique_nums)
    return kinds


def replay_dedup(pages: list[str]) -> tuple[list[tuple], list[tuple]]:
    """Re-run the build_tree article loop and split hits into kept vs dropped.

    Mirrors the seen_articles contract: key is (number, inserted_qualifier);
    a repeated key is discarded as a cross-reference.
    """
    seen: set = set()
    kept: list[tuple] = []
    dropped: list[tuple] = []
    for pageno, page in enumerate(pages, start=1):
        for line in page.split("\n"):
            s = line.strip()
            if not s:
                continue
            if CHAPTER_AR.match(s):
                continue  # chapters are not articles
            if not is_article_line(s)[0]:
                continue
            _, num, inserted = _article_header_info(s)
            key = (num, inserted) if num is not None else None
            rec = (pageno, num, inserted, s[:70])
            if key is not None and key in seen:
                dropped.append(rec)
            else:
                if key is not None:
                    seen.add(key)
                kept.append(rec)
    return kept, dropped


def ordering_verdict(numbers: list) -> str:
    """Out-of-order emitted articles break citations regardless of count."""
    seq = [n for n in numbers if isinstance(n, int)]
    if len(seq) < 2:
        return "n/a"
    inversions = sum(1 for a, b in zip(seq, seq[1:]) if a > b)
    if inversions == 0:
        return "OK (strictly increasing)"
    return (
        f"DISQUALIFYING: {inversions}/{len(seq) - 1} out-of-order pairs. "
        "Citations resolve by lookup, so a scrambled tree returns the wrong "
        "article even where the article exists."
    )


def emitted_articles(doc: dict) -> list:
    """Walk the emitted structure tree and collect article nodes."""
    out: list = []

    def walk(nodes):
        for n in nodes or []:
            if isinstance(n, dict):
                if n.get("type") == "article":
                    out.append(n.get("number"))
                walk(n.get("children"))

    walk(doc.get("structure"))
    return out


def probe(pdf: str, json_path: str | None = None) -> dict:
    pages = read_pages(pdf)
    text = "\n".join(pages)
    kinds = classify_hits(pages)
    kept, dropped = replay_dedup(pages)
    hijri, greg = digit_corruption(text)
    r = {
        "pdf": pdf,
        "pages": len(pages),
        "chars": len(text),
        "raw_header_hits": len(AR_HEADER.findall(text)) + len(FR_HEADER.findall(text)),
        "kinds": kinds,
        "true_article_count": kinds["unique_numbers"],
        "detected_kept": len(kept),
        "dropped_by_dedup": len(dropped),
        "dropped_lines": dropped,
        "hijri_bad": hijri,
        "greg_bad": greg,
    }
    if json_path and os.path.exists(json_path):
        d = json.load(open(json_path, encoding="utf-8"))
        nums = emitted_articles(d)
        r["json"] = json_path
        r["emitted"] = len(nums)
        r["emitted_numbers"] = nums
        # Assumes contiguous 1..N numbering. Codes that restart per باب will
        # show spurious "missing" entries here -- cross-check against the
        # emitted-number list before quoting specific article numbers.
        r["missing"] = sorted(set(range(1, kinds["unique_numbers"] + 1)) - set(nums))
        r["ordering"] = ordering_verdict(nums)
    return r


def find_pdf_for(stem: str) -> str | None:
    hits = glob.glob(
        f"/home/mohammed/Mizan/data/corpus/*/raw/*/**/{stem}.pdf", recursive=True
    )
    return hits[0] if hits else None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2

    if "--json-dir" in sys.argv:
        base = sys.argv[sys.argv.index("--json-dir") + 1]
        print(
            f"{'json':<30} {'emitted':>8} {'true':>6} {'short':>6} {'chapters':>9}  gate"
        )
        print("-" * 78)
        blocked = 0
        for jp in sorted(glob.glob(f"{base}/**/*.json", recursive=True)):
            d = json.load(open(jp, encoding="utf-8"))
            stem = os.path.basename(jp)[: -len(".json")]
            pdf = find_pdf_for(stem)
            if not pdf:
                print(f"{stem:<30} {str(d.get('num_articles_detected')):>8}  (no pdf)")
                continue
            r = probe(pdf, jp)
            short = (r["true_article_count"] or 0) - (r["emitted"] or 0)
            order = r["ordering"]
            flag = "SUSPECT" if (r["hijri_bad"] or r["greg_bad"]) else ""
            if order.startswith("DISQUALIFY"):
                flag = (flag + " ORDER").strip()
                blocked += 1
            print(
                f"{stem:<30} {str(r['emitted']):>8} {r['true_article_count']:>6} "
                f"{short:>6} {r['kinds']['chapter']:>9}  {flag}"
            )
        print(f"\n{blocked} file(s) disqualified on ordering alone.")
        print("'true' = unique article NUMBERS (comparable to emitted).")
        print("'chapters' = الفصل lines the detector accepts; excluded from 'true'.")
        return 0

    for pdf in args:
        stem = os.path.splitext(os.path.basename(pdf))[0]
        cand = find_pdf_for(stem)
        jp = cand.replace("/raw/", "/json/").replace(".pdf", ".json") if cand else None
        r = probe(pdf, jp)
        k = r["kinds"]
        print(f"\n=== {r['pdf']} ===")
        print(f"pages={r['pages']} chars={r['chars']}")
        print(f"\n-- detector hits by kind (total {k['total_hits']}) --")
        print(f"  exact 'المادة N' (ARTICLES) : {k['exact']}")
        print(f"  الفصل headers   (chapters)  : {k['chapter']}   <- excluded from count")
        print(f"  bare-digit lines            : {k['bare_digit']}")
        print(f"  other matches               : {k['other']}")
        print(f"\nraw header hits   : {r['raw_header_hits']}   (NOT comparable to output)")
        print(f"TRUE article count : {r['true_article_count']}   (unique numbers)")
        print(f"detector kept     : {r['detected_kept']}")
        print(f"DROPPED BY DEDUP  : {r['dropped_by_dedup']}")
        for pageno, num, ins, line in r["dropped_lines"]:
            print(f"  p{pageno:<3} num={str(num):<5} ins={ins} | {line}")
        if "emitted" in r:
            print(f"\nJSON emitted      : {r['emitted']}  {r['emitted_numbers']}")
            short = r["true_article_count"] - r["emitted"]
            print(f"SHORTFALL         : {short} articles" + (f"  missing={r['missing']}" if short else ""))
            print(f"ORDERING          : {r['ordering']}")
        print("\nDIGIT CORRUPTION   :", end=" ")
        if r["hijri_bad"] or r["greg_bad"]:
            print(f"SUSPECT (hijri={r['hijri_bad']} greg={r['greg_bad']})"
                  " — article NUMBERS may be wrong, not just missing.")
            print("  Verify against the rendered page before fixing anything:")
            print("  render header bands at 400dpi, read them with vision.")
        else:
            print("clean (no impossible-year tokens)")
        print("\nNote: QUALITY BLOCKED does not remove the JSON from disk —")
        print("check the gate verdict per file, not the presence of its JSON.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())