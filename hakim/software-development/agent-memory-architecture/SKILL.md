---
name: agent-memory-architecture
description: "Design multi-layer agent memory systems."
version: 1.0.0
author: agent
license: MIT
platform: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, ai-agents, sqlite, architecture, rag]
---

# Agent Memory Architecture

Design and implement multi-layer memory systems for AI agents. Covers the
three-layer pattern (short-term / long-term / reasoning), relational storage,
extraction pipelines, entity deduplication, temporal validity, and the design
decisions that separate a working system from a noisy one.

## When to use this skill

- Building or extending a memory layer for an AI agent
- Implementing entity extraction, fact storage, or reasoning traces
- Migrating from a flat key-value store to a structured memory system
- Debugging extraction pipelines that produce garbage
- Designing privacy-gated transcript capture

## The three-layer pattern

Graph-native agent memory systems (Neo4j Agent Memory, Mem0, Zep) converge on
the same three layers. Implement them relationally in SQLite:

| Layer | Stores | Key operations |
|---|---|---|
| **Short-term** | conversations, messages | append, search, session-scope |
| **Long-term** | facts, entities, preferences | extract, dedup, link, temporal-validate |
| **Reasoning** | tool traces, decisions | record steps, search by outcome |

The layers inform each other: short-term conversations feed long-term
extraction; reasoning traces link back to triggering messages.

## Schema design

### Short-term: messages

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL DEFAULT 'default',
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_messages_dedupe
    ON messages(namespace, session_id, content_hash) WHERE content != '';
```

Deduplicate on `(namespace, session_id, content_hash)` so a replayed turn
(retry, resume, re-injection) cannot duplicate the transcript.

### Long-term: entities + fact_entities

```sql
CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN (
        'person', 'organization', 'location', 'event', 'concept', 'product',
        'project', 'other'
    )),
    subtype TEXT,
    description TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_entities_normalized_unique
    ON entities(namespace, normalized_name, kind);

CREATE TABLE fact_entities (
    fact_id INTEGER NOT NULL REFERENCES facts(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    namespace TEXT NOT NULL DEFAULT 'default',
    created_at TEXT NOT NULL,
    PRIMARY KEY (fact_id, entity_id)
);
```

Entity deduplication resolves the same `(namespace, normalized_name, kind)`
to one row, so "La Trattoria" and "la  trattoria," are one entity.

### Reasoning: traces + steps

```sql
CREATE TABLE reasoning_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL DEFAULT 'default',
    session_id TEXT,
    task TEXT NOT NULL,
    outcome TEXT,
    success INTEGER CHECK(success IN (0, 1)),
    metadata TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE trace_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id INTEGER NOT NULL REFERENCES reasoning_traces(id),
    namespace TEXT NOT NULL DEFAULT 'default',
    step_index INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('tool_call', 'observation', 'decision', 'error')),
    tool_name TEXT,
    input TEXT,
    output TEXT,
    summary TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(trace_id, step_index)
);
```

### Temporal validity

The `facts` table should carry `valid_until` and `superseded_by` columns.
Superseding points the old fact at its replacement; every search path filters
`superseded_by IS NULL`, so the old fact drops out of retrieval while
remaining auditable. Invalidating is reversible, unlike archiving.

## Extraction pipeline

### LLM-backed extraction

Extend the JSON schema to ask for entities alongside candidates:

```python
_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {"type": "string",
                               "enum": ["fact", "preference", "convention", "skill", "knowledge"]},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["content", "evidence"],
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string",
                              "enum": ["person", "organization", "location", "event", "concept",
                                      "product", "project", "other"]},
                    "subtype": {"type": "string"},
                },
                "required": ["name", "kind"],
            },
        },
    },
    "required": ["candidates"],
}
```

### Heuristic extraction

A regex phrase-matcher cannot classify entity kinds. Return `[]` for entities
and leave them to the model backends. An unclassified entity would be
indistinguishable from noise.

### Entity auto-link on accept

Entities are structural (typed names), not claims. Auto-link them on accept
without a separate review step:

```python
for ent in candidate.get("entities") or []:
    name = str(ent.get("name", "")).strip()
    kind = str(ent.get("kind", "other")).strip().lower()
    if not name or kind not in _ALLOWED_ENTITY_KINDS:
        continue
    er = store.add_entity(name, kind, subtype=...)
    eid = er.id or er.existing_id
    if eid is not None:
        store.link_fact_entity(fact_id, eid)
