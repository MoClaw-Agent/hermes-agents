#!/usr/bin/env python3
"""Re-read article numbers from rendered pixels, WITHOUT a VLM.

The prose text layer of a CMap-damaged PDF is intact; only the digit glyphs
decode wrongly. So prose never needs OCR — only the short digit runs that
follow an article keyword do. This renders those runs and template-matches them
against `0-9` rendered from the document's own embedded font.

**MEASURED AT 11.3% SELF-CONSISTENCY ON CLEAN FILES — THIS DOES NOT WORK.**
Kept as a reference for the failure mode and the PyMuPDF API traps, not as a
recommended fix. Do not ship a reader built this way without first running the
negative control below.

WHY A POSITIVE SCORE LIES
A 5/7 score on seven hand-read pairs from a single already-suspicious file is
coincidence, not accuracy. Small labelled sets on suspect files cannot validate
an extractor, because those files are exactly the population where failure is
already suspected. You need a NEGATIVE CONTROL: files whose text layer is
known correct, where the reader must simply agree.

    CLEAN-FILE SELF-CONSISTENCY: 12/106 = 11.3%   <- broken
    truth=42 read=34   truth=0 read=5   truth=1 read=6

Run that first, on files with zero impossible-year signature, before believing
any positive score.
"""
from __future__ import annotations

import sys

import fitz
import numpy as np

DPI = 400
GW, GH = 22, 30
THRESH = 0.70
KEYWORDS = ("المادة", "الماده", "الفصل", "فصل")


# ── PyMuPDF API traps, all of which fail SILENTLY ────────────────────────────

def to_gray(pix):
    """Pixmap samples -> 2-D float grayscale.

    TRAP: `samples` is a flat buffer of height*stride bytes where
    stride == width*n. Reshaping to (height, stride, n) raises, and averaging
    over axis=1 collapses to 1-D so the mask silently goes empty.
    """
    a = np.frombuffer(pix.samples, np.uint8)
    w, n, alpha = pix.width, pix.n, 1 if pix.alpha else 0
    ch = n - alpha
    need = pix.height * pix.stride
    if a.size < need:
        a = np.pad(a, (0, need - a.size))
    a = a[:need].reshape(pix.height, pix.stride)[:, :w * ch]
    if ch >= 3:
        g = a.reshape(pix.height, w, ch)[:, :, :3].mean(axis=2)
    else:
        g = a.reshape(pix.height, w)
    return g.astype(np.float32)


def fit(img, w, h):
    yi = (np.arange(h) * img.shape[0] / h).astype(int).clip(0, img.shape[0] - 1)
    xi = (np.arange(w) * img.shape[1] / w).astype(int).clip(0, img.shape[1] - 1)
    return img[np.ix_(yi, xi)]


def ncc(a, b):
    a, b = a - a.mean(), b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


def segment(band_ink):
    """Split a 2-D ink array into glyph column-blobs.

    TRAP: accept EITHER a grayscale array or an already-bool mask. Testing
    `bool_mask.max(axis=0) > 40` yields all-False and returns [] with no error,
    which reads as "no digits found" rather than as a bug.
    """
    on = band_ink.max(axis=0)
    if band_ink.dtype != bool:
        on = on > 40
    if not on.any():
        return []
    runs, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(on)])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= 2:  # antialiasing can split one glyph
            merged[-1][1] = r[1]
        else:
            merged.append([r[0], r[1]])
    return [(a, b) for a, b in merged]


def page_chars(page):
    """[(char, Rect)] in LOGICAL order.

    TRAP: get_texttrace() emits Arabic in reversed visual order, so keyword
    search never matches there. Use get_text("rawdict") — logical order, with
    per-character bboxes.
    """
    out = []
    for blk in page.get_text("rawdict").get("blocks", []):
        for line in blk.get("lines", []):
            for sp in line.get("spans", []):
                for ch in sp.get("chars", []):
                    out.append((ch["c"], fitz.Rect(ch["bbox"])))
    return out


def get_font(doc):
    best, buf, nm = 0, None, None
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Type")[1] != "/Font":
                continue
            bf = doc.xref_get_key(xref, "BaseFont")[1] or ""
            _, _, _, b = doc.extract_font(xref)
            if b and "Times" in bf and len(b) > best:
                best, buf, nm = len(b), b, bf
        except Exception:
            continue
    return nm, buf


