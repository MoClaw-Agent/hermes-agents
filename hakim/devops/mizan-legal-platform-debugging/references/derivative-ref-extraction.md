# Derivative Ref Extraction — Instrument-Marker Gate

## Problem

When a document is a derivative instrument (dahir/decree that promulgates or implements a law), the filename and title often carry the CITED law's ref, not the instrument's own ref.

### Real Cases

| File | Title | Wrong Ref | Correct Ref |
|------|-------|-----------|-------------|
| `dahir 2.02.645.pdf` | `ظهير الشريف رقم 1.03.26 بتنفيذ القانون رقم 61.02` | 2.02.645 | 1.03.26 |
| `decret 1.84.8.pdf` | `مرسوم رقم 2.84.20 يتعلق بكيفية تطبيق الظهير الشريف رقم 1.84.8` | 1.84.8 | 2.84.20 |
| `loi 120.12.pdf` | `القانون رقم 120.12 المتعلق بإلغاء الزيادات` | 120.12 | 1.13.07 |

## Root Cause

The `extract_ref` function uses filename as priority 1, title as priority 2. When the filename contains a dotted ref, it always wins — even if it is the cited law's ref, not the instrument's own ref.

## Fix: Instrument-Marker Gate (v1.99.2)

In derivative mode, only trust refs preceded by instrument markers (ظهير شريف/مرسوم/قرار) from title/filename. Refs preceded only by قانون are the cited law's ref and must be skipped.

```python
_instr_ref_pat = re.compile(
    r"(?:ظهير\s+(?:ال)?شريف|ظهير|مرسوم|قرار)\s*(?:رقم)?\s*([\d.]+)"
)
```

The title's instrument-marker ref wins over the filename's. If neither has an instrument marker, the parser scans pages for the promulgation-header pattern:

```python
_promul_pat = re.compile(
    r"ظهير\s+شريف\s+رقم\s*([\d.]+)\s*(?:صادر|بتاريخ|في\s)"
)
```

## Detection

A JSON whose `ref` matches a law number (e.g. 120.12) but whose `document_type` is `dahir` is a red flag — the dahir's own ref is different from the law it promulgates. Cross-check the title: if it contains `القانون رقم X` where X equals the JSON's ref, the ref is wrong.

## Files

- `fetching/adala/parser/extraction.py` — the derivative gate in `extract_ref()`
- `fetching/adala/parser/_shared.py` — `_DERIVATIVE_KEYWORDS_AR`, `_OWN_REF_PAT_AR`, `_scan_derivative_own_ref`
