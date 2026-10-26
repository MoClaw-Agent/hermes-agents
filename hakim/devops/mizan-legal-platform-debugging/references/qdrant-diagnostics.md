# Qdrant Diagnostic Principles

When debugging Qdrant issues, follow these principles (from Qdrant Skills):

## Diagnostic Principles

1. **Don't tune Qdrant before verifying the embedding model is right** — most search quality issues are model issues
2. **Don't assume memory leak when page cache fills RAM** — normal OS behavior
3. **Latency vs throughput are opposite tuning directions** — know which you're optimizing
4. **Check `/telemetry` and `/metrics` FIRST** before any config change
5. **Test exact vs approximate search** to isolate the layer (model vs HNSW vs filters)

## Quick Diagnostics

### Search quality is bad

1. Test exact search (`exact=true`) vs approximate
2. If exact is also bad → wrong embedding model, not Qdrant
3. If approximate is worse than exact → tune HNSW `ef`, enable oversampling with `rescore`
4. Check if filters are too restrictive (payload index missing?)

### Search is slow

1. Check `/metrics` — is it latency or throughput?
2. For latency: check HNSW `ef`, check if vectors are on disk, check payload indexes
3. For throughput: reduce segment count (`default_segment_number`), use batch search, limit `optimizer_cpu_budget`

### Memory is high

1. Check `/telemetry` for per-segment breakdown
2. Is it vectors? → quantization, smaller datatypes, move to disk
3. Is it payload indexes? → reduce indexed fields
4. Is it page cache? → normal OS behavior, not a problem

## Qdrant Skills

Qdrant diagnostic skills are available in:
- `.mimocode/skills/qdrant/` — 10 skills (search-quality, performance-optimization, scaling, monitoring, etc.)
- `.mimocode/skills/qdrant-advisor/` — meta-skill that routes problems to the right diagnostic skill

Source: https://github.com/qdrant/skills
