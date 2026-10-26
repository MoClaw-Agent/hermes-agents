# Diffing old vs new behaviour on real inputs

Use when a change alters how a *class* of inputs is handled — a new gate, a substituted helper, a re-ordered priority, a strategy switch — and you need evidence that the new behaviour is better. Passing tests are not that evidence: they cover the inputs someone thought of, and a latent bug lives in the ones nobody did.

## 1. Make both versions importable

The changed module almost always has relative imports, so you cannot load the old file standalone. `importlib.util.spec_from_file_location` on it fails with *"attempted relative import with no known parent package"*. Write the old version into the package directory as a sibling module instead:

```bash
git show HEAD:path/to/module.py > path/to/_module_head_tmp.py
```

```python
from pkg.mod import target_function as new
from pkg import _module_head_tmp as old_mod
old = old_mod.target_function
```

Place it *inside* the package — that is what makes the relative imports resolve. Delete it when done (`rm`), and remember it is untracked: never stage it.

## 2. Run over the real corpus, not a fixture

Load real inputs (cached artefacts, source files). For each, call old and new and classify:

```python
same, diff = 0, 0
examples = []
for inp in real_inputs:
    a, b = new(inp), old(inp)
    if a == b:
        same += 1
    else:
        diff += 1
        if len(examples) < 15:
            examples.append((label(inp), b, a))
```

Report `same / diff`, then inspect every differing example by hand and classify it:

- new value *more complete or more correct* → the change working
- new value *shorter, wrong, or plausible-but-different* → a latent bug the change exposed

Quantify the classification ("293 identical, 177 more complete, 0 regressions") rather than asserting no regressions. A difference is never self-evidently an improvement — you must look at it.

## 3. Substituting a shared helper for local code

The two are rarely equivalent. Before swapping:

- run both against real inputs and compare their captures side by side
- read the shared helper's docstring for the preconditions it documents — a guard the caller must apply, an ordering requirement — and confirm your call site meets them

A shared pattern *looser* than the local one (an extra alternation, a wider quantifier, filler allowed between tokens) matches things the local one declined, and the caller may be relying on that declination. Real shape: a reference extractor swapped its strict own-header pattern for a loose shared one and began returning a *cited* item's identifier instead of the item's own — plausible, silent, wrong, and precisely the defect its own tests existed to catch.

## 4. Harness shape for large samples

Several medium runs that append to a workspace file beat one long run — progress survives a timeout. Aggregate and count with Python, never by reading the output by eye. Print a compact per-input table plus the means and a win/loss/equal tally.

## 5. When a gate re-routes inputs, sample everything

A new guard sends its inputs down a path that rarely or never ran. Do not sample only the inputs the gate targets — the new path is reached by exactly the inputs you were not thinking about. Diff the whole sample and classify as above.
