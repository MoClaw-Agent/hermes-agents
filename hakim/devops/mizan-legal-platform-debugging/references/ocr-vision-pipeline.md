# OCR / Vision Pipeline

Topic depth for the vision/OCR side of the parser: the context budget, the
corruption gates, the fallbacks and their failure modes, and the cost
measurements. The always-on rules stay in SKILL.md.

## Pitfall: num_ctx Must Fit Page Images

For 150 DPI Arabic PDF page renders, the vision model needs a context window large enough to hold the image tokens. The default `num_ctx = max_tokens + 2048` (typically 6144) is too small — the model either hangs or returns empty because the image exceeds the context budget. The `_response_done` flag fires prematurely and the response is truncated.

**Detection**: QARI requests show no HTTP error but return empty or very short responses, and each request takes several minutes before completing or timing out.

**Fix**: Set `num_ctx` to at least 16384 for 150 DPI Arabic pages. Test at lower DPI (100) if inference speed is a concern, but verify OCR quality is still acceptable against the fixture. The `_qari_transcribe_png` timeout should also be raised to match (e.g. 1800s) so a single page has time to complete.

## Pitfall: Corruption Gates Are Blind to the Digit Font

`is_arabic_cmap_corrupt`, `is_garbled`, and `is_reversed_arabic` in `fetching/pipeline_base/pdf_quality.py` all return **False** on a file whose every article number is wrong. They inspect the Arabic *text*, and the Arabic words are fine — the break is in the embedded digit font's ToUnicode CMap.

**This is why a file parses to `extraction_mode: native` with full confidence while its numbers are garbage.** The parser had no signal to distrust the layer, and `native_usable` was True, so the vision/OCR rescue path was never entered. Treat a clean gate result as "no *text* corruption", never as "this layer is trustworthy".

**Detection**: run the gates, then spot-check one or two article numbers against the rendered page. A clean gate plus a wrong number is the signature of this defect.

**Consequence for triage**: a defect in this class is upstream of the parser. Extending the gate to detect broken digit CMaps and routing those files to vision/OCR is a change to shared corruption-detection code, so it needs the same ADALA/SGG/BDJ regression pass as any other `structure.py`/`pdf_quality.py` edit. A gate that over-fires sends good files down a slow OCR path, so verify the pattern on a second and third file before widening the check — one file is a defect report, a corpus-wide ratio is a systemic bug.

## Pitfall: Stale Bytecode After Patching Pipeline Files

After patching `.py` files in `fetching/`, the running Python process may still execute old bytecode from `__pycache__/` directories. This is especially dangerous when verifying fixes — the file on disk shows the patch, but the runtime behavior is unchanged.

**Detection**: You patched the code, verified the file on disk with `grep` or `read_file`, but the process still produces the old error (e.g., 404 on the old endpoint). Multiple re-runs all fail identically. The `.pyc` mtime is older than the `.py` mtime.

**Fix**: Before every re-run after a patch, clear all `__pycache__` directories:
```bash
find /home/mohammed/Mizan -type d -name __pycache__ -exec rm -rf {} +
```
Then verify the patch is active in the **runtime**, not just on disk:
```python
import inspect, fetching.pipeline_base.vision_pipeline as VP
src = inspect.getsource(VP._qari_transcribe_png)
assert '/api/generate' in src and '/chat/completions' not in src
```
Always check the runtime source via `inspect.getsource()` — a file read can lie when stale bytecode is loaded. This applies to every patched module, not just `vision_pipeline.py`.

## Pitfall: Establish GPU- vs CPU-Bound Before Quoting Any OCR Speed

Do not accept "OCR is slow" as a property of the model. Ask the host what hardware it uses:

```bash
curl -s http://<host>:11434/api/ps | python3 -c "
import sys,json
for m in json.load(sys.stdin).get('models',[]):
    print(m.get('name'), '%.2f GB'%(m.get('size',0)/1e9), 'vram %.2f GB'%(m.get('size_vram',0)/1e9))
"
```

**`size_vram: 0.00 GB` with non-zero `size` means the weights sit entirely in system RAM** — nothing offloaded, so every token re-reads GBs from ordinary memory. This is invisible in the parse log: the run looks alive, pages complete, each takes forever.

Measured on one 4B at full resolution: **~316-922 s/page (mean ~502 s) on a CPU-only host** — a 76-page document is ~10.6 hours — versus a T4 expected 10-25x faster. That inverts the corpus decision from overnight to multi-week. **Always report per-page cost with `size_vram`**; a speed figure whose hardware basis is unstated is not a measurement.

