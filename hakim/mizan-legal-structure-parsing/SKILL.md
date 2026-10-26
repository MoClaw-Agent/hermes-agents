---
name: mizan-legal-structure-parsing
description: "Debug Mizan legal structure parsing and phantom articles."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [mizan, parser, structure, arabic, legal-hierarchy]
    related_skills: [mizan-legal-platform-debugging, systematic-debugging]
---

# Mizan Legal Structure Parsing

## When to Use

- Phantom articles appear in parsed structure (cross-references mistaken for headers)
- Structure node types don't reflect the Arabic keyword used (الفصل vs المادة)
- JSON output has `structure: null` but `num_articles_detected > 0`
- الفرع/الفصل/المادة keywords aren't producing the right hierarchy nodes

## Moroccan Legal Hierarchy Keywords

Arabic keywords map to distinct node types. Conflating them produces semantically wrong trees:

| Arabic | Transliteration | Node type | Scope |
|--------|---------------|-----------|-------|
| القسم | qism | `section` | **Largest** division; sits above الباب. 69 nodes in the corpus |
| الباب / كتاب | bab / kitab | `title` (rarely `book`) | Subdivision of القسم; 246 nodes |
| الجزء | juz' | `part` | Rarely used (19 nodes) — placed before or after القسم depending on the code |
| الفرع | far' | `branch` | Subdivision of باب/جزء; 64 nodes |
| المبحث | mabhath | (unassigned) | Subsection of فرع. **Not observed in this corpus** — 0 occurrences in 132 ADALA ar docs |
| الفصل | fasl | `chapter` | Operative unit in general/foundational codes (Penal Code, Constitution, D.O.C.); 1291 nodes |
| المادة | madah | `article` | Operative unit in modern/specific codes (Labour, Family, territorial-collectivity) |

**المادة and الفصل are the SAME level, not sequential ones.** They are two names for the smallest
unit of a legal text, chosen per code: الفصل in general/foundational codifications, المادة in modern
and specific ones. The corpus uses الفصل as a header exclusively (المادة never appears as a title
here). Both are operative provisions, so anything counting provisions must filter
`type in ("article", "chapter")` — see rule 6. Never model المادة as a child of الفصل.

Order: القسم > الباب > الجزء > الفرع > المبحث > الفصل/المادة

## Always-On Rules

