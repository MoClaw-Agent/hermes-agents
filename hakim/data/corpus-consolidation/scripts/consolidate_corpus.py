#!/usr/bin/env python
"""Consolidate overlapping raw PDF corpora into one namespaced, manifest-backed set.

Order matters: namespace BEFORE materialising, manifest BEFORE dedup reporting.
Exact-hash dedup only -- fuzzy/near-duplicate detection is deferred until the text
layer is trustworthy (see SKILL.md rule 8).

Materialises with hardlinks, so a multi-GB consolidation costs no disk and removing the
output cannot damage the source tree.

    python consolidate_corpus.py --out OUT_DIR [--no-link]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")

# Bidi controls, zero-width joiners and the BOM that scraped slugs carry
# (e.g. "\u202b\u0638\u0647\u064a\u0631\u202c\u202b\u0634\u0631\u064a\u0641\u202c ...").
INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
STAMP = re.compile(r"_\d{10,}$")

STOPWORDS = (
    "في من على إلى عن مع هذا هذه التي الذي أن إن ما لا قد كل بعد قبل بين "
    "عند تحت فوق كما حيث وهو وهي"
).split()

HEALTH_RANK = {"clean": 0, "suspect": 1, "ciphered": 2, "empty": 3}

PROBE_PAGES = 4
CHUNK = 1 << 20


def clean_stem(stem: str, limit: int = 90) -> str:
    """Normalise a filename into a safe, readable token.

    Strip by codepoint range, not by guesswork: a directional mark left in place makes
    two visually identical names compare unequal, and the download stamp defeats
    basename matching against a sidecar.
    """
    s = INVISIBLE.sub("", stem)
    s = unicodedata.normalize("NFC", s)
    s = STAMP.sub("", s)
    s = UNSAFE.sub("_", s)
    s = re.sub(r"\s+", "_", s.strip())
    s = re.sub(r"_+", "_", s).strip("._-")
    if len(s) > limit:
        s = s[:limit].rstrip("_.-")
    return s or "untitled"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def page_count(path: Path) -> int | None:
    try:
        import fitz
    except ImportError:
        return None
    try:
        with fitz.open(path) as doc:
            return len(doc)
    except Exception:
        return None


def probe_text(path: Path, pages: int = PROBE_PAGES) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    try:
        with fitz.open(path) as doc:
            return "\n".join((doc[i].get_text() or "") for i in range(min(pages, len(doc))))
    except Exception:
        return ""


def arabic_chars(text: str) -> int:
    return len(re.findall(r"[\u0600-\u06ff]", text))


def content_health(text: str) -> str:
    """Floor, not a verdict -- see SKILL.md rule 6.

    'empty' means image-only and needs OCR; 'ciphered' means a glyph-substitution
    cipher (rule 7), which a digit-plausibility detector scores as clean.
    """
    if arabic_chars(text) < 50:
        return "empty"
    hits = sum(1 for w in STOPWORDS if w in text)
    if hits >= 6:
        return "clean"
    return "suspect" if hits >= 2 else "ciphered"


def read_sidecar(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sidecar_for(pdf: Path) -> Path | None:
    s = pdf.with_name(pdf.name.replace(".pdf", ".meta.json"))
    return s if s.exists() else None


def discover(roots: list[tuple[str, Path]]) -> list[dict]:
    """roots: list of (source_name, directory). Walks recursively for *.pdf."""
    found: list[dict] = []
    for source, root in roots:
        if not root.exists():
            print(f"  WARNING: {source} root missing: {root}", file=sys.stderr)
            continue
        for pdf in sorted(root.rglob("*.pdf")):
            rel = pdf.relative_to(root)
            domain = rel.parts[-2] if len(rel.parts) >= 2 else "unsorted"
            sc_path = sidecar_for(pdf)
            sc = read_sidecar(sc_path) if sc_path else {}
            found.append({
                "source": source,
                "origin_path": pdf,
                "domain": domain,
                "raw_stem": pdf.stem,
                "title_hint": sc.get("title"),
                "sidecar_path": sc_path,
                "sidecar": sc,
            })
    return found


MANIFEST_FIELDS = [
    "rel_path", "sidecar_rel_path", "source", "domain", "sha256", "bytes", "pages",
    "content_health", "declared_ref", "declared_title", "language",
    "arabic_chars_probe", "duplicate_count", "origin_path",
    "source_url", "scraped_at", "downloaded_at", "bo_number", "doc_date",
    "legal_rank", "legal_domain", "effective_date", "is_amendment",
    "amends_doc_ref", "subject", "has_sidecar", "sidecar_content_hash",
    "content_hash_agrees",
]


def build(out_dir: Path, roots: list[tuple[str, Path]], link: bool = True) -> int:
    (out_dir / "pdf").mkdir(parents=True, exist_ok=True)
    (out_dir / "meta").mkdir(parents=True, exist_ok=True)

    items = discover(roots)
    print(f"[1/4] discovered {len(items)} PDFs {dict(Counter(i['source'] for i in items))}")

    # Phase 2 -- namespace. Do this before any materialisation.
    used: dict[str, int] = defaultdict(int)
    for it in items:
        base = f"{it['source']}__{clean_stem(it['domain'])}__{clean_stem(it['raw_stem'])}"
        if base in used:
            base = f"{base}__{used[base]}"
        used[base] += 1
        it["rel_path"] = f"pdf/{base}.pdf"
    collisions = sum(1 for v in used.values() if v > 1)
    print(f"[2/4] namespaced {len(items)} files; {collisions} collisions disambiguated")

    # Phase 3 -- manifest rows.
    by_hash: dict[str, list[dict]] = defaultdict(list)
    for idx, it in enumerate(items, 1):
        src: Path = it["origin_path"]
        digest = sha256_of(src)
        it["sha256"] = digest
        it["bytes"] = src.stat().st_size
        it["pages"] = page_count(src)
        text = probe_text(src)
        it["content_health"] = content_health(text)
        it["arabic_chars_probe"] = arabic_chars(text)
        it["declared_title"] = it["title_hint"] or clean_stem(it["raw_stem"]).replace("_", " ")
        m = re.search(r"\d+[.\-]\d+[.\-]?\d*", it["raw_stem"])
        it["declared_ref"] = m.group(0).replace("-", ".") if m else None
        it["language"] = "ar"

        sc = it["sidecar"]
        it["source_url"] = sc.get("source_url")
        it["scraped_at"] = sc.get("scraped_at")
        it["downloaded_at"] = sc.get("downloaded_at")
        it["bo_number"] = sc.get("bo_number")
        it["doc_date"] = sc.get("date")
        it["legal_rank"] = sc.get("legal_rank")
        it["legal_domain"] = sc.get("legal_domain")
        it["effective_date"] = sc.get("effective_date")
        it["is_amendment"] = sc.get("is_amendment")
        it["amends_doc_ref"] = sc.get("amends_doc_ref")
        it["subject"] = sc.get("subject")
        it["sidecar_content_hash"] = sc.get("content_hash")
        it["has_sidecar"] = bool(it["sidecar_path"])
        # Independent witness (rule 5): written by the crawler, not by us.
        it["content_hash_agrees"] = (
            (it["sidecar_content_hash"] == digest) if it["sidecar_content_hash"] else None
        )

        by_hash[digest].append(it)
        if idx % 500 == 0:
            print(f"      hashed {idx}/{len(items)}")

    # Phase 4 -- exact-hash dedup. Record, never delete (rule 9).
    survivors, dropped = [], []
    for group in by_hash.values():
        if len(group) == 1:
            survivors.append(group[0])
            continue
        ordered = sorted(group, key=lambda r: (
            HEALTH_RANK.get(r["content_health"], 9), len(r["rel_path"]), r["rel_path"]))
        keep, rest = ordered[0], ordered[1:]
        keep["duplicate_count"] = len(group) - 1
        survivors.append(keep)
        for r in rest:
            r["duplicate_of"] = keep["rel_path"]
            dropped.append(r)
    print(f"[3/4] exact-hash dedup: {len(survivors)} survivors, {len(dropped)} recorded")

    made = linked_meta = 0
    for it in survivors:
        dst = out_dir / it["rel_path"]
        if not dst.exists():
            try:
                os_link_or_copy(src=it["origin_path"], dst=dst, link=link)
                made += 1
            except OSError as exc:
                print(f"      LINK FAILED {dst}: {exc}", file=sys.stderr)
        sp = it.get("sidecar_path")
        if sp:
            mdst = out_dir / "meta" / (Path(it["rel_path"]).stem + ".meta.json")
            it["sidecar_rel_path"] = str(mdst.relative_to(out_dir))
            if not mdst.exists():
                try:
                    os_link_or_copy(src=sp, dst=mdst, link=link)
                    linked_meta += 1
                except OSError as exc:
                    print(f"      SIDECAR LINK FAILED {mdst}: {exc}", file=sys.stderr)

    with (out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        w.writeheader()
        for it in sorted(survivors, key=lambda r: r["rel_path"]):
            w.writerow({k: it.get(k) for k in MANIFEST_FIELDS})

    with (out_dir / "duplicates.jsonl").open("w", encoding="utf-8") as fh:
        for it in dropped:
            fh.write(json.dumps({
                "rel_path": it["rel_path"], "sha256": it["sha256"],
                "origin_path": str(it["origin_path"]),
                "duplicate_of": it["duplicate_of"],
            }, ensure_ascii=False) + "\n")

    health = Counter(r["content_health"] for r in survivors)
    agree = [r for r in survivors if r["content_hash_agrees"] is True]
    disagree = [r for r in survivors if r["content_hash_agrees"] is False]
    summary = {
        "discovered": len(items),
        "survivors": len(survivors),
        "exact_duplicates_recorded": len(dropped),
        "accounting_balances": len(survivors) + len(dropped) == len(items),
        "by_source": dict(Counter(r["source"] for r in survivors)),
        "content_health": dict(health),
        "needs_ocr": sum(1 for r in survivors if r["content_health"] == "empty"),
        "files_created": made,
        "sidecars_linked": linked_meta,
        "survivors_with_sidecar": sum(1 for r in survivors if r["has_sidecar"]),
        "content_hash_agreements": len(agree),
        "content_hash_disagreements": len(disagree),
        "disagreeing_files": [r["rel_path"] for r in disagree],
        "manifest_column_population": {
            f: sum(1 for r in survivors if r.get(f))
            for f in ("source_url", "bo_number", "effective_date", "legal_domain", "subject")
        },
        "notes": [
            "content_health is a floor, not a verdict.",
            "Exact-hash dedup only; near-duplicate detection deferred until text is "
            "readable.",
            "Hardlinks: removing this output cannot damage the sources.",
        ],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[4/4] manifest.csv ({len(survivors)} rows), duplicates.jsonl, summary.json")
    print(f"      created {made} files + {linked_meta} sidecars")
    print(f"      health: {dict(health)}")
    print(f"      hash cross-check: {len(agree)} agree, {len(disagree)} disagree")
    if disagree:
        for r in disagree:
            print(f"      DISAGREE {r['rel_path']}")
    return 0


def os_link_or_copy(src: Path, dst: Path, link: bool) -> None:
    import os
    if link:
        os.link(src, dst)
    else:
        dst.write_bytes(src.read_bytes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--root", action="append", default=[], metavar="NAME=PATH",
                    help="provider source name and raw directory (repeatable)")
    ap.add_argument("--no-link", action="store_true", help="copy instead of hardlink")
    args = ap.parse_args()

    roots = []
    for spec in args.root:
        if "=" not in spec:
            print(f"bad --root {spec!r}, expected NAME=PATH", file=sys.stderr)
            return 2
        name, path = spec.split("=", 1)
        roots.append((name, Path(path).resolve()))
    if not roots:
        print("at least one --root NAME=PATH is required", file=sys.stderr)
        return 2

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"output: {out}")
    return build(out, roots, link=not args.no_link)


if __name__ == "__main__":
    raise SystemExit(main())