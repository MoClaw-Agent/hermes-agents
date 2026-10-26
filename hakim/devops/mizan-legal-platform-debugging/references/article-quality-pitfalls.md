# Article Quality Pitfalls

## Phantom articles from cross-references

Amendment notes, constitutional court decision references, and promulgation headers create phantom article nodes when OCR splits them into standalone header lines. The `_CITATION_TAIL_RE` and `_CROSS_REFERENCE_TAIL_RE` patterns in `structure.py` must reject:

- Quote marks after article numbers (amendment notes: `المادة 2 "عملا بأحكام`)
- `في المادة` ("in Article" cross-references)
- `تطبيقا للمادة N من القانون` ("pursuant to Article N of the law")
- `انظر المادة` ("see Article")
- `المصرح بعدم مطابقتها للدستور` (constitutional court references)
- `السابقة الذكر` ("aforementioned")
- Isolated headers ending with colon (`المادة 34:`)
- `المادة الأولى المرسوم رقم` (cross-reference to another decree)

**Test each pattern against real headers AND phantoms before trusting the filter.** A pattern that rejects real articles is worse than no filter.

## Annex content absorbed into preceding article

`الملحق رقم N` (Annex N) headers must create a new `annex` node in `build_tree`, not be treated as body text of the preceding article. Without this, all annex templates and forms get absorbed into the last article's content.

## Compound ordinals truncated

`الرابع والعشرون` (24) must parse as 24, not 4. The `_ordinal_int` function needs a compound-ordinal branch: if the token is `ones + وال + tens`, return ones + tens. Also add indefinite tens forms (`عشرون`, `ثلاثون`, ...) and ش-suffix variants (`العشرين`, `الثلاثين`, ...) to `_AR_TENS_WORDS`.

## Promulgation-title ref extraction

When the title is `القانون رقم X بمثابة...` (the law being promulgated) and the filename has no dotted ref, the derivative gate triggers. Inside the gate, match the promulgation header pattern (`ظهير شريف رقم Y صادر`) FIRST, before any `ظهير شريف رقم Y` reference. Page 2 amendment references (`الصادر بتنفيذ الظهير الشريف رقم Y`) are NOT the own ref.

## Recursive article counting required

Article nodes are nested inside parent containers (title, chapter, section). Counting only top-level `article` type nodes reports 0 for a document with 58 correct articles. Always count recursively:

```python
def count_articles_recursive(nodes):
    count = 0
    for node in nodes:
        if node.get('type') == 'article':
            count += 1
        if node.get('children'):
            count += count_articles_recursive(node['children'])
    return count
```

A document showing `detected=58, actual=0` is almost certainly a counting error, not a parse failure.

## Implementing Dahir misclassification

When a Dahir's title cites the law it implements (e.g. "قانون رقم 02.03 يتعلق بدخول وإقامة الأجانب") and the actual "ظهير شريف رقم X" header appears deeper in the text, the parser classifies it as `loi` with the law's ref instead of `dahir` with the Dahir's ref.

Fix: in `_validated_doc_type`, when `_scan_own_instrument_marker` returns "loi" but "ظهير شريف" appears in the first 4000 chars, the document is a Dahir implementing/amending that law — override to `dahir`. The LLM cannot fix this because it only sees the first few pages, which carry the law title, not the Dahir header.

## Hybrid structure from PP-OCRv5 + vision OCR

When both OCR sources are available, run `build_tree` on both and pick the tree with more article nodes. PP-OCRv5 finds `المادة N` headers even when garbled; vision OCR produces cleaner text but may miss headers on dense layouts. This is a quality gate, not a fallback — the best available text wins.

## Parser state: reverting incorrect failed marks

Files marked `status: failed` in `data/logs/adala_parser_state.json` will be reprocessed by `--retry-failed`. When analysis reveals a document was correctly parsed (the failure was an analysis error, not a parse error), revert the status to `success` to avoid unnecessary re-processing. Only keep `failed` marks on files that genuinely need re-parsing (e.g., vision OCR produced degenerate output).

ISM parser must use the same hash-based cache naming as ADALA: `{stem}_{hash[:12]}_vision.json`. Using `{stem}_vision.json` creates duplicate cache files for the same PDF.

## JSON filename convention

Both ADALA and ISM parsers name output files as `{doc_type} {ref}.json` (e.g., `dahir 1.15.83.json`). ISM's `_naming_stem` must use `document_type` and `ref` from the doc, matching ADALA's `_compute_output_path` convention.

## Parser state file management

To force reprocessing of specific files, mark them as `status: failed` in `data/logs/adala_parser_state.json`. The `--retry-failed` flag will then reprocess them. Use `--force` to reprocess regardless of status.

## CMap repair: corrupted file handling

`auto_repair_pdf` writes the repaired PDF to a temp file, swaps it into the original location (keeping the original filename), and moves the corrupted original to `data/corpus/<provider>/raw/corrupted/<lang>/` with a `_corrupted` suffix. Both parsers exclude `corrupted/` from `rglob` enumeration. The old `_mapping_repaired` suffix approach caused infinite re-processing.
