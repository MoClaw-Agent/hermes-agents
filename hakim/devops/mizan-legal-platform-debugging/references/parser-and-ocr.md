# Mizan — Parser and OCR how-to

Extracted verbatim from `SKILL.md`.  Running a parse batch, reading its
output, the article-loss probe, and the OCR/QARI plumbing.  The pitfalls
that go with this material are in `references/pitfalls.md`.

## Index

- Running a Parser Batch
- Article-Loss Probe (scripts/article_loss_probe.py)
- JuriThèque Scraping
- Debugging OCR issues
- Editing a Colab Notebook or Any JSON-Sourced Code Cell
- QARI Endpoint Transport: Ollama-Native by Default, OpenAI-Compatible Opt-In
- Confirming QARI Is Actually Running During a Parse

---

## Running a Parser Batch

**Always invoke a parser through its guarded module entry point, never a throwaway runner script.**

```bash
MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \
  venv/bin/python -m fetching.<provider>.<provider>_parser --lang ar --retry-failed
```

Pitfall: an ad-hoc runner that calls `run()` at module top level (no `if __name__ == "__main__":` guard) is a silent no-op. `run()` does `mp.set_start_method("spawn", force=True)`, so every pool worker re-imports the runner as `__main__` and re-invokes `run()`, recursing instead of parsing.

**Detection — the log line repeats N times and nothing is written:**
```bash
grep -c 'Found .* PDFs to process' data/logs/<provider>_parser.log
```
A healthy run logs that line once. Fifty repeats in a minute with zero JSONs written is the spawn-recursion signature, not a slow parse. Check the count BEFORE assuming a batch is progressing.

**Smoke-test one file before a batch.** Use `--file <path> --lang <lang>`; it exercises model load, extraction, and structure build in ~2 min. A 149-file batch is a bad way to discover the entry point is wrong.

`--retry-failed` re-processes files the state file marks failed. State lives in `data/logs/<provider>_parser_state.json` and is the sole resume authority; the on-disk JSON is only a fallback. Confirm the state file exists — a missing one means a previous run never got far enough to write it.

### Never diagnose a batch as stalled from the progress bar

**A frozen tqdm counter means the bar is not refreshing, not that the work stopped.** tqdm is constructed with `mininterval=2.0`, so its displayed position lags the real work and can sit unchanged for minutes while a 90+ page file is being processed. Killing a parse on that evidence destroys a healthy run: the worker dies mid-file and the only trace left is a `BrokenPipeError` from the pool and a leaked-semaphore warning at shutdown — which then *looks* like a parser fault and sends you debugging the wrong thing.

Judge liveness from the per-file completion lines, which are written synchronously as each file finishes:

```bash
grep -a '\[OK\]' data/logs/<provider>_parser.log | tail -5
# [<OK>] <file> | <pages>p | <arts> arts | <mode> | <secs>s
```

A run is genuinely stuck only when the last `[OK]` timestamp is older than the slowest plausible per-file time. Budget from the observed per-file seconds, not from tqdm's ETA — a large scanned code on CPU legitimately runs 150-200 s, and three of those back to back is normal, not a hang.

If you do kill a parse, say so explicitly in the report: the resulting `BrokenPipeError` / `resource_tracker` warnings are artifacts of the kill, not findings.

## Article-Loss Probe (scripts/article_loss_probe.py)

Splits "articles missing" into detection failure vs dedup discard, names the dropped lines, and screens for digit-CMap corruption. Run it before proposing a parser fix:

```bash
MIZAN_HOME=/home/mohammed/Mizan PYTHONPATH=/home/mohammed/Mizan \\
  venv/bin/python scripts/article_loss_probe.py data/corpus/ism/raw/ar/<domain>/<n>.pdf

# sweep an already-parsed directory, one row per JSON
... venv/bin/python scripts/article_loss_probe.py --json-dir data/corpus/ism/json/ar
```

A SUSPECT verdict means the numbers may be *wrong*, not merely missing — confirm with `scripts/digit_cmap_verify.py` before touching extraction code.

## JuriThèque Scraping

Discovery checklist, scraper architecture, folder layout, metadata fields, run
commands and sitemap namespacing live in the `juritheque-scraper` skill.
Converter output is re-parsed here via
`python -m fetching.juritheque.juritheque_parser`.

## Debugging OCR issues

When a parse looks wrong and you suspect OCR:

1. **Read `extraction_mode` from the parsed JSON first.** This tells you which backend produced the text — `native`, `vl` (PaddleOCR-VL), `docling`, `ocr` (PP-OCRv5), or `ocr_forced`. There is no mode that says "qari". The extraction pipeline (`fetching/pipeline_base/extraction.py`) routes through PaddleOCR-VL / PP-OCRv5 / Docling / fitz and has **no Qari path**. If `extraction_mode` is any of those, Qari was never in the running for this parse.

