# Hermes state.db recovery / salvage from a backup

Use when a Hermes profile lost its session store (crash, reinstall, empty
`state.db`) but a backup copy of `state.db` exists, and the goal is to
restore the historical sessions/messages into the live profile without
losing the current session or corrupting the live DB.

## Key paths

- Live store: `$HERMES_HOME/state.db` (SQLite + FTS5, WAL mode). Also
  `state.db-wal` / `state.db-shm` while Hermes is running.
- Backup: any copy of `state.db` (often with its own `-wal`/`-shm`).
- Schema version must match between backup and live; check
  `SELECT * FROM schema_version;` on both before merging.

## Safety first

- Never overwrite a live `state.db` while Hermes is running. WAL-mode
  databases have uncheckpointed writes in `-wal`; replacing the main file
  loses them and can corrupt. Prefer a merge.
- Do not stop/restart Hermes just to swap files unless the user explicitly
  asks; a merge can be done online.
- Keep the live DB's current sessions/messages: the merge must be additive.
- Always run `PRAGMA integrity_check;` and `PRAGMA quick_check;` on both
  DBs before and after.

## Merge procedure (online, additive)

1. Verify both DBs pass integrity checks and have the same schema version.
2. Attach the backup as `bak` with a long busy_timeout (Hermes may be
   writing concurrently):
   ```sql
   PRAGMA busy_timeout = 60000;
   ATTACH DATABASE '/path/to/backup/state.db' AS bak;
   ```
3. Merge in FK order so foreign keys resolve:
   - `system_prompts` first (`INSERT OR IGNORE INTO main.system_prompts SELECT * FROM bak.system_prompts;`) — sessions reference `system_prompt_hash`.
   - `sessions` next (`INSERT OR IGNORE INTO main.sessions SELECT * FROM bak.sessions WHERE id NOT IN (SELECT id FROM main.sessions);`).
   - `messages` last. The `id` column is `INTEGER PRIMARY KEY AUTOINCREMENT`, so **omit `id`** and let SQLite assign new rowids; inserting explicit ids collides with the live sequence. List every other column explicitly. FTS triggers on `messages` auto-populate `messages_fts` / `messages_fts_trigram`, so do not touch the FTS tables by hand.
4. Deduplicate messages so a re-run or partial overlap does not create
   duplicates. Guard with `NOT EXISTS` on (session_id, timestamp, role,
   content) — or any stable natural key available.
   Only merge messages whose `session_id` already exists in `main.sessions`.
5. Commit, detach, re-run integrity checks.

## Pitfalls

- `messages.id` is autoincrement: inserting with explicit ids causes
  `UNIQUE constraint failed` or holes; omitting it keeps FTS triggers correct.
- FTS tables are trigger-maintained; inserting into `messages` populates them.
  Do not bulk-copy FTS tables.
- FK order matters: `system_prompts` → `sessions` → `messages`. Reversing
  leaves orphan rows or constraint failures.
- WAL visibility: a separate sqlite3 connection sees committed data from
  the live DB including uncheckpointed `-wal` content; that is expected.
  Do not delete `-wal`/`-shm` while Hermes is running.
- `INSERT OR IGNORE` on `sessions` by primary key skips collisions silently;
  if titles collide on a unique constraint, the whole insert for that row is
  skipped — check row counts afterward.
- Dedup key must be stable; if `content` is NULL in some rows, use
  `COALESCE(content,'')` in the comparison.
- Messages belonging to sessions that did not merge (skipped) must be
  excluded (`WHERE session_id IN (SELECT id FROM main.sessions)`) to avoid
  orphan messages.

## Verification

- Row counts before/after on both DBs; backup sessions + current sessions
  should sum (minus overlaps) in the merged DB.
- `PRAGMA integrity_check;` and `PRAGMA quick_check;` → `ok`.
- Spot-check `SELECT id, source, title, started_at FROM sessions ORDER BY started_at;`.