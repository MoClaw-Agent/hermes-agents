# Hermes Memory Plugin — Architecture and Operations

A local-first long-term memory layer for Hermes Agent, stored entirely in
SQLite. No graph database, no cloud, no hosted service. Implements the
short-term / long-term / reasoning three-layer split used by graph-native
agent memory systems, expressed relationally.

## Architecture

### Three layers

| Layer | Table(s) | Stores | Trust |
|---|---|---|---|
| Short-term | `messages` | Conversations per session | Privacy-gated (off by default) |
| Long-term | `facts`, `entities`, `fact_entities` | Facts, typed entity nodes, fact↔entity links | Review queue before becoming a fact |
| Reasoning | `reasoning_traces`, `trace_steps` | Ordered tool-call traces | Not yet wired |

### Schema migrations

`schema.sql` is the source of truth. The store runs numbered migration
blocks on open, each gated by `storage.backup_before_migration` (default
`true`). A pre-migration backup is written via the online backup API and
named `.pre-v{max_pending_version}.{timestamp}.bak`. Migrations are
checksummed against the embedded `schema.sql` file.

**Pitfall:** `memory_history` has NO `namespace` column. Every other
table does. When writing prune queries or any `WHERE` clause that
references namespace, check the actual schema first. The migration
backup filename encodes the highest *pending* version, not the current
one — assert the shape (`pre-v`), never a literal version string.

### Extraction pipeline

Four backends, selected by `HERMES_MEMORY_EXTRACTION_BACKEND` in `.env`:

| Backend | What it does | Entities? |
|---|---|---|
| `manual` | No extraction | No |
| `heuristic` | Regex phrase-matcher (recall/preference) | No — cannot classify kinds |
| `ollama` | Local Ollama with JSON-schema structured output | Yes |
| `hermes_llm` | Hermes's own `ctx.llm.complete_structured()` | Yes |

**Pitfall:** `hermes_llm` requires `hermes_bootstrap` to be imported
first in the runtime interpreter. Without it, `ruamel` is unresolvable
and `agent.auxiliary_client` fails with `ModuleNotFoundError`. This is a
probe-harness issue, not a code bug — the plugin itself works inside
the running Hermes process.

**Poll:** The heuristic backend captures literal `remember this:` / `note
that` spans out of the agent's own prose. When explaining the heuristic
to the user, the model will dutifully extract those explanations as
facts. Switch to `hermes_llm` for real extraction.

### Entity extraction

Entities are extracted from model backends alongside candidates. They ride
in the candidate row (`memory_candidates.entities` JSON column) so they
survive the review queue. On `accept_candidate`, entities are:

1. Deduplicated by `(namespace, normalized_name, kind)` — so
   "La Trattoria" and "la  trattoria," resolve to one node.
2. Linked to the new fact via `fact_entities`.
3. Invalid kinds are silently skipped (closed kind set).

Entities are structural (typed names), not claims — so they don't go
through the review queue. A wrong entity link is noisy, not dangerous.