Workarounds: page-by-page assembly (each page an independent request, so per-call cost stays tractable); lower DPI (verify against the fixture); move to a GPU host (a 4B Q8_0 plus projector is ~5.2 GB, comfortable in a T4's 16 GB); or accept the PP-OCRv5 fallback (`mode=ocr_forced`).

## Pitfall: PaddleOCR Layout Model Crashes After QARI Fails

When QARI returns no text (404, timeout, or empty response), `extract_vision_pages` falls through to the PaddleOCR/layout path and calls `create_model("PP-DocLayoutV3")`. On this system, that call crashes with `ValueError: I/O operation on closed file` — a secondary failure that masks the original QARI failure. The crash happens in `paddlex/inference/models/__init__.py` during predictor creation.

**Detection**: Parse log shows QARI 404 warnings followed by a crash trace through `paddlex.model` → `create_predictor` → `_resolve_local_model_dir`. The process exits with a traceback, not a clean fallback.

**Fix**: The vision pipeline should handle QARI failure gracefully without falling through to a broken layout path. If QARI is the intended rescue and it fails, return `None` from `extract_vision_pages` so the caller can decide how to proceed, rather than crashing in the PaddleOCR path. Also clear `PP-DocLayoutV3` cached model files at `~/.paddlex/official_models/PP-DocLayoutV3` if the layout model is suspected to be corrupted.

## Pitfall: extraction_mode Misreads the OCR Backend

The parsed JSON's `extraction_mode` field names the backend that produced the text, but the names don't map 1:1 to `.env` flags:

| `extraction_mode` | What actually ran |
|---|---|
| `native` | fitz text layer only |
| `vl` | PaddleOCR-VL (vision model) |
| `docling` | Docling export |
| `ocr` / `ocr_forced` | PP-OCRv5 |
| *(none of these)* | Qari — Qari does not set `extraction_mode`; it only re-saves `structure_pages` inside the ADALA parser after extraction already ran |

A JSON with `extraction_mode: ocr_forced` means PP-OCRv5 produced the text, even if `ADALA_QARI_OCR_ENABLED=true` and `QARI_OCR_BASE_URL` points at a live endpoint. Those flags only matter if the ADALA parser's vision gate opens.

## Pitfall: The Client Pixel Budget Is the Difference Between 12x Slower and Not

The client sends whole rendered pages and total pixel count drives vision-token
count. Mizan's adapter renders at 150 DPI (~2.18 M px A4) and, with no client-side
cap, spent **228 s of prompt evaluation per page** (2165 vision tokens) against ~47 s
for the same model behind a notebook that already downscaled. Declare the budget as
a real settings field (`QARI_OCR_MAX_PIXELS`, default `640 * 28 * 28`) and apply it
to **both** transports, so local and notebook deployments behave alike; a module that
previously handled only raw PNG bytes needs an explicit `from PIL import Image`.

It is a **quality dial, not only a speed dial** — Arabic letterforms degrade below
~500 K px. Raising 360→640 fixed 5 of 7 character confusions (`جنازة` → `جائزة`,
`المعبوم` → `المرسوم`, `تنقيط` → `تنفيذ`) and made one worse. Whole-word confusions
are lexical, not detail limits, so stop raising before the VRAM wall. The losing side
is legal references: at the same budget one deployment returned `141.192` and another
**omitted the decree number entirely** — which reads as clean output. Validate that
reference numbers are *present*, not just correct when present.

**Resolution does not fix digit transposition — do not sell it as the lever.** The
same model transposed digit runs at every budget tested, and got *worse* at full
resolution: `141.192` → `192.141` points at a different instrument, so treat digit-run
transposition as disqualifying independent of quality. Full budget tables, the
halve-and-retry memory pattern, and the A/B-one-axis rule: `references/qari_ocr.md`.

**Measure twice before converting one timing sample into a cost projection.** A cold first request includes model load: `load_duration` 21.6 s inflated `prompt_eval_duration` 228 s into a "252 s/page" figure, and a whole feasibility table ("125 h vs 30 h") was built on it. Steady state was **66.6 s** — but that makes full resolution affordable *on that host only*. On a 16 GB T4 the same page (3.87 Mpx at 200 DPI) makes the vision tower request 13.74 GiB against 5.16 GiB free and every page 500s; compare `width*height` against `gpu_total - model_resident` before a corpus run (`references/colab-vlm-ocr-serving.md`). Read `load_duration` / `prompt_eval_duration` separately, and re-measure before publishing arithmetic.

**Confirm which host and which model is actually serving.** Two Ollama instances can run on one box with different model sets (`localhost:11434` holding only a general-purpose `qwen3.5:4b` while a LAN host held the Qari GGUF), and a run believed to be using Qari may be resolving a different host entirely. `.env` is not evidence of what ran. Read the request URL in the log and `curl /api/tags` per host.

**Grep the log for the request line, not the provider name.** Searching for `qari` returns zero while OCR is firing on every chunk, because the evidence is `POST http://localhost:11434/api/generate` and `[OCR NORM] Chunk N`. Grep the URL or `[OCR NORM]` markers.

**A 404 from Ollama does not mean the endpoint is missing.** It also means the model name is unknown. Probing with a placeholder model reported the OpenAI path as dead when both transports were serving. Probe with the real `QARI_OCR_MODEL`.

**A/B one axis at a time.** Changing the checkpoint *and* the pixel budget together makes the result unattributable. Set the new model to the old model's budget so only the weights vary, hold the page set fixed, and save the prior run's results before overwriting them.

- **Choosing a source: native layer vs OCR (references/extraction_source_comparison.md)** — whole-run digit reversal is a distinct defect from glyph substitution; never score one extraction source against another suspect source.
- **Serving a VLM OCR service (references/colab-vlm-ocr-serving.md)** — backend choice, transport, pixel budget, HTTP framing, and the executable harness gate.

## Pitfall: Dead OCR flag ADALA_FORCE_OCR

`ADALA_FORCE_OCR` appears in `.env.example` and is commonly set to `true` alongside Qari, but the codebase has **zero references** to it. It does not bypass any gate, does not force Qari, and does not force any OCR backend. Relying on it produces a false belief that OCR is forced when it is not.
