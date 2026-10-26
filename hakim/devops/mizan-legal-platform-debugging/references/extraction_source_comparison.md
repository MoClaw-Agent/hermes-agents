# Choosing an Extraction Source: Native Layer vs OCR

How to decide which text a document should be parsed from, and how to compare two
candidate sources without scoring one against the other.

## Reversal is a distinct signature from substitution

Two different defects live under "the digits are wrong", and they need different
responses.

| Signature | Example | Nature |
|---|---|---|
| Per-digit glyph substitution | `المادة22` → printed 11 | positional, no consistent map, unrepairable |
| **Whole-run digit reversal** | `رقم4.99.4` → printed **1.00.484** | mechanical; the ToUnicode CMap maps glyphs in reverse |

Reversal is easy to miss because the output still looks like a plausible number.
Confirm it by extracting one page and reading every number on it. Reversal is
unmistakable once seen — `4.99.4`, `4149`, `4999`, `0553` reverse cleanly to
`1.00.484`, `1439`, `1999`, `3550` — but reads as arbitrary noise without that
hypothesis in mind.

Extract a page and print every line containing a digit:

```python
doc = fitz.open(pdf); page_text = doc[2].get_text(); doc.close()
for line in page_text.split("\n"):
    if any(ch.isdigit() for ch in line) and line.strip():
        print(repr(line.strip()))
```

## The native text layer is not automatically the better source

Measured against a human read of the printed page on one 16-page Moroccan code:

| | articles recovered | reference numbers |
|---|---|---|
| Native text layer → parser | 25 (and re-detected 46, scrambled) | **reversed**: `4.99.4` for `1.00.484` |
| Third-party OCR service | **44** — exactly the human read | **correct**: `19.94`, `51.09`, `1.10.26` |

The OCR service was strictly better on *both* structure and digits for that
document. The native layer was not a degraded fallback — it was the worst
available source.

This inverts the usual default. "Prefer the native layer, fall back to OCR" is
wrong whenever the native layer carries reversal corruption, and no cheap
structural signal detects it (see the dead-detector table in SKILL.md).

## Never score one extraction source against another suspect source

Validating an OCR output against the PDF's own text layer produces a confidently
wrong verdict: the text layer is the artifact under suspicion, so it "disproves"
correct output by being wrong in the opposite direction. During this work that
mismatch produced the exact inverse of the truth — a correct OCR service was
reported as garbled, and the conclusion only reversed when the user checked the
printed page.

Order of operations:

1. Establish ground truth **first** — the rendered page read with vision, or the
   user's read. Never a second automated source.
2. Then score each candidate against that ground truth.
3. Report which source won per axis (structure, digits), not as one verdict.

## Clean-looking output is not correct output

The same OCR file drifted systematically on prose while reading fluently and
preserving layout perfectly:

```
14x  المغريبة  →  المغربية
13x  العذل       →  العدل
15x  مكيرية      →  مديرية
```

Letter drift is cosmetic. A wrong instrument number is a citation resolving to
a law that may not exist. **Score the numbers separately from the prose, and
never let a good prose score stand in for the numbers.** A dropped reference
(`رقم 1436 (24 ديسمبر 2014)` where `141.192` belongs) is worse than a misread
one, because it still looks like clean output.

Validate that reference numbers are **present**, not merely present-and-correct.

## Comparison checklist

- Ground truth fixed before any candidate is scored.
- One axis varied at a time — swapping engine while also changing pixel budget
  or DPI makes the comparison meaningless.
- Save the prior run's output before overwriting; the baseline is the comparison.
- Structure axis: article/chapter counts against the human read, and whether
  ordering holds (`article_order` disqualifies independently of count).
- Digits axis: a handful of known reference numbers, checked for presence first
  and correctness second.