```

Facts still go through the review queue as before.

## Privacy-gated transcript capture

See `hermes-agent` skill → `references/plugin-authoring.md` → "Privacy gates
belong INSIDE the writing function".

Key rules:
- The function that writes data owns the gate
- Only `user` and `assistant` roles are stored
- Secrets are redacted before the write
- The transcript tail is bounded (last 20 entries)
- Replays are no-ops via content-hash dedupe

## Retention and size monitoring

Growth is the #1 operational risk. Two unbounded tables dominate: `messages`
(per-turn) and `trace_steps` (per-tool-call). Add retention TTLs and hard caps:

```yaml
retention:
  messages_days: 7          # 0 = keep forever
  candidates_rejected_days: 30
  traces_days: 14
  history_days: 90

limits:
  max_messages_per_session: 500   # 0 = uncapped
  max_candidates: 1000
  max_traces: 500
  max_history: 5000
```

`prune()` runs on every turn via `pre_llm_call`. Eviction is oldest-first;
rejected candidates are evicted before pending ones.

**SQL pitfall:** `memory_history` has NO `namespace` column. Queries filtering
`WHERE namespace = ?` on that table raise `no such column`. Check the schema
before adding namespace filters to existing tables.

**SQL pitfall:** `ORDER BY (status = 'rejected') DESC` keeps rejected rows and
evicts pending ones — the opposite of the requirement. Use `ASC` to evict
rejected first.

## Two-tier injection model

Facts are injected in two tiers:

1. **Pinned tier** — always injected every turn, no matching needed. Bounded by
   `pinned.max_items` (10) and `pinned.max_tokens` (500).
2. **Lexical tier** — only injected when FTS5 search finds a match between the
   current message and the fact's content. Up to 20 results, confidence >= 0.5.

An unpinned fact that doesn't match the current query sits in the store but is
never injected. To make a fact always-on, pin it: `store.pin_fact(id, order=N)`.

## Runtime interpreter testing

When testing with the runtime interpreter (`hermes --print-runtime-command`),
`hermes_bootstrap` MUST be imported first — it puts Hermes's dependency tree
(ruamel, etc.) on `sys.path`. Without it, `agent.auxiliary_client` fails with
`ModuleNotFoundError: No module named 'ruamel'`.

## Pitfalls

### Extraction inside the sanitize loop

If entity extraction is called *inside* `for raw in self._sanitize(...)`,
it never runs when zero candidates are produced. Move it out of the loop:

```python
# WRONG: entity extraction never runs if no candidates
for raw in self._sanitize(backend_items, ...):
    if self._entities_enabled:
        raw["entities"] = self._backend.extract_entities_from_turn(...)

# RIGHT: extract independently of candidate production
entities_for_source = []
if self._entities_enabled:
    entities_for_source = self._backend.extract_entities_from_turn(...)
for raw in self._sanitize(backend_items, ...):
    raw["entities"] = entities_for_source
```

### Entity kind misclassification

The model sometimes misclassifies entity kinds: "Mizan" came back as `person`
when it's a project. The closed kind set constrains values but does not
guarantee correct classification. Noisy-but-harmless for now.

### Test artifacts that look like code bugs

- `refresh_backend()` rebuilds the backend from config/env, discarding any
  double injected after construction. Pin the fake: `orch._backend_pinned = True`.
- A test asserting a literal migration version in a backup filename breaks on
  every migration added. Assert the shape (`"pre-v" in name`) instead.
- A temp-copy migration probe may show 0 rows if the WAL wasn't copied. Check
  the live DB directly.

### The running process holds the OLD plugin

Editing plugin files does not reload them. A long-lived Hermes process called
`register()` once at startup and keeps executing that version. Before claiming
a plugin change is live, check whether the process predates it.

## Verification checklist

1. Migration applies on a fresh DB and on a copy of the live DB
2. Pre-migration backup is written first (fail-closed)
3. `pragma integrity_check` = ok after migration
4. Entity extraction works against the real model
5. `accept_candidate` auto-links, deduplicates, rejects invalid kinds
6. `queue_candidates` stores entities; `get_candidate` parses them back
7. Privacy gate: default OFF stores nothing; enabled stores only user/assistant
8. Replay deduplication: same turn text in same session = no-op
9. Temporal validity: supersede drops old fact from retrieval, keeps it auditable
10. All tests pass; ruff/format/mypy clean
