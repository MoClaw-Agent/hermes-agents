>#!/usr/bin/env python3
"""Render article-header bands for visual verification of digit-CMap corruption.

Use this when `scripts/article_loss_probe.py` reports SUSPECT, or when a file's
article numbers are suspected wrong. The probe tells you the text layer is
untrustworthy; only a rendered pixel is ground truth.

Emits one tight PNG per article header plus the text-layer token that occupies
the same band, so the two can be compared side by side. Read the PNGs with the
vision tool, then confirm the hypothesis by solving for a per-digit
substitution map across several pairs (see `check_map` below).

    MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \\
      venv/bin/python scripts/digit_cmap_verify.py <pdf> [--out DIR] [--limit N]

Run with the project venv; the Hermes kernel python has no fitz.

Two things this handles that a naive crop gets wrong:

  * `get_text("words")` SPLITS a header like `المادة511` into separate tokens,
    so filtering for a token equal to the full header finds nothing. Anchor on
    the keyword (`الماد`) and take the whole line band instead.
  * The number is often NOT on the keyword's own baseline -- it can sit on the
    next line, or be offset horizontally. A tight crop around the word's bbox
    excludes it and the vision read returns a bare dash. Pad generously.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import fitz

KEYWORD = "الماد"
DPI = 400
# Generous padding. The printed number is frequently offset from the keyword's
# own baseline, so a tight bbox crop is the most common way a visual check
# silently returns "no number here" and gets misread as "no corruption".
PAD_UP = 25
PAD_DN = 25
PAD_LEFT = 30


def find_headers(pdf: str, limit: int) -> list[tuple[int, fitz.Rect, str]]:
    """Return (page_index, clip_rect, text_layer_band) for each header."""
    out: list[tuple[int, fitz.Rect, str]] = []
    doc = fitz.open(pdf)
    try:
        for pno in range(len(doc)):
            pg = doc[pno]
            for w in pg.get_text("words"):
                if not w[4].startswith(KEYWORD):
                    continue
                band = " ".join(
                    pg.get_text(
                        clip=fitz.Rect(w[0], w[1], min(pg.rect.x1, w[0] + 260), w[3])
                    ).split()
                )
                # Require a number or ordinal right after the keyword, and reject
                # in-prose cross-references ("بمقتضى المادة 57 من القانون ...").
                if not re.match(r"^الماد[ةه]\s*\S", band):
                    continue
                if re.search(r"(بمقتضى|مشار إليه|السالف|من القانون|من المرسوم|هذه المادة)", band):
                    continue
                clip = fitz.Rect(
                    max(0, w[0] - PAD_LEFT),
                    max(0, w[1] - PAD_UP),
                    pg.rect.x1,
                    min(pg.rect.y1, w[3] + PAD_DN),
                )
                out.append((pno, clip, band[:60]))
                if len(out) >= limit:
                    return out
    finally:
        doc.close()
    return out


def check_map(pairs: list[tuple[str, str]]) -> bool:
    """True when one per-digit map explains every (text_layer, printed) pair.

    Digit runs are right-aligned because Arabic renders RTL. If this returns
    False the same text digit decodes to different printed digits in different
    places, which means the corruption is positional rather than a font-table
    substitution -- so there is NO deterministic repair function and no
    in-text-layer fix is possible. Route the file to vision/OCR instead.

    pairs: [("1", "5"), ("22", "11"), ...] as read off the rendered crops.
    """
    mapping: dict[str, str] = {}
    conflicts: list[str] = []
    for text_tok, printed in pairs:
        for a, b in zip(text_tok[::-1], printed[::-1]):
            if a in mapping and mapping[a] != b:
                conflicts.append(f"text digit {a!r} -> {b!r} (already {mapping[a]!r})")
            mapping.setdefault(a, b)
    if conflicts:
        for c in conflicts:
            print(f"  CONFLICT: {c}")
    print("consistent per-digit map:", not conflicts)
    return not conflicts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default="/home/mohammed/.hermes/cache/scratch")
    ap.add_argument("--limit", type=int, default=8)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    stem = os.path.basename(a.pdf).rsplit(".", 1)[0]
    headers = find_headers(a.pdf, a.limit)
    if not headers:
        print("no article headers located — check the keyword or the numbering unit")
        return 1

    print(f"{a.pdf}: {len(headers)} header band(s)")
    for i, (pno, clip, band) in enumerate(headers):
        doc = fitz.open(a.pdf)
        pix = doc[pno].get_pixmap(dpi=DPI, clip=clip)
        doc.close()
        out = os.path.join(a.out, f"hdr_{stem}_p{pno + 1}_{i}.png")
        pix.save(out)
        print(f"  p{pno + 1:<4} text={band!r}\n        {out}")

    print(
        "\nNow read each PNG with vision and record (text_layer, printed) pairs.\n"
        "Then run check_map(pairs) to decide whether any in-text-layer repair\n"
        "is even possible before proposing a fix."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
