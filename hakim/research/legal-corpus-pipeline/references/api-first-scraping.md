# API-First Scraping Pattern

## When to Use

Before building a browser-based scraper for a JS-rendered SPA, check if the site exposes a backend API. Many modern legal platforms (JuriThèque, etc.) use Supabase or similar BaaS backends with REST APIs that return structured data directly.

## Discovery Steps

1. **Download the main JS bundle** — look for `<script src="...index-*.js">` in the HTML
2. **Search for API patterns**:
   - `createClient("https://...", "key")` — Supabase client initialization
   - `from("table_name")` — Supabase table references
   - `fetch("/api/...")` — REST API calls
   - `https://*.supabase.co` — Supabase project URL
3. **Extract credentials** — the publishable/anon key is often hardcoded in the bundle
4. **Test the API** — `curl` the REST endpoint with the key to verify access

## Supabase REST API Pattern

```bash
# List records
curl -s "https://<project>.supabase.co/rest/v1/<table>?select=*&limit=100&offset=0" \
  -H "apikey: <key>" \
  -H "Authorization: Bearer <key>"

# Get count (may timeout on large tables)
curl -s "https://<project>.supabase.co/rest/v1/<table>?select=count" \
  -H "apikey: <key>" \
  -H "Prefer: count=exact"
```

## Memory-Efficient Batch Processing

For large datasets (>1000 records), NEVER accumulate all records in memory:

```python
while True:
    batch = fetch_batch(offset, limit)
    if not batch:
        break
    for record in batch:
        transformed = transform(record)
        save_to_disk(transformed)
    del batch  # Explicitly free memory
    offset += limit
```

## Resume Support

Persist processed IDs to a progress file after each batch:

```python
progress = {"processed_ids": sorted(processed_ids), "last_offset": offset}
with open("scrape_progress.json", "w") as f:
    json.dump(progress, f)
```

On restart, load the progress file and skip already-processed IDs.

## File Collision Handling

When the same law reference (ref) appears in multiple domains or instrument types, the output filename (`<doc_type>_<ref>.json`) will collide. The last-write-wins behavior means only one copy survives. Handle collisions by:

1. **Detecting after scrape** — count files vs unique IDs to find collision count
2. **Deduplicating during ingestion** — let the ingestion pipeline use doc_id (UUID) as the primary key, not the filename
3. **If collision rate is high** — consider appending a disambiguator (e.g., domain) to the filename

## Cross-Reference Relation Ingestion

When a provider's backend exposes a relations table (e.g., `legal_relations` with REPEALS, MODIFIES edges):

1. **Ingest the law corpus FIRST** — the relation endpoints must exist as documents in Mizan's `documents` table
2. **Map provider law IDs → Mizan doc_ids** — via the `ref` column in the downloaded JSON files
3. **Insert edges into `citation_graph`** — map relation types (REPEALS→repeals, MODIFIES→modifies, etc.)

If relations are fetched before the corpus is ingested, store them in a staging table and resolve during ingestion.

## Pitfalls

- **Count endpoint timeout** — Supabase `select=count` can timeout on large tables. Use pagination instead.
- **ID gaps** — Supabase IDs may have gaps (deleted records). Use ID-based resume, not offset-based.
- **Rate limits** — even with API access, add small delays (0.1-0.5s) between batches.
- **Subagent timeout** — subagents exit after ~5 minutes. The script must be resilient (progress file, batch processing) so it can be re-dispatched.
- **False negatives in cross-reference mapping** — refs from the provider may not match Mizan's document refs if the laws aren't ingested yet. Always check the ref overlap before attempting edge insertion.
