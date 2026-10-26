# Running a mechanical rewrite across many files

Use when a change is applied by script rather than by hand: wrapping over-long
lines, reordering imports, renaming a symbol, migrating a config format, adding
`strict=` to every `zip`. The failure mode is not a wrong edit — it is a
*corrupted file* and a sweep that reports success.

## 1. Make it revertable before the first write

- Snapshot the directories you will touch to a scratch dir, or commit.
- Then run the tool. A bulk edit that cannot be undone is a bulk edit you will
  run twice.

## 2. Verify the rewrite before writing it, not after

The guard that works: re-parse the candidate and compare the invariant you care
about against the original. For a text rewrite, that is the set of string
values; for a rename, the set of defined names.

```python
import ast

def string_values(src: str) -> list[str] | None:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None            # candidate is broken: refuse
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]

if string_values(candidate) != string_values(original):
    skip_this_file()           # do not write
```

Compare *values*, not raw token text — comparing `t.string` for STRING tokens
includes the quotes, so a legitimate re-split never compares equal and every
file is rejected.

Validate **per change, not per file.** A whole-file gate throws away every good
rewrite because one line in the file could not be handled. Build the candidate
for one line, parse it, and only commit that line if it holds.

## 3. Tokenize; never regex for "a quoted string"

A regex for string literals matches quotes inside docstrings, inside comments,
and literals nested in f-strings. `tokenize.generate_tokens` does not. Even
then, tokenize reports the literals *inside* an f-string as separate STRING
tokens, so a group of them looks like an implicit concatenation. Reject any
candidate group whose value does not round-trip:

```python
seg = line[start:end]
if ast.literal_eval(seg) != "".join(t.string[1:-1] for t in group):
    continue      # an f-string's innards, not a concatenation
```

## 4. Process insertion edits bottom-up

An edit that *adds* lines invalidates the line numbers of everything below it.
Iterate the collected line numbers in reverse, or recompute offsets after each
write. Applying edits top-down against a stale line map is how the wrong line
gets rewritten — and it is silent, because the output still parses.

## 5. Prefer the tool's own fixer, then review what it chose

For a well-defined rule, the linter's `--fix` is better tested than your script
(`ruff check --select <RULE> --fix --unsafe-fixes`). Read the diff anyway: the
fixer picks the *permissive* option when a rule admits several. `zip()` without
`strict=` is fixed to `strict=False`; when a length mismatch would be a real
bug (a column list paired with a row), change it to `strict=True` and let the
suite adjudicate — a passing run is then genuine evidence that the lengths agree
on every path.

## 6. Know what the formatter will not do

`ruff format` does not split string literals, and most long lines in real code
are long SQL column lists, descriptions and f-strings. Wrapping them is an
implicit concatenation: split at a **space that stays on the preceding chunk**,
so the concatenated value is byte-identical. Then re-run the formatter over the
result, and finish with a syntax check on every touched file plus the full
suite.
