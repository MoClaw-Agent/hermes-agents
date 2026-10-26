# Artifact Execution Harness

How to verify something you cannot run in place — a Colab notebook, a remote
runtime, a hosted model endpoint — before handing it over.

The failure this prevents: shipping unexecuted code and having the user
discover the defect as a runtime traceback. On a notebook this is not
hypothetical — a run of notebook changes that were patched but never executed
produced six separate failures, every one of them a defect that executing the
artifact would have surfaced immediately.

## The shape

Extract the artifact's cells/modules, execute them in one namespace with the
*environment* stubbed, and drive the real entry points. Four layers, in order:

1. **Static cross-cell dependency check.** For each cell, collect every free
   name it reads (`ast.Name` with `Load` ctx) and subtract what it binds itself
   (assignments, `def`/`class`, imports, `arg`, `except ... as`, comprehension
   targets). Any remainder must be bound by an earlier cell or be a builtin.
   This catches the whole class of execution-order bugs — `NameError` on a name
   that exists three cells later — with no runtime needed.

2. **Execute every cell** into a single shared namespace, in order. Strip
   IPython magics (`!pip`, `%cd`) first, but only at **column 0**: an indented
   `%` is an operator continuation (`value\n    % other`), and stripping it
   silently breaks a valid expression while manufacturing a fake syntax error.

3. **Call the real entry points.** Do not settle for "the cells imported".
   Invoke the public function on both dispatch branches, and POST to the
   server the artifact itself started rather than spinning up your own.

4. **Exercise the failure paths.** Auth rejection, malformed payloads, large
   bodies, resume-after-interrupt, and the retry-exhausted branch. A harness
   that only proves the happy path has not proven the service.

## Stub the environment, never the subject

This is the rule that matters most, and it is violated by well-intentioned
fakes.

A harness that pre-binds a global which production code is responsible for
binding makes the buggy path unreachable. The shape of it: a model loader
declares `global _torch` but binds it via a local `import torch` placed *after*
an early return. Because the server cell loads the model at startup, the early
return always fires, `_torch` stays `None`, and every request dies on
`None.no_grad()`. A harness that pre-sets `_torch` never runs the early return
against real code, so it reports green against a service returning HTTP 500 on
every request.

Before trusting a fake, ask: *if the production code were completely broken
here, would this stub hide it?* If yes, the stub is too generous. Set it to the
value production code is supposed to produce, not the one production code
fails to produce.

## Finding defects the harness exposes

Expect to find, and check for, each of these:

- **A cell that depends on a name defined later.** Reorder; do not add an
  import that papers over an ordering bug.
- **A cell placed before the resource it consumes** — a smoke test above the
  cell that starts the server raises `Connection refused` on a healthy setup.
- **Dead code referencing globals that no longer exist.** Unreferenced
  functions are not harmless: they are a landmine for whoever wires them up
  next. Delete them, and check for a constant duplicated in two cells — the
  live copy and the stale one diverge silently.
- **An endpoint dropped during an unrelated patch.** Diff the route table
  before and after any change to request handling.

## Scaffolding gate

The harness should assert the absence of test scaffolding, not merely tolerate
it: `PASTE_KEY_HERE`, smoke-test cells, `run_batch(limit=1)`-style commented
usage, `TODO`, `FIXME`, `XXX`. A placeholder credential is the sharpest case —
it leaves auth silently disabled, which is worse than a hard failure. Prefer a
cell that raises with the exact remedy over one that proceeds with a stub.

Pair each of these with a presence assertion (`the notebook still provides a
handler / server start / teardown`). Removing a smoke test must not quietly
remove the service along with it.

## Commit the harness

Put it in the repo (`tests/`), not a scratch directory, and make it a
re-runnable command. Its value is that the next edit is checked the moment it
is written, which is the only time the check is cheap.

## Notebook-specific: two OCR passes, one persisted

Applies to any pipeline where a second OCR pass can supersede the first. When a
parser writes its structure from a vision-rescue pass while a separate cache
holds the earlier extraction's text:

- The cache may contain **different, worse text** than the JSON was built from.
- `full_text_in_cache: true` can be a lie — check whether the cache mtime
  actually postdates the artifact, and whether distinctive strings from the
  artifact appear in the cache at all.
- The expensive pass is the one you lose. Persist it alongside the cheap pass,
  under a distinct filename so it cannot clobber it, and record which pass
  built the structure in the output as an explicit provenance field.
- Give the three log outcomes distinct wording — accepted / rejected-with-
  reason / never-ran. When all three share a message, a rejected rescue is
  indistinguishable from a missing one.

Before re-running a parse to test a parser fix, check for a stale cache: a
valid cache hit returns immediately and the re-parse silently tests nothing.
Move it aside rather than deleting it.