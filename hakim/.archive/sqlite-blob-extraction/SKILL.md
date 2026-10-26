---
name: sqlite-blob-extraction
description: Extract files stored as BLOBs in a SQLite database.
---

# SQLite BLOB / File Extraction

## When to use
- User asks to "extract PDFs / images / attachments" from a `.db` / `.sqlite` file.
- You suspect an app stores documents inline (common in mobile/desktop apps that cache legal docs, books, attachments, message media).

## Workflow
1. **Inspect schema BEFORE assuming structure.** Two databases that look "the same" (same app family, same folder) can have completely different schemas. List tables via `sqlite_master`, then `PRAGMA table_info(<table>)` for each candidate.
2. **Find the file column.** Look for columns typed `BLOB`. If none, the DB may store only text records — scan text columns for embedded markers (`%PDF-`, `JVBERi0`, `data:application/pdf`) but treat hits cautiously (a substring like `Pdf` can appear inside random tokens).
3. **Verify format.** For each candidate blob, check the first bytes against known magics (`%PDF-` → PDF, `PK\x03\x04` → zip/office, `\x89PNG`, `\xff\xd8\xff` → jpg). Only extract what parses as a real file.
4. **Extract to the target folder** (same folder as the db, or a subfolder the user names). Preserve the human-readable name from a sister column when available.
5. **Sanitize filenames:**
   - Strip path separators and illegal chars: `[\\/:*?"<>|]` → `_`.
   - Keep Unicode/Arabic names intact (don't transliterate) — filesystems handle UTF-8.
   - Handle collisions by suffixing `_2`, `_3`, … ; track used names.
   - Append the correct extension from the magic bytes.
6. **Verify.** Report count, total bytes, and a few sample filenames. Confirm headers are valid.

## Pitfalls
- **Never assume schema parity across "similar" DBs.** In one session `wdapp_unencrypted.db` had `lois.FichierLois BLOB`; `jurisprudenceapp_unencrypted.db` (same project, same folder) had NO blob at all — only text ruling records plus an opaque `url` token column. Inspecting first saved a wasted extraction attempt.
- **Opaque tokens are NOT URLs.** A column of values like `CfDJ8M6suWo2TLhKoCBwOk5P9Teh8mHfgU…` is a storage/reference key, not a fetchable link — there is no scheme/host. Don't tell the user "here are downloadable URLs." To actually retrieve the documents you need the app's base endpoint/API pattern (find it in the app's network traffic or source).
- **Don't transliterate or drop non-ASCII filenames** — preserve the original (Arabic, etc.) so output is recognizable to the user.
- **Blob cells can be empty/NULL** — skip them; don't write zero-byte files.

## Reusable script
`scripts/extract_sqlite_blobs.py` — auto-detects BLOB columns, sniffs extensions by magic bytes, sanitizes names (Unicode-safe), handles collisions. Run:
`python3 scripts/extract_sqlite_blobs.py <db> <out_dir> [--name-col <col>] [--table T --column C]`
If a BLOB column is found but you want filenames from a text column, pass `--name-col`.

## Verification
After extraction: `ls -1 <out>/*.pdf | wc -l`, check a sample header (`head -c 5 file.pdf` should be `%PDF-`), and compare count to `SELECT COUNT(*) FROM <table> WHERE <blob> IS NOT NULL`.
