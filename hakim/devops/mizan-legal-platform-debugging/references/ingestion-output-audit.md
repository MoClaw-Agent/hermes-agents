# Auditing a parsed legal document against ground truth

Use when a user supplies a human count (chapters/articles) for a document and
you must explain why the parser disagrees — or confirm it agrees.

## Step 0: establish provenance BEFORE touching parser logic

A parsed JSON can disagree with the cache that supposedly produced it. Two OCR
passes exist and, historically, only one of them persisted:

```
extract_pages()        → extraction cache, written
extract_vision_pages() → vision rescue, preferred for structure
```

The vision rescue is the text that often builds `structure` for CMap-corrupt
legal PDFs. **Check the output record first — it names which text won:**

```python
d = json.loads(path.read_text(encoding="utf-8"))
d.get("structure_source")        # "vision" | "extraction"
d.get("structure_text_cache")    # path, when vision won
```

`structure_source` and `structure_text_cache` are emitted by ISM, and now by
ADALA as well. Before they existed for a provider, its vision text was
in-memory only: `full_text_in_cache: true` could point at text that was **not**
used, and re-parsing re-OCR'd every page. If `structure_source` is absent from a
record, treat the vision text as unavailable and say so rather than auditing the
extraction cache as if it were the source.

When `structure_source` names a cache, audit **that file**. The extraction
cache holds native/legacy page text, which for a corrupt PDF is not what the
tree was parsed from.

**Checks, in order:**

1. Compare mtimes. A cache older than the JSON is stale — it is not the
   source. `stat -c '%y  %n' <json> <cache files>`
2. Probe for a distinctive string from the JSON's node text inside the cache.
   Absent means different provenance, not a regex bug.
3. Confirm the cache belongs to this PDF: cache dirs are provider-wide and keys
   are `<stem>_<hash>`, so verify the hash suffix and page count rather than
   trusting the stem.

Only after this: is the text wrong, or is the parser wrong? Attacking
`build_tree` while the source text is unavailable wastes the whole session.

## Step 1: count DISTINCT article numbers, not nodes

`len(articles)` is not the article count. Report both:

```python
nums = [int(m.group(1)) for m in re.finditer(AR, text) if m.group(1).isdigit()]
len(nums)                      # nodes / occurrences
len(set(nums))                 # distinct numbers — the comparable figure
missing = sorted(set(range(1, GROUND+1)) - set(nums))
```

Reporting node count as the article count is the single easiest way to give
the user a confident wrong number. Duplicates and false positives both inflate
it.

Arabic-Indic digits (`٠١٢٣`) appear in OCR output; normalise before comparing:

```python
s.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
```

Use a permissive header class: `الماد[ةهة]` — OCR varies the final letter, and
`المادَة` (with tatweel) is common enough to account for real gaps.

## Step 2: classify false positives before fixing anything

**Citation fragments.** `المادة 94 من هذا القانون التنظيمي` is a *reference
inside* a repeal clause, not an article. These collide with the real article
of the same number and are the usual cause of apparent duplicates. The safe
test is self-verifying: the node's text starts `المادة N من ...` **and N equals
the node's own declared number**. On a 76-page law that matched 24 nodes with
zero false positives (no case where a real article citing another matched).

**Do not delete citation-fragment nodes — split them.** Eleven of the 24 ran
past 400 chars and carried real article bodies; one contained the entire text
of article 21. Dropping the node destroys content. Strip the citation prefix
and re-scan the remainder, so the embedded header becomes its own node.

**"Two or more headers in a node" is usually not a defect.** Before believing
it, read the context. On the 76-page law all 24 such nodes were ordinary
in-body cross-references — `وِفْقاً لأحكام المادة 74 من القانون التنظيمي رقم
59.11`, `البند 8 من المادة 22 أعلاه`, `المشار إليه في المادة 42 أعلاه`. A
regex count read as a structural fault is not evidence of one; this was
asserted, then retracted, then never needed.

When headers genuinely are missed, the cause is almost always a **spelling
variant the header matcher does not accept**, not a splitter failure. Check
what `is_article_line` returns for the exact string before touching `build_tree`:

```
'المادة 21'  -> (True, 21)
'المادَه 21' -> (False, None)   ← U+064E FATHA inside the keyword
'المـادة 7'  -> (False, None)   ← U+0640 TATWEEL
```

That one spelling accounted for articles 21 and 23 being invisible in a
256-article law. Fix it in `_header_candidates` as an **additional candidate
variant** — that function already absorbs lam-alef ligature and dropped-hamza
corruption, so marks belong there rather than in a new mechanism. Strip them
with `str.translate(table)` mapping each mark to `None`; replacing with a space
splits the word (`المـادة` → `الم ادة`) and still fails. Cover U+0640,
U+064B–U+065F, U+0670, U+06D6–U+06ED. Confirm the change makes marks in *body*
text and mid-word still fail to match, and that a clean line yields an
identical candidate set.

## Step 3: legitimate duplicates are not bugs

Multi-instrument PDFs bundle decrees that each restart at المادة الأولى. Three
nodes numbered "1" can be correct. Do not write a dedup rule that collapses
them. Article numbers legitimately repeat across chapters — dedup scope must
be (part, book, chapter, article), never document-global.

## Reporting

State ground truth, nodes, distinct numbers, and missing — then say which
stage the loss is in, and what you cannot tell without the source text. Do
not propose a parser fix while the artefact that produced the output cannot
be reproduced.