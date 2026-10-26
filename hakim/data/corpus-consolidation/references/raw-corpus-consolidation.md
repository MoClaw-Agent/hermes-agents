# Raw Corpus Consolidation — Measured Reference

Figures below were produced by executing against the Mizan corpus. Re-measure on a
new corpus; treat them as the shape of the problem, not as constants.

## Provider artefact census

| provider | pdf | txt | json sidecars | text location |
|---|---|---|---|---|
| ADALA | 4,627 | 0 | 4,624 | PDF text layer |
| JuriThèque | 0 | 0 | 7,037 | inside `content_ar` / `content_fr` metadata fields |
| ISM | 139 | 7 | 139 | PDF text layer |

Two structural facts that change the plan:

- **A JSON-only provider is not a file corpus.** JuriThèque held zero PDFs and zero
  txt files; its only non-JSON artefact was `sitemap.xml`. Its text lived in a metadata
  field, so using it as a repair source required extraction first. Its records did
  point at downloadable PDFs (5,511 Arabic records with a resolvable `source_url`;
  120/120 sampled URLs returned HTTP 200), which makes "no PDFs" and "no coverage"
  different claims.
- **The Arabic bulk is not where the directory name says.** ADALA's `raw/ar` held 2
  files; 4,088 sat in `raw/bk`. `raw/fr` held 537, and was 98% image-only. Walking
  the directory named for the language finds almost nothing.

## Text-layer health by provider

Function-word frequency over the first pages of extracted text.

| provider | n | clean | image-only | suspect | ciphered |
|---|---|---|---|---|---|
| ADALA `raw/bk` | 300 | 99% | 1% | 0% | 0% |
| ADALA `raw/fr` | 300 | 0% | **98%** | 0% | 2% |
| ADALA all (sampled) | 600 | 84% | 14% | 2% | 0% |
| ISM (all) | 139 | 19% | **27%** | 45% | 9% |

The intuition that one provider is "the good one" inverted: the provider assumed to be
a clean PDF source was the damaged one, and the presumed-clean corpus was 98% scanned
in its French half.

## Cipher vs digit transposition

Under a glyph-substitution cipher the extracted text is real Arabic with letters
permuted within words:

```
expected:  الجريدة الرسمية
extracted: يذوَح انشغم
```

Decisive test — check whether the phrase's letter multiset exists anywhere in the
document text:

```python
from collections import Counter
target = "الجريدةالرسمية"
ok = all(Counter(target)[c] <= Counter(all_arabic_text)[c] for c in set(target))
```

`ok == False` proves a substitution cipher. A digit-transposition detector keyed on
implausible years scores such a document as clean, because no year is actually wrong —
the letters are.

## Overlap measurements

**By normalised reference** (`.` and `-` unified):

| pair | shared refs |
|---|---|
| ADALA × JuriThèque | 3,092 |
| ADALA × ISM | 0 |
| JuriThèque × ISM | 1 |

**By content** (SHA-256 of downloaded files vs the other side's raw set):

- 60 JuriThèque PDFs sampled: **52% byte-identical** to a file in ADALA raw, 48% net-new
- 45% had a reference absent from every ADALA filename

So ref overlap overstated content overlap. ISM's zero is not "no overlap" — see below.

## The near-duplicate that defeats every cheap key

ADALA `مدونة الشغل.pdf` (171 pp) vs ISM `droit_du_travail/1.pdf` (170 pp, whose own
sidecar title is `مدونة الشغل`):

| signal | value |
|---|---|
| normalised reference overlap | none (ISM carries no refs) |
| normalised title match | 18/137 exact across the corpus — weak |
| 8-gram jaccard on token stream | 0.34 |
| **exact shared long lines** | **319 of 513 / 515** |
| rendered-page MD5 at 40 dpi | **0 / 170 identical** |
| per-page Pearson r | 0.05 – 0.16 |

Same instrument, two scans. Detectable only from readable text on both sides; invisible
to refs, titles, hashes, and pixels.

## Title matching fails both ways

Against 8,623 union titles (ADALA parsed + JuriThèque), ISM's 139 titles:

```
exact match       0
substring match  61
reported absent  78
```

The 78 "absent" included `قانون المسطرة المدنية` and other laws demonstrably in ADALA.
The 61 substring matches were mostly 3–5 character topic labels (`الماء`, `المقالع`)
matching anything containing that word. False positives and false negatives in one run —
never key on titles.

## Reference collisions

612 of 6,226 distinct refs mapped to more than one record (1,300 records). Two classes:

```
3202.24  [arrete]  Arrêté ministériel n° 3202.24 …
3202.24  [decision] Décision de la Cour de cassation n° 3202-24 …

86.12    [law] ×4   Loi n° 86.12 relative aux contrats de partenariat …
```

Key on `(instrument_type, number, issue_date)`.

## Sidecar schema

`<stem>.meta.json`, one per binary, pairs 1:1 (4,763 sidecars, 0 orphans, 3 binaries
without one):

```json
{
  "filename": "27.pdf",
  "source_url": "https://ism.ma/pdf/ARABE/Textesdeloiarabe/comercial/27.pdf",
  "scraped_at": "2026-09-29T23:06:44Z",
  "downloaded_at": "2026-09-29T23:06:44Z",
  "lang": "ar",
  "subject": "أبحاث ودراسات ونصوص قانونية > نصوص قانونية",
  "title": "السوق الآجلة للأدوات المالية",
  "legal_domain": "droit_commercial",
  "bo_number": null,
  "date": null,
  "legal_rank": null,
  "effective_date": null,
  "is_amendment": false,
  "content_hash": "c4ae1e03…"
}
```

`content_hash` is a SHA-256 written by the crawler at download time. Cross-checking it
against a freshly computed hash is an independent integrity test. Result on that corpus:
4,224 agree, 1 disagrees — and the disagreement was a CMap repair that had been written
back over the original, improving it. The check found a real mutation; reading the file
showed it was a fix, not damage.

`bo_number` and `effective_date` were **0% populated** across the whole corpus. Those are
the citation fields; nothing inherits them, so post-parse extraction must derive them.

## Basename collisions

| provider | files | distinct basenames |
|---|---|---|
| ISM | 139 | **28** |
| ADALA | 4,627 | 4,622 |

ISM worst offenders: `1.pdf`, `2.pdf`, `3.pdf`, `4.pdf` — each appearing ~11 times across
legal-domain subfolders. 133 of 139 files sat in a colliding name.

## Output shape that worked

```
corpus_consolidated/
  pdf/          uniquely-namespaced files (hardlinks)
  meta/         sidecars under the same namespaced stem
  manifest.csv  one row per file, 28 columns
  duplicates.jsonl
  ocr_queue.csv, ocr_batch_NN.jsonl, ocr_queue_summary.json
  summary.json, README.md
```

Hardlinks meant a 3.7 GB consolidation cost no disk, and deleting the output could not
damage the source tree.

## Cost asymmetry in practice

Of 4,229 files, exact-hash dedup removed **3**. The meaningful consolidation work was
elsewhere: namespacing (prevented 111 silent overwrites), the manifest (made coverage
measurable), the health census (found 195 files needing remediation), and deferring
fuzzy dedup (prevented false deletions). Report the stages that did the work, not the
one with the most impressive-sounding description.