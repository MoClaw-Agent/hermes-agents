# Arabic OCR Corruption Marker Detection

## Problem

When auditing Arabic legal corpus JSON for OCR hallucination markers (وذارة, ديرية, وزلره family), **naive substring search produces massive false positives** because these marker fragments appear inside legitimate Arabic words.

## The Core Bug

```python
# WRONG — catches legitimate words
if "ديرية" in text:        # matches مديرية (administration), ديرية (monastery), etc.
if "وزارة" in text:        # matches كل كلمة تحتوي على "وزارة" — but also وزارة التعليم, etc.
```

These are **substrings of common Arabic words**, not standalone hallucination indicators. A corpus-wide scan with substring matching flags hundreds of clean files.

## Correct Detection: Word-Boundary Check

A corruption marker is only a corruption marker when it appears as a **standalone Arabic word** — not as a substring of a larger word.

```python
import regex  # pip install regex — \X grapheme clusters

_ARABIC = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]')

def is_arabic_word_boundary(text: str, pos: int, length: int) -> bool:
    """True when marker at pos is a standalone Arabic word."""
    before = pos == 0 or not _ARABIC.match(text[pos - 1])
    after  = (pos + length >= len(text)) or not _ARABIC.match(text[pos + length])
    return before and after

def find_markers(text: str, markers: list[str]) -> list[str]:
    """Find corruption markers that appear as standalone words only."""
    found = []
    for m in markers:
        pos = text.find(m)
        while pos != -1:
            if is_arabic_word_boundary(text, pos, len(m)):
                found.append(m)
                break
            pos = text.find(m, pos + 1)
    return found
```

## Known Marker Set (R1-AR.5 hallucination patterns)

These are specific hallucinated ministry-name fragments from CMap-corrupt OCR:

```python
CORRUPTION_MARKERS = [
    "وذارة",   # وذارةX → وزارةX hallucination (و→و، ذ→ز)
    "ديرية",   # ديريةX → دائرةX / ديرةX hallucination
    "وزلره",   # وزلرهX → نور/زيرة hallucination
]
```

Also check the exact known-bad strings: `ذهارة`, `ذيرية`, `زلره`.

**Only flag when standalone.** `مديرية` is legitimate; `ديرية` appearing as a standalone word is a hallucination.

## Where to Check

Check in the **preamble zone** (first 2 article bodies in the structure tree) and the first 5 article bodies. This is where masthead hallucinated ministry names land. Checking the entire document text would catch legitimate cross-references.

```python
# In audit:
check_texts = [preamble_text] + [a.get("content","") for a in articles[:5]]
all_check = "\n".join(t for t in check_texts if t)
markers = find_markers(all_check, CORRUPTION_MARKERS)
```

## R1-AR.6 Split-Keyword Corruption

A separate corruption class: the article keyword itself is split or ta-marbuta-swapped:

```python
_AR_ARTICLE_KW = re.compile(r'الماد[ةه]\s?[ةه]?\s*(\d+)')
# Flags: الماد ه الثانية (split), الماده 12 (ta-marbuta→ه)
```

Check the first line of each article for keyword corruption. This is distinct from the ministry-name hallucination markers above.

## ISM CMap Detection Gap

The standard `is_arabic_cmap_corrupt()` detector (in `fetching.pipeline_base.pdf_quality`) can produce false negatives on ISM (ism.ma) PDFs. The detector has a vocabulary early-out: if ≥8 of 16 common Moroccan legal words appear in the text, it is classified as clean. ISM garbled text often retains 1-3 common words (e.g. "ظهير", "رقم") by chance while the rest is mojibake — the early-out fires and the document is treated as clean, producing a flat single-`preamble` structure with `num_articles_detected: 0`.

**Supplemental detection for ISM:** if a JSON has >3000 Arabic chars in its structure but ≤2 of these 9 specific legal-structure keywords, treat it as garbled even if `is_arabic_cmap_corrupt()` returns False:

```python
STRUCTURAL_KEYWORDS = ['مادة', 'قانون', 'وزارة', 'مرسوم', 'ظهير', 'المغرب', 'المملكة', 'الباب', 'الفصل']

def is_ism_garbled(text: str) -> bool:
    arabic = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    if arabic <= 3000:
        return False  # too short to be garbled
    found = sum(1 for kw in STRUCTURAL_KEYWORDS if kw in text)
    return found <= 2
```

This catches the class where CMap corruption destroys article boundaries and hierarchy markers while leaving a few common words intact — the exact pattern seen in `droit_constitutionnel/3.pdf`, `droit_environnement/5.pdf`, `droit_sante/7.pdf`, and several others.

## Digit corruption is a separate, undetectable-by-this class

`is_arabic_cmap_corrupt()` handles **letter** substitution (alif->lam, ta-marbuta->ha) and has no
digit handling whatsoever. It returned `False` on every document tested where the digits were
demonstrably destroyed — including ones carrying its own documented dominant-form signal
(`هلل` x3 against zero `لله`).

Before designing any repair, test whether the corruption is invertible: a bijective glyph
permutation preserves the multiset of digit characters, so comparing per-digit counts against a
trusted reference settles it without any alignment. Measured, the multiset is **not** preserved
(digits both vanishing and appearing), so no substitution table exists and no digit repair is
available. `references/corruption-invertibility.md` has the test, the two alignment-based methods
that produce confident wrong verdicts instead, and the "fewer than ~30 pairs is not a verdict"
floor.

## Re-Parse Recovery for ISM

When ISM JSONs need re-parsing after quality audit, two failure modes to guard against:

**Stem collisions:** ISM PDFs share short numeric filenames across legal-domain subfolders (`droit_civil/7.pdf`, `droit_penal/7.pdf`, `droit_sante/7.pdf` are three distinct laws). A repair script that deletes individual garbled JSONs and re-parses them one domain at a time will overwrite correct JSONs with wrong-domain output. **Fix:** always do full wipe-and-reparse — delete ALL JSONs in `data/corpus/ism/json/ar/`, then parse every raw PDF in domain-sorted order. Never cherry-pick individual stems when >3 garbled docs span multiple domains with shared stems.

**Fast re-parse path:** The full parser pipeline includes LLM OCR normalization with 12s rate-limit between chunks, making garbled-doc re-parses take 200-400s each. Screen first:

```python
from fetching.pipeline_base.extraction import extract_pages
from fetching.pipeline_base import is_arabic_cmap_corrupt

pages, mode, tables = extract_pages(str(pdf_path), cache_dir, language_hint="ar")
text = ' '.join(pages) if pages else ''
if not pages or is_arabic_cmap_corrupt(pages) or is_ism_garbled(text):
    force = True   # needs OCR, ~40-60s
else:
    force = False  # clean, ~10s
process_file(pdf_path, lang="ar", force=force)
```

Screening before forcing turns a 30+ minute full-force re-parse of 62 ISM PDFs into ~12-15 minutes.

**Over-deletion guard:** When deleting garbled JSONs for re-parse, check whether the JSON has ANY article blocks before deleting. A doc with 6 article blocks but ≤2 common vocabulary words is garbled but retains parseable structure — call `process_file(force=True)` to re-extract in place rather than deleting. Only delete JSONs that have 0 article blocks AND are garbled.
