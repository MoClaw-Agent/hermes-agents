# Serving a local VLM for OCR (Colab / GPU hosts)

Depth for standing up a Qwen-VL OCR service to replace a CPU-bound local host.
Companion to the `QARI` and `Debugging OCR issues` sections of SKILL.md.

## Prefer the safetensors repo on Colab — it needs no build

| repo | format | loader | build step |
|---|---|---|---|
| `Qwen/Qwen3-VL-4B-Instruct` | safetensors | `transformers.from_pretrained` | none |
| `Qwen/Qwen3-VL-4B-Instruct-GGUF` | GGUF | `llama-cpp-python` | compile |

Colab ships torch+CUDA and `transformers` working out of the box, so the
GGUF route costs a compile for no benefit. Route it through a declared setting
so both paths stay testable:

```python
BACKEND = os.environ.get("QARI_BACKEND", "transformers")
```

Dispatch inside `load_model()` and `transcribe()`; the HTTP service, tunnel and
batch mode are then backend-agnostic.

## An unbounded pixel budget does not just run slow — it OOMs

`QARI_OCR_MAX_PIXELS=0` means *no limit*, and on a 16 GB GPU that is a hard
crash, not a slow run. Every page returns HTTP 500 after the generation window:

```
CUDA out of memory. Tried to allocate 13.74 GiB.
GPU 0 has a total capacity of 14.56 GiB of which 5.16 GiB is free.
Including non-PyTorch memory, this process has 9.40 GiB memory in use.
```

The arithmetic is checkable before the run: a 200 DPI A4 page is
`1654x2339 = 3.87 Mpx`; the model resident in fp16 takes ~9 GB; the vision
tower then asks for the remainder in a single allocation and there is none left.
Render the page, compute `width * height`, and compare it against
`gpu_total - model_resident` **before** launching a corpus.

Budget of record: `1280 * 28 * 28 = 1,003,520 px` (~1600 vision patches, roughly
a quarter of the 200 DPI area). It sits deliberately *above* the `640*28*28`
default because letterform fidelity is the thing being protected — do not
"fix" an OOM by quietly reverting to the old default and losing Arabic
character accuracy.

Enforce the cap on **both** sides: the client, and the service. A service that
trusts its client can still be taken down by a full-resolution page. Raise
explicitly on `0` rather than accepting it and dying at request time.

Set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`. Long generations
fragment the allocator — the failure report above showed 284 MB reserved but
unallocated at the point of failure.

**This qualifies an earlier conclusion.** A CPU-host measurement found full
resolution affordable (~66.6 s/page steady state, versus 228 s at a capped
budget). That is true of a host with no resident model competing for VRAM and
false of a T4. Budget guidance is hardware-specific; never carry a "full
resolution is fine" note across hosts.

## Match the transport to what the endpoint actually serves

A tunnel that serves OpenAI-compatible `/v1` returns **404** on the Ollama
route. Check both the style and the path before blaming the model:

```bash
curl -s -o /dev/null -w '%{http_code}' $BASE/healthz          # 200
curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/api/generate -d '{}'   # 404 on an OpenAI service
```

`QARI_OCR_API_STYLE` must agree with the endpoint, and the base URL must carry
the `/v1` prefix the service actually publishes. Set both together.

## GET-only checks pass while every real request fails

`/healthz` and `/v1/models` exercise `do_GET`. They cannot detect a request-body
fault, a `transcribe()` exception, or a model that never loaded — all three
present as a perfectly healthy service. Probe with a POST that carries a real
image, and read the **body** of the failure, not just the status code:

```python
req = urllib.request.Request(f"{base}/v1/chat/completions", data=body,
                             headers={"Authorization": f"Bearer {API_KEY}",
                                      "Content-Type": "application/json"})
t0 = time.time()
resp = urllib.request.urlopen(req, timeout=900)
```

Probe against **localhost** before opening a tunnel, otherwise a tunnel fault
is indistinguishable from a model fault.

## Cloudflare Tunnel: ngrok Replacement for Long-Running OCR

ngrok's free tier has a ~2 minute timeout for HTTP requests. Vision OCR on a single page can take 5-10 minutes, causing ngrok to drop the connection. The error appears as `ERR_NGROK_3004` or a 503 with an HTML body.

**Cloudflare Tunnel** is a free alternative with no account needed:

```bash
# Install
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb

# Start (no account needed)
cloudflared tunnel --url http://localhost:8888
```

The URL changes on every Colab runtime restart. Update `VISION_OCR_BASE_URL` in `.env` with the new URL.

**Key differences from ngrok:**

| Feature | ngrok (free) | Cloudflare Tunnel |
|---|---|---|
| Timeout | ~2 minutes | 125s (524) |
| URL changes | Every restart | Every restart |
| Account required | No | No |
| Speed | Good | Good |
| Reliability | Good | Better |

**Notebook integration:** Replace `from pyngrok import ngrok` with `subprocess.Popen(['cloudflared', 'tunnel', '--url', f'http://localhost:{PORT}'])` and parse the URL from stdout.

### Cloudflare 524: Proxy Read Timeout (125s)

Cloudflare's free tier enforces a **125-second Proxy Read Timeout**. If the origin (Colab) does not respond within 125s, Cloudflare returns `HTTP 524`. This is NOT configurable on free tier.

A single page of Arabic legal OCR on a T4 can take 30-60s, but with model loading, queueing, or larger documents, it can exceed 125s. The 524 error means Cloudflare connected to the tunnel but the origin did not respond in time.

**Symptom:** `HTTP Error 524` from the client, no output after 3+ minutes.

**Solution: Polling pattern.** Instead of one long POST that blocks until OCR completes:

1. `POST /v1/chat/completions` starts a background thread and returns immediately with a `job_id`
2. Client polls `GET /v1/result/<job_id>` every 5 seconds
3. Each poll is a short request (<1s), well within the 125s limit
4. When OCR finishes, the poll returns `{"status": "done", "result": "..."}`

Server-side implementation:

```python
# In the HTTP handler:
_JOBS = {}
_JOBS_LOCK = threading.Lock()
_JOB_COUNTER = 0

# In do_POST: start background job, return job_id immediately
global _JOB_COUNTER
with _JOBS_LOCK:
    _JOB_COUNTER += 1
    job_id = str(_JOB_COUNTER)
    _JOBS[job_id] = {'status': 'pending'}

def _process():
    try:
        text = transcribe_checked(png)
        with _JOBS_LOCK:
            _JOBS[job_id] = {'status': 'done', 'result': text}
    except Exception as exc:
        with _JOBS_LOCK:
            _JOBS[job_id] = {'status': 'error', 'error': str(exc)}

threading.Thread(target=_process, daemon=True).start()
# Return immediately with job_id

# In do_GET: poll for result
elif path.startswith('/v1/result/'):
    job_id = path.split('/v1/result/')[-1]
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        body, status = _json({'error': 'job not found'}, HTTPStatus.NOT_FOUND)
    elif job['status'] == 'pending':
        body, status = _json({'status': 'pending'})
    elif job['status'] == 'error':
        body, status = _json({'status': 'error', 'error': job['error']})
    else:
        body, status = _json({'status': 'done', 'result': job['result']})
```

Client-side (Mizan vision_pipeline.py):

```python
# After POST, if response contains job_id, poll for result
job_id = result.get('job_id')
if job_id:
    # base_url already ends with /v1, so don't add another /v1
    poll_url = f"{base_url}/result/{job_id}"
    poll_interval = 5  # seconds
    poll_timeout = timeout  # use same timeout for total polling
    poll_start = time.time()
    while time.time() - poll_start < poll_timeout:
        time.sleep(poll_interval)
        poll_request = urllib.request.Request(poll_url, headers=headers, method="GET")
        with urllib.request.urlopen(poll_request, timeout=30) as poll_response:
            poll_result = json.loads(poll_response.read().decode("utf-8"))
        status = poll_result.get('status')
        if status == 'done':
            return poll_result.get('result', '')
        if status == 'error':
            raise RuntimeError(poll_result.get('error', 'unknown error'))
    raise TimeoutError(f"polling timeout after {poll_timeout}s")
