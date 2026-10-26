# Operating a vision-OCR inference service (GPU host behind a tunnel)

A notebook (Colab/Kaggle) runs an HTTP service that fronts a local model server
(Ollama); a remote parser polls it over a tunnel. These are the operational
failures that make the service look healthy while producing nothing. Read this
before reporting an OCR endpoint as working, and before diagnosing "it is slow".

---

## Liveness, readiness, and generation are three different checks

| Check | What proves it | Ollama endpoint |
|---|---|---|
| Liveness | process/port answering | `GET /api/tags` |
| Readiness | a model is **resident in memory** | `GET /api/ps` |
| Generation | the model actually produces tokens | a real end-to-end request |

`/api/tags` **lists** models on disk and loads none. A health endpoint built on
it reports `model_loaded: true` while nothing is in VRAM — a claim the next real
request pays for.

### Warm at startup, with the request's own keying parameters

Ollama keys a loaded instance on its parameters. Warm with values different from
the real requests and the first page reloads anyway.

```python
def _warm_ollama(...):
    # 1. reachable?  GET /api/tags        -> hard error if not
    # 2. already resident?  GET /api/ps   -> if the model is listed, return
    # 3. otherwise POST /api/generate {
    #        prompt: "ok", num_predict: 1,
    #        keep_alive: KEEP_ALIVE,
    #        options: {num_ctx: NUM_CTX}}
    #    -> the load happens HERE, where the wait is visible
```

Measured on a T4 with an 8B Q8 build: cold `load_duration` **41.04 s**, warm
**0.0 s**, throughput identical (28.3 vs 28.6 tok/s). Without the warmup that
41 s lands inside the *first page's* per-request timeout budget; with it, cell
startup pays it once.

Fail loudly when the tag is absent: name the models actually present and the
exact `ollama pull <id>` command. Otherwise a missing tag surfaces only as a
generic timeout minutes later.

---

## Bound the job store in a polling service

A `POST`-starts-a-job / `GET /result/<id>`-polls design keeps results in memory.
Two leaks, both silent:

- **Finished results are never deleted.** Each holds a whole page of text, so
the dict grows one entry per page for the life of the process.
- **A client that never polls grows it without bound.**

Fix both:

- **Drop a terminal result the moment it is read.** A second poll then returns
  "job not found" — that is the intended contract, not an error.
- **Cap the store**, evicting only *completed* jobs. A pending job may still be
  polled and must never be evicted. Insertion order gives oldest-first eviction
  for free.

---

## Bound the model's context per request

An unset `num_ctx` makes the server allocate each KV cache against the model's
**advertised** context (262k for Qwen3-VL / olmOCR) — the dominant driver of
resident-memory growth across a corpus run.

Send an explicit `num_ctx` sized to the real input (a page at a ~1M-pixel budget
is roughly 320–1300 vision tokens; 8192 is ample) and an explicit `keep_alive`,
so the model stays resident between pages of one run and is released predictably
between batches (`keep_alive: 0` unloads immediately).

---

## Separate client errors from server faults

A handler that iterates a request field directly crashes on an unexpected shape.
The classic: `content` is a plain string when there is no image part, so
iterating it yields **characters** and `part.get(...)` raises `AttributeError` →
HTTP 500 with a full traceback for what is a malformed request.

Parse the body defensively, raise a distinct exception for bad input, and map it
to **400** — reserving **500 + traceback** for genuine server faults. Validate
every level:

- body is a JSON object
- `messages` is a non-empty list
- `messages[0]` is an object
- `content` is a **string or a list** (handle both)
- an `image_url` part exists
- its `url` is a data URL

---

## Measure throughput; never infer it

`total_duration - load_duration` is **not** generation time. On a cold call the
remainder also carries warmup and prompt-eval, so the subtraction overstates
slowness and invites a wrong diagnosis (it produced a "250x too slow" claim on a
perfectly healthy T4).

Measure directly, and run it **twice** to separate load from throughput:

```python
tok_per_s = d["eval_count"] / (d["eval_duration"] / 1e9)
```

Reference point: a T4 with an 8B Q8 model runs **~28 tok/s** (about 77% of the
card's memory-bandwidth ceiling). Cold and warm throughput should be nearly
identical; only `load_duration` differs. If a response is truncated before
`eval_count` / `eval_duration`, you do **not** have a measurement — request the
full body or read the fields you need before concluding anything.

---

## `llamacpp` in `ollama ps` is Ollama's runner, not your backend

Ollama wraps llama.cpp, so every GGUF it serves reports `llamacpp` in the runner
column. That is not the same as a separate `llama-cpp-python` backend loaded
inside the Python process — that one never appears in `ollama ps` at all. Seeing
`llamacpp` there confirms Ollama is the active backend; it says nothing about a
separate in-process loader.

---

## Model identity has one source of truth

Derive the served model id once (`MODEL_REPO` + quantisation) and reference it
everywhere — the request body, the health payload, the model list. Hardcoded
copies of the model string drift apart silently and are invisible until the tag
changes.

---

## Editing the notebook safely (and keeping variants in sync)

A `.ipynb` is JSON; the service core is one large code cell. Edit it as data,
never by hand-editing the JSON on disk.

1. **Find the exact string in the parsed source, assert it occurs exactly once,
   replace, write back.** A `count() != 1` is a stop, not a warning — a repeated
   anchor means you would silently edit the wrong copy.
2. **Re-parse every edited cell with `ast.parse` after writing.** Catches a
   broken replacement before the user runs the cell in Colab.
3. **Keep variants byte-identical apart from model identity.** When two
   notebooks differ only by model, diff the edited block and assert the
   difference is exactly the expected lines.
4. **Never reflow the notebook's line list while patching.** Rebuild
   `cell['source']` from the edited string and strip the trailing newline; do
   not hand-splice lines.

**Pitfall — do not strip `!`/`%` lines before `ast.parse`.** A naive "remove
shell magics" filter also deletes continuation lines of a `%` **operator** (the
`% (...)` inside a multi-line `raise RuntimeError(...)`) and reports a false
syntax failure (`'(' was never closed`) in a perfectly valid cell. Either parse
the cell unfiltered, or skip cells whose *first* line is a magic. A cell that
truly contains shell magics mid-cell is expected to fail parsing — confirm that
is the cell you think it is before acting.

**Pitfall — a notebook committed to git carries any literal credential in it.**
A key pasted into a cell is visible to anyone the notebook is shared with and
lands in git history permanently. Prefer a secret lookup with the literal only
as a fallback, and tell the user plainly when a literal is written to a tracked
file.
