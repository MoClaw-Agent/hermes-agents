# Serving a VLM OCR service from a free Colab T4

Measured constraints, in the order they bite.

## The tunnel ceiling is the binding constraint

Free tunnels reject a request at **300 s**. A dense legal page through a 4B
vision model runs ~215 s, so *any* retry — degeneracy, 5xx, transport — pushes
the page past the ceiling and the caller sees
`ERR_NGROK_3004 "The server returned an invalid or incomplete HTTP response"`
at exactly 300.4 s. A client timeout of 1800 s cannot see a ceiling it does not
control; align the client timeout below the tunnel or accept the loss.

Identify this from the error *body*, not the status: the tunnel returns its own
HTML page, so a 503 with HTML is the tunnel, while a 503 with JSON is your
service.

**Batch mode is the way out.** Calling the transcribe function in-process means
no HTTP, no tunnel, no ceiling. That only helps if the result reaches the parser
— which needs the cache to be readable, not just writable.

## Hardware facts

- Colab T4 is Turing (sm_75): **no bfloat16**. Pick `float16` explicitly or
  generation degrades.
- **16 GB shared.** The vision tower allocates far faster than the pixel count
  suggests — a 3.87 Mpx page asked for 13.74 GiB in one allocation against
  14.56 GiB total, with ~5 GiB free once the model is resident. Cap pixels well
  below what fits on paper.
- Set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`; long generations
  fragment and the OOM report shows reserved-but-unallocated.
- Cap on **both** sides. A client sending a full-resolution page must not be
  able to take the service down.

## Package reality

- A GGUF repo ships GGUF + a vision projector only; `from_pretrained` cannot read
  it. The projector must be fetched explicitly — the chat handler validates
  `os.path.exists` in `__init__`, before any download runs, so passing a bare
  filename always fails. Weights download fine and the projector silently does
  not, which looks like a weight problem.
- **The projector must match the model's quantisation family.** Mismatched
  projector/weights yield blank output.
- `llama-cpp-python` wheels exist only for older CPython tags. On a newer
  interpreter pip builds from source, and a source build has **no CUDA** — the
  notebook runs, layer-offload is accepted silently, and everything lands on
  CPU. Print the backend's system info and assert CUDA is present; a successful
  import does not mean GPU inference.
- **Prefer the safetensors repo when the runtime already has torch+transformers.**
  No compilation, and the GPU is live on the first cell. Keep the GGUF route only
  as a selectable backend for A/B, not as the default.

## HTTP handler pitfalls for long requests

- Drain the request body on **every** path, including auth failure, and parse it
  during the drain. An undrained body poisons a kept-alive connection and the
  tunnel reports an unframable reply.
- Prefer `HTTP/1.0` when each request is independent: keep-alive framing hazards
  buy nothing.
- Strip query strings before path matching.
- Keep the OpenAI discovery endpoints. A GET-only self-check cannot detect a
  body-drain fault, a transcription exception, or a broken model load — all of
  which pass while every real request fails. Post a real image in the check.

## Notebook hygiene

- Import what each cell uses, or make cells self-contained. Cross-cell imports
  make a re-run of one cell fail with a bare `NameError`, which is the normal
  thing to do when a service needs restarting.
- `from module import name` when you will call it; `import module` binds a
  module and calling it raises `TypeError: 'module' object is not callable`.
- Validate with a static cross-cell dependency check — `scripts/notebook_local_harness.py notebook.ipynb --deps` runs it without executing anything, and `--all` execs every cell into one shared namespace. A fresh namespace per cell cannot see a missing cross-cell dependency, because the defining cell is simply never in scope; that is the whole class of bug the check exists for.
- Remove scaffolding before calling it done, and assert in the harness that it does not return.