def ref_masks(font):
    """0-9 rendered from the document's own font, one glyph per scratch page.

    Rendering all ten onto one page lets a wide glyph bleed into its neighbour
    and corrupt the next reference; one page each keeps crops independent.
    """
    out = {}
    for d in "0123456789":
        doc = fitz.open()
        page = doc.new_page(width=140, height=170)
        page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
        # TextWriter.write_text needs a Page/Rect, never a Pixmap (Pixmap has
        # no .rect) — another trap that fails as a confusing AttributeError.
        tw = fitz.TextWriter(page.rect)
        tw.append((30, 120), d, font=font, fontsize=72)
        tw.write_text(page, color=(0, 0, 0))
        g = 255.0 - to_gray(page.get_pixmap(dpi=300, clip=page.rect))
        ys, xs = np.nonzero(g > 60)
        if len(ys):
            m = fit(g[ys.min():ys.max() + 1, xs.min():xs.max() + 1], GW, GH)
            out[d] = (m / m.max()).astype(np.float32)
        doc.close()
    return out


def reread(path, max_pages=None, thresh=THRESH):
    doc = fitz.open(path)
    nm, buf = get_font(doc)
    refs = ref_masks(fitz.Font(fontbuffer=buf)) if buf else {}
    rows = []
    for pno in range(len(doc) if max_pages is None else min(len(doc), max_pages)):
        page = doc[pno]
        chars = page_chars(page)
        s = "".join(c[0] for c in chars)
        for kw in KEYWORDS:
            start = 0
            while True:
                k = s.find(kw, start)
                if k < 0:
                    break
                j = k + len(kw)
                while j < len(chars) and chars[j][0] in " .:- ":
                    j += 1
                run = []
                while j < len(chars) and chars[j][0].isascii() and chars[j][0].isdigit():
                    run.append(chars[j])
                    j += 1
                if run:
                    # Per-char bboxes COLLAPSE on a broken CMap — every digit in
                    # a run crops to the same blob. Segment the whole rendered
                    # band by ink-column gaps instead.
                    ry0 = min(r[1].y0 for r in run)
                    ry1 = max(r[1].y1 for r in run)
                    rh = ry1 - ry0
                    bx0 = min(r[1].x0 for r in run)
                    bx1 = max(r[1].x1 for r in run)
                    band = fitz.Rect(bx0 - 3, ry0 - rh * 0.30,
                                     bx1 + 3, ry1 + rh * 0.30) & page.rect
                    if not band.is_empty and band.width > 2:
                        g = 255.0 - to_gray(page.get_pixmap(dpi=DPI, clip=band))
                        out = ""
                        for a, b in segment(g > 40):
                            sub = g[:, a:b]
                            ys, xs = np.nonzero(sub > 40)
                            if not len(ys):
                                out += "?"
                                continue
                            m = fit(sub[ys.min():ys.max() + 1, :], GW, GH)
                            m = m / m.max() if m.max() else m
                            sc = sorted(((ncc(m.astype(np.float32), rm), d)
                                         for d, rm in refs.items()), reverse=True)
                            out += sc[0][1] if sc and sc[0][0] > thresh else "?"
                        rows.append({"page": pno + 1,
                                     "claimed": "".join(r[0] for r in run),
                                     "reread": out})
                start = k + len(kw)
    doc.close()
    return rows


def selfcheck(paths):
    """NEGATIVE CONTROL — run this before trusting any positive score.

    On clean files the text layer is known correct, so the reader must agree
    with it. Needs no labels at all.
    """
    total = agree = 0
    disagreements = []
    for p in paths:
        for r in reread(p, max_pages=12):
            total += 1
            if r["claimed"] == r["reread"]:
                agree += 1
            else:
                disagreements.append((p, r))
    rate = 100.0 * agree / max(1, total)
    print(f"CLEAN-FILE SELF-CONSISTENCY: {agree}/{total} = {rate:.1f}%")
    for p, r in disagreements[:20]:
        print(f"  {p} p{r['page']} truth={r['claimed']} read={r['reread']}")
    return rate


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck([a for a in args if a != "--selfcheck"])
    else:
        for p in args:
            print(p)
            for r in reread(p, max_pages=15):
                print(f"  p{r['page']:<4} claimed={r['claimed']:<6} reread={r['reread']}")
