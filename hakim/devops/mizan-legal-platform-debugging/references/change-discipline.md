# Change discipline — standing rules for editing this user's working code

Apply to every task in this repo. These are standing preferences, not one-off
advice; violating them has cost this user real work and trust.

## Never remove, disable, or degrade working functionality without explicit permission

A build error is fixed by reverting to the last committed good state and
rebuilding **additively** — never by deleting the feature that exposed the
error. "Fix X" does not authorize removing Y. If a change you are considering
removes, bypasses, or weakens something the user already has working, stop and
ask first, even when the removal looks like the obvious fix.

Corollary: an in-progress edit that breaks a file is not permission to drop the
code that revealed the breakage. Restore and try again.

## When your own edits break a file, restore it — do not patch the corrupted copy

Use git to get back to a known-good base:

```bash
git checkout <rev> -- <path>          # restore one file from a commit
git show <rev>:<path>                 # inspect a committed version without touching the tree
python3 -m py_compile <path>          # confirm syntax before continuing
```

Two failed patches on the same region are the signal to STOP and restore, not
to vary the anchor string. Repeated `patch` attempts on a corrupted file make it
worse (they can delete the very definition you were editing). Re-read the file
(or `git show`) and rebuild from the clean base.

## Damage-first when the user asks what you broke

On any "what did you break / analyze the damage first" request:

1. Stop all edits immediately. Fix nothing.
2. Produce a read-only inventory: `git status --short`, `git diff`,
   `git log --oneline`, `git diff <good-rev> -- <path>`.
3. Separate committed changes from uncommitted working-tree changes.
4. Report exactly what differs from the last good revision, then wait for the
   user's instruction.

Do not fix anything while inventorying, even if the fix is obvious. The request
is for a report, not a repair.

## One root cause, minimal diff, do not disturb working paths

- Change only what the defect requires. No drive-by refactors, renames, or
  reformatting.
- "Don't break what's working": leave every currently-passing path untouched.
- Revert immediately if a change overreaches past the one root cause.

## Verify by executing; report only what actually ran

- Run the real code and report only results you observed. Never state a result
  you did not see (see `references/verification-gate.md`).
- **Never run the test suite without explicit permission.** Verify with targeted
  real runs (parse one file, call one function) and say which runs you did.
- A claim stated before verification has cost this user significant time. Verify
  first, then report.

## A directory the user calls a backup is not a source of truth

Before reading counts, sizes, or content from a directory to answer a question,
confirm which tree is **live**. Reading numbers out of a backup and reporting
them as current is a wrong answer delivered confidently. Ask or check the
consumer's configured path first.
