# The workflow documents

Six planning/tracking documents live in `doc/workflow/` under `/home/mohammed/Mizan`.
They are the agent's own working memory for the project and are maintained as
part of every wave — not a one-off artifact created on request.

## The set

| File | Question it answers |
|---|---|
| `PRD.md` | what is being built, for whom, and what "done" means |
| `ARCHITECTURE.md` | stack, folders, data flow |
| `DESIGN.md` | colours, fonts, components, vibe |
| `RULES.md` | coding style and what the agent must never do |
| `TASKS.md` | the open work, one small step per item |
| `PROGRESS.md` | what is done, what broke, what is next |

Placement rule: a workflow set gets its own folder. If a same-named file
already exists elsewhere in the tree, move its content in and leave the old path
as a short pointer — never create a second file with the same name at the root.
(`doc/ARCHITECTURE.md` was consolidated into `doc/workflow/ARCHITECTURE.md` and
the old file became an 11-line pointer.)

## Maintenance rules

1. **Update in the same wave as the work they describe.** A fix that is not in
   `PROGRESS.md` is undocumented no matter how many commits carry it.
2. **`PROGRESS.md` is the agent's changelog.** Record: the current git state, the
   verified work (with the commit SHA and the measured before/after), what is
   still open, and the next steps. Distinguish *verified* from *assumed* — the
   file is read as evidence, so an unverified claim in it is a defect.
3. **`TASKS.md` holds the open work, one small step per item.** Each item must
   be finishable and checkable in a single pass. Move an item to *Done* only
   after it was actually run and observed. Keep the layer classification with the
   symptom (retrieval / chunking / context builder / generation / corpus OCR) —
   it is what makes the list actionable.
4. **`RULES.md` is the standing contract.** When the user corrects how a class of
   task is done, the correction goes into `RULES.md` (and into the skill that
   governs that class), not only into the session report.
5. **`DESIGN.md` records the tokens as they exist in the code.** Read them from
   the stylesheet (`api/static/mizan_base.css`) rather than from memory, and
   note in the file that the CSS is the source of truth.
6. **`ARCHITECTURE.md` stays consolidated.** New sections go into the existing
   file; do not start a parallel architecture document.

## What each file must NOT become

- `PROGRESS.md` must not become a narrative of the session. It is a state
  snapshot: state, done, open, next.
- `TASKS.md` must not become a project plan. If an item cannot be finished in one
  pass, split it.
- `RULES.md` must not restate the codebase map — that belongs in
  `ARCHITECTURE.md`.
- None of them is evidence for a legal claim. They describe the system, not the
  law.
