---
name: arabic-legal-structure-parser
description: "Debug Arabic legal hierarchy parser structure."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [mizan, arabic, legal, structure, parser, hierarchy]
    related_skills: [mizan-legal-platform-debugging, systematic-debugging]
---

# Arabic Legal Structure Parser

## Status (2026-10-21)

**The ADALA/ISM parser audit is CLOSED** — all 15 findings fixed and measured across four waves (the TOC/table/citation fixes, the shared-engine consolidation, the ISM pipeline, and the #14/#15 wave). The full report, with every measurement and every rejected hypothesis, is `docs/audits/2026-10-20-parser-audit-adala-ism.md`. **Do not re-audit the parser from scratch** — read the report first.

The **stored corpus is still pre-fix**: the parser fixes live in the code, not on disk. A reparse is required before the corpus reflects them, and the reparse is a data operation the user runs.

## When to Use

- Structure tree has wrong node types (e.g., الفصل nodes as "article" instead of "chapter")
- Phantom articles appear in parsed output (cross-references mistaken for headers)
- Missing hierarchy levels (الفرع/branch not represented)
- `count_articles` returns 0 for الفصل-numbered documents
- `num_articles_detected` metadata is wrong
- A document reports `num_articles_detected: 0` while `structure_source` is `"vision"` (an OCR-cache story would be wrong — see "Auditing a reparse")
- The user reparsed a document set and asks you to check the output
- Provisions of a الفصل-numbered instrument are missing from search/retrieval
- Need to add or modify Arabic legal keyword handling in build_tree

## Arabic Legal Hierarchy Terminology

The parser maps Arabic legal keywords to node types. The user has explicitly corrected the mapping:

| Arabic | English | Node Type | Notes |
|--------|---------|-----------|-------|
| المادة | article | `article` | Feminine — laws (loi/ظهير) |
| الفصل / فصل | chapter | `chapter` | Masculine — decrees (مرسوم/ dahir) |
| الباب | book | `title` | NOT "book" — the parser uses `title` |
| الجزء | part | `part` | |
| الفرع / فرع | branch | `branch` | Added 2026-10 session |
| القسم | section | `section` | |
| الباب الأول | book 1 | `title` (number=1) | Common in Moroccan codes |

**Critical — read this before touching the mapping.** الفصل is typed `chapter` and المادة `article`, even in documents where the document-unit vote (`fasl_is_article_unit`, `doc_uses_madah=False`) says الفصل IS the article unit. That is a deliberate decision, not an oversight: do not "correct" it back to the vote, and do not flip it to make a count look right. The downstream half of the contract was repaired on 2026-10-17 (see "Ingestion Chain"): ingestion now emits childless `chapter` nodes as الفصل provisions and the counters count them, so a الفصل-numbered instrument no longer publishes `num_articles_detected: 0`. When such a document still looks broken, present the parser side and the ingestion side together and let the user decide which side to change.

## Node Type Dispatch in build_tree

`fetching/pipeline_base/structure.py` — `build_tree()` dispatches lines to node types via `_container_hit()` and `_article_header_info()`.

Dispatch order (first match wins):
1. `book` — كتاب (NOT الباب — that's `title`)
2. `part` — الجزء / partie
3. `branch` — الفرع / branche
4. `title` — باب / titre
5. `chapter` — الفصل (only when `doc_uses_madah=True`)
6. `section` — القسم / section
7. `article` — المادة / الفصل (when `doc_uses_madah=False`)

When `doc_uses_madah=False` (document numbers units with الفصل), a chapter interception block creates `type: "chapter"` nodes before the article path.

## Phantom Article Bugs

### Pattern: Citation lead-in creates phantom article

**Root cause**: `_split_runon_article_headers()` uses `finditer` to locate headers mid-line. When OCR returns the whole page as one line, `بناء على الفصل 102 من الدستور` hits finditer. The only guard is `before.isalnum()` (rejects if inside a word), but a space before الفصل passes.

**Fix**: `_CITATION_LEAD_RE` — matches prepositional citation lead-ins (بناء على, بحسب على, وفق على, طبق على, عملا على, بموجب, بمقتضى, استنادا إلى, تمشيا مع). The trailing preposition is REQUIRED (not optional) so a bare `بناء` at end-of-line ("the construction") doesn't suppress a real header.

**Test pattern**:
```python
def test_citation_lead_preposition_does_not_split():
    line = "أمرنا بما يلي: بناء على الفصل 102 :أصدرنا أمرنا الشريف"
    parts = _split_runon_article_headers(line)
    assert len(parts) == 1, f"split into {len(parts)}: {parts}"
```

### Pattern: Simple preposition before keyword creates phantom article

**Root cause**: `_CITATION_LEAD_RE` only matches **compound** prepositions (بناء على, بحسب على, etc.). Simple prepositions like `في` (in), `من` (from), `على` (on), `إلى` (to) that directly precede `المادة`/`الفصل` are NOT matched. So `في المادة 6 أعاله` (in Article 6 above) is split at `المادة 6`, creating a phantom article and truncating the real article's text.

**Secondary gap**: `_CITATION_POINTER_RE` includes `أعلاه` but NOT the variant spelling `أعاله` (same word, different hamza placement). So even without the lead-in fix, `المادة 6 أعاله` should have been caught by the pointer guard but wasn't.

**Fix**: Extend `_CITATION_LEAD_RE` to also match simple prepositions (`في`, `من`, `على`, `إلى`, `عن`, `ب`, `ل`) before the keyword. Add `أعاله` to `_CITATION_POINTER_RE`.

**Regression pitfall**: Do NOT generalize `_CITATION_LEAD_RE` to match ANY Arabic word (`[\u0600-\u06FF]+\s*$`). This breaks real headers that follow plain text mid-line (e.g. `نص سابق الفصل 12` — "previous text" before a real chapter header). The correct pattern matches only prepositions (single or compound), not arbitrary words.

**Test pattern**:
```python
def test_simple_preposition_does_not_split():
    line = "توجه نسخة من الحكم المشار إليه في المادة 6 أعاله، بطلب من وكيل الملك"
    parts = _split_runon_article_headers(line)
    assert len(parts) == 1, f"split into {len(parts)}: {parts}"
```

### Pattern: Citation lead-in with intervening text

**Root cause**: `_CITATION_LEAD_RE` requires the preposition to be **immediately** before the keyword. Real Moroccan enacting clauses have intervening text: `بناء على الدستور ولا سيما الفصل 102 منه` — the preposition `على` is separated from `الفصل 102` by `الدستور ولا سيما` (3 words). The regex doesn't match, so the split fires and creates a phantom chapter 102.

**Fix**: Allow bounded intervening text between the preposition and the keyword. The regex pattern is:
- Lead-in word (بناء, بحسب, وفق, طبق, عملا, بموجب, بمقتضى, استنادا, تمشيا, يلغى, يلغي, يعوض, يعوّض)
- Preposition (على, إلى, الى, لل, في, من, ل, ب, عن, حتى)
- Up to 15 words of intervening text
- End of string

**Test pattern**:
```python
def test_citation_lead_with_intervening_text():
    line = "بناء على الدستور ولا سيما الفصل 102 منه، أصدرنا أمرنا الشريف بما يلي"
    parts = _split_runon_article_headers(line)
    assert len(parts) == 1, f"split into {len(parts)}: {parts}"
```

### Pattern: Phantom empty chapter/article nodes (title but no content)

**Root cause**: OCR line breaks split a chapter header from its body text. The parser creates a node for the header but the content either goes to a different node or is lost. The result is a node with a title like `الفصل217` (keyword + digits, no space — the OCR glue signature) but zero content and zero children.

**Fix**: `_drop_empty_chapter_article_nodes()` — a post-processing pass in `build_tree()` that removes chapter/article nodes with no content and a keyword+digits title (no space), **regardless of whether they have children**. Children of a phantom node are promoted to the parent level. Runs after `_drop_spurious_bare_digit_nodes()` and before `_order_preliminary_containers()`.

**Critical**: The filter must be **targeted** — only remove nodes with the OCR glue signature (no space between keyword and number). Do NOT remove all empty chapter/article nodes, as legitimate empty containers exist (repealed chapters, inserted provisions with properly-spaced titles). An aggressive filter that removes all empty nodes breaks tests for inserted provisions and nested containers.

### Pattern: Title absorption (body text in title field)

**Root cause**: OCR garbles the chapter header and the title absorbs body text. A title like `الفصل 1248 من ق. ل ع على ما يلي: "الديون الممتازة..."` is actually body text, not a real title.

**Fix**: Title-length guard in `_split_container_header`. A real chapter/article title is short (e.g. `الفصل الأول: أحكام عامة`). A title longer than 100 chars is body text. Truncate at the first sentence boundary (colon, period, comma) or at 100 chars.

**Test pattern**:
```python
def test_phantom_empty_nodes_removed():
    pages = ["الفصل217", "الفصل الأول تحذف وزارة الدفاع الوطني"]
    tree = build_tree(pages, document_language="ar")
    # الفصل217 (no space, no content) should be removed
    # الفصل الأول (with space, with content) should be preserved
    assert all(n.get("title") != "الفصل217" for n in tree)
```

### Pattern: Preamble cross-reference parsed as false article

**Root cause**: `_CITATION_TAIL_RE` did not match "المادة N المكررة من قانون X" (article N bis of law X) — a cross-reference to another law in the preamble. The existing rule required a word between "من" and the instrument noun, but "من قانون" has none. This produced a false high-numbered article node ahead of article 1 (measured: dahir 41.10 → [16, 1, 2, …]).

**Fix**: Added patterns to `_CITATION_TAIL_RE` for "المكررة من <instrument>" and "من <instrument>" (with optional ال prefix). Real article bodies are unaffected (tested with 6 negative samples).

**Test pattern**:
```python
def test_cross_reference_rejected():
    from fetching.pipeline_base.structure import _article_header_info
    assert _article_header_info("المادة16 المكررة من قانون المالية")[0] == False
    assert _article_header_info("المادة 1 ،أعاله محل عبار")[0] == True
```

### Pattern: Cross-reference dedup missing in chapter path

**Root cause**: When `doc_uses_madah=False`, الفصل lines become chapter nodes via the interception block. The article path has cross-reference dedup (`_is_split_cross_reference_header` + `seen_articles` set), but the chapter path initially lacked it.

**Fix**: Chapter path now has:
- `_is_split_cross_reference_header(line, next_line)` guard
- `seen_chapters` set with dedup key `(scope, number, inserted_qualifier)`
- Compound header exclusion (`_AR_COMPOUND_HEADER_RE` — stays article, not chapter)

### Pattern: Chapter dedup gap — container dispatch path lacks seen_chapters guard

**Root cause**: `build_tree` has TWO chapter creation sites. The container dispatch path (line ~2014) fires FIRST for فصل headers and creates chapter nodes WITHOUT the `seen_chapters` dedup guard. The dedup-protected interception path (line ~2143) is unreachable for those headers. Result: duplicate chapter nodes when OCR re-reads a header or a run-on split surfaces it twice.

**Fix**: Mirror the full dedup guard (regex → inserted qualifier → cross-reference guard → seen_chapters check) from the interception path into the container-dispatch chapter path.

**Diagnostic technique**: When a duplicate survives despite identical dedup-key components, the guard is not on the executed path. Instrument `node()` with `sys._getframe(1).f_lineno` to trace which creation site actually fires for each node.

### Pattern: Alef normalization destroys hamza distinctions (legal terminology corruption)

**Root cause**: The alef regex `[أإآٱ]` normalizes ALL alef variants to bare `ا`, stripping the hamza (همزة) that distinguishes legal terms: `تأسيس` (establishment) → `تاسيس`, `إعلامات` (notifications) → `اعلامات` (media). The OCR fragment merge regex matched ANY 1-4 char Arabic word as a prefix, creating false compounds: `لا رجوع` → `لارجوع`, `قبل شهر` → `بشهرقبل`.

**Fix**: Alef regex narrowed to `[آٱ]` — preserves hamza-bearing variants. OCR fragment merge restricted to known Arabic prefixes (`ال|ب|ك|ل|و|ف|س|أ`).

**Diagnostic technique**: When Qdrant chunk text is garbled but the vision/extraction cache is clean, trace each sub-step of `normalize_arabic` individually and count the garbled patterns after EACH step. The step where the count jumps from 0 to N is the culprit — the input to `normalize_arabic` is clean, so the corruption is introduced inside it, never upstream.

### Pattern: Parser writes `"ref": "None"` (string) — blocks synthetic ref fallback

**Root cause**: For pre-modern instruments with no numbered ref in the title, the parser writes `"ref": "None"` (string) into JSON metadata. This string is truthy, so the builder's `if not ref_val:` guard never fires — the synthetic ref fallback is dead code.

**Fix**: Filter string `'None'` at every layer, AND make the parser emit a real ref so the JSON is self-contained:
- `fetching/adala/parser/pipeline.py` — `_build_meta` assigns `effective_date = llm_meta.get("date")` on the LLM path, then after malformed-ref discard generates `SYN.YYYY.MM.DD` from `effective_date` when `ref` is still null.
- `ingestion/extractor.py` — skip when copying `ref` from JSON metadata
- `ingestion/metadata_projection.py` — skip in nested flattening AND scalar copy
- `ingestion/pre_converters/law.py` — treat as empty in enrichment dict
- `ingestion/pipeline/builder.py` — synthetic ref generates `SYN.YYYY.MM.DD` from document date

**Rule — the parser MUST write the ref into the JSON.** A JSON carrying `"ref": null` while Qdrant carries a `doc_ref` is a defect the user will flag: "it makes no sense to have a json file without ref but qdrant has". Fixing the synthetic ref only in the ingestion builder leaves the JSON artifact and the index disagreeing, and any consumer that reads the JSON (audit, reparse-diff, provenance) sees a document with no identity. Fix at the parser source so the JSON and the index match.

**Pitfall — `_build_meta` has TWO code paths; the block goes on BOTH.** It has an LLM branch (`if llm_meta:`) and a regex fallback branch (`else:`). The synthetic-ref block AND the `effective_date = llm_meta.get("date")` assignment must be present in both. Adding only to the regex branch leaves the LLM path silent: `effective_date` is `None` there, so the block never fires and the log shows `ref from regex fallback: None` followed by no synthetic-ref line. When adding fallback logic to a multi-branch function, add it to every branch and re-run the probe for each branch.

**Pitfall — the output filename is derived from the ref, so a changed ref creates a NEW file and leaves the old one stale.** `_compute_output_path` builds `{doc_type} {ref}.json`. A document previously parsed with `ref: null` gets a synthetic ref on reparse → the parser writes `arrete SYN.1926.08.31.json` (or similar), and the old stem-named file keeps `ref: null`. When the user asks "why didn't this file get a synthetic ref", list the folder and look for a NEW file named after the synthetic ref before concluding the fix failed — the fix worked, it landed under a different name. Remove the stale stem-named file and any `(2)` duplicates so only the ref-named artifact remains.

**Diagnostic technique**: If a pre-modern document has `doc_ref=None` in Qdrant, probe `merge_item_metadata(extracted_items)` — if `item_metadata['ref']` is the string `'None'`, the projection/extractor filter is not working.

### Pattern: Stale BM25S index hides newly ingested documents from hybrid search

**Root cause**: After reingestion, BM25S still serves chunks from the old doc_id until `rebuild_from_source()` runs. Dense search finds the document (Qdrant is up-to-date) but BM25 doesn't, so RRF fusion ranks it below dual-list documents.

**Fix**: Call `SparseRetriever().rebuild_from_source()` after reingestion.

**Diagnostic technique**: If a document is in Qdrant (verified by doc_id filter) but doesn't appear in search results, check BM25 directly — if its top chunks belong to the old doc_id, the index is stale.

### Pattern: Chapter nesting under branch

**Root cause**: Chapter dispatch checked `current["title"]` > `current["book"]` > `current["part"]` but not `current["branch"]`. Siblings became parent-child.

**Fix**: Added `current["branch"]` to the nesting chain.

## count_articles and count_chapters

`fetching/pipeline_base/amendment.py`:
- `count_articles(structure)` — counts BOTH `article` AND `chapter` node types
- `count_chapters(structure)` — counts ONLY `chapter` node type

All three pipelines (ADALA, ISM, parser_base) import `count_chapters` and write `num_chapters_detected` to JSON output.

## Container Nesting Hierarchy

The `current` dict tracks the nesting state. When a new container is created, all deeper levels are reset:

```
current["book"] = current["title"] = current["branch"] = current["chapter"] = current["section"] = None
```

Nesting chain (outermost to innermost):
`root` > `book` (كتاب) > `title` (الباب) > `part` (الجزء) > `branch` (الفرع) > `chapter` (الفصل) > `section` (القسم) > `article` (المادة/الفصل)

## Vision OCR Pipeline

### Layout-guided VLM OCR (hybrid mode)

The vision engine route sends full pages to a VLM for transcription. A layout-guided mode uses PP-DocLayoutV3 to detect regions, sorts them into reading order via `merge_boxes_into_lines`, and sends each region separately — guaranteeing correct within-page article ordering.

**Performance pitfall**: Per-line VLM calls multiply API calls by 5-15x per page (one call per detected line/region). A 27-page PDF went from ~30 min to over an hour.

**Hybrid approach (default)**: Run full-page VLM first (fast, 1 call per page), detect ordering issues per page via `_page_has_ordering_issues` (uses `_article_header_info` to reject cross-references), then re-run only problematic pages through the layout-guided route. This avoids the cost for pages that do not need it.

**Settings**:
- `VISION_OCR_LAYOUT_GUIDED` (default `True`): enable layout-guided route
- `VISION_OCR_LAYOUT_GUIDED_FALLBACK` (default `True`): hybrid mode

**Flow**: full-page VLM → detect ordering issues → layout-guided re-run for bad pages only. Falls back to layout-guided-first if hybrid is disabled, then to EasyOCR/PaddleOCR if the VLM route is unavailable.

### Cross-reference rejection in `_CITATION_TAIL_RE`

Preamble citations to another law (المادة 16 المكررة من قانون المالية) were parsed as numbered articles, producing false high-numbered nodes. Added patterns for "المكررة من <instrument>" and "من <instrument>" (with optional ال prefix). Real article bodies are unaffected.

## Testing

Run structure tests:
```bash
venv/bin/python -m pytest tests/test_runon_marked_header.py tests/test_parser_structure_quality.py tests/test_branch_and_chapter_metadata.py --no-header -q
```

**A single-process full-suite run is killed by the memory cgroup.** The whole suite in one `pytest` process is OOM-killed (anon-rss ~4 GB); the journal shows `Memory cgroup out of memory: Killed process <pid> (python)`. Run ONE test file per process (resumable, skip the files already logged) and consolidate the logs. The ready-made runner, its OOM-recovery procedure and how to report the total are in the `mizan-repo-delivery` skill (its `run_suite_chunked.py` script and its `chunked-suite-run` reference). Two traps this avoids: a detached run reports the LAUNCHER's exit code, so a green exit code can hide a killed pytest — read the log, not the exit code; and under an `RLIMIT_AS` cap, torch/libtorch mmap fails, so torch-dependent tests must run WITHOUT the cap.

Key test files:
- `tests/test_runon_marked_header.py` — run-on OCR splitting, citation lead-in guard
- `tests/test_parser_structure_quality.py` — hierarchy structure, compound headers, cross-references
- `tests/test_branch_and_chapter_metadata.py` — الفرع/branch nodes, count_chapters, pipeline imports
- `tests/test_cid_fonts_text_layer_probe.py` — CID font handling, فصل detection
- `tests/test_penal_code_structure.py` — Penal Code-specific structure tests

## Ref Extraction Patterns — citation guards, target semantics, rank classification

### Always-on rules for the ADALA ref / relationship layer

Full patterns, regex bodies, worked examples and the direction table: `references/adala-ref-and-relationship-extraction.md`. The rules that apply on every call:

- **The citation connector guard must match whole words, and the clitic may be glued.** `من` inside `المنتدب` / `الأمن` / `منظمة` / `منشورات` must not read as a citation, or a real own header is taken for a cited law. A single pattern with an optional clitic (`(?<![AR])[وفبلك]?(?:conn)`) can never fire its clitic branch — the lookbehind is evaluated BEFORE the clitic — so use two branches: a bare connector bounded on BOTH sides, and a clitic+connector form bounded only on the trailing side. The same shape applies to the amendment connectors.
- **A connector guard added for one language is inert in the other.** The Arabic guard never sees French text and the French guard never sees Arabic text — write both.
- **A keyword that inflects by suffix cannot be listed as a bare stem.** `نسخ` also matches `نسخة` ("a copy"), which flips a document into amendment-style ref mode; use `نسخ(?!ة)`.
- **The target instrument is the law cited in the SAME CLAUSE as an enacting formula**, not every law in the preamble. Enacting formulas (`يأمر بتنفيذ القانون رقم X`) are deliberately separate from visa formulas (`بناء على` / `بمقتضى` / `Vu la loi`): a visa states what the instrument is founded on, not what it enacts. The clause is bounded by newline and clause punctuation, and DOTS ARE NOT BOUNDARIES (refs contain dots).
- **Direction is derived from the rule, never read off the model.** target + `dahir` → `promulgates`/`upward`; target + `decret` → `implements`/`downward`; anything else → `references`/`lateral`.
- **Ref comparison is canonicalised, never literal.** Dots (`26.16`) and dashes (`26-16`) are the same law. Keep a comparison-only key separate from the stored spelling; never overwrite the stored spelling with the canonical form.
- **`extract_relationships` must receive the caller's already-resolved own ref** and compare self-references by canonical key — not recompute the own ref through a different path.
- **An instrument's type comes from its OWN header, in the document's language**, matched whole-word on the EARLIEST instrument keyword (the own word comes first, cited ones follow). A framework law (`قانون إطار` / `loi cadre`) is checked AFTER the own-instrument scan. The same classifier must be shared by every caller, or two code paths disagree about the same document.
- **A guard that reads a value ANOTHER layer computes must veto only on a POSITIVE disagreement — never on the absence of agreement.** The consolidated-law guard rejected a document's own law whenever the title did not LEAD with it. But the pipeline's real title for a consolidated law is the promulgating dahir's line: the title extractor returns the first PATTERN that matches, and the dahir pattern is listed before the law pattern, so the title begins with the dahir. Requiring the title to lead with the law made the guard fire on every real consolidated law, and the ref fell through to the dahir that enacted it — the law was indexed under its promulgating instrument. The head's own order already decides the annex case (a dahir that reproduces a law names its own instrument FIRST), so the title is a SECOND opinion: veto only when it names a DIFFERENT law. Widening the title extractor instead (taking the earliest match across every pattern) fixed the target and moved an unrelated document's value — the guard's condition was the correct place to change.
- **Decide "leads with" by the first INSTRUMENT keyword, not the first character.** A title carrying a promulgation formula in front of the law (`تم نسخ القانون رقم 41.10 المتعلق بـ …`) DOES lead with the law; a dahir reproducing a law as an annex (`ظهير شريف رقم 1.10.191 صادر … بتنفيذ القانون رقم 41.10`) names the dahir first and does not. An anchored `^قانون` rejects both the formula case and the annex case, and cannot tell them apart.
- **French title stop markers cut at the EARLIEST match, with grouped alternation** — an ungrouped `\\s*:modifiant|complétant|abrogeant` scopes its precedence wrongly and cuts the title mid-word.
- **Filename extension stripping must not truncate a ref.** `filename.rsplit(".", 1)[0]` turns `ظهير شريف رقم 1.12.34` into `1.12`. Strip the crawler timestamp FIRST, then only a REAL extension (`pdf`/`doc`/`docx`/`txt`/`html`). A bare `rsplit(".", 1)` is never correct here.

### Pattern: Repeal verbs missing from amendment detection

**Root cause**: `_AMEND_KEYWORDS_AR` includes amendment verbs (يغير, معدل, نسخ) but NOT repeal verbs (يلغى, يعوض). A repealing dahir whose title says `يلغى ويعوض بموجبه الظهير الشريف رقم X` is not detected as amendment-style, so the filename priority returns the repealed ref instead of the own ref.

**Fix**: Add `يلغى|يلغي|يعوض|يعوّض` to `_AMEND_KEYWORDS_AR`.

### Pattern: Amendment detection only checks filename/title, not pages

**Root cause**: `is_amendment_style` in `extract_ref()` only scans `filename` and `title` for amendment keywords. Repeal verbs often appear only in the page text (preamble), not in the title or filename.

**Fix**: After checking filename/title, also scan `pages[:5]` for amendment keywords.

### Pattern: Parser output metadata contract — ref at top level only

**Root cause**: The ADALA parser writes `ref` at the top level of the output JSON
but does NOT include it in the `metadata` sub-dict. The ingestion layer
(`law_adapter.py`) reads `metadata.get("ref")` — which returns None — and
falls back to extracting refs from text, producing wrong values.

**Fix**: Add `"ref": str(ref)` to the metadata sub-dict in the parser's output
dict construction (`fetching/adala/parser/pipeline.py`, metadata block).
Fix at the source — do not patch every downstream consumer.

**Test pattern**:
```python
def test_metadata_ref_populated():
    # After parsing, metadata.ref should match top-level ref
    assert doc["metadata"]["ref"] == doc["ref"]
```

### Pattern: Law ref mid-title not detected as derivative

**Root cause**: The auto-derivative detection in `extract_ref` only caught titles ending with the law number (regex `رقم\s*[\d.]+\s*$`). Titles like "القانون رقم 41.10 المتعلق بتحديد شروط..." have the law number in the middle, so the detection failed and the parser extracted "41.10" (the law number) as the ref instead of the promulgating dahir "1.10.191" on page 3.

**Fix**: Remove the `$` anchor from the `last_was_num` regex so it matches "القانون رقم X" anywhere in the title. The `ins_marker_before` check still correctly rejects titles that have both a law ref and an instrument ref with publication markers.

**Test pattern**:
```python
def test_mid_title_law_ref_detected():
    from fetching.adala.parser.extraction import extract_ref
    title = "القانون رقم 41.10 المتعلق بتحديد شروط ومساطر الاستفادة من صندوق التكافل العائلي"
    pages = ["", "", "ظهير شريف رقم 1.10.191 صادر في 7 محرم 1432"]
    ref = extract_ref(pages, "ar", title=title, filename="صندوق_التكافل_العائلي_1707305363226.pdf")
    assert ref == "1.10.191"
```

### Pattern: ADALA pipeline missing num_chapters_detected

**Root cause**: The ADALA pipeline (`fetching/adala/parser/pipeline.py`) never sets `num_chapters_detected` in its output dict, even though `parser_base` and `ISM` pipelines do.

**Fix**: Import `count_chapters` from `fetching.pipeline_base.amendment` and add `"num_chapters_detected": int(count_chapters(structure)) if structure else 0` to the output dict.

## Ingestion Chain — what survives the parser

The parser's node types decide what ingestion keeps. Trace in this order:

1. `ingestion/pre_converters/helpers.py::_flatten_adala_structure` (reached via `pre_converters/base.py::_flatten_structure` from `pre_converters/law.py::convert`) walks the tree and emits a flat article for:
   - every node with `type == "article"` — always;
   - childless nodes of type `title|book|part|section|preamble|chapter` carrying >= 20 chars of content.

   `chapter` was missing from the second list until 2026-10-17. A `chapter` node holding provision text in `content` with no children — exactly the shape `build_tree` produces for الفصل-numbered documents — was dropped. It is now emitted with `provision_ref: "Fasl. N"` (the label the regex chunker already used) and `chunk_kind: "fasl"`; a chapter container that holds articles still has children, so it is still skipped.
2. `ingestion/adapters/law_adapter.py` trusts `metadata["flat_articles"]` whenever it is non-empty and skips the Arabic text-based article extractor; that extractor does not recognise الفصل headings either (measured: 0 articles on الفصل-numbered pages), so nothing recovers downstream.
3. `ingestion/stages/chunk/_engine.py::chunk_from_structured` iterates `flat_articles`, reads `chunk_kind` off each flat item (default `"article"`) and labels الفصل units `Fasl.N` in `article_id`. Its regex/full-text fallback and the `MZ-E-CHUNK-001` silent-degradation alarm fire ONLY when `flat_articles` is empty — one surviving preamble item suppresses both.

Consequence of the pre-fix state: such a document indexed its preamble and nothing else, with no degradation metric raised. The text still reached ingestion as `full_text`, so the document stayed findable as a blob; what was lost was provision-level chunking, `provision_ref`, and article-level retrieval.

Measured on the ADALA Arabic set before the fix: 9 of 31 reparsed documents (every الفصل-numbered instrument) retained 8-47% of their source text through the flatten; the 21 المادة-numbered documents retained 87-99%. After the fix on the same 37-document set: 136 fasl provisions emitted, 0 documents below 0.5 retention, and 1.72.524 went from 1 flat item (0.084) to 18 (0.95) — 18 chunks with `chunk_kind: "fasl"` through the real `chunk_from_structured`.

Widening the counters is part of the same change: `count_articles` in all three provider `_shared.py` copies, `has_article_structure` and the ADALA hybrid `_count_articles_in_tree` must all count `("article", "chapter")`, otherwise they keep publishing `0` for exactly the documents the flatten now recovers.

## Page-Level Loss and Cross-Provider Drift

These are parser-layer rules that are NOT phantom-article variants: they lose whole pages, whole documents, or whole provider behaviours. Verified against the real corpus and real vision caches.

1. **A TOC marker that matches a body word silently deletes the page.** `_TOC_MARKER_RE` matched `محتويات` anywhere on the page. "Physical contents" (`المحتويات المادية`) inside a list item made an ordinary page look like an index, and `build_tree` skips TOC pages outright — the page's provisions vanish, no counter moves, and `structure_degraded` stays `false`. A TOC marker must be line-initial / heading-shaped, never a bare body word that also occurs in prose. Always measure `_is_toc_page` over every cache and report *pages dropped per document*, not just documents affected — a page-count ratio is the only thing that shows how much was lost.

2. **A richness signal that counts citations steers selection to the wrong page.** `_article_identity_set` counted mid-line `الفصل N` citations as provisions, so an amendment-note page out-scored the operative page and won the per-page text-source selection. The note then became a chapter header carrying the SAME `provision_ref` as the genuine provision (`Fasl. 446` for both the citation and the real article 446). Any count used to RANK or SELECT pages must apply the same citation guards the semantic path uses — use `_article_header_info` (citation-tail + pointer guards), never a raw header regex. A "fix" that only drops the note block but leaves the selection signal counting citations does not remove the phantom.

3. **A dedup key built from a truncated number collides.** `_split_container_header` truncated 4-digit provision numbers (`الفصل 1000` → `100`, `الفصل 1248` → `124`), so distinct provisions collapsed onto one dedup key and one was dropped silently. Provision identity must carry the full number.

4. **Bidi formatting characters survive ref normalisation and defeat self-reference exclusion.** `STRIP_RE` in `core/ref_normalizer.py` covered zero-width and C0 controls but not U+202A–U+202E, U+2066–U+2069, U+200E/U+200F. A ref like `'\u202b\u202a1.10.191\u202c\u202c'` therefore reached the JSON, the FILENAME and Qdrant. Separately, `_drop_self_references` compared raw strings, so the document ended up with a `promulgates` edge to itself. Strip bidi marks in the normaliser AND compare self-references by canonical key, not literal string.

5. **LLM-extracted relationships need the same validation as regex ones.** The LLM path only *defaulted* `direction` and never checked that `target_ref` is a reference, so a title phrase ("the civil society award") became a `promulgates` edge, and the LLM's `direction` contradicted the deterministic `_relationship_label` rule. Re-derive `direction` from the rule and reject non-ref targets.

6. **A duplicated provider implementation drifts silently — scan for SYMBOL presence, not just behaviour.** One provider forked from another and missed 11 fix commits; 25+ symbols present in one were absent in the other, and the divergences were behavioural (rank classification, ref dedup, `legal_rank` validation, an escaped-regex bug). When two providers share an implementation, diff the symbol sets and run identical input through both, then compare. A behavioural spot-check is not enough — it will not surface the symbols that only one side has. **COUNT the copies before calling it a two-provider divergence** — grep the SYMBOL across the whole tree, because the shared base is usually a THIRD copy and two of the three may already carry the refined rule (a native-sufficiency gate lived in `parser_base`, `ism` AND `adala`, and only the third had drifted). Share the implementation so all copies are the IDENTICAL function object rather than copying the refined rule into the stale one; the recipe is the `mizan-pipeline-audit` skill's `references/shared-helper-extraction.md`.

   **The specific instances measured in the 2026-10-22 wave** (all three in the ISM pipeline, all fixed by sharing): ISM had NO `_drop_self_references` at all while ADALA had it, and called `extract_relationships` without `own_ref` — so a document's own ref survived as its own relationship and citation. ISM's `_valid_instrument_ref` kept an inline regex with `{0,3}` repetitions, so ZERO were permitted and a single-segment token (`"719"`, `"03"`, `"5"`) passed where ADALA's validator and the shared `_plausible_ref` contract both reject it — the LLM path could then persist a ref the deterministic extractor can never produce, and a citation fragment became the document's identity. And ISM's `_validated_doc_type` lacked BOTH of ADALA's guards: the implementing-dahir fix (a document the scan calls `loi` whose head carries `ظهير شريف` deeper in is the dahir, not the law) and the `loi_cadre` check — so an ISM document could get a type that contradicts its own `legal_rank`, and the framework-law case returned `loi` from ISM and `loi_cadre` from the rank classifier. **A guard that only one side has is invisible to a behaviour spot-check** — diff the symbol sets and run identical input through both providers.

7. **Regex escaping is lost when code is copied between providers.** A fork carried `r"...\\s*..."` (literal backslash + s) where the source had `r"...\s*..."`, so the pattern never matched whitespace and an entire guard became inert with no error. After any copy between providers, re-run each changed pattern against a known-good sample and assert it matches — a pattern that matches nothing raises nothing.

8. **Count corpus-wide defect classes with the strictest pattern that still matches, then re-verify before reporting.** A loose regex (`\s*` between keyword and digits) conflates genuine spaced headers with OCR-shredded ones and inflated a measured rate roughly fourfold. State the pattern used next to the number, and when an earlier number in the same report is wrong, correct it explicitly rather than quietly restating — the correction is the evidence that the number was re-measured.

9. **A synthetic example in an audit is not evidence that the shape exists.** A finding written as "الفصل 1000 → 100" may rest on an invented string. The real corpus occurrences of that shape were six-digit running-head folios (`الفصل 436133` = chapter 436 on page 133), not four-digit chapter numbers. Search the corpus for the real shape before building a fix, then treat the synthetic case as the latent one it is.

## Structure-engine defect classes

### Pattern: a Markdown pipe table is a cross-reference index, not a provision

**Root cause**: some vision-OCR output renders an index as a Markdown pipe table. Each row NAMES a provision — `| | - القتل غير المتعمد (المصدر: الفصل 489) | 489 |` — and the run-on splitter cut the row at that name, so every row became a phantom provision carrying a `provision_ref` ("Fasl. 489") indistinguishable from the real one (70 in one document).

**Fix**: recognise a pipe row by its SHAPE (a leading `|` and at least two pipes in the line; Arabic legal prose does not use pipes) and refuse it in three places — the article-header detector, the container-header detector and the run-on splitter — then drop the table block from the hierarchy.

**The text is not lost**: the ingestion layer reads the authoritative page text from the vision cache, so every row stays searchable as text; the rows leave the HIERARCHY only. Verify the source of `full_text` before assuming a drop is safe.

**Pitfall — the drop set is shared with the footnote record.** `build_tree` collects dropped lines into one index set and then records them as footnote text. A table is not editorial apparatus, so its rows must be subtracted from the recorded text or they get filed as footnotes. Give each drop reason its own set and subtract the new one.

### Pattern: a citation-tail regex anchored at `^` misses punctuation-prefixed citations

**Root cause**: every alternative of `_CITATION_TAIL_RE` is anchored at the first character, but the OCR leaves the separator in front of the citation — "الفصل446 ،من القانون الجنائي" — so the tail starts with "،" and no alternative fired. Nine provision nodes in the corpus were pure citation continuations.

**Fix**: do NOT rewrite the alternatives. Add a helper that ALSO tries the punctuation-stripped form, and route every call site through it:

```python
def _is_citation_tail(rest: str) -> bool:
    if not rest:
        return False
    if _CITATION_TAIL_RE.match(rest):
        return True
    return bool(_CITATION_TAIL_RE.match(_LEAD_PUNCT_RE.sub("", rest)))
```

The stripped form is only ever ADDED to the verdict, so a tail that already matched still matches. Call sites: the header-info path, the compound path, the split path and the container path — miss one and the class survives there.

### Pattern: a shredded citation and a real provision are indistinguishable by line shape

**Root cause**: the native text layer shreds a page so that a citation lands on a line of its own —

```
القاضي بتغيير وتتميم
الفصل446
،من القانون الجنائي
```

— and "الفصل446" has the same shape as a real shredded header. Any position-based rule (keyword at line start, keyword glued to the number) rejects real headers too, because the native layer glues THOSE as well — measured: 198 of 207 native pages carry glued candidates while 0 of 207 vision pages do.

**Fix**: decide on what FOLLOWS the candidate, not on the candidate's shape. A provision is followed by its own words; a citation is followed by the instrument it points at. Look ahead to the next header candidate and test the intervening text with the citation-tail guard.

**Share the SIGNAL, not the decision.** Put the identity function in `fetching/pipeline_base/structure.py` and have every provider call it; a per-provider copy of a selection signal is exactly how two providers drift (see item 6). Each provider keeps its own POLICY — which text source wins — in its own module.

### Pattern: a single-provision instrument prints its ONE provision in a form the map does not hold

**Root cause**: an instrument that consists of a single provision heads it with `فصل فريد` ("a unique chapter") or `مادة فريدة` ("a unique article"). `ingestion/patterns.py::AR_ORDINAL_MAP` already carried these as sentinels — `الفريد`/`الفريدة` → *unique*, `الوحيد`/`الوحيدة`, `التمهيدي` → *preliminary* — and `_article_header_info` returns `(True, None, None)` for a sentinel ("a header with NO number"). **Only the definite forms were in the map**, so the bare form matched nothing and the whole document collapsed into one preamble node: `dahir 1.17.42`, `dahir 1.72.138`, `decret 2.64.344`, `decret 411.67`, `dahir 1.94.288` all parsed with **zero articles** (which also trips the `MZ-E-CHUNK-001` silent-degradation alarm).

**Two facts had to be fixed, not one**: the sentinel map, AND the fact that the bare `فصل` is not a container keyword — so the line falls through to the article path, where the keyword must be followed by a resolvable number or ordinal. The `ال` in the article keyword pattern is optional (`(?:ال)?`), which is exactly why `الفصل الفريد` was already recognised and `فصل فريد` was not.

**Fix**: add the bare sentinels beside the definite ones (`فريد`, `فريدة`, `وحيد`, `وحيدة` → *unique*). A unique provision is a **numbered-free** header: it yields an `article` node with `number=None`. Never invent a number — a fabricated provision number is a fabricated citation.

**Rule — check the ORDINAL MAP for the bare/definite asymmetry before concluding a header form is unsupported.** The map is a lookup of spellings, and legal instruments are inconsistent about the article. Grep the map for the word in BOTH forms; the definite form existing proves nothing about the bare form.

### Pattern: a header inside an unclosed parenthesis is a note, not a provision

**Root cause**: the same words are used as STRUCTURAL NOTES. The penal code prints `(فصل وحيد)` under a branch to say the branch holds one chapter — it heads nothing; a penalty table prints `(الفصل 392-فقرة 1)` inside a table cell — a cross-reference. The run-on splitter **cut the line at the opening parenthesis** and the right-hand fragment became a header in its own right, so the penal code grew an empty chapter titled `فصل وحيد)`.

**Fix**: one principle, applied at every place that can promote a fragment —

> A header inside an unclosed parenthesis is a cross-reference or a structural note, never a provision of this document.

`_inside_unclosed_paren(text, position)` (prefix-based: is `position` inside a `(` that is still open?) is consulted by `_split_embedded_headers` (the reflow splitter), `_split_runon_article_headers` (the run-on splitter), `_article_header_info` (the article path) and `_container_hit` (the container path). **Miss one and the class survives there** — the same rule as the citation-tail guards.

**Pitfall — a BALANCED parenthesis is unaffected.** `الفصل 233 (الفصول 233 – 262)` is a real chapter header with a range note and must still parse as chapter 233. The check is on the unclosed prefix, never on the mere presence of a `(`.

**Pitfall — do not check the LINE's prefix in the article path.** A candidate can be lifted from anywhere in the line, so the surrounding text may hold an unrelated parenthesis. Check the CANDIDATE's own prefix there, and the line's prefix in the splitters, where the boundary position is known.

### Pattern: a missing source directory is not an error

**Root cause**: `output_stem_for` lists a PDF's siblings to decide whether its base name collides with another file. The listing crashed in THREE copies: ADALA's `_sibling_pdf_names` had an `except OSError` branch that called `iterdir()` on the *same* missing path (re-raising the same `FileNotFoundError`), and ISM's and parser_base's called `iterdir()` with no guard at all. A source category directory that was renamed or moved is a NORMAL state, not an exception.

**Fix**: the canonical `sibling_pdf_names(directory)` in `fetching/pipeline_base/paths.py` returns `()` for a directory that is missing, unreadable, or is not a directory. A folder that is not there cannot collide with anything. The third copy is exactly why the lookup belongs in the shared module.

**Rule — an `except OSError` branch that calls the same failing API is not a fallback.** Ask what the answer should be when the operation legitimately cannot succeed; here it is "no siblings", not "raise the same error one line later".

**Rule — make the three provider copies AGREE while you are in there.** They each stripped the extension with a fixed-length slice (`other[: -len(".pdf")]`), which leaves a trailing dot for an UPPERCASE extension — `doc_1710247000003.PDF` became `doc_1710247000003.`, the timestamp no longer matched, and the timestamp stayed in the output name. Cut at the last dot instead.

### Pattern: a first-group check needs the COMPLETE kind set, not a plausible one

**Root cause**: `_normalize_ref_order` repaired an RTL group-order reversal whenever the first group was not an instrument kind and the last group was 1-4. But `4` is not an instrument kind: every corpus ref of the shape `<n>.<n>.4` is a BO or case number, and the rule rewrote `000.500.4` into `4.500.000` — a ref that never existed. The rule also accepted any middle group, so a money amount ending in a small group could be reshaped.

**Fix**: require the last group to be a REAL kind (`{1,2,3}` — dahir, decret, loi) and the middle group to look like the Hijri year (2-3 digits). Both corpus reversals (`18.13.2` → `2.13.18`, `202.02.1` → `1.02.202`) are still repaired.

**Measure the kind set, do not assume it.** Across all five providers and 195 stored refs, exactly two have a first group outside `{1,2,3}` — and both are the reversals the rule exists to fix. Everything else that looks like a ref outside the instrument set is a MONEY AMOUNT (`104.769.65 درهم`, `150.000.000`) or a reversed citation.

**Residual risk to state plainly**: a ref whose first group is outside `{1,2,3}` is still reordered. That is safe for this corpus because the kind set is measured complete, but a future provider numbering instruments "4.xx.x" would need the rule widened — and the honest fix is a CONTEXT-aware reorder that confirms the kind from the instrument word before the ref ("المرسوم رقم X" ⇒ kind 2), not a longer list of kinds.

### Pattern: a heading filter that matches a LETTER matches half the language

**Root cause**: `_is_phantom_provision_title` decides whether a provision title is body text glued onto a header. Three of its rules matched ordinary chapter titles: a continuation rule that fired on the first LETTER of a title word (`وثيقة التجنیس` starts with و, and `وما بعده` is a compound label), a clause rule that treated any spaced dash as a run-on (a dash between two noun phrases and a numeric range are both headings), and a glue rule that fired on any Arabic letter glued to a digit anywhere in the title (a footnote number at the end of a title, and the bis label `الفصل 86 مكرر76`, are not glue).

**Fix — one principle each**: a continuation must be a CLAUSE (3+ words), not a short noun phrase; a spaced dash is a clause boundary only when it CLOSES A SENTENCE (it follows a full stop); the OCR-glue signature must be IN THE MARKER (the keyword run together with its own number) or a digit glued to a SPELLED-OUT ORDINAL (`الفصل الرابع عشر8`, whose tens words must be listed explicitly — the canonical ordinal map has the compound forms but not the bare tail word).

**Measure the filter as a set, not per rule.** Over the corpus: 69 flagged before, 57 after, 12 over-filters removed, **0 newly flagged** — the change only ever releases, never rejects. The two-root diff then shows 0 provisions gained, 0 lost, 0 numbers changed, which is the real proof that the filter was tightened without changing an outcome.

**Why the corpus impact was 0 and the defect was still real**: the drop only fires on a node with no content AND no children, and 0 flagged nodes were empty. The defect was LATENT — a chapter whose descriptive title matched the patterns and whose body fell on the next page would be dropped. Note the asymmetry: a false positive DESTROYS a real provision, a false negative only leaves an empty node behind.

### Pattern: a running-head folio glued to a container number

**Root cause**: the OCR merges the running head with the page folio, so "الفصل 436133" is chapter 436 printed on page 133. The container-number regex capped at three digits, so the number came out right by accident while the TITLE kept the folio — and a real four-digit chapter was truncated to three.

**Fix**: allow four digits in the container-number group, and when the digit run continues past the number, split it — a Moroccan code numbers its chapters below 1000, so the first three digits are the chapter and the rest is a folio that must leave the title.

## Auditing a reparse ("check now")

**Rule — quarantine is not a defect.** Before reporting a document as broken, check WHERE its source PDF lives. A PDF under `data/corpus/<provider>/raw/corrupted/` is a known-CMap-corrupt file that was quarantined on purpose; a JSON built from it that has only a `preamble` node and `num_articles_detected: 0` is the EXPECTED outcome, not a parser regression. The same is true of a source that never had a vision cache. Report these as "awaiting vision OCR", separately from documents whose source is a clean PDF in `raw/` — mixing the two turns a quarantine backlog into an alarming defect list.

**Rule — a preamble-only tree has a specific shape.** `structure` containing exactly one `preamble` node with no article or chapter child, and `num_articles_detected: 0` AND `num_chapters_detected: 0`, means the parser found no provision headers at all in the text it was given. That points upstream (garbled or empty page text) rather than at the typing or flattening layer. Dump the node kinds before theorising.

The user reparses a set and then asks you to check it. Never re-parse to answer that — read what is on disk, in this order:

1. Per document, read `structure_source` and `structure_degraded` from the JSON. `structure_source: "vision"` means the tree came from `cache_vision/<stem>_<sha12>_vision.json` and `structure_text_cache` names that exact file; `structure_degraded: true` means a vision pass was attempted and lost. This separates an OCR-cache problem from a structure/typing problem.
2. Load that exact cache file and count the line-initial markers the parser should see (`الماد[ةه]` vs `الفصل`). N الفصل headers together with `num_articles_detected: 0` is a node-typing/ingestion problem, not a missing cache.
3. Re-run the REAL functions over the cached pages instead of reasoning about them, then compare against the JSON on disk:

   ```python
   from fetching.pipeline_base.structure import build_tree
   from ingestion.pre_converters.helpers import _flatten_adala_structure

   tree = build_tree(pages, document_language="ar")
   flat = _flatten_adala_structure(tree, None)
   ```

   `scripts/audit_parsed_structure.py` does this for a whole JSON directory.
4. Report the retention ratio (`kept flat-article chars / source chars`), not only the article count — the ratio is what shows the loss is real. Flag every document below ~0.5 and every `num_articles_detected == 0`.

Run probes with the project interpreter, `./venv/bin/python` from the repo root: the system `python3` lacks the app dependencies (`pydantic_settings`) and the import fails before any probe runs.

## Force-reparse workflow (cache-first, no duplicates)

When the user says "reparse the files in this folder", the expected behavior is: overwrite existing JSONs in place, reading from the vision cache — NOT create `(2)` duplicates and NOT re-run OCR from PDFs.

**Procedure**:
1. Identify which PDFs have a vision cache: match the PDF stem against filenames in `data/corpus/adala/cache_vision/`.
2. Run `process_file(pdf, lang="ar", force=True)` only for PDFs with a cache. Skip PDFs without a cache — the user expects the cache to be the source of truth.
3. After the reparse, verify no `(2)` files exist. If any appear, check the collision-fix patch is present in `pipeline.py`.

**Root cause of `(2)` duplicates on force-reparse**: The ADALA parser's collision handler appends `(2)`, `(3)`, etc. when a file with the same name already exists. Under `force=True`, the `_existing_by_source` resolution was skipped (the `elif not force` branch was not taken), so the handler never found the existing JSON. Fix: added an `else` branch that also runs under `force=True` to resolve `_existing_by_source` (v1.113.3).

**Pitfall — force=True must still resolve the existing path**: Any code path that bypasses the `not force` guard must still resolve `_existing_by_source` before the collision handler runs, or duplicates are created. The collision handler's reuse logic only fires when `existing_path` is not None and matches the expected pattern.

## Ingestion API for Single-Document Testing

When testing ingestion of a specific JSON file (e.g. verifying a reparse), use the Python pipeline directly — the API endpoint requires auth and times out on cold model loads.

```python
from ingestion.pipeline.runner import IngestionPipeline

runner = IngestionPipeline(enable_ocr=False)  # NOT qdrant_manager=...
result = runner.process_file(
    json_path,
    doc_metadata={"source_provider": "adala", "language": "ar"},  # NOT default_metadata=
    run_id=f"adala_single_{int(time.time())}",
)
# result is None on failure; runner.last_skip_reason() gives the cause
```

**Pitfall**: The constructor does NOT accept `qdrant_manager`. The method is `process_file` (not `process_single`), and its second argument is `doc_metadata` (not `default_metadata`).

## Comparing a revision against the working tree

To prove a defect comes from an uncommitted change, do NOT stash or check out in the user's repo. Materialise the committed tree in the scratch directory and run the SAME probe against both roots:

```bash
SC=<scratch>/headcheck && rm -rf $SC && mkdir -p $SC
cd <repo> && git archive HEAD | tar -x -C $SC
./venv/bin/python probe.py $SC   <repo>   # committed behaviour
./venv/bin/python probe.py <repo> <repo>   # working-tree behaviour
```

**`HEAD` is the CURRENT commit — name the revision the baseline is meant to be.**
After the fix is committed, `git archive HEAD` materialises the FIX, so the
"before" run exercises the fixed code and the comparison reports agreement
that proves nothing. For a pre-fix baseline use the revision the change was
measured against (`HEAD~1`, or the wave's base SHA) and say which revision the
"before" came from. The trap is silent: the run succeeds, the numbers look
plausible, and the conclusion is backwards.

**Parameterise the probe's import root; a hardcoded path silently tests the
wrong tree.** A probe with `sys.path.insert(0, "/home/mohammed/Mizan")`
imports the LIVE tree no matter which root it was copied into, so the
"committed" run measures the working tree. Read the root from the environment
(`os.environ.get("MZ_ROOT", ...)`) or pass it as an argument, and print the
root the probe actually imported at the top of its output — then a wrong-root
run is visible instead of plausible.

**Detect the language from the HEAD, never from the stored `language` field.**
A corpus A/B that re-extracts a field per document must not trust the stored
language: jurisprudence records carry Arabic text with `language: "fr"`, and
running the French extractor on Arabic text produced 200+ spurious "changes"
that read as a regression. Count Arabic-block letters against ASCII letters in
the head and say which method you used.

`git archive HEAD | tar -x` yields a whole committed tree, so a probe may import anything; `git show HEAD:<path> > <scratch>/<path>` is the single-file variant. Same probe, two roots, one variable — and the working tree, caches and JSON outputs stay untouched. Keep the copy in the session scratch directory, never inside the repo.

**The corpus is not in `git archive` — pass its path as a second argument.** The data tree is untracked, so a probe rooted at the scratch copy finds no JSON. Symlinking `data/` into the scratch root does NOT work either: `glob.glob(..., recursive=True)` does not descend into a symlinked directory, so the probe silently finds nothing and reports "no documents". Pass the corpus root explicitly and glob against it.

**The probe must reproduce the pipeline's selection, or the diff is meaningless.** A JSON on disk was built from a SELECTION between the vision and native layers; a probe that rebuilds from one layer alone reports provisions as "lost" that the pipeline never produced that way. Call the provider's own selection function inside the probe, or compare two roots through the same path.

**Classify every provision the diff reports as lost — "lost" is not a verdict.** For each missing number, ask whether the document prints it as a SPACED header somewhere ("الفصل 446") or only ever GLUED ("الفصل446"). A spaced occurrence is a real provision the change destroyed — blocking. A glued-only occurrence is a native-layer shred artefact — removable. This classifier is the difference between "4 provisions lost" (revert) and "0 real lost, 4 artefacts" (ship).

Full harness, metric set and the policy-comparison recipe: `references/parser-change-measurement.md`.

**The two-root diff catches the regression YOU introduced.** In the 2026-10-20 wave, adding a French branch to an `if language == "ar":` block by writing `else:` put the whole Arabic auto-derivative block into the `else:` — so Arabic documents stopped being auto-detected and one arrete began reporting the cited law instead of its own ref. Nothing in the unit tests noticed; the corpus diff did, in one run. Treat a diff that shows a change in a provider whose behaviour you did not intend to alter as a BLOCKER, not a curiosity.

**Watch the indentation scope of a patch, not just its text.** A patch that looks like a two-line addition can capture an arbitrary block when it introduces an `else:`/`elif` at the wrong level. After any edit that adds a branch, re-read the surrounding 40 lines and confirm which statements the new branch now owns.

**A changed ref is not automatically a regression — check what the DOCUMENT's own identity is.** Compare against the JSON's stored `ref` and the title's own header: "own ref instead of a cited law" is an improvement, "own ref instead of a scrambled group order" is an improvement, and "cited law instead of own ref" is a regression. The pipeline's own `metadata.ref` is the ground truth to check against.

## Where the reference grammar lives now (2026-10-20)

The ref grammar and the ref extraction were consolidated out of three drifting copies (`parser_base`, `ism/parser`, `adala/parser`):

- `fetching/pipeline_base/ref_grammar.py` — the canonical ref patterns and the helpers that read them (`_plausible_ref`, `_scan_derivative_own_ref`, `_scan_own_instrument_marker`, `_classify_target_type`).
- `fetching/pipeline_base/ref_extraction.py` — the canonical extraction (`extract_ref`, `extract_relationships`, `_ref_key`, `_own_ref_match`, `_explicit_instrument_ref`, `normalize_refs`).
- `fetching/pipeline_base/classification.py` — the canonical classification (`detect_legal_rank`, `detect_amendment`, `detect_legal_domain`, `_folder_to_domain`, `validate_legal_rank`).
- `fetching/pipeline_base/paths.py` — `rebase_corpus_path()`, which re-roots a corpus path at the LOCAL project root (a JSON parsed on another host carries that host's absolute path, and the ingestion layer OPENS `source_file` to read the sidecar), and `sibling_pdf_names()`, the crash-free directory listing every provider's `output_stem_for` uses.

The provider `_shared.py` / `classification.py` / `extraction.py` files import or re-export from them. **Add a pattern or a rule to the canonical module, never to a provider copy** — a provider-local pattern is how the copies drifted apart in the first place. `core/ref_normalizer.is_instrument_ref()` is the strict schema for "is this a legal reference" (`normalize_ref` is the loose DISPLAY canonicaliser and cannot answer that question).

**Consolidating two forks: take the UNION of their data, not one side's.** The ISM `FOLDER_DOMAIN_MAP` carried 14 legacy crawler folder names (`comercial`, `penal`, `social`, `droitdelhome`, …) that ADALA's map lacked. Consolidating onto ADALA's map would have silently cost ISM its folder mapping — the project's own guard test caught it, but only because that test existed. When merging two provider copies of a LOOKUP TABLE, diff the keys first and keep every entry from both.

**The two ref producers disagree on shape, and the output must accept both.** `extract_refs` returns `(type, value)` TUPLES; the LLM path builds DICTS. Rebuilding the list with `for t, v in refs` stored the dict KEYS as data — every reference became `{"type": "type", "value": "value"}` (14 across 7 ISM documents). `normalize_refs()` accepts both shapes; use it wherever references are serialised.

**`mypy` does NOT cover `fetching/`** — the pre-commit gate runs it on `api core retrieval reasoning ingestion graph ontology query billing services` only. Check `venv/bin/python -m mypy fetching` by hand after touching the parsers. And narrow an `object`-typed input explicitly (`isinstance(x, (list, tuple))`) before iterating it: mypy rejects `for x in obj` with `"object" has no attribute "__iter__"`.

## Pitfalls

- **Parser writes `ref` at top level only — ingestion reads `metadata.ref`**: The parser's output dict has `ref` at the top level but NOT inside the `metadata` sub-dict. The ingestion layer (`law_adapter.py`) reads `metadata.get("ref")` — which returns None — and falls back to text extraction, producing wrong refs. Fix at the parser source by adding `"ref": str(ref)` to the metadata sub-dict. Do not patch every downstream consumer.
- **Qdrant scroll requires POST to `/collections/{name}/points/scroll`**: The Python client's `scroll()` method is slow on large collections and can time out. Use the REST API directly: `POST /collections/{name}/points/scroll` with `{"limit": N, "with_payload": true}`.
- **ref=None does NOT prevent ingestion**: Documents with no extractable ref
  still ingest successfully — `doc_id` is a random UUID, `law_name` falls
  back to title, chunks are created, points land in Qdrant. To verify a
  document was ingested, check SQLite first (`SELECT doc_id, title, ref
  FROM documents WHERE title LIKE ...`), then Qdrant (filter on `doc_id`).
  A doc in SQLite but not Qdrant = ingestion failed after chunking. A doc
  not in SQLite = never ingested (e.g. reparsed after the last ingestion
  run). Do NOT assume ref=None drops a document — prove it with data.
- **ref=None makes documents invisible to ref-aware retrieval**: Even though
  the document is in Qdrant (points exist), it cannot compete in search
  results because there is no `doc_ref` for `RERANKER_REF_EXACT_BOOST`,
  no citation display, no short_name. A query from the document's own
  content will rank properly-referenced laws above it. Diagnosis: if a
  document is in Qdrant but never appears in search, check `doc_ref` in
  the payload — if None, the document is indexed but unfindable by legal
  reference. Fix: assign a synthetic ref (e.g. date-based) at parse time
  for pre-modern instruments, or accept text-only matching as a limitation.
- **Layout-guided VLM OCR multiplies API calls**: Per-line VLM calls (one per detected region) multiply API calls by 5–15x per page. A 27-page PDF went from ~30 min to over an hour. Use the hybrid approach (full-page first, layout-guided only for problematic pages) to avoid the cost for pages that do not need it.
- **Before applying an approved fix, grep the test tree for the behaviour you are about to change — an approval given on a wrong diagnosis is not approval for the corrected fix.** The user's tests are the contract, and the uncommitted ones are the newest part of it: `tests/test_parser_structure_quality.py` asserts a الفصل-numbered code yields `chapters == [1,2,3,4]` with `articles == []`, so the obvious "revert the chapter-typing block" fix fails that suite the moment it lands. Read the tests and the uncommitted diff BEFORE editing; when they contradict the fix you proposed, stop, report the conflict with the corrected root cause, and re-confirm — do not apply the approved-but-wrong change, and do not silently substitute your own corrected version either.
- **Node type reflects the keyword, and that is deliberate — do not revert it to make a count look right.** الفصل → `chapter`, المادة → `article`, regardless of the document-level vote. Changing either side of that mapping, or the ingestion emit list that consumes it, needs explicit permission; report the trade-off instead of switching it silently (see the Terminology note and "Ingestion Chain").
- **Cross-reference guards need both sides**: `_CITATION_TAIL_RE` checks what comes AFTER the number (منه, من القانون), `_CITATION_POINTER_RE` checks pointer words (أعلاه, أعاله, بعده). But pre-keyword context (بناء على, وفق على, في, من) requires a separate lead-in regex.
- **Citation lead-in regex must match prepositions only, not any Arabic word**: A pattern like `[\u0600-\u06FF]+\s*$` is too broad — it rejects real headers that follow plain text mid-line (e.g. `نص سابق الفصل 12`). Match specific prepositions instead: `(?:(?:بناء|بحسب|وفق|طبق|عملا|عمال|بموجب|بمقتضى|استنادا|تمشيا)\s*)?(?:على|إلى|الى|لل|في|من|ل|ب|عن|حتى)\s*$`.
- **Citation lead-in with intervening text**: Real enacting clauses have `بناء على الدستور ولا سيما الفصل 102` — the preposition is separated from the keyword by intervening words. The regex must allow bounded intervening text after the preposition.
- **Variant spellings matter in pointer words**: `أعلاه` (above) has a variant `أعاله` (different hamza placement). Both must be in `_CITATION_POINTER_RE` or the guard fails for one spelling.
- **Compound headers stay articles**: `الفصل 1-35` is a compound provision, not a chapter. The `_AR_COMPOUND_HEADER_RE` check must come before the chapter interception.
- **A shared lookup table is a blast radius — measure the WHOLE corpus, not the documents you were aiming at.** Adding the bare `فريد`/`فريدة`/`وحيد` sentinels to `AR_ORDINAL_MAP` fixed the 9 single-provision instruments and turned the penal code's `(فصل وحيد)` into a phantom chapter, because the same words are used as structural notes. The parenthesis rule then had to be added to FOUR call sites. When a change touches a shared table (ordinals, stop markers, folder maps), the two-root corpus diff over EVERY document is the only thing that shows the second-order effect; the target documents were all fine before the fix was even finished.
- **A "provision lost" in a corpus diff is a QUESTION, not a verdict — and a number-set diff hides duplicates.** The diff reported three lost nodes; two had an UNCHANGED number set, which means a DUPLICATE was removed, and the third (`dahir 1.18.19`, chapter 392) was a table cell — the document's own chapters are 1–18, 61, 302, 396, 404, 407, 431, 446, 481, so 392 was never one of them. Always print the removed node's TITLE and the document's own numbering before calling a loss real.
- **A test that PINS the shapes a filter accepts is a contract on that filter, and narrowing the filter does not license breaking it.** `tests/test_phantom_provision_titles.py` enumerates the accepted and rejected title shapes (bare marker, compound label, short descriptive title, run-on clause, cross-reference, repeal formula, glued digit on a spelled-out ordinal). Narrowing the glue rule to the marker alone broke the ordinal case; the fix was to WIDEN the rule so the pinned case still fires, not to edit or delete the test. Read that file before narrowing any title/header heuristic, and keep the pinned case in the new rule.
- **A provider module's module-level import is invisible to a test that execs it standalone.** `tests/test_adala_shared_fixes.py` loads the provider `_shared.py` TAIL in a sandbox with a hand-written `_PRELUDE` of stubs, so a new module-level import in that module is missing at run time and surfaces as `NameError: name '…' is not defined` far from the change. When you add a module-level import to a provider module, declare the new dependency in the test's sandbox prelude (or move the call to a local import) — and note that the canonical modules are imported by the prelude already, so the pattern is to add one line there.
- **An audit's own example can be synthetic — verify it exists before building a fix around it.** The #15 ref-order finding was written with `4.72.1` and `5.11.2` as "a legal ref rewritten"; neither exists in the corpus (`4.72.1` has 0 occurrences, `5.11.2` only occurs inside a case number). Building the fix on the audit's example would have chased a shape that never occurs, while the REAL defect behind it (the `4` in the kind set, which reshaped money amounts) went unfixed. Re-derive every example from the corpus before you act on it.
- **A "duplicate" artifact is often a RESOLUTION bug, not a data bug.** The corpus had one source with two output JSONs, and the real defect was that `setdefault` over `rglob` picked whichever copy the filesystem reached first — so a reparse updated one and left the other stale forever. Fix the RESOLUTION to be deterministic (here: the deeper path wins, because the output tree mirrors the raw tree) and REPORT the shadow; the data itself is a separate operation.
- **Arabic regex binding: `ال?` is NOT optional "ال".** The `?` quantifier binds only to the immediately preceding character, so `ال?` means "ا" + optional "ل" — it matches "ا" or "ال", NOT optional "ال". To make the definite article optional, use `(?:ال)?`. Measured: `من\s+(?:ال)?قانون` matches both "من قانون" and "من القانون"; `من\s+ال?قانون` matches neither (requires "ا" before the instrument noun). This silently produces zero matches with no error — test both prefixed and unprefixed forms.
- **Ordering detection must use `_article_header_info`, not the raw header regex.** `_AR_ARTICLE_HEADER_RE` matches any "المادة N" line including preamble cross-references ("المادة 16 المكررة من قانون المالية"), producing false-positive ordering issues. `_article_header_info` runs the full citation-tail + pointer guards and correctly rejects cross-references. Use the guarded function for any semantic decision (ordering, dedup, counting), the raw regex only for surface matching.
- **count_articles counts chapters too**: After the fix, `count_articles` returns the total of both `article` AND `chapter` nodes. If you need only articles, filter by type.
- **الباب is title, not book**: The parser maps الباب to `type: "title"`, not `type: "book"`. Only كتاب maps to `book`.
- **Part nesting**: الجزء nests under الباب (title), not at root. The part dispatch must check `current["title"]` and `current["book"]`.
- **Import chain**: `count_chapters` is defined in `amendment.py`, imported in `core.py`, re-exported in `__init__.py`. The `_shared.py` files have their own copies — update both.
- **Post-processing filters must be targeted, not aggressive**: When removing phantom nodes, only remove nodes with the specific defect signature (e.g. keyword+digits with no space). An aggressive filter that removes ALL empty nodes breaks legitimate empty containers (repealed chapters, inserted provisions). Always run the full test suite after adding a filter — a filter that removes 3 legitimate nodes will show up as 3 test failures.
- **When investigating phantom titles, check the correct text source**: The structure may be built from vision OCR text (`cache_vision/`), not the extraction cache (`cache/`). Searching the wrong cache produces false positives — titles that appear missing are actually present in the other text source. Always check `structure_source` in the JSON to know which cache to search.
- **NEVER fix without explicit permission — always analyze and report first.** When a bug is found, do NOT start fixing it. Analyze the problem, report findings, and wait for a go-ahead. This applies to all parser changes.
- **Stop re-reading unchanged files.** If `read_file` returns the same content multiple times, stop calling it — the content hasn't changed. Use the content from the first read and proceed with the task. Re-reading the same file in a loop wastes time and frustrates the user.
- **Widening a counter's semantics breaks every consumer that filters by the OLD node type — widen them in the same change.** When `count_articles` began counting `chapter` as well as `article`, test helpers that selected nodes with `node.get("type") == "article"` (in `test_penal_code_structure.py`, `test_cid_fonts_text_layer_probe.py`, `test_parser_structure_quality.py`) silently returned empty lists, so a correct parser change presented as a cascade of assertion failures and read as a regression. Before accepting that read: grep the test tree AND the provider `_shared.py` copies for the old predicate (`grep -rn '"article"' tests/` and the per-provider `_shared.py`), then widen each to the new pair. A helper named `_articles` that also matches chapters is a naming trap — it now over-counts for any caller that genuinely wants articles only, so say which is which in the name or the docstring.
- **A test's own node-type filter is not the parser's contract.** When a test fails after a node-type change, first ask whether the test encoded the OLD (wrong) semantics — الفصل nodes being `article` was the defect, so tests asserting `type == "article"` for فصل were asserting the bug. Update the test to the corrected type and add a guard case that fails under the old behaviour, rather than reverting the parser to make the old assertion pass.

**The same rule applies to a COUNT expectation and to a deliberate normalisation contract.** A guard test that asserted a provision count included the phantoms (39 = 8 real + 31 table rows): the count encoded the bug, so the correct expectation is the real count and the guard must additionally assert the phantom class is absent. And when the CODE's contract is deliberate and documented — alef normalisation preserves the hamza on أ/إ because it carries legal meaning (تأسيس must not become تاسيس) while folding آ/ٱ onto the bare alef — the stale test is the defect: update the assertions to the new contract, keep asserting the part that still applies, and say in the docstring which contract is in force. Do not "fix" deliberate behaviour to satisfy a test written against the old one.
- **`num_articles_detected: 0` with `structure_source: "vision"` is a node-typing or ingestion problem, not an OCR-cache problem.** The vision cache is present and its headers are detectable — check node types and the flatten emit list before touching caches or re-transcribing. Blaming the OCR cache sends the session down a re-parse that cannot change the result.
- **A non-empty `flat_articles` suppresses every downstream fallback.** The Arabic text-based article extractor and the chunk engine's regex/full-text path both run only when `flat_articles` is empty, so a single surviving preamble item hides the loss of every provision. Never accept "it produced a chunk" as evidence the structure survived.
- **Never compare revisions by stashing or checking out in the user's repo.** Materialise the committed tree in the session scratch dir (`git archive HEAD | tar -x -C <scratch>`) and run the same probe against both roots — see "Comparing a revision against the working tree" for the corpus-path argument and the REAL/ARTEFACT classifier. Identical evidence, zero risk to the working tree, caches and JSON outputs. Archive the revision the baseline is MEANT to be: `HEAD` is the current commit, so a pre-fix baseline needs `HEAD~1` (or the wave's base SHA) — otherwise the "before" run exercises your own fix.
- **Never edit a source file while the test suite is running.** `tests/test_normalizer_no_lemmatize.py::TestChunkStageSegmentationContract` asserts on `inspect.getsource(ChunkStage.chunk_and_embed)`. Editing that file mid-run left a stale line table, so `getsource` returned `chunk_from_structured`'s body and the test failed with a nonsense message ("`\"text_segmented\": None` not in <chunk_from_structured source>"). It passed on a re-run with the edits frozen. Freeze the edits, re-run, and only then diff failure sets — and re-check any source-text assertion that fails before believing it.
- **`num_articles_detected` now counts الفصل chapter containers too.** `count_articles` totals `article` + `chapter`, so a المادة-numbered document that contains الفصل chapter headings reports a slightly higher number than its المادة count (measured: dahir 1.02.172 went 41 → 44 = 41 المادة + 3 الفصل containers). That is the intended semantic (both are operative units of law); do not read it as double-counting, and say so when reporting counts that changed for documents nobody complained about.
- **A full-suite failure set means nothing without a baseline from the same data and config.** Diff `pytest -q -m "not requires_server and not requires_qdrant and not requires_llm"` against a `git archive HEAD` copy, then classify every failure that exists only in the working tree: the local `.env` (which is gitignored, e.g. `OCR_PARSER_USE_PADDLE_VL=true`, `INGEST_PATH_ISM` with a trailing slash), data that the archive does not carry (SGG JSONs → a fixture that skips at HEAD and asserts a hardcoded count in the working tree), and new untracked test files can all produce "working-tree-only" failures that have nothing to do with the change under test.
- **A standalone probe is not the pipeline.** Re-running `build_tree` over the cache text reproduces the on-disk JSON exactly for the documents under investigation, but the pipeline filters pages and SELECTS between text layers, so counts legitimately differ elsewhere — and a probe that rebuilds from one layer alone reports provisions as "lost" that the pipeline never dropped. Call the provider's selection function inside the probe. Report probe numbers as probe numbers and JSON numbers as JSON numbers; never quote one as the other.
- **Triage a full-suite run with `scripts/diff_pytest_logs.py`, never by eye.** It splits each `pytest -q` log into per-test failure blocks, buckets them by error signature, and prints the failures that exist only in one log — the whole question when the suite is already red. Two traps it exists to avoid: the failures banner is `==== FAILURES ====`, so a `startswith("=== FAILURES")` check finds nothing and the parse silently reports zero failures; and the section headers (`___ Class.test ___`) are a different name form from the summary's `FAILED path::Class::test` ids, so both logs must be parsed the same way or every failure looks one-sided. Pointing the same script at a `git archive HEAD` copy's log is the cheap way to show a failure set is pre-existing.
- **Know which text source you are reading and how much to trust it.** Arabic page text comes from a cascade — fitz native → (garbled / reversed / CMap-corrupt?) → local PaddleOCR-VL → PP-OCRv5 — while for ADALA/ISM/SGG the *primary* transcriber is the remote vision engine (`VISION_ENGINE_ENABLED`, `OCR_ENGINE=vision`, `VISION_OCR_MODEL`); the local VL is the fallback for a garbled native layer. The local VL version is pinned in `fetching/pipeline_base/ocr_models.py` (`pipeline_version="v1.6"`, `~/.paddlex/official_models/PaddleOCR-VL-1.6`); no other version was ever wired, so "use 1.5 instead" is a one-line change plus a ~2 GB checkpoint download, not a config flip — and the vendor's claimed gains are table- and Chinese-centric with no Arabic evaluation, so an Arabic 1.5-vs-1.6 claim needs an A/B on real pages before it drives a config change. The VL pass is accepted on a weak gate (`len(p.split()) > 5`), so a garbage transcription can win silently: validate digits and article headers before trusting a `vl`/`vision` structure_source, and never read `[QUALITY] errors=0` as evidence, since `is_arabic_cmap_corrupt()` is letter-only.
