# Running code you cannot execute directly

Notebooks, cloud functions and GPU services are delivered by handing the user a
file and asking them to run it. That is a bad loop: every mistake costs a user
round trip, and the user is the one paying for it.

## Extract and exec locally

A `.ipynb` is JSON; each code cell is a source string. Exec them in order in one
namespace, stripping IPython magics:

```python
import ast, json
nb = json.load(open(NB, encoding="utf-8"))

def strip_magics(src):
    # Magics start at COLUMN 0. Stripping by .strip() or lstrip() also removes
    # indented '%' operator-continuation lines and turns valid code into a
    # SyntaxError -- which then reads as a notebook bug.
    return "\n".join(l for l in src.split("\n") if not l.startswith(("!", "%")))

ns = {"__name__": "__main__"}
for i, c in enumerate(nb["cells"]):
    if c["cell_type"] != "code":
        continue
    exec(compile(strip_magics("".join(c["source"])), f"cell{i}", "exec"), ns)
```

Stub only what is genuinely external — the platform module namespace, the
network tunnel, the model. Then drive the real entry point.

## Static cross-unit dependency check

Before executing, verify each unit only reads names an earlier unit binds. This
catches ordering bugs in one pass, with no runtime:

```python
def bound(tree):
    # Store ctx, def/class names, imports, arg names, except-as, comprehension targets
    ...
used = {n.id for n in ast.walk(t) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
missing = used - bound(tree) - available   # available = builtins | earlier units' bindings
```

## What to test, in layers

| Layer | Asserts |
|---|---|
| static | no unit reads an unbound name |
| exec | every unit runs; teardown units excluded |
| unit | the changed function, under stubs |
| integration | real server / real FS: auth, malformed input, repeat calls |
| round-trip | output of the remote unit is accepted by the real local reader |

Assert the round-trip explicitly. It is the layer that proves the two halves
actually agree, and it is the one usually skipped.

## Traps

- **Never fake what the code under test binds internally.** If the function does
  `_torch.no_grad()`, faking `_torch` lets a real "declared global, never
  assigned" bug pass. Set the fake to `None` and let the code bind it.
- **A stub overwritten by the code under test is a false signal.** Defining a
  stub in the exec namespace before running cells that define their own version
  means the stub is dead and the test proved nothing. Override *after* exec.
- **Exclude teardown units** from execution, or they shut down the server the
  later assertions need.
- **Module-level defaults run at exec time.** Point them at a temp directory
  first, or they try to create platform paths that do not exist locally.
- **Non-interactive shells block on prompts.** Supply tokens via the
  environment so the code takes the non-prompting path.
- **Guard against reintroduction.** Assert no scaffold markers remain so
  debugging scaffolding cannot creep back into a deliverable.
- **A failing test may be the harness.** When an assertion fails, first ask
  whether the stub is reachable; several apparent product bugs were the test's
  own shadowed stub.

## Reading the notebook back safely

Edit the JSON with Python, never a line-oriented patch tool — a partial
multi-line match corrupts the document silently and the file stops parsing.
Always `ast.parse` every cell afterwards, and assert that the anchors you
intended to replace are gone and the new ones present. Restore from version
control immediately if a write corrupts it.