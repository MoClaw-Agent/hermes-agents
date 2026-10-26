# Audit wave template

The shape of one delivered wave. Copy the skeleton, fill it with this
wave's own numbers, and delete what does not apply.

## The report section

```markdown
## N. Fix wave W — <the root cause in one line>

<One paragraph: the defect, the mechanism, and the number it moved.>

### N.1 <the first sub-defect>
<What was wrong, the code shape, the measured impact.>

### N.2 <the second sub-defect>
...

### N.M What is still open in this area
<The defects you did NOT fix in this wave, with their reproduction.>

### N.K Rejected: <the hypothesis>
<Why it is not a defect. Keep rejected hypotheses: a later session must
not re-litigate them.>
```

Rules the report must satisfy:
- Every number is measured on the real corpus, before and after.
- A claim about code is a claim about the code as it is now — if a
  previous section in the same document says otherwise, correct it in
  place and say that you are correcting it.
- The executive table near the top states, per finding, what is FIXED, what
  is MEASURED-BUT-OPEN, and what remains OPEN. It is written last.
- Findings the audits reported but the waves did not close stay in the
  findings table, each marked with the section that closes it.

## The release script

```python
import pathlib, re

ROOT = pathlib.Path("/home/mohammed/Mizan")
SECTION = """..."""          # the report section for this wave

# ── DERIVE the old version, never remember it ────────────────────────────
# A remembered OLD is stale the moment the previous wave shipped, and the
# assert below then fires half-way through the script.  Read it instead.
pyproject = ROOT / "pyproject.toml"
t = pyproject.read_text(encoding="utf-8")
_m = re.search(r'^version = "([^"]+)"$', t, re.M)
assert _m, "no version in pyproject.toml"
OLD = _m.group(1)
_parts = OLD.split(".")
NEW = "%s.%s.%d" % (_parts[0], _parts[1], int(_parts[2]) + 1)

# ── 1. the report section (string replace on a stable marker) ────────────
report = ROOT / "docs/audits/<the-audit>.md"
text = report.read_text(encoding="utf-8")
marker = "*(the reproduction appendix follows)*"          # stable anchor
assert text.count(marker) == 1, "the report anchor moved"
text = text.replace(marker, SECTION)

# ── 2. the findings table: match by SUBSTRING, never by exact row text ───
# The needle is a SHORT distinctive PHRASE ("the queue never retried"),
# never the whole row: the same report carries several tables with
# different column layouts ("| 3 | MAJOR | ... |" vs "| D | MAJOR | ..."),
# and a full-row needle matches none of them.
# The guard is SECTION-SPECIFIC.  A generic `"FIXED in §" not in line`
# skips a row that already carries a note for an EARLIER wave, and the
# wave's note is then silently lost — the row keeps saying "open".
FIX_NOTES = {"<a short phrase unique to the row>": " — **FIXED in § N**"}
lines = text.split("\n")
hits = 0
for i, line in enumerate(lines):
    for needle, note in FIX_NOTES.items():
        if needle in line and "FIXED in § N" not in line:
            lines[i] = line.rstrip() + note
            hits += 1
            break
assert hits == len(FIX_NOTES), "matched %d of %d" % (hits, len(FIX_NOTES))
text = "\n".join(lines)

# ── 3. the changelog and the label documents: compute the bodies ────────
changelog = ROOT / "CHANGELOG.md"
c_lines = changelog.read_text(encoding="utf-8").split("\n")
_idx = next((i for i, l in enumerate(c_lines) if l.startswith("## [v%s]" % OLD)), None)
assert _idx is not None, "the previous release heading was not found"
c_lines.insert(_idx, CHANGELOG_ENTRY)
changelog_text = "\n".join(c_lines)

label_docs = (...)               # the documents that quote the label
label_bodies = {}
for rel in label_docs:
    body = (ROOT / rel).read_text(encoding="utf-8")
    for head in LABEL_HEADS:
        body = re.sub("(" + head + ")" + re.escape(OLD) + r"(`?)",
                      lambda m: m.group(1) + NEW + m.group(2), body)
    label_bodies[rel] = body

# ── 4. EVERY assert has passed — now write, report LAST ─────────────────
# No write happens before this point: an assert that fires leaves the
# tree untouched, not half-released (the report written, the version and
# the labels not).
pyproject.write_text(t.replace(f'version = "{OLD}"', f'version = "{NEW}"'), encoding="utf-8")
(ROOT / "VERSION").write_text("v%s\n" % NEW, encoding="utf-8")
changelog.write_text(changelog_text, encoding="utf-8")
for rel, body in label_bodies.items():
    (ROOT / rel).write_text(body, encoding="utf-8")
report.write_text(text, encoding="utf-8")                 # write LAST
# manuals: ./venv/bin/python doc/build_manual.py --all --deploy
```

## The per-wave checklist

1. The defect reproduces against the real data (command + real output).
2. The fix is structural and minimal — one root cause, no drive-by edits.
3. A regression test fails without the fix and passes with it — **PROVEN,
   not assumed**: run it against the pre-fix file with
   `scripts/ab_verify.py` BEFORE the code commit, because HEAD still
   holds the pre-fix code then. A test that passes both ways does not
   discriminate, and the usual cause is that it marks the wrong content:
   a duplication of the paragraphs that PRECEDE an over-long paragraph
   is not detected by a marker inside the over-long paragraph.
4. The measurement is re-run with the same probe (before → after) — and
   the "before" is **PROVEN NON-ZERO** by running the probe against the
   pre-fix code. A probe that reports zero before AND after is
   measuring the wrong thing: a text source with no over-long paragraph,
   a corpus subtree the defect does not live in, a field the defect
   never reaches. A "before" that is zero and an "after" that is zero
   is not a measurement, and the report must not claim a delta from it.
5. mypy is clean on the changed modules; the repo's gate files pass.
6. The report section, the changelog entry, the version, the labels and the
   manuals are all in the wave.
7. Two commits (code, then docs+release) or one, consistently with the
   repo's history; `SKIP=pip-audit` only when no requirement pin changed.
8. Pushed, and `origin/main` verified against HEAD.
9. The next wave is already open — the report's open-findings list is the
   queue.

## Running the verification commands

Keep them short and single-purpose — the rule and the recovery procedure
live in `mizan-repo-delivery` (its suite section), so do not re-derive
them here: one focused subset per command, one for the repo's gate
files, one for mypy.
