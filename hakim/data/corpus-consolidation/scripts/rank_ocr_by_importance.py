#!/usr/bin/env python
"""Re-rank the OCR queue by DOCUMENT IMPORTANCE rather than severity of failure.

Severity optimises for data hygiene; importance optimises for the user. An unreadable
circular is cheaper to leave broken than an unreadable constitution. Ranks the queue
produced by build_ocr_queue.py and rewrites the batch files.

Score = instrument class (dominant) + 0.35 * legal domain + log-scale page count
+ reference presence. Every row carries score_breakdown so the ranking can be audited
or overridden rather than trusted -- a weighting nobody can inspect is a weighting
nobody can correct.

Reads declared_ref from manifest.csv, not from the queue: a queue may carry only
declared_title, and inferring identity from a title loses the field entirely.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# (class, weight, cues) -- first match wins. Arabic + French; add cues as domains grow.
CLASS_RULES: list[tuple[str, int, tuple[str, ...]]] = [
    ("constitution",      100, ("دستور", "constitution")),
    ("organic_law",        95, ("قانون apearf", "قانون أساسي", "loi organique", "organic")),
    ("code",               92, ("مدونة", "code de", "code du", "code des", "قانون الالتزامات")),
    ("procedure_code",     88, ("المسطرة المدنية", "المسطرة الجنائية",
                                "procédure civile", "procédure pénale")),
    ("companies",          78, ("شركات المساهمة", "شركة التضامن", "التوصية البسيطة",
                                "société anonyme")),
    ("status_persons",     74, ("الحالة المدنية", "الأحوال الشخصية", "statut")),
    ("labor",              72, ("الشغل", "العمل", "travail")),
    ("commercial",         70, ("التجارة", "الملكية الصناعية", "commerce",
                                "propriété industrielle")),
    ("public_law",         68, ("الجماعات", "العمالات", "جهات", "collectivités",
                                "regions", "provinces")),
    ("penal",              66, ("الجناي", "الجنائي", "pénal", "correctionnel")),
    ("family",             64, ("الأسرة", "الأسري", "famille")),
    ("fiscal",             58, ("المالية", "الجبائية", "الضريبة", "finances", "fiscal")),
    ("health",             52, ("الصحة", "sanitaire", "santé")),
    ("environment",        48, ("البيئة", "environnement")),
    ("real_estate",        46, ("العقارية", "القرض العقاري", "immobilier", "foncier")),
    ("water",              44, ("الماء", "eaux", "eau")),
    ("treaty",             40, ("اتفاقية", "convention")),
    ("decree",             34, ("مرسوم", "decret", "décret")),
    ("order",              26, ("قرار", "arrêté", "arrete")),
    ("circular",           18, ("دورية", "منشور", "circulaire", "note")),
    ("report",             12, ("تقرير", "rapport", "programme", "مشروع")),
]
CLASS_DEFAULT = ("other", 25)

DOMAIN_RANK = {
    "المادة المدنية": 80, "المادة الجنائية": 78, "المادة الأسرية": 76,
    "المادة الإدارية": 68, "المادة التجارية": 70, "مادة الوظيفة العمومية": 60,
    "المادة المالية": 58, "المادة الجبائية": 55, "المادة الأمنية": 62,
    "مادة المهن": 60, "مادة التربية والتعليم": 48,
    "مادة الصناعة والاقتصاد والاستثمار": 46,
    "مادة اختصاصات وتنظيم القطاعات الحكومية والمؤسساتية": 52,
    "المادة الاجتماعية": 56, "المادة العقارية": 50, "مادة الفلاحة": 40,
    "المادة البيئية": 38, "مادة الطاقة": 36,
    "droit_constitutionnel": 95, "droit_civil": 80, "droit_penal": 78,
    "droit_familial": 76, "droit_du_travail": 72, "droit_commercial": 70,
    "droit_administratif": 68, "droit_foncier": 50, "droit_immobilier": 48,
    "droit_sante": 52, "droit_environnement": 38, "droit_international": 44,
}
DOMAIN_DEFAULT = 34


def norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[ً-ْـ]", "", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def classify(title: str) -> tuple[str, int]:
    n = norm(title)
    for name, weight, cues in CLASS_RULES:
        for cue in cues:
            c = norm(cue)
            if c and c in n:
                return name, weight
    return CLASS_DEFAULT


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/corpus_consolidated")
    ap.add_argument("--batch-size", type=int, default=50)
    args = ap.parse_args()

    corpus = Path(args.corpus).resolve()
    with (corpus / "manifest.csv").open(encoding="utf-8") as fh:
        manifest = {r["rel_path"]: r for r in csv.DictReader(fh)}
    with (corpus / "ocr_queue.csv").open(encoding="utf-8") as fh:
        queue = list(csv.DictReader(fh))

    need = []
    for r in queue:
        if r["needs_ocr"] != "True":
            continue
        m = manifest.get(r["path"], {})
        r["declared_ref"] = m.get("declared_ref") or ""
        r["content_health"] = r.get("content_health") or m.get("content_health", "")
        need.append(r)

    for r in need:
        title = r["declared_title"]
        cls, cls_w = classify(title)
        dom_w = DOMAIN_RANK.get(r["domain"], DOMAIN_DEFAULT)
        pages = int(r["pages"] or 0)
        size_w = min(20.0, math.log10(pages + 1) * 7.0)
        ref_w = 6.0 if r["declared_ref"] else 0.0
        # class dominates: a constitution is foundational at 20 pages;
        # a 3-page decree is not, however long its neighbours are.
        r["instrument_class"] = cls
        r["importance_score"] = round(cls_w + 0.35 * dom_w + size_w + ref_w, 2)
        r["score_breakdown"] = (
            f"class={cls}:{cls_w} + domain:{dom_w}*0.35 + "
            f"size:{size_w:.1f} + ref:{ref_w:.0f}"
        )

    need.sort(key=lambda r: (-float(r["importance_score"]),
                             -int(r["pages"] or 0), r["path"]))
    for i, r in enumerate(need, 1):
        r["priority_rank"] = i

    with (corpus / "ocr_queue_by_importance.csv").open("w", newline="",
                                                        encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "priority_rank", "importance_score", "instrument_class", "score_breakdown",
            "tier_label", "pages", "source", "domain", "declared_ref",
            "declared_title", "path", "sha256",
        ], extrasaction="ignore")
        w.writeheader()
        w.writerows(need)

    # one queue, not two: drop the severity-ordered batches before rewriting
    for old in corpus.glob("ocr_batch_*.jsonl"):
        old.unlink()

    batches = defaultdict(list)
    for i, r in enumerate(need):
        batches[i // args.batch_size].append(r)

    for idx in sorted(batches):
        p = corpus / f"ocr_batch_{idx:02d}.jsonl"
        with p.open("w", encoding="utf-8") as fh:
            for r in batches[idx]:
                fh.write(json.dumps({
                    "path": r["path"], "sha256": r["sha256"],
                    "pages": int(r["pages"] or 0),
                    "instrument_class": r["instrument_class"],
                    "importance_score": float(r["importance_score"]),
                    "tier_label": r["tier_label"],
                    "source": r["source"], "domain": r["domain"],
                }, ensure_ascii=False) + "\n")

    summary = {
        "queue_documents": len(need),
        "ordering": "document importance (desc), then pages (desc)",
        "batch_size": args.batch_size,
        "batches_emitted": len(batches),
        "total_pages": sum(int(r["pages"] or 0) for r in need),
        "class_distribution": dict(Counter(r["instrument_class"] for r in need)),
        "per_batch": {
            f"ocr_batch_{i:02d}.jsonl": {
                "docs": len(batches[i]),
                "pages": sum(int(r["pages"] or 0) for r in batches[i]),
                "score_range": [float(batches[i][0]["importance_score"]),
                                float(batches[i][-1]["importance_score"])],
            }
            for i in sorted(batches)
        },
        "note": (
            "Ranking is user-facing value, not severity. score_breakdown in "
            "ocr_queue_by_importance.csv makes every ranking auditable. Cues are "
            "substring matches and will misfire on titles that merely contain a "
            "keyword -- fix the cue, do not silently accept the ordering."
        ),
    }
    (corpus / "ocr_queue_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"queue   : {len(need)} documents, {summary['total_pages']} pages")
    print(f"batches : {len(batches)} (size {args.batch_size})")
    print("\ntop 15 by importance:")
    for r in need[:15]:
        print(f"  {r['priority_rank']:3d}. {float(r['importance_score']):6.1f} "
              f"{r['instrument_class']:16s} {r['pages']:>4}pp  "
              f"{r['declared_title'][:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())