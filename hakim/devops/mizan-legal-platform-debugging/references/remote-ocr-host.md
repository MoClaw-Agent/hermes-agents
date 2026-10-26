# Operating the Remote OCR Host

The Qwen/Qari Ollama instance is a **separate machine**. Two failure classes live there and
neither is visible from the client: the service's runtime identity (which user, which model
store, which bind address) and how to change them without breaking reachability.

Verified shape of a real host: 8× i5-8250U @1.6 GHz, UHD 620 iGPU dropped, Ollama running
`User=ollama`, models in one user's home store.

## Read the state before changing anything

```bash
systemctl is-active ollama; systemctl is-enabled ollama
systemctl show ollama -p User -p Group -p Environment --value
ss -ltnp | grep 11434                     # 0.0.0.0 = reachable, 127.0.0.1 = LAN cannot reach
curl -s -o /dev/null -w '%{http_code}' -m 8 http://<host>:11434/api/tags
ollama list                               # empty list means the service cannot see its models
free -h                                   # available vs swap, not just totals
journalctl -u ollama -n 20 --no-pager
```

`ollama list` returning only a header, while `/api/tags` returns 200, is the signature of a
**model-store mismatch** — see below.

## The service user and the interactive user have different model stores

A unit with `User=ollama` gets `OLLAMA_MODELS=/usr/share/ollama/.ollama/models`. The models
were most likely pulled by an interactive user into `~/.ollama/models`. Two distinct
stores; the service sees none of the other's models.

Symptom sequence, and it is distinctive:

```
POST "/api/show"  -> 404     model not found
POST "/api/pull"  -> 200     starts re-downloading
```

That pair repeats. The service is downloading a model it already has on disk, into the
store that is empty. Check disk before letting it run — a multi-GB re-pull on a nearly full
filesystem is a second outage.

```bash
find <home>/.ollama/models/manifests -type f 2>/dev/null | wc -l
find /usr/share/ollama/.ollama/models/manifests -type f 2>/dev/null | wc -l
du -sh <home>/.ollama/models /usr/share/ollama/.ollama/models 2>/dev/null
getent passwd ollama | cut -d: -f6          # the service user's home
```

### Fix: point the service at the store that holds the models

Prefer changing the unit's runtime identity over loosening directory permissions:

```ini
# /etc/systemd/system/ollama.service.d/override.conf
[Service]
User=<owner-of-the-store>
Group=<owner-of-the-store>
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_MODELS=/<owner-home>/.ollama/models"
```

Running as the store's owner needs no permission changes. The alternative — keeping
`User=ollama` and pointing at another user's home — requires the service user to traverse
that home, and a home directory is typically `0750`, so it silently fails until the
traversal bit is widened. Widening `/home/<user>` to let another account in is the cost;
prefer the identity swap.

A drop-in beats editing the unit: the original stays intact, and undo is `rm` of one file
plus `daemon-reload`.

## Bind address is a separate axis from model visibility

A healthy service that listens on `127.0.0.1` is unreachable from the client host no matter
how many models it has. The client sees `Connection refused`, and retries at the transport
layer — which is **not** the same as an HTTP 500 and not the same as a slow model. Read the
error before theorising about the model:

| client error | layer |
|---|---|
| `Connection refused` / `tags=000` | nothing listening on the address the client dials |
| `500` with a body | the service answered and inference failed |
| `attempt N/M` repeating on a timer | one of the above, being retried |

Restarting a service re-reads its unit, so a drop-in added but not applied disappears; check
`ss` after every restart rather than assuming the edit took.

## `use_pty` makes `sudo -S` unreliable — and pipes bind outside sudo

When sudo is configured with `use_pty`, it reads the password from the controlling
terminal and **ignores the pipe**. Consequences seen in one session, in order:

1. `echo PW | sudo -S <cmd>` — sudo blocks on a pty prompt nobody answers, times out, and
   eventually runs the command **unelevated**. The failure looks like a permissions error
   on the command's target, not like an auth failure, so it is easy to misread as "wrong
   path" or "read-only mount". Confirm the actual identity before chasing the target:
   ```bash
   sudo -S -k -p "" id        # -k forces re-auth; must print uid=0(root)
   ```
   `-k` matters: without it a cached timestamp can let a command run unelevated on a stale
   credential and look like a permissions problem.
2. **A pipe under `sudo` runs its right-hand side unprivileged.** `sudo … echo X |
   base64 -d > /etc/...` has the shell bind the pipe outside sudo, so `base64 -d` writes as
   the invoking user and fails on an `/etc` path. Stage the file where the invoking user can
   write, then copy it under sudo:
   ```bash
   echo <b64> | base64 -d > /tmp/x.conf          # unprivileged: fine
   sudo -S -k -p "" cp /tmp/x.conf /etc/...     # privileged: the copy
   rm -f /tmp/x.conf
   ```
3. A pty-based workaround (allocate a shell, send the password when a prompt marker appears)
   can itself mis-parse its own echoed command markers. Prefer form 1 with `-k`; it is the
   simplest thing that actually works.

Verify privilege separately from the task. "It ran and printed `Permission denied`" is not
evidence the command ran as root.

## No log means no diagnosis

A service started by hand with stdout on a terminal records nothing: no journal entries, no
`/var/log` file, no `nohup.out`. When it dies, the reason is gone and the next symptom is
unexplained.

```bash
readlink -f /proc/$(pgrep -f 'ollama serve' | head -1)/fd/1     # -> /dev/pts/N means nowhere
```

Resolve the pid dynamically — a restart changes it, and a probe with a hardcoded pid
silently reports "not running" for every field and looks like a dead service.

Put it under systemd (or `nohup … > ~/log 2>&1 &`) before the next failure. A pid change
between two checks is itself a finding: the service restarted, and nothing recorded why.

## Throughput expectations from the hardware, before quoting a per-page cost

`ollama ps` showing `100% CPU` with `total_vram="0 B"` and a log line
`dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1` means inference is CPU-only.
A laptop U-series part at ~0.2 tok/s makes **minutes per page** normal, not pathological.

Two numbers that are routinely misread:

- The first request pays model load. Discard it or label it cold before dividing into a
  per-page or per-corpus budget.
- `num_ctx` shown by `ollama ps` can reflect a per-request `num_ctx`, not the server default
  (`default_num_ctx` in the log is the server's own). Do not attribute it to configuration.

Lowering `MAX_NEW_TOKENS` caps the damage of a runaway generation; it does not make
generation faster. If latency is the problem, the lever is hardware or batching.

## Do not repair the client when the transport is broken

Before any model-level hypothesis, confirm the endpoint answers from the client host. A
`Connection refused` on the health route explains a failed parse completely and no amount of
prompt, DPI, or pixel-budget work addresses it.