# Citability and Numeric Integrity

Why a corpus can be complete, deduplicated, and OCR'd — and still unable to answer a
legal question correctly. Companion to `references/raw-corpus-consolidation.md`, which
covers the file-level mechanics.

## The digit-dropping OCR failure

The defect that motivates the validation gate. A document's OCR output reads as fluent,
correct Arabic while every digit has been discarded.

```
source text layer : ظهٍز شزٌف رلى.1.3161 ... ًصادر ف02 ... ٌىنٍى02.3
OCR output        : ... ظهير شريف رقم ___ صادر في ___ من رمضان ___
                    ↑ words recovered    ↑ numbers gone
```

Measured on one such document:

| | numeric tokens |
|---|---|
| PDF text layer | 140 |
| OCR output | 5 |

Why it is dangerous: nothing signals it. There is no exception, no HTTP error, and the
prose is idiomatic. `ظهير شريف رقم` followed by whitespace reads as a document that
simply has no number yet, not as one that lost its number. And the document carries a
populated `ref` — recovered from a filename or an LLM metadata pass, not from the text —
so a manifest built from metadata shows it as identified.

It is strictly worse than a document that reads badly. A garbled document scores `ciphered`
on a health screen and gets queued for remediation. A fluent one scores `clean` and never
gets looked at again.

Note that `extraction_mode: ocr_forced` marks the document as having taken exactly this
path. It is a flag that the native layer was rejected and re-extraction ran; it is not a
quality signal.

## The validation gate

Run on every OCR result before it enters the corpus. Cheap; no re-OCR needed to run it.

1. **Numeric yield** — numeric tokens in OCR output vs. the source text layer. Fail below
   roughly 70%. This is the decisive check and the only one that is comparative.
2. **Number-with-no-value** — regex `رقم` followed by whitespace then a non-digit. Catches
   `ظهير شريف رقم ___` directly.
3. **Identity present in the text** — a reference matching `\d+\.\d+` must appear in the
   OCR text. A reference inferred from a filename does not count; it is not evidence the
   document says what the metadata claims.
4. **Version decidable** — `صيغة محينة` (consolidated) vs. an original text must be
   determinable from the OCR text. If undecidable, flag it. Do not guess a version.

Failing document → re-queue. Still failing → ship as
`source_authority: republication, citable: false`, so it is retrievable but can never be
quoted as authority.

## Usable vs citable

A citation must answer three questions: **which law, which version, as of when.**

| signal | ADALA-shaped source | republished source |
|---|---|---|
| reference recoverable | 86% (from filename), plus an explicit `ref` field | 0% (bare `1.pdf`–`N.pdf`) |
| date / BO issue | populated in metadata | 0 of 139 populated |
| version marker | `صيغة محينة` + a date on page 1 | locked inside the cipher |

Both can be the same instrument — proven by 319 of 513 exact shared long lines across two
different scans. Only one can be pinned to a version.

What makes a document *uncitable* is not thin metadata; thin metadata is fillable. It is
having **no anchor at all**: no reference in any layer, no date, and the one version signal
unreadable. OCR converts uncitable into citable — but only if rule 17's gate passes,
because OCR is also the thing that loses the numbers.

## Provider identity

Assert what a source publishes only after reading its own crawler. A provider long assumed
to be Morocco's Official Journal publisher is in fact a justice-sector training institute
republishing texts for training, with zero identity metadata in its sidecars. A merge
policy recommended on the false identity picked the wrong source for authoritative
content; the correct policy followed once the real identity was known.

One grep settles it:

```bash
sed -n '1,12p' fetching/<provider>/<provider>_crawler.py
```

## Complete files ≠ complete law

Delivering every document once, with nothing missing, satisfies coverage. It does not make
the corpus legally sufficient, because a later consolidated version of a law is a different
and more correct object than the promulgated text — not a duplicate of it. Legifrance
models this as an instrument plus a version list plus an amendment graph, addressing
articles by `(instrument, as_of)` rather than "current"; EUR-Lex/CELLAR keeps base act,
amending act as a diff, and consolidated version as three distinct objects.

The consequence is measurable rather than theoretical: over a static corpus of current
versions, RAG systems retrieved the date-applicable version of a legal article 0% of the
time, against 98.3% when the corpus carries versions. Consolidating files without a version
layer produces a corpus that answers amended-law questions confidently and wrongly.

Report coverage and legal sufficiency as two separate claims. A manifest that closes its
arithmetic proves the first and says nothing about the second.