```

**Why this works:** Each HTTP request completes in <1s, so Cloudflare's 125s timer is never hit. The polling loop runs client-side and can wait as long as needed.

**Alternative:** Use LocalTunnel (`lt --port 8888`) or Serveo (`ssh -R 80:localhost:8888 serveo.net`) which have no timeout limits.

## ERR_NGROK_3004: the tunnel reports a framing fault, not a model fault

Symptom: every POST returns 503 in ~0.3 s as an HTML page while GET returns 200.

```
ngrok gateway error The server returned an invalid or incomplete HTTP response. (ERR_NGROK_3004)
```

Cause: `protocol_version = "HTTP/1.1"` on `ThreadingHTTPServer` with the request
body left undrained on the early-return paths. An undrained POST body poisons
the kept-alive connection and the tunnel sees an unframable reply. GETs carry
no body, which is exactly why the health check looks fine.

Fix:

- `protocol_version = "HTTP/1.0"` — one request per connection. Batch clients
  open a fresh request per page anyway, so keep-alive buys nothing and only
  adds framing hazards.
- Drain and parse the body **before** auth and before any 404 return, so every
  path sends a complete response. Read it once and reuse the parsed object.

Distinguishing feature: the handler returns **500** with a JSON body on
exception. A 503 carrying an HTML page did not come from your code.

## dtype: T4 is float16

A T4 is Turing (sm_75) and does **not** support bfloat16. Load with
`torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16`, or
generation fails or silently degrades. ~9 GB at fp16 fits a 16 GB T4 with room
for the image budget.

## A module global bound after an early return stays `None` forever

```python
global _torch, _hf, _hf_processor
if _hf is not None:
    return _hf          # startup already populated _hf, so this always fires
