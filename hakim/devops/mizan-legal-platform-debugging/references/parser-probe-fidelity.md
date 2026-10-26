# Probe and fixture fidelity

How to keep a measurement from lying about the parser.

## Hand-written non-Latin fixtures corrupt, and the failure points the wrong way

Literal Arabic typed into a test and `A + L + M + D + TA` codepoint assembly were **both** corrupted in transit, twice, in both directions. Every corruption produced a *false test failure* that named the parser as the cause.

One of those false failures was load-bearing: a probe reported `(False, None)` for every case including the most basic `المادة 2`, which the suite showed passing. That "evidence" was used to revert a correct fix. The fix had been measured at +88 articles on a real corpus file; the revert was a pure artifact of the rig.

**Extract the fixture from the corpus instead of transcribing it**, and commit the generated test:

```python
real = next(l.strip() for l in corpus_text.split("\n") if MARKED in l)
Path("tests/test_x.py").write_text(template % (real,), encoding="utf-8")
```

Corpus-derived fixtures also assert things synthetic ones cannot. The real run-on line contained a `- 2 -` page marker mid-string; no hand-written case would include it, yet "that marker must not become a second article 2" was the most valuable assertion in the file.

If the fixture must be synthetic, verify the bytes round-trip before trusting the result:

```python
assert [hex(ord(c)) for c in WORD] == ["0x627", "0x644", "0x645", "0x62f", "0x629"]
```

## A probe that contradicts the suite is the suspect

Order of trust: real fixture from corpus > committed test suite > ad-hoc probe.

When a probe reports total or near-total failure while the suite is green, check the probe against **one known-good input taken from the suite** before touching the implementation. Reverting a verified fix on probe evidence discards real work and corrupts the measurement you were trying to take.

## Re-parsing stored output is a ceiling, not a count

Running `build_tree` over article text extracted from a previous parse answers *"would today's parser recover this from that text"*, not *"does today's parse get it"*. The stored text is post-parse output, so an article the earlier parse never emitted is simply absent, and the count can only fall.

Report it as a ceiling on what is recoverable from that text. A believed article count needs a fresh parse against a known OCR source, checked against a human count off the rendered page.

## Validate an audit heuristic against real samples before reporting hits

A "corrupt year" heuristic flagged `5997`, `7210`, `1456`. Those were Journal Officiel issue numbers (`الجريدة الرسمية عدد N`, legitimately in the thousands) and page cites (`ص N`). Every flagged item was good data, and reporting it as corruption would have sent the investigation at the wrong layer.

Before reporting a heuristic's hits as defects, dump every hit **with surrounding context** and read a sample. Cheap, and it is the difference between a finding and a false alarm.

## Overloaded entry points must be proven equivalent

`build_tree(text_or_pages: str | list[str])` had a `str` branch that was a bare `split("\n")` while only the page-list branch ran the run-on header splitter. Same text, different tree.

```python
assert _numbers(build_tree(text, document_language=lang)) == \
       _numbers(build_tree([text], document_language=lang))
```

One assertion, and it is the only thing that catches this class.

## Offsets must be mapped when scanning a normalised copy

A splitter that removes Arabic diacritics and tatweel before matching must carry each kept character back to its original index. Deleting codepoints shifts every later position, so `cuts.append(m.start())` on the stripped copy cuts mid-word. Build `posmap` alongside the stripped string and index through it.