1. **الفصل = chapter, المادة = article.** The parser's `build_tree` must emit node types matching the keyword, not the document-level unit vote.
2. **Prepositional citation lead-ins signal cross-references.** Compound prepositions (`بناء على`, `بحسب على`, `وفق على`, `طبق على`, `عملا على`, `بموجب`, `بمقتضى`, `استنادا إلى`) AND simple prepositions (`في`, `من`, `على`, `إلى`, `عن`) before a keyword → cross-reference, never a header. The trailing preposition is REQUIRED in compound forms (bare `بناء` = "the construction", a noun). Simple prepositions like `في` must also be recognized — `في المادة 6 أعاله` is a cross-reference, not a header. **Bounded intervening text** (up to 15 words) between the preposition and the keyword is allowed — `بناء على الدستور ولا سيما الفصل 102` is a cross-reference, not a header. The regex pattern is `(?:(?:بناء|بحسب|...)\s*(?:على|إلى|...)\s+)?(?:على|إلى|...)\s+(?:\S+\s+){0,15}?$`.
3. **Compound headers stay articles.** `الفصل 1-35` carries a compound label as full identity; it must NOT be intercepted as a chapter.
4. **Chapter dedup scope excludes the chapter itself.** Chapters nest under book/part, not under other chapters. Dedup keys use (part, book) scope — including current chapter in the scope breaks dedup because the scope changes after each chapter is created.
5. **JSON serialization fallback nulls the structure.** When `json.dumps(doc)` fails, the fallback sets `structure: null` while keeping `num_articles_detected > 0` — a contradictory state. The parser state records success anyway, so later runs skip. Re-parse with `force=True` to regenerate.
6. **`count_articles` counts article AND chapter nodes.** الفصل chapters are operative units of law, so the counter includes both; `count_chapters` counts chapters alone, and `num_chapters_detected` is emitted beside `num_articles_detected`. Any helper or test filtering `type == "article"` alone under-counts a فصل-numbered document — filter `in ("article", "chapter")`. When a node type changes, search the test tree for the affected filter before assuming the parser broke: the failure is usually a helper still encoding the old shape, not the new code.
7. **Never state an effect before reading the patched lines back.** Describe what a change does only from the diff on disk, not from what the edit was intended to do. A fallback written `new or old` is strictly additive and provably cannot regress — so a warning that a field will "become mostly None" is false when that field falls back to its previous value. When the user pushes back ("are you sure X won't hurt Y?"), the answer is to grep for the field's real consumers and re-read the diff, not to defend the original claim. Prefer a bare correction over a padded one: say the earlier claim was wrong, state what the code actually does, then move on.
8. **Grep for a field's consumers before claiming a quality impact.** A payload field only matters if something reads it. For this corpus the hierarchy fields reach Qdrant and stop: `hierarchy_str`/`hierarchy_path` have no reader outside `ingestion/`, while `chapter` is consumed only by the citation string in `reasoning/engine/helpers.py` and the provision API. Say "this fixes citations and makes JSON and chunks agree, but does not move retrieval yet" rather than implying a win.
9. **Repeal verbs must be in the amendment detection pattern.** `_AMEND_KEYWORDS_AR` must include `يلغى`, `يلغي`, `يعوض`, `يعوّض` (repeal/replace verbs). Without these, repealing dahirs are not detected as amendment-style, and the filename priority returns the OLD ref (the repealed dahir's ref) instead of the own ref. Also: `is_amendment_style` detection must scan `pages[:5]` for repeal verbs, not just filename/title — repeal formulas often appear only in the body text.
10. **Phantom empty chapter/article nodes need a post-processing filter.** When OCR splits a chapter header from its body, a node with a keyword+digits title (no space) but no content is created. Add `_drop_empty_chapter_article_nodes()` after the tree is built. The filter must be targeted: only remove nodes with the OCR glue signature (no space), not all empty nodes — legitimate empty containers exist. **Children of phantom nodes are promoted to the parent level** — a phantom node with children is removed and its children are moved up, not deleted.
11. **Provider-specific metadata gaps.** When a field like `num_chapters_detected` is missing from one provider's output but present in others, check whether that provider's pipeline actually sets it. The ADALA pipeline never imported `count_chapters` or wrote `num_chapters_detected` to its output dict, while parser_base and ISM did. Grep all provider pipelines for the field name to find which ones are missing it.
12. **Never fix without explicit permission — always analyze and report first.** When a bug is found, do NOT start fixing it. Analyze the problem, report findings, and wait for a go-ahead. This applies to all parser changes. **The exception is an explicit fix mandate**: when the user asks for an audit-and-fix pass, or says to keep fixing until everything is done, that IS the permission — analyse and report as you go, but do not stop at the findings and wait.
13. **Stop re-reading unchanged files.** If `read_file` returns the same content multiple times, stop calling it — the content hasn't changed. Use the content from the first read and proceed with the task. Re-reading the same file in a loop wastes time and frustrates the user.
14. **When investigating phantom titles, check the correct text source.** The structure may be built from vision OCR text (`cache_vision/`), not the extraction cache (`cache/`). Searching the wrong cache produces false positives — titles that appear missing are actually present in the other text source. Always check `structure_source` in the JSON to know which cache to search.
15. **Self-references and enacting clauses need a separate guard.** `المشار إليهم في ظهيرنا الشريف هذا`, `أصدرنا أمرنا الشريف بما يلي`, `طبقا لظهيرنا الشريف هذه` — these phrases govern a keyword as a cross-reference to the document itself, never as a new header. Add `_SELF_REF_RE` anchored to the end of the preceding text (within 5 words of the keyword). Do NOT match generic references like `طبقا للقانون` — only references to "our" instrument.
16. **Title absorption: truncate long titles.** A real chapter/article title is short (e.g., `الفصل الأول: أحكام عامة`). A title longer than 100 chars is body text that was incorrectly absorbed into the title by OCR garbling. Add a title-length guard in `_split_container_header` that truncates at the first sentence boundary or punctuation (colon, period, comma, semicolon).
17. **Verb lead-ins in the citation guard.** `المنصوص عليها في` (stipulated in), `يعتبر` (considered), `تطبق` (applied), `تمنح` (grant) are verbs that introduce cross-references, not prepositions. The `_CITATION_LEAD_RE` must include them with an **optional** preposition group — verb lead-ins match without a following preposition, unlike compound prepositions (`بناء على`) which require one. Making the preposition group optional is safe because the lead-in word list is specific.
18. **Vision cache staleness blocks investigation.** When the vision cache is updated after the JSON is created, the phantom title cannot be found in the cache — the JSON was parsed from an older OCR pass. Signs: `(title not found in vision cache)` for every phantom. The fix is to delete the vision cache file and re-OCR, not to keep searching. Do NOT conclude the regex is broken when the cache is stale — test the regex directly against known text patterns instead.
19. **LLM metadata prompt: own instrument type determines doc_type.** When a dahir's title mentions a law (e.g., `القانون رقم 41.10`), the LLM classifies it as `loi` instead of `dahir`. Add a rule to the LLM metadata extraction prompt: the document's OWN instrument type (from its header/prefix: ظهير شريف → dahir, مرسوم → decret) determines `doc_type`, not the instrument it references. Mirror the existing ref rule: "The document's OWN ref is the one in its title/header, NOT cross-references."
20. **Repeating dahirs: filename contains the OLD ref.** When a dahir repeals and replaces another dahir, the crawler may name the file after the OLD ref (the repealed one). `extract_ref()` uses filename as highest priority, so it returns the old ref. Fix: `_AMEND_KEYWORDS_AR` must include repeal verbs (`يلغى`, `يعوض`), and `is_amendment_style` detection must scan `pages[:5]` for these verbs (they often appear only in body text, not title/filename). Without this, repealing dahirs get the wrong ref and wrong filename.
21. **Footnote detection is gated on a horizontal rule — documents with no rule get zero capture.** `_end_of_page_footnote_block()` requires `_is_hr_line()` as a hard precondition; when a document has no separator rules the function returns `[]` for every page and the whole footnote block flows into `build_tree` as ordinary text. Many ADALA/ISM Arabic PDFs print amendment-note blocks with no rule: a marker line (`كما تم تعديله بـ:`) followed by numbered citation lines (`1- القانون رقم ...`). Three effects: note text contaminates article bodies; `_split_runon_article_headers` splits long note lines at `الفصل N` citations creating phantom chapters whose numbers come from the notes; the `footnotes` metadata field stays empty. Before treating numbered-citation lines as operative content, check for an uncaptured footnote block.
22. **Footnote contamination mimics cross-reference phantoms.** A phantom chapter whose content is an amendment note (`القانون رقم ... الصادر بتنفيذ ظهير شريف رقم ...`) is indistinguishable from a cross-reference phantom by content alone. The distinguishing signal is a run of numbered citation lines (`^\d{1,4}\s*[-–.]`) introduced by an amendment marker — a single isolated citation line is a cross-reference, a run of them is an uncaptured footnote block.
23. **Arabic tatweel (U+0640) breaks naive marker regexes.** The marker `بـ:` is U+0628 U+0640 U+03A; `[ب]?` matches the bare letter then expects the colon and fails. When a marker regex matches 0 of N candidate lines, print the codepoints of a real line before concluding the marker is absent.
24. **The safe footnote gate is per-line, and fragment absorption is the regression risk.** The gate that works: (a) marker — anchored full-line `^كما\s+تم\s+تعديله\s*(?:بـ?)?\s*[:：]?\s*$`, then drop to the end of the page, stopping before a real header that cites no instrument; (b) tail — a trailing run of >= 2 consecutive numbered lines that **each** cite an instrument. The version that regressed: absorbing OCR fragments into the run plus a `shredded`-page exemption that suspended the prose stop. It swallowed 28 provisions from one fixture (`test_no_regression_in_provision_count`) and broke `test_parser_structure_quality::test_preamble_and_container_content_preserved`, because a real chapter header is often one short line (`الفصل 482`) and an unanchored marker match fires on inline prose (`كما تم تغيير وتتميم الفصل 4-218 أعلاه، بمقتضى …`). Rule of thumb: prefer a rule whose failure mode is *leaving* note text over one whose failure mode is *dropping* provisions.
25. **Diagnose against `page_lines`, never the cache.** `page_lines` after `_reflow_runon_headers` + `_split_runon_article_headers` is a different shape from the vision cache: a clean cache line arrives shredded into bare fragments, one of which is just `الفصل446` and is then read as a header. Dump `page_lines` from inside `build_tree` when chasing a phantom.
26. **A vision transcription merges a superscript footnote marker into the heading it follows.** `المادة 1` + a marker `3` is transcribed as `المادة 13`, so the provision's NUMBER and its CONTENT disagree — the chunk labelled `Art.1` begins with `المادة 13`. The PDF's own geometry is the proof: the marker is a separate small-type span beside the heading (`size=10.6` next to `size=16`), and the page model reads the heading correctly as `المادة1`. The vision path has no geometry, so the repair must be made where the number is already known: `structure.py` already carries a first-article footnote-digit repair (a first article numbered 11..19 whose body is the definitions clause is really article 1), and the repair must ALSO rewrite the heading in the stored content — the French path already normalizes its own glued header for exactly this reason. Guard the rewrite twice: the keyword must be the article keyword, and the line's own number must be exactly the corrupted one. A repair that fixes only the number leaves the contradiction visible to the reader.
27. **The two text layers disagree about the same document, and neither is automatically right.** The PDF's own text layer can be a bad OCR (`الإقامات` printed as `اإلقامات`) while the vision transcription is clean — so the page model may be rejected as corrupt while the vision text is the better Arabic. The reverse holds for geometry: only the PDF's own layer knows that a marker is a superscript. Decide per defect which layer is the authority, and prove it: compare the layer's output with the printed spans before rewriting legal text.
28. **A bilingual document's title field is usually the filing language, not the document's language.** When a source dump carries both `title_ar` and `title_fr` (or a top-level `title`), the top-level title is typically the filing language. For an Arabic document, prefer `title_ar` for display — but extract refs from the French title, which carries the instrument's own number. The Arabic title often names only the law the instrument implements ("مرسوم ... القانون رقم 37.99"), so extracting from it files the decree under the law's number. Measure: compare ref extraction from each title against the site's number field on a sample before choosing. Anchor title patterns at the start of the title — a title names its own instrument first and cites others afterwards.

## Debugging Procedure

**Structure is empty / zero provisions on a document that has text:**
1. Do NOT assume the marker grammar is wrong. Check how many **pages** were
   passed to `build_tree`. Given a whole document as a single element, the
   per-page drop-gates fire with no page boundary to stop them — the
   amendment-note gate walks to the end of the stream and swallows the
   document (measured: 337 of 346 lines dropped, a 41-article decree reduced to
   one `preamble` and zero provisions, while the same text parsed correctly
   once segmented). Confirm by building the tree twice, once with the text as
   one element and once with it split, and comparing the provision counts.
2. If segmentation is the cause, fix it in the **producer** (split at the
   source's printed page numbers, cap a segment) rather than widening the
   shared gate. Mechanism and code: the `juritheque-scraper` skill,
   `references/parsing-the-flat-text-layer.md`.

**Phantom article (node exists that shouldn't):**
1. Find the cache file: `data/corpus/<provider>/cache[_vision]/<stem>_<hash12>[_vision].json`
2. Locate the offending text: search pages for the number/keyword
3. Check what precedes the keyword — prepositional lead-in? mid-word? citation tail?
4. Reproduce with `build_tree([page], document_language="ar")` on the cached pages
5. Fix the guard in `_split_runon_article_headers` or `is_article_line`, add failing test first

**Structure is null but num_articles_detected > 0:**
1. The doc serialization failed; fallback stripped the structure
2. Re-run: `process(pdf_path, force=True, language_hint="ar")`
3. If it recurs, wrap the `json.dumps(doc)` call to log the offending field before the fallback fires

**Node type wrong (article vs chapter):**
1. Check `doc_uses_madah` vote — `fasl > madah` and article-like numbering → chapters
2. Verify compound header guard: `_AR_COMPOUND_HEADER_RE` must be checked BEFORE chapter interception
3. Run `build_tree` on cached pages and inspect node types directly

**Footnote block leaking into structure:**
1. Count horizontal rules per page: `any(S._is_hr_line(l.strip()) for l in page.split("\n"))` — if 0, `_end_of_page_footnote_block` cannot fire.
2. Find note lines: `^\s*\d{1,4}\s*[-–.]\s*(?:تم|الجريدة|القانون|المادة|مرسوم)` and measure each one's distance from the last non-empty line of its page.
3. Dump the last 6 non-empty lines of 3 note-bearing pages to see the marker + numbered structure.
4. Check the marker's codepoints for tatweel before writing the regex.
5. Quantify: `len(doc["footnotes"])` vs note-line count; grep the structure for the marker phrase.
6. Simulate the candidate drop rule on all pages and audit every dropped line before implementing.

## Tests

- `tests/test_runon_marked_header.py` — run-on splitting, citation lead-in guard
- `tests/test_branch_and_chapter_metadata.py` — الفرع hierarchy, count_chapters, pipeline imports
- `tests/test_parser_structure_quality.py` — structure quality, chapter/article typing
- `tests/test_cid_fonts_text_layer_probe.py` — CID font text layer, cross-ref dedup
- `tests/test_penal_code_structure.py` — compound headers, page furniture

## References

- `references/footnote-detection.md` — footnote-block layout, marker inventory, corpus-wide damage, proposed fix direction, diagnosis scripts

## Downstream Consumer

The structure this skill produces is consumed by the ingestion pre-converters.
Before changing node types, hierarchy levels, or the fields written on a node,
load the `mizan-legal-platform-debugging` skill and read its
`references/parser-ingestion-contract.md`. It documents the parser→ingestion
contract, including the `position{}` block that carries each article's
hierarchy and the gate order that can discard a populated structure entirely.
