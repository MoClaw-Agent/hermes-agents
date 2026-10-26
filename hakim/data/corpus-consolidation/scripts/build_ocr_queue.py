#!/usr/bin/env python
"""Build a health-tiered OCR queue from a consolidated corpus manifest.

Tiers by severity of silent failure, NOT by importance -- rank by importance afterwards
with rank_ocr_by_importance.py. Image-only PDFs are first: they index as empty
documents and look complete, so their failure is silent.

Emits ocr_queue.csv, ocr_batch_NN.jsonl, ocr_full_corpus.jsonl, ocr_queue_summary.json
into --out. Writes nothing into the source tree.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

TIER = {"empty": 1, "ciphered": 2, "suspect": 3, "clean": 4}
TIER_LABEL = {
    1: "image_only_no_text",
    2: "ciphered_unreadable",
    3: "suspect_needs_verification",
    4: "already_readable",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/corpus_consolidated")
    ap.add_argument("--batch-size", type=int, default=50)
    args = ap.parse_args()

    corpus = Path(args.corpus).resolve()
    with (corpus / "manifest.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    for r in rows:
        r["pages"] = int(r["pages"]) if r["pages"] else 0
        r["tier"] = TIER.get(r["content_health"], 9)
        r["tier_label"] = TIER_LABEL.get(r["tier"], "unknown")
        r["needs_ocr"] = r["tier"] <= 3

    # largest first inside a tier: biggest OCR bill surfaces earliest
    rows.sort(key=lambda r: (r["tier"], -r["pages"], r["rel_path"]))
    for i, r in enumerate(rows, 1):
        r["queue_pos"] = i

    with (corpus / "ocr_queue.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "queue_pos", "tier", "tier_label", "needs_ocr", "rel_path", "source",
            "domain", "pages", "content_health", "sha256", "declared_title",
        ], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    need = [r for r in rows if r["needs_ocr"]]
    batches = defaultdict(list)
    for i, r in enumerate(need):
        batches[i // args.batch_size].append(r)

    for idx in sorted(batches):
        p = corpus / f"ocr_batch_{idx:02d}.jsonl"
        with p.open("w", encoding="utf-8") as fh:
            for r in batches[idx]:
                fh.write(json.dumps({
                    "path": r["rel_path"], "sha256": r["sha256"],
                    "pages": r["pages"], "tier": r["tier"],
                    "tier_label": r["tier_label"],
                    "source": r["source"], "domain": r["domain"],
                }, ensure_ascii=False) + "\n")

    with (corpus / "ocr_full_corpus.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({
                "path": r["rel_path"], "sha256": r["sha256"],
                "pages": r["pages"], "content_health": r["content_health"],
            }, ensure_ascii=False) + "\n")

    per_tier = defaultdict(lambda: {"docs": 0, "pages": 0})
    for r in rows:
        t = per_tier[r["tier_label"]]
        t["docs"] += 1
        t["pages"] += r["pages"]

    summary = {
        "corpus_documents": len(rows),
        "documents_needing_ocr": len(need),
        "documents_already_readable": len(rows) - len(need),
        "batch_size": args.batch_size,
        "batches_emitted": len(batches),
        "total_pages": sum(r["pages"] for r in need),
        "per_tier": {
            k: {"docs": v["docs"], "pages": v["pages"],
                "share_of_corpus": round(100 * v["docs"] / len(rows), 2)}
            for k, v in sorted(per_tier.items())
        },
        "per_batch": {
            f"ocr_batch_{i:02d}.jsonl": {
                "docs": len(batches[i]),
                "pages": sum(r["pages"] for r in batches[i]),
            }
            for i in sorted(batches)
        },
        "note": (
            "Severity ordering only. content_health is a floor, not a verdict: "
            "'suspect' documents may already be fine. A fluent OCR result is NOT "
            "evidence of correctness -- apply references/citability-and-numeric-"
            "integrity.md before accepting any OCR output."
        ),
    }
    (corpus / "ocr_queue_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"corpus documents : {len(rows)}")
    print(f"needing OCR      : {len(need)}")
    print(f"already readable : {len(rows) - len(need)}")
    print(f"batches          : {len(batches)} (size {args.batch_size})")
    for k, v in sorted(summary["per_tier"].items()):
        print(f"  {k:32s} {v['docs']:5d} docs  {v['pages']:6d} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())