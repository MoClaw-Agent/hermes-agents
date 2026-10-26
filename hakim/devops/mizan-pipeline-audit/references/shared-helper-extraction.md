# Extracting a shared helper across providers

The recipe for the fix to a DRIFTED DUPLICATE: when the same decision
exists in two or three places and one copy has gone stale. Copying the
refined rule into the stale copy leaves the class in place; the point is to
make the divergence impossible.

## 1. Count the copies — grep the SYMBOL, not the files you were handed

```bash
grep -rn 'def <symbol>' --include=*.py . | grep -v venv
```

A "two-provider divergence" is often a three-way split: the shared base,
provider A and provider B. Two of the three may already carry the refined
rule, which makes the stale copy obvious and the fix a copy of an existing
implementation rather than a new design.

Read every copy's DOCSTRING before choosing the winner. The refined copy
usually records the real cases that motivated it; the stale one records
the reasoning that has since been superseded. A docstring that explains why
the rule changed is the copy to keep.

## 2. Pick the lower layer — the direction of the import edge

The shared module must sit BELOW its consumers. Check the edge, not the
names:

```bash
grep -c 'from fetching.pipeline_base\|import fetching.pipeline_base' <consumer>.py   # >0 = consumer is above
grep -c 'from fetching.parser_base' fetching/pipeline_base/*.py                        # 0 = no back-edge
```

Put the helper in the package the others import from and which imports
nothing back. A helper placed in the upper layer forces the lower one to
import upward, which is a cycle waiting to happen.

## 3. Write the shared module

- One function, one docstring carrying the reasoning and the real cases.
- Import heavy symbols LAZILY inside the function body when the module sits
  in the lower layer (`from x import y` inside the def). The providers
  import this module at load time, so a module-level import of a symbol
  from the importing package is a circular import.
- Export the public name from the package `__init__.py` if the consumers
  prefer the package-level import form; otherwise import the submodule
  directly.

## 4. Replace each copy with an ALIASED import

```python
from fetching.pipeline_base.native_gate import (
    native_structure_is_sufficient as _native_structure_is_sufficient,
)
```

Keep the existing PRIVATE name. The call sites stay untouched and the
tests that import `_private_name` from the provider module keep working —
the name is still bound in that module's namespace. Renaming across the
providers is a drive-by refactor and costs a wave's worth of churn for
nothing.

The import must name the SUBMODULE, not the package. An automated insert
that lands in the existing `from <package> import ( ... )` block instead
of `from <package>.<module> import ...` parses cleanly and fails at
runtime with `ImportError: cannot import name ... from <package>` — the
package's `__init__` does not re-export it. `ast.parse` proves nothing
about name resolution, so VERIFY BY IMPORTING THE MODULE:

```bash
venv/bin/python -c "import <provider_module>; print('ok')"
```

If the consumers genuinely want the package-level form, export the name
from `__init__.py` as well — but do that deliberately, and re-run the
import check. A silent `ImportError` is the failure this step is meant to
prevent; catching it at `ast.parse` time is not catching it.

Delete the stale body, not just the return line: leave no dead constant
behind (a `_MIN_CHARS = 200` that nothing reads is a trap for the next
reader, who will assume the gate still uses it).

## 5. Prove the sharing is real

```python
from a import _gate as x
from b import _gate as y
from shared import gate as z
assert x is z and y is z
```

Identity, not equality. Three copies that happen to return the same value
on today's inputs are still three copies; one function object is the
guarantee. Report the identity check in the wave.

## 6. Re-check the gates and the pins

- **The god-file gate**: removing a body SHRINKS the provider files. The
  repo's repin script is raise-only by convention, so the pins become
  ceilings ABOVE the real size and the gate permits growth it was written
  to block. Decide explicitly whether to tighten them; do not leave the
  stale ceiling unmentioned.
- **The bare-except ratchet** and any per-file pin: run the gate files
  after the extraction.
- **mypy**: the lazy import inside the function body must still resolve.

## 7. Measure the behaviour change, then write the regression test

The gate's behaviour changed for the stale copy only, so measure that
copy's decision on a set of synthetic inputs covering: the case the stale
rule got wrong, the case both rules agreed on, and the case the refined
rule deliberately keeps. A table of before/after per case is the evidence;
"they now agree" is not.

The regression test should assert the SHARED behaviour (import the shared
function) and pin the case that used to diverge.
