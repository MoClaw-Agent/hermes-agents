# Footnote Detection in ADALA/ISM Arabic PDFs

## The defect

`fetching/pipeline_base/structure.py` → `_end_of_page_footnote_block()` is gated on
`_is_hr_line()` as a **hard precondition** (it walks backward looking for a horizontal
rule and returns `[]` if none is found). Documents with zero separator rules get
**zero** footnote capture. The footnote block then flows into `build_tree` as
ordinary text.

## Layout pattern (measured on a 207-page penal code)

The block is real and well-formed, printed at the bottom of pages with **no**
separator rule:

```
'ظهر شريف رقم 1.59.413 صادر في 28 جمادى الثانية 1382 ...'
'كما تم تعديله بـ:'          ← marker
'1- القانون رقم 43.22 ...'   ← numbered amendment notes
'2- القانون رقم 12.18 ...'
```

- Notes continue across pages **without** the marker re-appearing.
- 155 of 163 note lines sit within 5 lines of the page end; 76 are the last line.
- The block is a genuine bottom-of-page trailing block — the gate is simply wrong.

## Marker inventory

Scanned all 133 vision caches. **One family only** (26 docs):

| variant | count |
|---|---|
| `كما تم تعديله بـ:` | 12 |
| `كما تم تعديله ب:` | 12 |
| `كما تم تعديله:` | 2 |

Tatweel matters: `بـ` = U+0628 U+0640 U+03A. A regex like `[ب]?` fails.
Use a prefix match: `^كما\s+تم\s+(?:تعديله?|تغييره?|تغييرته?|تتميمه?)`.

## Three downstream effects

1. **`footnotes` field empty** — `merge_footnotes(None, docling_footnotes_for(pdf))`;
   Docling finds no footnote regions (notes are inline, no superscript anchors).
2. **Content contamination** — note text becomes article/chapter bodies.
3. **Phantom chapters** — `_split_runon_article_headers` splits long note lines at
   `الفصل N` citations: `الفصل 446` ← note 26, `الفصل 219` ← note 29,
   `الفصل 455` ← note 33. These numbers are footnote citations, not provisions.

## Corpus-wide damage (all 130 ADALA ar docs)

| signal | count | rate |
|---|---|---|
| `footnotes == 0` | 57 | 43.8% |
| marker leaked inside `structure` | 20 | 15.4% |
| note-like chapter nodes in tree | 11 | 8.5% |

## Proposed fix direction (UNVERIFIED — simulation only)

Add a second detector alongside the HR call in `build_tree()` with two gates:

- **Marker gate** — `^كما\s+تم\s+(?:تعديله?|تغييره?|تغييرته?|تتميمه?)` → drop
  the marker line plus every following consecutive `^\s*\d{1,4}\s*[-–.]` line.
- **Trailing-run gate** — ≥2 trailing numbered lines where at least one carries a
  citation marker (`القانون رقم` / `الظهير الشريف رقم` / `مرسوم ملكي رقم` /
  `الجريدة الرسمية عدد`) → drop the run. Needed for continuation pages.

Simulation on the 207-page doc: **123 lines dropped, 0 suspicious** (every dropped
line matched marker/numbered/citation). Page 2 keeps only the title line.

Safety: the marker phrase is unambiguous prose; the trailing gate needs ≥2 numbered
lines AND a citation marker, so a numbered operative list (`1. يعاقب ...`) is
untouched and bare-digit article headers (`25`) do not match.

Residual risk: a page ending in ≥2 numbered operative lines that cite an instrument
could be over-dropped. Strengthen by requiring the **topmost** line of the run to
carry the citation marker rather than any line.

The dropped block is already routed to `footnote_sink`, so `footnotes` would get
populated — turning a dead metadata field into a working one.

## Diagnosis scripts

Scratch probes used (not committed):
- `diag_fn_layout.py` — page-tail dump, distance-from-end histogram, separator count
- `diag_fn_gate.py` — confirms 0 rules, boundary structure, phantom provenance
- `enum_markers.py` — marker variant inventory across all vision caches
- `sim_fn_rule.py` — simulates the candidate drop rule and audits every drop
- `audit_fn_all.py` — corpus-wide `footnotes`/marker/note-node counts
