# Is the Corruption Invertible? (Permutation vs. Destruction)

## The question this answers

A corpus's text layer corrupts its digits. The natural next thought is "then it's just a glyph
substitution — find the mapping and reverse it", which repairs the whole corpus for the cost of
one table. That idea is only valid if the corruption is a **permutation**: every source glyph
decodes to exactly one codepoint, bijectively. Measured on ISM `droit_administratif` PDFs, it is
**not**, and knowing that cost one wasted repair design.

**The answer is always no. Plan for re-OCR or a trusted reference, never for inversion.**

## Why it is no: compare the digit multiset

A bijective permutation preserves the *multiset of digit characters*. If the printed page contains
three `1`s, the decoded text contains three `1`s, merely relabelled. So a per-digit character count
against a trusted reference separates the two cases cleanly, and — critically — **needs no
alignment**.

```python
DIGITS = set("0123456789")

def ar2ascii(s: str) -> str:          # normalise Arabic-Indic digits first
    return s.translate(str.maketrans(
        "".join(chr(c) for c in range(0x660, 0x66A)), "0123456789"))

def digit_inventory(text: str) -> Counter:
    return Counter(c for c in ar2ascii(text) if c in DIGITS)
```

Measured:

| doc | reference | native | digit | ref | nat | status |
|-----|-----------|--------|-------|-----|-----|--------|
| 14  | 518       | 199    | `1`   | 132 | 30  | LOST 102 |
| 14  |           |        | `4`   | 47  | 5   | LOST 42  |
| 14  |           |        | `9`   | 51  | 4   | LOST 47  |
| 15  | 170       | 95     | `1`   | 35  | 9   | LOST 26  |
| 15  |           |        | `4`   | 20  | 0   | LOST 20  |
| 15  |           |        | `6`   | 3   | 15  | EXTRA +12 |

Digits are **destroyed and replaced**, not relabelled. Note the `EXTRA` rows as much as the `LOST`
ones: a substitution table cannot explain new digits appearing either. The information is gone from
the native layer; only a re-OCR or the reference text restores it.

Corroborating signal: the native layer kept ~86% of the document's *characters* while losing ~60% of
its digit characters. Prose survives, citations do not — so "the extraction looks complete" and "the
citations are wrong" are the same document.

## Two approaches that look decisive and are not

Both were run before the inventory test and both produced a confident wrong verdict. They fail the
same way: **they manufacture a substitution table out of unrelated numbers.**

**Matching digit tokens by length.** Pair every native-only token with every reference-only token of
the same length. Produces `2211 -> 1423`, `2211 -> 2002`, `2211 -> 1414`, all at equal counts.
Equal-length four-digit tokens are not evidence of anything.

**`difflib` alignment.** The two texts diverge too much to align: character-level yielded 17 digit
pairs, word-level yielded 4. This is the dangerous failure — a script will happily emit
`2 -> {6: 1, 0: 1, 9: 3, 4: 2}` and call it `AMBIGUOUS, NOT LEARNABLE`, which reads like a finding
and is pure sampling noise. **A verdict that rests on fewer than ~30 aligned pairs is not a
verdict**; make the script exit non-inconclusive below a floor rather than printing a table.

Prefer the inventory test above: it needs no alignment, no pairing heuristic, and no sample-size
threshold to be trustworthy.

## CMap detectors do not see this

`is_arabic_cmap_corrupt()` returned `False` on **all four** documents tested, including ones with
systematic damage:

```
doc 14: هلل x3  (canonical لله: 0)      السيما x4  (canonical الدستور: 1)
doc 15: هلل x3  (canonical لله: 0)      السيما x1  (canonical الدستور: 1)
```

`هلل` three times against zero occurrences of `لله` is exactly the dominant-form pattern the
detector's own documented rule should catch. It does not, because the detector handles **letter**
substitution (alif→lam, ta-marbuta→ha) and has **no digit handling at all**. A green quality gate
(`errors=0 warnings=0`) on such a document means structure, article markers and masthead all passed
— it says nothing about numbers. Assert digit fidelity separately; never read a green gate as a
clean bill.

## Run the inventory test FIRST, before designing the repair

The reflex ordering is: suspect a substitution → build a mapping extractor →
discover it does not fit → try alignment → discover alignment does not fit →
finally reach the inventory test, which needed neither. That is three
implementations and two confident wrong verdicts spent on a question the
inventory answers in twenty lines with no alignment and no sample-size floor.

Ask "is this a permutation?" and test it with per-digit counts **before** writing
any repair code. The inventory test is cheap, alignment-free and decisive; a
mapping extractor is expensive, needs alignment to validate, and its failure
mode is a plausible-looking table rather than an error. Corollary: when you do
build a heuristic that produces a table, make the script **exit non-inconclusive
below a sample-size floor** rather than printing a verdict it cannot support.

## What to do instead

1. **Treat the reference or a re-OCR as the only source for these documents.** Not "a better
   reference" — when the layer destroys citations, it is the only source that contains them.
2. **Do not invest in digit repair.** No table exists to apply.
3. **Report the extraction-mode split.** On a four-document sample two were `scanned` (native
   extraction yielded 1-2 characters) and two were `cid_fonts` (~86% characters retained). The
   corruption is document-specific, which is why `OCR_FIRST` is routed per provider rather than
   globally.
4. **Check whether a digit detector is wanted at all** before building one. Note that a swapped
   dotted reference is locally undetectable (see the digit-reversal caveat in SKILL.md), so a
   detector keyed on implausible years sees only the dominant form.