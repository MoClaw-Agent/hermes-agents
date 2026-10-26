# Content-hash corpus cleanup

Deleting duplicate source documents is irreversible. The rule that makes it
safe: **only ever delete a file whose bytes are identical to a file you are
keeping.** A dedup pass that groups by *filename* will happily delete a distinct
document; one that groups by *content* cannot lose anything.

## Non-negotiable preconditions

1. **Nothing may be running.** A parser batch enumerates its work list at
   start-up; deleting sources mid-run leaves queued workers pointing at missing
   paths, and path-keyed state keeps success records for files that no longer
   exist. Stop first, or defer the cleanup entirely.
2. **Re-stat the corpus immediately before deleting.** A re-crawl replaces files
   in place, so any grouping computed earlier may describe bytes that are gone.
3. **Dry run first, always.** Print the full plan and the reclaimed bytes.

## Grouping

Group by `(folder, sha256)`, never by basename.

- Same hash, >1 file → the extras are safe to delete.
- Same basename, **different** hash → a collision, NOT a duplicate. These need
  investigation: a name resolver that finds no collision entry will let the
  second download overwrite the first, and the document is already lost. Do not
  delete either; report them.

Prefer keeping the plain basename over a hash-suffixed one (`14.pdf` over
`14_9da6b234.pdf`) so the survivor keeps the canonical name that downstream
stem-keyed output paths expect.

## Guard, in code

Refuse to delete anything if any planned deletion would leave a hash with zero
copies on disk. Cheap, and it converts a silent data-loss bug into a loud abort:

```python
survivors = defaultdict(int)
for p in keep:
    survivors[sha(p)] += 1
for dup, survivor, h in plan:
    if survivors[h] < 1:
        sys.exit(f"ABORT: {dup} is the last copy of {h[:12]}")
```

## Sidecars

Each PDF has a `<stem>.meta.json` beside it. Delete the duplicate's sidecar with
it, or the corpus ends up with orphaned metadata pointing at absent files.

## Manifest

Write every deletion to a JSON manifest (`deleted`, `kept`, `sha256`,
`deleted_sidecar`) **before** removing anything, and print the survivor check
afterwards. It is the only record of what went, and it makes the operation
auditable rather than a bare `rm`.

## Verify

Re-run the grouping after deletion. The success criterion is **zero
content-identical duplicate groups remaining** — distinct-content basename
collisions are expected to survive and are not a failure.
