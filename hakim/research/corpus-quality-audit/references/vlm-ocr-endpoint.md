# VLM OCR Endpoint

Standing up a vision-language-model transcription service that a corpus pipeline
consumes, and the ways it silently destroys the corpus.

Everything here fails *quietly* — a 200 response, a written file, and no signal
to the operator. That is what makes them worth pre-empting rather than
debugging.

## 1. The pixel budget is not optional

A vision tower allocates super-linearly in image area. One A4 page at 200 DPI
is ~3.9 Mpx and a 4B-class VLM tried to allocate **13.74 GiB** for it on a
14.56 GiB card — fatal, every request, while the model sat resident using 9 GB.

`MAX_PIXELS = 0` reads like "unlimited" and means exactly that. On any GPU you
do not exclusively own, it is a guaranteed OOM.

- Compute the budget from what fits, not from what looks sharp: the loader
  already holds the weights, so the headroom is *total − resident − other
  tenants*. A shared card shows less free memory than you expect.
- Budgets are conventionally expressed in patches: `N * 28 * 28`. `640*28*28`
  (~0.5 Mpx) and `1280*28*28` (~1.0 Mpx) are the useful rungs; pick from the
  measured letterform error at each, do not assume more is better.
- **Cap on both sides.** The client that renders pages and the service that
  receives them each enforce a budget, and the service raises on `0` rather
  than accepting it. A client-side cap alone means any other caller can still
  take the service down; a server-side cap alone means the client wastes
  bandwidth uploading a page that will be downscaled anyway.
- Set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`. Long generations
  fragment the cache, and the OOM report typically shows hundreds of MB
  reserved-but-unallocated at the point of failure.
- **Resolution and legibility trade against each other.** Too small and the
  model cannot resolve the glyphs — which does not produce an error, it
  produces the degeneration in §2. Treat "the loop keeps coming back" as a
  resolution symptom before treating it as a decoding symptom.

## 2. Validate the output, not just its presence

A greedy VLM decoding a dense page can fall into a repetition loop and return
it as a successful transcription: 4336 characters, 3 distinct lines, 15 of
them identical, HTTP 200. A corpus run stores that as text. It is worse than a
failure, because a failure is visible and this is not.

- Compute a **degeneracy ratio** — the share of output lines that are not
  repeats — and refuse to return anything below a threshold (0.6 catches the
  measured case at 0.07 while passing genuine multi-line text at 1.00).
- On degeneracy, retry once at a lower pixel budget (§1 — too-small-to-read is
  the other common cause). If the retry is also degenerate, **raise**: the
  page is recorded lost. Do not return the best non-degenerate-looking sample;
  "looks like text" is the exact failure you are guarding against.
- Size the threshold to the domain. Legal text legitimately repeats
  (`من هذا القانون`, standing formulas, repeated article headers), so a ratio
  that would condemn ordinary boilerplate will make you reject good pages.

This is the same discipline as "partial page loss must be visible", applied to
content rather than coverage: a short document and a looped document are both
plausible-looking artifacts that are wrong.

### 2a. The guard's scope must match the caller's error handling

A per-page guard is only useful if the caller treats the failure per page. The
raise is correct and the loss still happens: measured, the degeneracy `raise`
was outside the caller's caught exception tuple, propagated out of the per-page
loop, and the document-level extractor discarded the whole 207-page pass —
falling back to the weaker engine and turning 612 articles into 222.

- **Per-item failure is recorded, not fatal.** A stage that iterates pages wraps
the per-item call in its own `try/except`, appends the page number to a
failed list, and returns the partial result. Otherwise one looped page silently
re-OCRs an entire code with the wrong engine.
- **Assert the exception tuple covers what the callee raises.** Grep the callee
for `raise` rather than assuming; a raised type absent from the `except` tuple
is invisible in review and fatal at scale.
- **Do not retry a deterministic failure.** Degeneracy is a property of the
page's pixels; the endpoint already retried internally at a second pixel budget,
so a caller-level retry just spends the budget of a 200-page document on a page
that cannot change. Fail it on the first degenerate verdict.
- **Granularity is not the lever.** Splitting the input (chunking a large PDF)
does not help when the guard is per-page — the failing page remains one page
inside one chunk with the same verdict. Read the guard's scope before changing
the input's shape.

## 3. Decoding: penalise repetition, do not ban n-grams

- `repetition_penalty` (≈1.05) is the right lever for a loop.
- `no_repeat_ngram_size` is the wrong lever for legal and statutory text.
  Phrases like `من هذا القانون التنظيمي` recur legitimately across dozens of
  articles; banning n-grams corrupts exactly the citations the corpus exists to
  preserve.

## 4. HTTP framing: an undrained request body breaks every POST

`BaseHTTPRequestHandler` with `protocol_version = "HTTP/1.1"` on a
`ThreadingHTTPServer`, where any early-return path responds without first
reading the request body, produces an unframable reply. Through a tunnel it
surfaces as `ERR_NGROK_3004 — "The server returned an invalid or incomplete
HTTP response"`, HTTP 503 in ~0.3 s, as an HTML page rather than JSON.