**Known limitation:** the model sometimes misclassifies entity kinds
("Mizan" came back as `person` when it's a project). The closed kind set
constrains values but doesn't guarantee correct classification.

## Config surface

### Privacy gates

| Key | Default | Effect |
|---|---|---|
| `privacy.store_transcripts` | `false` | Whether `messages` are persisted at all |
| `privacy.redact_secrets` | `true` | Redact known secret patterns before storing |
| `privacy.log_memory_content` | `false` | Log memory content (off by default) |
| `privacy.cloud_extraction` | `false` | Allow cloud extraction backends |
| `privacy.cloud_embeddings` | `false` | Allow cloud embeddings |

**Pitfall:** `privacy.store_transcripts` was declared in config.yaml
but never read anywhere in the code. Wiring a hook that writes
transcripts without honouring the flag would silently persist every
conversation. The privacy gate must be checked *inside* the function
that writes data, not only at the call site — a future caller must not
be able to bypass it by forgetting to check.

When `store_transcripts` is enabled:
- Only `user` and `assistant` roles are stored (never `system`/`tool`)
- Secrets are redacted before the write
- The transcript tail is bounded to the last 20 entries (the host
  passes 800+ entry transcripts)
- Replays are no-ops via content-hash dedup

### Retention and hard caps

All default to 0 (off). `prune()` runs on every turn via `pre_llm_call`.

| Key | Effect |
|---|---|
| `retention.messages_days` | TTL for `messages` |
| `retention.candidates_rejected_days` | TTL for rejected candidates |
| `retention.traces_days` | TTL for reasoning traces |
| `retention.history_days` | TTL for fact history |
| `limits.max_messages_per_session` | Cap per session, evict oldest |
| `limits.max_candidates` | Cap total; rejected evicted before pending |
| `limits.max_traces` | Cap total, evict oldest |
| `limits.max_history` | Cap total, evict oldest |

**Pitfall:** Candidate eviction SQL uses
`ORDER BY (status = 'rejected') ASC` — this is deliberate. `DESC` would
keep rejected rows and evict pending ones, the exact opposite of the
requirement. When reading boolean-sort SQL, verify the sort order
matches the stated intent.

### Env precedence

`HERMES_MEMORY_ENV_PRECEDENCE` controls which layer wins for
`HERMES_MEMORY_*` keys. Default `file` (`.env` is authoritative). Set
to `process` to restore process-env-wins behaviour. The switch is read
straight from `os.environ` and stripped from the parsed file, so a
`.env` cannot flip the rule that decides whether the file wins.

**Pitfall:** `env_str()` reads `os.environ` before the `.env` file.
A stale exported variable silently wins over an edited `.env` unless
precedence is set to `file`.

## Dashboard tab

The Memory tab is a separate dashboard plugin (`integrations/dashboard/`)
that follows the host plugin SDK. It declares a tab at `/memory` and
provides 8 FastAPI routes for review, search, and injection preview.

**Pitfall:** The host's `Tabs` component is a render-prop API, not
shadcn. See `references/dashboard-plugins.md` for the full contract.

## Install / publish workflow

```bash
# 1. Reinstall from source (copies dashboard/ into the plugin dir)
bash scripts/install-plugin

# 2. Verify installed == source
for f in dist/index.js manifest.json plugin_api.py dist/style.css; do
  diff -q integrations/dashboard/$f \
    ~/.hermes/plugins/hermes-memory/dashboard/$f
done

# 3. Restart the dashboard (the user does this — never kill it yourself)
#    User runs: hermes dashboard
```

**Pitfall:** The dashboard discovers plugins by scanning
`<plugin dir>/dashboard/manifest.json`. An edit that never gets copied
looks exactly like a code bug. The install script handles the copy;
diff source against installed after every change.

## Verifying

### Quick checks

```bash
# Store health
hermes plugins validate ~/.hermes/plugins/hermes-memory

# Backend API (401 without session token is expected)
curl -s http://127.0.0.1:9119/api/plugins/hermes-memory/status

# Discovery
python -c "
import sys; sys.path.insert(0,'/home/mohammed/.hermes/hermes-agent')
from hermes_cli.web_server_dashboard import _discover_dashboard_plugins
for p in _discover_dashboard_plugins():
    print(p['name'], p['tab'].get('path'), p['has_api'])
"
```

### Running tests

```bash
# Full suite (168-227 tests, ~60s)
PYTHONPATH=. hermes-agent/venv/bin/python -m pytest tests -q

# Specific layer
PYTHONPATH=. hermes-agent/venv/bin/python -m pytest tests/test_three_layer_memory.py -q
PYTHONPATH=. hermes-agent/venv/bin/python -m pytest tests/test_short_term_capture.py -q
PYTHONPATH=. hermes-agent/venv/bin/python -m pytest tests/test_long_term_entities.py -q
PYTHONPATH=. hermes-agent/venv/bin/python -m pytest tests/test_retention.py -q
```

### Live browser verification

The tab must be verified in a real browser, not just via TestClient:

1. `hermes dashboard` (user starts this)
2. Navigate to `/memory`
3. Read `document.body.innerText` — confirm panes render
4. Drive one action (Accept/Reject) and assert visible state changed

**Pitfall:** React swallows render exceptions. An empty console is NOT
evidence of success. Install a trap before app code runs:
```js
window.addEventListener('error', e => window.__errs.push(e.message));
window.addEventListener('unhandledrejection', e => window.__errs.push(String(e.reason)));
```
Then read `window.__errs` after load. A message naming the host's
`ui-*.js` means a component-contract problem, not your logic.

## Usage workflow

### Manual storage (works immediately)

Tell the agent in conversation:
```
Remember this: the Mizan staging port is 8080
```

Or use the tool directly:
```
memory_add "we deploy from the main branch"
```

This creates a fact immediately — no review queue, no extraction.

### Automatic learning (requires config)

Edit `config.yaml`:
```yaml
extraction:
  enabled: true
  backend: hermes_llm    # or ollama
  auto_store_inferred: false  # keep false: inferred goes to review queue
  entities: true
```

With `backend: hermes_llm` and `entities: true`, every turn:
1. LLM extracts candidates → review queue
2. LLM extracts entities → held in candidate row
3. Review in dashboard tab or `hermes-memory candidates list --watch`
4. Accept → fact created + entities linked. Reject → marked rejected.

### Retrieval (automatic, no action needed)

- **Pinned facts** → injected every turn, always
- **Relevant facts** (FTS5 search matches message) → injected if relevant

## Store maintenance

### Inspect size

```python
from core.store import Store
from core.config import MemoryConfig
s = Store(config=MemoryConfig(), db_path=MemoryConfig().storage_path)
print(s.table_sizes())       # row counts per table
print(s.total_size_bytes())  # DB file size
```

### Manual cleanup

```python
# Delete rejected candidates
with s._lock:
    con = s._connect()
    con.execute("DELETE FROM memory_candidates WHERE status = 'rejected'")
    con.commit()

# Delete old extraction_runs (keep last 5)
con.execute('''
    DELETE FROM extraction_runs WHERE id NOT IN (
        SELECT id FROM extraction_runs ORDER BY id DESC LIMIT 5
    )
''')
```

### Automatic cleanup

`prune()` runs on every turn via `pre_llm_call`. Set retention/caps in
`config.yaml` to enable. All default to 0 (off).

**Note:** SQLite does not reclaim deleted page space automatically.
A `VACUUM` would shrink the file but rewrites the entire database —
only do this if the user asks.

## Status

### Wired

- Short-term layer: `pre_llm_call` → `messages` (privacy-gated, off by default)
- Long-term layer: entity extraction from model backends, auto-link on accept
- Retention: `prune()` runs every turn, TTLs + caps enforced
- Dashboard tab: renders, all 3 panes functional, Accept/Reject verified
- CLI: `candidates list --watch`, full tool surface

### Not wired

- Reasoning traces: tables exist, no hook writes to them yet. Recording
  every tool call has real cost and privacy weight — needs explicit user
  decision on what gets recorded.