import torch             # never reached; _torch stays None for the kernel's life
_torch = torch           # note: `import torch` alone binds only a LOCAL name
```

Symptom is an attribute error on a `None` global at request time
(`'NoneType' object has no attribute 'no_grad'`), long after startup succeeded
and with the model reported loaded. Bind every global **before** the early
return, so load order cannot matter.

## The vision projector is never downloaded for you

`Llama.from_pretrained(repo_id=..., filename=MODEL_FILE)` fetches the weights
and resolves them to a cache path. It does not touch the projector, and the
chat handler validates `os.path.exists(clip_model_path)` in `__init__` — before
any download runs — so passing the bare filename always raises
`ValueError: Clip model path does not exist: mmproj-....gguf`.

Fetch it explicitly:

```python
projector = hf_hub_download(repo_id=MODEL_REPO, filename=MMPROJ_FILE)
handler = Qwen3VLChatHandler(clip_model_path=projector)
```

Derive the projector filename from the weights' quantisation family, and pair
them: `Qwen3VL-4B-Instruct-Q8_0.gguf` with
`mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf`. A mismatched projector yields blank or
garbled output rather than an exception. When the filename is wrong, list the
`mmproj` entries the repo actually has in the error — the bare
"path does not exist" sends people looking at the wrong problem.

Prefer `Qwen3VLChatHandler` and fall back to `Qwen25VLChatHandler` so the
notebook is not pinned to whichever handler a given `llama-cpp-python` build
happens to expose.

## Dependency hygiene

- Cap `huggingface_hub<2.0`. An unbounded `>=0.25` resolves to 2.x on a fresh
  image and conflicts with gradio, transformers, datasets, tokenizers,
  diffusers and gradio-client, all of which require `<2.0`.
- Do not install the compile-heavy backend in a general `pip install -U` line
  before the CUDA-aware branch. On an interpreter with no matching wheel that
  compiles once, uselessly, then the CUDA path rebuilds it again. Check what
  the wheel index actually publishes for the runtime's interpreter tag —
  a missing tag makes the wheel path unreachable and every run fall back to a
  source build that silently has no CUDA.
- Do not `-U` a package the runtime already ships working. Upgrading Pillow in
  place leaves modules from two releases side by side and fails at import with
  `ImportError: cannot import name '_Ink' from 'PIL._typing'`. Import it inside
  a `try` and force a clean reinstall only on failure.
- Removing a package because nothing imports it is unsafe:
  `transformers.from_pretrained` probes `importlib.metadata.version` for
  optional accelerators, so an "unused" library can still be load-time required.

## Batch mode that survives a dropped session

A long corpus run will be interrupted by idle disconnects and session caps.
The design that holds up:

- write `<out>/<pdf-stem>/page_<n>.txt` as each page completes;
- on start, scan for existing `page_*.txt` and skip those pages, so a resume
  continues instead of restarting;
- write an **empty file for a page that failed** its retry budget. Without
  this, a permanently-failing page is retried on every resume and the run never
  finishes. Empty files must be filtered out before use.
- point `OUT_DIR` at mounted Drive when the output must outlive the runtime.

Verify the resume path with a stubbed transcription function before pointing it
at a real corpus: run twice and assert the second run performs zero new calls.

## Common failure modes when deploying the notebook

These are the issues that have actually occurred when deploying the Colab notebook. Check them in order:

1. **`_JOBS_LOCK` not defined.** The polling code references `_JOBS_LOCK` but it is never created. The notebook will start fine but every POST returns 500 with `NameError: name '_JOBS_LOCK' is not defined`. Fix: add `_JOBS_LOCK = threading.Lock()` next to `_JOBS = {}`.

2. **Polling URL has double `/v1/v1/`.** If `base_url` ends with `/v1`, then `f"{base_url}/v1/result/{job_id}"` creates `/v1/v1/result/...`. The server returns 404. Fix: use `f"{base_url}/result/{job_id}"`.

3. **Model name mismatch.** `ollama pull qwen3vl:8b` downloads a model named `qwen3vl:8b`, but the transcribe function sends `'model': 'hf.co/Qwen/Qwen3-VL-8B-Instruct-GGUF:Q8_0'`. Ollama returns 400 because the model name is unknown. Fix: use the same name in both places, or use `MODEL_ID`.

4. **Wrong Ollama API endpoint.** Vision models use `/api/chat` with `messages` format, not `/api/generate` with `prompt`/`images`. The `/api/generate` endpoint returns 400 for vision models. Fix: use `/api/chat` with `messages` array.

5. **`ollama pull` before `ollama serve`.** The install cell runs `ollama pull` before starting the server. The pull fails with "could not connect to ollama server". Fix: start the server first, then pull.

6. **`images` field expects raw base64, not data URLs.** Ollama expects `'images': [base64_string]`, not `'images': ['data:image/png;base64,...']`. Fix: send raw base64.

7. **Health check reports `model_loaded: false` for Ollama.** The health check only looks at `_llm` and `_hf`, but the Ollama backend does not set either. Fix: check if the Ollama server is reachable instead.

8. **`loaded` check in cell 7 fails for Ollama.** The `loaded` check only looks at `_llm` and `_hf`, but `load_model()` returns `True` for Ollama. Fix: capture the return value of `load_model()`.

9. **Error handler does not include traceback.** The 500 response only includes the error message, not the traceback. Fix: include `traceback.format_exc()` in the response body.

10. **Parser does not log response body on 500.** The parser log only shows "HTTP Error 500" without the actual error. Fix: read and log the response body.

## Cell order is part of the contract

A cell that probes the service must come *after* the cell that starts it. Put
the probe first and running the notebook top to bottom fails with
`Connection refused` on a perfectly healthy setup — the same class of failure
as a missing import, and the same reason a static review misses it.

When a test or probe cell is removed, find **every** instance. Two variants of
the same smoke cell survived one removal pass here, because the rewrite had
added a second cell rather than replacing the first. Search by content, not by
the description you remember, and assert the marker is gone from all cells.

## A production notebook carries no test scaffolding

Before the notebook is called production-shaped, remove: placeholder credential
fallbacks (a key literal that silently leaves auth disabled is worse than a
refusal — hard-fail instead), commented usage prompts, and probe cells. Assert
their absence in the harness so scaffolding cannot quietly return, and assert
the production capabilities are still present so that removal cannot quietly
delete the service itself.

## Harness the whole notebook, not one cell

Extracting and driving a single cell is not enough; it is what let the real
defect through. The harness that works executes **every cell in one shared
namespace** and covers four things a per-cell check cannot:

1. **Static cross-cell dependency check.** Every free name a cell reads must be
   bound by an earlier cell, a local binding, or a builtin. This is the only
   check that catches execution-order faults before the operator does.
2. **Execute every cell in order**, stubbing only Colab-only modules
   (`google.colab`, `pyngrok`) and the model. Skip teardown cells explicitly —
   running them shuts down the service the later checks need.
3. **POST against the notebook's own server** — small image, repeat POST
   (proving the body drained), page-sized, unauthenticated, malformed, plus the
   GET endpoints.
4. **Batch resume** — pass one, resume with zero new calls, and the failure path.

Keep it in the repo and re-run it after every notebook edit; it is the gate, not
a one-off script.

### A fake that stands in for the thing under test hides its defect

This is the failure the harness itself introduced. The test double set the very
global the code was supposed to bind, so the branch under test never executed
and a real `None` global shipped. **Set the global to `None` and let the code
bind it.** Generalise: every substitute must be placed *below* the assignment
you are testing, never on top of it.

A green harness therefore proves only what the harness actually executed. When
a run later fails in a way the harness said was impossible, suspect the harness
first — re-run it with the substitute removed before touching the service.