- **GETs carry no body, so a GET-only check passes** while every real POST
  fails. Never validate a request-serving endpoint with GETs alone.
- Drain the body at the top of the handler, before auth and before every 404
  and error return, and parse it there rather than re-reading `rfile`.
- `HTTP/1.0` is the cheap fix when the client opens a fresh connection per
  request anyway; it removes keep-alive framing hazards entirely.
- Check `Content-Length` is actually set before blaming the tunnel — a
  correct-looking response can still be unframable.
- Report which pass built what: the accept / reject-with-reason / never-ran
  distinction matters most here, where a GET returning 200 and a POST returning
  503 have completely different causes.

## 5. Know the transport's request-duration ceiling before designing the route

A free tunnel caps a single request at roughly 300 s. A dense legal page measured
**215 s** to transcribe — leaving room for exactly zero retries. Add any retry
(5xx, degeneracy, transport) and the request is cut off, which surfaces as the
same `ERR_NGROK_3004` seen in §4 and reads like a server bug when it is a
transport limit.

The ceiling is not visible from the client and is not raised by any amount of
client-side timeout configuration. Check it before designing for per-page HTTP
at all:

- **Measure one page's wall time on the real hardware first**, then compare
  against the ceiling before committing to a corpus.
- **If the margin is thin, per-page HTTP is the wrong route.** Provide a
  batch mode that calls the transcription function **in-process** — no HTTP, no
  auth, no tunnel — and writes one file per page as each completes, so an
  interrupted run resumes. Batch is not a convenience feature here; it is the
  only route with no duration ceiling.
- **Make the batch output consumable by the parser directly.** Emit the
  consumer's own cache format (mode/source/pages) alongside the per-page text.
  A batch run whose output needs manual reformatting will not get used, and the
  parser will silently re-run inference it was supposed to read.
- The durable shape is **OCR once, parse later**: the vision pass writes a cache
  the parse reads back with zero inference calls. This also makes a stalled
  backend a non-event for parsing, and makes the parse reproducible and
  auditable — which is the whole point when the corpus is legal text.

## 6. On a notebook runtime, prefer the pre-installed stack over a compiled one

Requesting the GGUF build of a model forces compilation when the pre-installed
`transformers` path needs none. Colab ships torch+CUDA and transformers, both
working, so the safetensors repo loads on the first cell while the GGUF repo
needs a build that may not even be CUDA-capable.

- Check which distributions exist for the runtime's **Python version** before
  choosing a route. Wheels are published per CPython tag; a runtime on a newer
  interpreter than the wheel index covers falls through to a source build, which
  carries no CUDA and runs on CPU while accepting every GPU argument.
- Verify the loaded build, do not assume it: read the library's system-info
  string and check for the accelerator, and treat a source-build line in the
  install output as suspect rather than successful.
- A source build silently CPU-executing is the worst outcome in this document:
  it looks like a working run, every argument is accepted, and throughput is
  indistinguishable from "GPU is slow".
- When a CUDA wheel is unavailable and a build is unavoidable, pin the compute
  architecture for the actual device — an unset value compiles every architecture
  it can detect, which is the difference between a ten-minute build and an hour.
- Keep the compiled route behind a selectable setting rather than deleting it,
  so backend and quantisation can still be compared.
- **dtype is a device property, not a preference.** A pre-Turing card does not
  support bfloat16; selecting it fails or silently degrades. Derive it from the
  loaded device.

## 7. A long-running service grows resident memory unless every buffer is bounded

A notebook-hosted OCR service that runs for a whole corpus grows RAM
monotonically. Two independent causes, both in the service, both invisible
until the kernel dies mid-run:

- **Results kept forever.** A polling design (`POST` starts a job, `GET`
  collects it) that stores each job's full transcription in a module-level dict
  and never deletes it retains one whole page of text per page, for the life of
  the process. Two fixes, both needed: **drop the result the moment the client
  reads it** (delete the entry in the collector, so a second poll reads "not
  found"), and **cap the dict** so a client that never polls cannot leak either
  (`_JOBS_MAX`, evicting oldest *completed* entries; never evict a pending one,
  the client may still be polling it). Drop-on-read alone leaks if the client
  never collects; the cap alone retains every result until eviction.
- **Unset inference-context bounds.** A request that omits the KV-cache size
  makes the backend allocate against the model's advertised context — which for
  these vision models is 262k tokens, not the few hundred a downscaled page
  needs. Send the context size explicitly (a page at the §1 pixel budget is
  ~320–1300 vision tokens, so 8192 is ample) and set the model-keep-alive
  explicitly: long enough to avoid a reload between pages of one run, or `0` to
  unload and hand the memory back between batches. **The advertised context is
  the dominant memory driver and it is not visible from the client** — a
  request that looks small still allocates a large cache.

Also bound the concurrency-shaped buffers: `ThreadingHTTPServer` spawns a
handler thread per request and a polling design spawns a second worker per job,
so each in-flight request pins its decoded image until it finishes — fine at low
concurrency, a pile-up under a burst. And a module-level "last request body"
retains one base64 page (~1–3 MB); bounded to one, so minor, but it is the same
class.

**Separate the two routes when diagnosing this.** A batch mode that calls the
transcription function in-process (§5) has no HTTP and no job dict, so it cannot
leak the first way — if RAM grows only in service mode, the job store is the
cause; if it grows in both, look at the backend context bound. Distinguish
"the model lives in VRAM" from "the service process grew": an mmap'd model,
image preprocessing and backend buffers all grow the *system* RAM even when the
GPU holds the weights.

## 8. Make the health endpoint prove the model is loaded

`/healthz` returning `{"status":"ok"}` while `model_loaded` is false, or while
the GPU is busy, is a health check that cannot fail. Include backend, model id,
and whether the model is actually resident. Clients will trust it.

### 8a. "Lists the model" is not "loaded the model"

The startup path is where this bites hardest. A loader that reaches the backend
with a model-*listing* call (`GET /api/tags`) and returns `True` has verified
nothing: listing reads the disk, it does not put weights in memory. The startup
cell then prints `Model loaded: True` with an empty VRAM, and the **first real
page pays the whole cold load inside its own request** — measured at 41 s for an
8B Q8 build, spent inside a per-page budget sized for inference.

- Warm with a **real generate**, not a listing call: one trivial prompt with
  `num_predict: 1`. That forces the load where you can see it, at startup.
- **Warm with the same parameters the requests will use.** The backend keys a
  loaded instance on its context size and keep-alive; warming with different
  values just forces a reload on the first page. Send the same `num_ctx` and
  `keep_alive` the real requests send.
- Skip the warm-up when the model is already resident — query the running-model
  endpoint (`GET /api/ps`) first, so a re-run of the cell is a no-op rather than
  a reload.
- On failure, name the models that *are* present and the exact pull command.
  A warm-up that silently proceeds against a missing tag reproduces the same
  first-request stall it was added to prevent.
- **`ollama ps` being empty right after a pull is correct, not a fault.**
  Loading is lazy and happens on first use; `ollama list` shows the disk state
  and `ollama ps` shows memory. Do not diagnose an empty `ps` after install as
  a failed pull — check `list`.
- The runner column reading `llamacpp` is the backend's own inference engine,
  not a separate compiled client. It is expected and says nothing about which
  route the caller chose.

### 8b. The `100% GPU` label is a claim about assignment, not execution

A running-model report that says `100% GPU` means every layer was *assigned* to
the device. It does not mean the work runs there. Read the memory split —
`size_vram` against `size` — for the truth.

Measured: a report showing `100% GPU` alongside `size=14.71GB,
size_vram=0.34GB` was a model executing **2% on GPU and 98% on CPU**. Text
returned in ~2 s (tolerable) while a single image page took **122 s**, because
the vision encoder — the expensive half — was on CPU. That is the signature to
look for when the same model is fast on one host and glacial on another: compare
`size_vram` to `size` on both, do not compare the labels.

- Partial offload is usually free-VRAM pressure at load time, not a bad model.
- The fix is on the host: free VRAM, request full offload explicitly, or drop to
a smaller quant or parameter class that fits.
- **Isolate text from image before theorising.** A text-only request that
  returns fast proves the model and server are healthy and localises the fault
  to the vision path; a text-only request that also hangs means the backend, not
  the modality. Two calls, opposite conclusions — make them first.

## 9. A `global` declared but bound on only one path stays `None` forever

The service-side half of the `global _torch` defect recorded in
`artifact-execution-harness.md`: the loader declared the global and bound it
via a local `import` placed *after* an early return, so a service that starts
fine returns 500 on every request.

- Bind module globals **above** every early return, not on the slow path only.
  A `global` statement declares intent; it does not assign.
- When a warmed service fails only on requests and never at startup, suspect a
  global bound on the load path but read on the request path.

## 10. Score the output form the model actually emits

The same page can be transcribed as `المادة 109` or, in RTL visual order, as
`109 المادة`. Both are correct; a scorer written for one reports the other as a
total miss — it returned `MISSING all 6` on output that contained every number.
Widen the pattern to both orders before drawing a conclusion, and print the
matched spans rather than only a count, so the mismatch is visible rather than
inferred. This is the endpoint-side twin of the parser-side RTL handling: the
server may hand the consumer a correct number in an order the consumer has
learned to recognise, and a naive check will call that a failure of the model.

The failure modes compound: an uncapped page OOMs; a capped-but-still-too small
page loops; a looped page is stored as content; and a page that finally succeeds
is cut off by a transport that cannot hold a request open long enough. Debug
them in that order, and confirm the pixel budget is set *before* investigating
decoding — a loop at an uncapped-but-lucky resolution is a resolution problem
wearing a decoding problem's clothes.

The last two are a capacity problem wearing a transport problem's clothes: once
content is clean, the next failure is that the route cannot deliver it. Measure
one page end-to-end on the real route before scaling out.

See also `references/artifact-execution-harness.md` for executing the service
artifact locally, and `references/ocr-model-selection.md` for choosing and
scoring the model itself.