2. **Confirm which OCR flags were active at parse time.** `ADALA_VISION_OCR_ENABLED`, `ADALA_QARI_OCR_ENABLED`, `OCR_ENABLED`, `ADALA_OCR_BACKEND`, `ADALA_FORCE_OCR`. Note that `ADALA_FORCE_OCR` is a **dead setting** — it is not read anywhere in the codebase. Setting it does nothing.

3. **Understand the two independent OCR gates.** Qari is wired into **one place only**: the ADALA parser's vision rescue gate in `fetching/adala/parser/pipeline.py` (the `if vision_requested and not native_usable:` block around line 791). That gate is reached from `extract_vision_pages()`, which is called **after** the extraction pipeline has already produced text. The gate tests:
   - `native_usable = _native_structure_is_sufficient(structure_pages) and not _native_text_corrupt(structure_pages)`
   - If the extraction pipeline already produced clean text with article headers, `native_usable` is `True` and the vision/Qari block is **never entered** — even with both `ADALA_VISION_OCR_ENABLED=true` and `ADALA_QARI_OCR_ENABLED=true`.
   - Qari also requires `language != "fr"`; French input skips the vision path entirely.

4. **Qari only runs when extracted text is still corrupt.** The practical trigger for Qari is: the extraction pipeline's OCR (PP-OCRv5 / PaddleOCR-VL / Docling) produced text that `_native_text_corrupt` (CMap corruption) or `_native_structure_is_sufficient` (no article headers, <200 chars) flags as unusable. Then `extract_vision_pages` → `_extract_qari_pages` runs, and Qari transcribes rendered page images through the configured `QARI_OCR_BASE_URL`.

5. **Diagnose why Qari was skipped by reading the gate values directly.** For a given PDF, run the gate-probe inline (use `venv/bin/python3`; the Hermes kernel python does not have `fitz`):
   ```bash
   /home/mohammed/Mizan/venv/bin/python3 -c "
   import fitz
   from fetching.pipeline_base.pdf_quality import is_arabic_cmap_corrupt, is_garbled, is_reversed_arabic
   from fetching.adala.parser.pipeline import _native_structure_is_sufficient, _native_text_corrupt
   from core.settings import settings

   pdf = 'path/to/file.pdf'
   doc = fitz.open(pdf)
   pages = [doc[i].get_text() for i in range(len(doc))]
   doc.close()
   print('cmap_corrupt:', is_arabic_cmap_corrupt(pages))
   print('is_garbled:', is_garbled(pages))
   print('is_reversed:', is_reversed_arabic(pages))
   print('native_usable:', _native_structure_is_sufficient(pages) and not _native_text_corrupt(pages))
   print('qari_enabled:', getattr(settings, 'ADALA_QARI_OCR_ENABLED', False))
   "
   ```
   If `native_usable` is `True`, Qari is skipped by design. If `qari_enabled` is `False`, the flag isn't set. If the PDF is French (`language == "fr"`), the vision path is closed regardless.

6. **If Qari was supposed to run but didn't, check for silent fallback.** `_extract_qari_pages` returns `None` (and falls through to the layout-model path) on: PDF open failure, Qari API error, timeout, or empty/whitespace response. Search `data/logs/adala_parser.log` for `[vision_pipeline] Qari API request failed` or `[vision_pipeline] Qari returned no page text`.

7. **Qari lives outside the extraction pipeline.** If you want Qari to be a real OCR backend choice during extraction (not just a post-OCR rescue), the routing needs to be added to `fetching/pipeline_base/extraction.py` — currently no extraction code path calls `_extract_qari_pages`. The ADALA parser's vision gate is the only caller.

## Editing a Colab Notebook or Any JSON-Sourced Code Cell

Notebooks are JSON, so string surgery misses anchors and lands in the wrong cell. **Assert every anchor** before replacing, and **read the rendered cell back** — a clean-looking patch can place a statement above the definition it depends on, which only fails at runtime. Never use the string-patch tool on a `.ipynb`; it writes unparseable JSON. Load with `json`, edit **whole lines** (a partial multi-line substring orphans continuation lines into `unexpected indent`), dump, re-load to prove it parses, then `ast.parse` each code cell. Strip magics at **column 0 only** — `l.strip().startswith("%")` also eats an indented operator continuation. A cell must import what it uses, or it fails with a bare `NameError` when re-run alone. An edited notebook must be **restarted** before re-testing. **Never hand over unexecuted code**: execute every cell in one shared namespace, statically check each cell's free names are bound earlier, and POST against its own server — a single-cell harness misses execution-order faults. Keep it as a repo gate. **A test double standing in for the thing under test hides its defect** (set the global to `None`, let the code bind it); when a run fails where the harness called it impossible, suspect the harness. **Cell order is a contract**: a probe cell must follow the cell that starts the service. **Removing a test cell means removing every instance** — search by marker. See `references/colab-vlm-ocr-serving.md`.

## QARI Endpoint Transport: Ollama-Native by Default, OpenAI-Compatible Opt-In

The operator's Qari server is Ollama, not an OpenAI-compatible proxy. On that host:
- `/api/generate` — works (prompt + images base64 payload)
- `/api/chat` — also works, same format
- `/chat/completions` — **returns 404**

