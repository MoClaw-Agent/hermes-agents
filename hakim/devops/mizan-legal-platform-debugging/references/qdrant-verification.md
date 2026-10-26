# Qdrant Verification Patterns

## When to Use

- Verifying ingestion results (doc counts, field population, collection routing)
- Debugging missing documents in Qdrant
- Post-ingestion quality checks

## Scroll vs Count Endpoint Discrepancy

The Python client's `scroll()` with `with_payload=True` can silently return 0 points
when the collection is large or the payload is heavy. The count endpoint still
shows N points. This is NOT evidence that documents are missing — it is a
client-side retrieval failure.

**Symptom:** `count` says 1215 points, `scroll` returns 0.

**Diagnosis:** Use curl with the correct REST endpoint:
```bash
# WRONG (returns 0 points):
curl http://localhost:6333/collections/mizan_law/points

# CORRECT (POST to /points/scroll):
curl -X POST http://localhost:6333/collections/mizan_law/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"limit": 200, "with_payload": true, "with_vector": false}'
```

**Rule:** When count and scroll disagree, trust count and verify scroll with
curl before concluding documents are missing.

## Batched Curl Scroll (Large Collections)

The Python client scroll with full payloads exceeds timeout windows on
collections with >1000 points. Use batched curl in a shell loop instead:

```bash
python3 - <<'EOF'
import json, subprocess
all_points = []
offset = None
while True:
    body = {"limit": 200, "with_payload": True, "with_vector": False}
    if offset is not None:
        body["offset"] = offset
    result = subprocess.run(
        ["curl", "-s", "--max-time", "30",
         "http://localhost:6333/collections/mizan_law/points/scroll",
         "-X", "POST", "-H", "Content-Type: application/json",
         "-d", json.dumps(body)],
        capture_output=True, text=True, timeout=60,
    )
    d = json.loads(result.stdout)
    pts = d.get("result", {}).get("points", [])
    if not pts:
        break
    all_points.extend(pts)
    offset = d.get("result", {}).get("next_page_offset")
    if offset is None:
        break
print(f"Retrieved {len(all_points)} points")
EOF
```

## Collection Routing Verification

When documents are missing from their expected collection, check ALL
collections for them before concluding an ingestion failure:

1. Get unique doc_refs from each collection (scroll with payload)
2. Compare JSON corpus refs against each collection
3. Check for misrouted docs (e.g., ADALA law docs in mizan_bo)
4. Check file timestamps — docs modified after ingestion are not "missing",
   they are simply not yet re-ingested

## Common Payload Fields for Verification

| Field | Purpose |
|-------|--------|
| `doc_ref` | Document reference (e.g., "1.10.191") |
| `provision_ref` | Article label (e.g., "Art. 28", "Fasl. 3") |
| `hierarchy_path` | JSON array of container titles |
| `hierarchy_str` | Fallback string form |
| `doc_id` | UUID for the document |
| `chunk_id` | UUID for the chunk |
| `source_provider` | "adala", "sgg", etc. |

## Pitfalls

- **Python client version mismatch:** qdrant_client 1.14.2 against server 1.19.0
  emits a UserWarning and may behave unexpectedly. Use `check_compatibility=False`
  or raw curl for critical verifications.
- **Full-payload scroll is slow:** Each point carries ~80 payload keys including
  text, metadata, and provenance. 1215 points × full payload can exceed 5 minutes.
  Use `with_vector: false` and batch in groups of 200.
- **next_page_offset is opaque:** It is not the point ID — it is a cursor token.
  Always pass it back as `offset` in the next request.
