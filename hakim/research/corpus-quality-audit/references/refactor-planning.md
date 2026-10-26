# Planning a Cross-Cutting Refactor in This Repo

## The coupling that breaks trees

The unit of atomicity in a rename is the **deployable state**, not the source file. A task
boundary that splits the code from the config leaves an intermediate commit where the old key is
unread and the new field silently takes its default — the exact failure the refactor exists to fix,
self-inflicted on the way to fixing it.

Coupled pairs that must land in one commit:

| change | must land together with |
|---|---|
| rename a Settings field | every reader, the whitelist, `FIELD_META`, `.env`, `.env.example` |
| rename a config key | the `.env` value **and** any test asserting on the effective value |
| change a type (bool -> str) | the `.env` literal, and a translator if the string form is not the old one |
| move a helper | every caller *and* the tests that import it by name |

**Pre-flight:** before task 1, list which of the coupled artifacts each task touches. If any task
introduces a name that a later task also introduces, the boundaries are wrong.

## The tell that a later task's name leaked into an earlier one

Applying a later task's names "early" produces phantom failures that look like code bugs — six
test failures caused entirely by tests referencing a field the production code does not read yet.
Do not debug them; check whether the plan ordered the introduction of that name after the test.

The symmetric error is worse: a plan that renames the code in task 1 and the config in task 3 leaves
two commits where the setting is inert.

## Test values: assert the code's default, never the live config

Defaults and live `.env` values routinely differ (`300` vs `1800`; `false` vs `true`). A test
written by reading the live config file asserts the wrong thing and fails against correct code.

Assert `Settings.model_fields["NAME"].default`, or better, assert the *invariants* (an alias table
fully wired, no undeclared keys, a new key winning over a legacy one) — those stay true regardless
of what the operator configured. Invariants are also what catch a renamed field that was never
actually read by anything.

## Rename discipline that needs no re-derivation

These are already standing rules; they are listed here because they are what a refactor plan must
account for, not because they are new:

- **Substring collisions.** A blanket replace of `QARI_OCR_` also rewrites `ADALA_QARI_OCR_ENABLED`
  into a duplicate field that pydantic drops without error. `mypy`'s `no-redef` catches it; pydantic
  does not. Grep for the prefix as a substring of longer names before replacing.
- **Prefix-probing readers.** A helper shaped
  `getattr(settings, f"A_{n}", getattr(settings, f"B_{n}", default))` goes dark when the new name
  carries neither prefix — it returns `default`, with no log line. After a rename, resolve the
  setting *through each reader*. Declaring it is not enough.
- **A test comparing a lookup to the value it reads is vacuous.** Both sides come from the same
  defect. Assert the intended truth (`is True`), not that two views of one source agree.
- **Aliases.** `validation_alias=AliasChoices` resolves per source and preserves documented
  precedence; a `mode="before"` model validator receives init kwargs and `.env` already merged and
  overrides it. A type change additionally needs a `field_validator(mode="before")` to translate,
  or the alias yields `"True"` and selects the wrong branch.
- **Dead vs live-but-inert keys.** An undeclared key is either dead (delete) or live via
  `getattr(settings, X, None)` applied only when not `None` (declare, keeping the `None` default).

## Ledger the ruling, not the plan

When execution forces a deviation from the plan, write the ruling into a progress ledger as it
happens: what deviated, why, and what it cost if wrong. Later steps need the ruling; they do not
need the original plan to have been right. The plan is a proposal, and its failure modes are
findings about the code — a plan whose task boundary is wrong is itself evidence about coupling that
was not understood before starting.