So the client defaults to the Ollama-native shape: POST `{base}/api/generate` with `{"model", "prompt", "images": [b64], "stream": false, "options": {...}}`, and reads `result["response"]`.

A second transport exists for deployments that expose an OpenAI chat-completions facade — POST `{base}/chat/completions` with `messages[]` carrying a `data:image/png;base64,...` block, and read `choices[0].message.content`. It is **opt-in via `QARI_OCR_API_STYLE=openai`**, and requires a `/v1` base URL. Ollama remains the default so existing deployments are untouched.

Both shapes are parsed by `_qari_response_text`, which prefers the Ollama `response` key and falls back to `choices`.

`ADALA_QARI_OCR_ENABLED` is the master gate on `_qari_enabled()`. A correct URL, model, style and key with that switch left off produce a configuration that looks complete and calls nothing — verify the gate opens before trusting a hand-edited `.env`. See `references/qari_ocr.md` for the remote-service debug deck: proving a foreign service is alive with a deliberately-malformed request, making a threaded server echo its traceback, and the "two backends fail identically → suspect the checkpoint" rule.

**Detection for the wrong transport**: `HTTP Error 404: Not Found` on every page while `curl` to the same host with `/api/generate` works means the OpenAI path was selected against an Ollama server — set `QARI_OCR_API_STYLE=ollama`. Conversely, if `QARI_OCR_API_STYLE=openai` and the base URL lacks the `/v1` prefix, the client posts to `{base}/chat/completions` where the facade expects `{base}/v1/chat/completions`.

**When evaluating a swap to a chat-completions facade, compare the model, not just the API.** A Colab-served Qari notebook may pin an older, smaller checkpoint than the local Ollama instance; switching transports then silently downgrades OCR quality on exactly the degraded files where it matters most. Check `QARI_OCR_MODEL` on both sides before recommending the move.

## Confirming QARI Is Actually Running During a Parse

A parse process can appear stuck with no output for hours while QARI processes pages one by one. `ss -tnp | grep <qari_port> | grep <parse_pid>` shows whether a request is **in flight** — an ESTABLISHED line means a request is open, nothing more.

**An open socket, non-zero CPU, and a responsive `/api/tags` are NOT evidence that Qari is succeeding.** They are consistent with a request that has been failing on every attempt for hours. A run can look perfectly alive while producing zero output, because `_qari_transcribe_png` catches `HTTPError`, logs a **WARNING**, returns `""`, and falls through to the Docling/PP-OCRv5 route — so every failure still produces a parse, just a worse one.

**The only liveness evidence is the log.** Grep the failure counters directly and read their timestamps:

```bash
grep -ac 'Qari API request failed' data/logs/<provider>_parser.log
grep -a 'Qari API request failed' data/logs/<provider>_parser.log | tail -6
```

Consecutive failures ~50 min apart with no new `[OK]` line between them is a hard 500, not slow inference. Confirm against the host directly before reporting anything about Qari's state:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://<qari_host>:<port>/api/tags   # 200 = server up
curl -s http://<qari_host>:<port>/api/ps                                     # is the model loaded?
```

`/api/tags` and `/api/ps` both healthy while generation 500s is **not a diagnosis** — it is a health check that came back well on a run that still failed. Health endpoints prove the process is up, nothing more. Do not conclude OOM, a bad checkpoint, or a host-side crash from it; a transient host fault clears on its own and leaves you having recommended *against* a host that was working all along. Probe a text-only generate and an image generate separately and **read the response body** — Ollama returns the real exception inside a 500 where a proxy returns a generic page, and discarding the body throws the diagnosis away. Read `prompt_eval_count` / `prompt_eval_duration` / `load_duration` on success: they turn "slow" into a number, and they are what exposes a client-side pixel-budget problem masquerading as slow hardware. See `references/qari_ocr.md`.

**Separate a proxy/tunnel failure from a backend failure before blaming the model.** Fast (sub-second), identical status on *every* path including a bare `GET /`, and a body that is the proxy's own error page means nothing is behind the public URL — restarting the server cell orphans the old URL and prints a new one. Slow, 500 only on the generation route, other routes healthy, body naming an exception means real inference failure.

When a remote dependency is failing this way, disable the path (`QARI_OCR_ENABLED=false`, `ADALA_QARI_OCR_ENABLED=false`) so the batch completes via the fallback, rather than paying the full remote timeout per page and then redoing the work through OCR. See `references/qari_ocr.md` for the full verification deck: model-name resolution, API-key interaction pattern, gate logic, `num_ctx` sizing, stale bytecode, `extraction_mode` semantics, and dead-settings list.

The vision/OCR pitfalls — the context budget, the digit-font corruption gates, the stale-bytecode trap, the GPU-vs-CPU cost basis, the PaddleOCR fallback crash, the `extraction_mode` mapping, the client pixel budget, and the dead `ADALA_FORCE_OCR` flag: `references/ocr-vision-pipeline.md`.

