#!/usr/bin/env python3
"""
Screen every ISM raw PDF for CMap garbling, then parse clean docs normally
and only force-OCR the garbled ones.

Usage:
    python scripts/ism_repair_screen_then_parse.py

What it does:
1. Deletes ALL JSONs in data/corpus/ism/json/ar/ (full wipe)
2. For each raw PDF: extracts text layer, runs corruption detection
3. Parses clean docs with force=False (~10s each)
4. Parses garbled docs with force=True (~40-60s each, OCR)
5. Verifies results: no garbled JSONs remain

Why screen first: the full LLM OCR normalization path has a 12s rate-limit
between chunks, making every doc ~200-400s. Screening lets clean docs skip
that path entirely. Mixed batch of 62 docs: ~12-15 min vs 30+ min.

Safety: raw PDFs are NEVER touched. Only JSON output files are overwritten.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fetching.pipeline_base import is_arabic_cmap_corrupt
from fetching.pipeline_base.extraction import extract_pages, ensure_models_loaded
from fetching.ism.parser.pipeline import process_file

RAW_DIR = Path("data/corpus/ism/raw/ar")
JSON_DIR = Path("data/corpus/ism/json/ar")
CACHE_DIR = Path("data/corpus/ism/cache")

STRUCTURAL_KEYWORDS = [
    "مادة", "قانون", "وزارة", "مرسوم", "ظهير",
    "المغرب", "المملكة", "الباب", "الفصل",
]

# Thresholds calibrated on ISM corpus (2026-09 audit)
MIN_ARABIC_FOR_GARBLE_CHECK = 3000
MAX_COMMON_FOR_GARBLE = 2


def is_ism_garbled(text: str) -> bool:
    """True when the text layer is CMap-corrupt but passed is_arabic_cmap_corrupt.

    The standard detector has a vocabulary early-out (>=8 common Moroccan legal
    words = clean). ISM garbled text often retains 1-3 common words by chance
    while the rest is mojibake — the early-out fires and the doc gets a flat
    single-preamble structure. This supplemental check catches that class.
    """
    arabic = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    if arabic <= MIN_ARABIC_FOR_GARBLE_CHECK:
        return False  # too short to be reliably garbled
    found = sum(1 for kw in STRUCTURAL_KEYWORDS if kw in text)
    return found <= MAX_COMMON_FOR_GARBLE


def main() -> None:
    ensure_models_loaded()

    # Phase 0: wipe existing JSONs (safe — raw PDFs are source of truth)
    existing = list(JSON_DIR.rglob("*.json"))
    if existing:
        print(f"Wiping {len(existing)} existing JSONs...")
        for f in existing:
            f.unlink()
        print("Done.\n")

    raw_pdfs = sorted(p for d in RAW_DIR.iterdir() if d.is_dir() for p in d.glob("*.pdf"))
    total = len(raw_pdfs)
    print(f"Found {total} raw PDFs to screen and parse.\n")

    # Phase 1: screen
    print("=== Phase 1: Screening ===")
    plan: list[tuple[str, str, bool]] = []  # (pdf_path, lang, force)
    garbled_count = 0
    clean_count = 0

    for i, pdf_path in enumerate(raw_pdfs, 1):
        stem = pdf_path.stem
        domain = pdf_path.parent.name
        rel = pdf_path.relative_to(RAW_DIR.parent)
        status = f"[{i:02d}/{total}] {domain}/{stem}.pdf"

        try:
            pages, mode, _tables = extract_pages(
                str(pdf_path), CACHE_DIR, language_hint="ar"
            )
        except Exception as exc:
            print(f"  {status}: extraction error ({exc}) — force OCR")
            plan.append((str(pdf_path), "ar", True))
            garbled_count += 1
            continue

        if not pages or not any(p.strip() for p in pages):
            print(f"  {status}: no text layer — force OCR")
            plan.append((str(pdf_path), "ar", True))
            garbled_count += 1
            continue

        text = " ".join(pages)
        arabic = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
        cmap = is_arabic_cmap_corrupt(pages)
        ism_garbled = is_ism_garbled(text)
        common = sum(1 for kw in STRUCTURAL_KEYWORDS if kw in text)

        if cmap or ism_garbled:
            print(
                f"  {status}: GARBLED (cmap={cmap}, ism_garbled={ism_garbled}, "
                f"arabic={arabic}, common={common}) — force OCR"
            )
            plan.append((str(pdf_path), "ar", True))
            garbled_count += 1
        else:
            print(
                f"  {status}: clean (arabic={arabic}, common={common}) — normal parse"
            )
            plan.append((str(pdf_path), "ar", False))
            clean_count += 1

    print(f"\nScreening done: {clean_count} clean, {garbled_count} garbled\n")

    # Phase 2: parse
    print("=== Phase 2: Parsing ===")
    ok = 0
    errors: list[tuple[str, str]] = []

    for i, (pdf_path, lang, force) in enumerate(plan, 1):
        label = f"{pdf_path}"
        t0 = time.time()
        try:
            process_file(pdf_path, lang=lang, force=force)
            dt = time.time() - t0
            tag = "FORCE" if force else "native"
            print(f"  [{i:02d}/{len(plan)}] {Path(pdf_path).stem}.pdf: OK ({dt:.1f}s, {tag})")
            ok += 1
        except Exception as exc:
            dt = time.time() - t0
            msg = f"{type(exc).__name__}: {exc}"
            print(f"  [{i:02d}/{len(plan)}] {Path(pdf_path).stem}.pdf: ERROR ({dt:.1f}s) — {msg}")
            errors.append((pdf_path, msg))

    # Phase 3: verify
    print("\n=== Phase 3: Verification ===")
    json_count = len(list(JSON_DIR.rglob("*.json")))
    print(f"JSONs on disk: {json_count} (expected {total})")

    remaining_garbled = 0
    for js_path in sorted(JSON_DIR.rglob("*.json")):
        try:
            doc = json.loads(js_path.read_text())
        except Exception:
            print(f"  UNREADABLE: {js_path.relative_to(JSON_DIR)}")
            remaining_garbled += 1
            continue

        text = " ".join(
            b.get("content", "") for b in doc.get("structure", []) if b.get("content")
        )
        if len(text) < 500:
            continue

        arabic = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
        common = sum(1 for kw in STRUCTURAL_KEYWORDS if kw in text)
        n_articles = sum(
            1
            for b in doc.get("structure", [])
            if b.get("type") == "article" and b.get("content")
        )

        # Check domain match
        folder = js_path.parent.name
        ld = doc.get("legal_domain", "")
        domain_ok = folder == ld

        if arabic > MIN_ARABIC_FOR_GARBLE_CHECK and common <= MAX_COMMON_FOR_GARBLE:
            remaining_garbled += 1
            print(
                f"  GARBLED: {js_path.relative_to(JSON_DIR)} "
                f"(arabic={arabic}, common={common}, articles={n_articles}, "
                f"domain={'OK' if domain_ok else 'MISMATCH'})"
            )

    print(f"\nRemaining garbled: {remaining_garbled}")
    print(f"Parse errors: {len(errors)}")
    for p, e in errors:
        print(f"  {p}: {e}")

    if remaining_garbled == 0 and len(errors) == 0:
        print("\nALL CLEAN — corpus is good.")
    else:
        print("\nISSUES REMAIN — review above.")


if __name__ == "__main__":
    main()
