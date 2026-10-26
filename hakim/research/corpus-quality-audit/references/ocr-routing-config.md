# OCR routing: three settings, four branches, one selector

Depth for always-on rule 0i. Everything here was measured on a live corpus.

## The three orthogonal questions

| Question | Setting | Failure if wrong |
|---|---|---|
| Does OCR run despite a usable text layer? | `OCR_FIRST` + `OCR_FIRST_PROVIDERS` | text layer trusted when it carries wrong references |
| Which engine does it use? | `VISION_OCR_ENABLED` (or `OCR_FIRST_ENGINE` env) | wrong engine, no error |
| May a Paddle backend load at all? | `OCR_PARSER_USE_PADDLE_VL` / `OCR_PARSER_USE_PP_OCRV5` | model never initialises; independent booleans, both true is valid |

`OCR_PARSER_USE_*` are **resource gates, not route selection**. Confusing the two produces
config that reads correct and behaves otherwise. The observed chain:

```
[OCR_FIRST] bypassing text layer for this provider   ← gate fires correctly
→ engine resolved to "ppocr"
→ PP-OCRv5 disabled by settings.OCR_PARSER_USE_PP_OCRV5=false
→ returned nothing
→ cascade continued → Docling, which registered PP-OCRv5 as its own engine anyway
→ document parsed "successfully" off the text layer
```

Note the last two steps. **Docling consults neither `OCR_PARSER_USE_PP_OCRV5` nor
`OCR_FIRST`.** It has a third door into the same engine. A flag that reads as "no PP-OCRv5"
only covers the direct `_paddle_ocr_pages()` calls.

## `getattr(settings, X, False)` is inert until X is a declared Field

The single most expensive defect in this class, because it is invisible:

- `.env` has `VISION_OCR_ENABLED=true`
- the key is **not** declared in `core/settings/`
- `extraction.py` reads `getattr(settings, "VISION_OCR_ENABLED", False)` → always `False`
- engine resolves to `ppocr`; the VLM the operator configured is never called

Assert the effective value through the settings object, never by grepping `.env`:

```python
from core.settings import settings
print(settings.VISION_OCR_ENABLED)     # <absent> is the tell
```

Declaring the Field is necessary but not sufficient. The same key must also be registered in
`core/settings/_admin_field_whitelist.py` **and** `api/routes/admin_config.py` `FIELD_META`,
or the pre-commit `admin-field-drift` hook (3-way WHITELIST ∪ FIELD_META − Settings) fails.
Run it directly: `venv/bin/python scripts/check_admin_field_drift.py`.

Other keys in `.env` that no code reads at all: `ADALA_FORCE_OCR`, `ADALA_OCR_BACKEND`.
They look configured while steering nothing.

## Branch reachability: a gate inside one `if/elif` chain is not a policy

`extract_pages()` dispatches on `_classify_pdf()`:

```
if   pages is not None     → French native-first
elif language_hint == "fr" → PP-OCRv5 (Latin recogniser, deliberately never Arabic)
elif pdf_type == "cid_fonts"    → probe text layer → PP-OCRv5 → VL → CMap repair
elif pdf_type == "scanned"      → PP-OCRv5        ← no OCR_FIRST gate
elif pdf_type == "native_small" → PaddleOCR-VL → Docling → PP-OCRv5
else                          → native_large
       └── OCR_FIRST gate lives HERE, at the bottom
```

Two independent reachability failures were found here:

1. **The OCR_FIRST gate sat inside the final `else`.** Measured on the real corpus, 299 of
   300 ADALA Arabic PDFs classify as `cid_fonts`, so the branch the corpus actually takes
   never consulted it. Same defect class as the path-inference bug: correct function, never
   called.

2. **The provider was inferred from the filesystem path.** `parts.index("corpus")` then the
   next segment. The consolidated layout has no provider directory — the provider is a
   *filename* prefix — so the lookup returned `False` for every document. Thread an explicit
   `provider=` argument from each parser instead of re-deriving it, and pin the path-form
   limitation in a test so it cannot regress unnoticed.

**Before assuming a gate applies, enumerate the branches and check which one the corpus
reaches.** Classify a real sample rather than reasoning about the dispatch:

```python
from fetching.pipeline_base.pdf_quality import _classify_pdf
Counter(_classify_pdf(p, language_hint="ar") for p in sample)
```

## Fix pattern: one selector function, every call site

The scanned branch hardcoded `_paddle_ocr_pages()` with no engine selection, so
`VISION_OCR_ENABLED` could not reach it. Conflating OCR_FIRST's reason to exist ("the text
layer is untrustworthy") with engine choice ("which OCR is better") is what produced a branch
where the best engine was unreachable.

Extract one function and call it from every site:

```python
def _run_ocr_engine(pdf_path, language_hint, cache_dir, reason):
    """Run one OCR pass with the configured engine. Returns (pages, engine_name)."""
    engine = os.environ.get(
        "OCR_FIRST_ENGINE",
        "vision" if getattr(settings, "VISION_OCR_ENABLED", False) else "ppocr",
    ).strip().lower()
    engine_name = engine
    if engine in ("vision", "qwen", "qari"):
        try:
            vdir = Path(getattr(settings, "CACHE_VISION_DIR", None)
                        or Path(cache_dir).parent / "cache_vision")
            vdir.mkdir(parents=True, exist_ok=True)
            pages = extract_vision_pages(
                pdf_path, cache_path=vdir / (pdf_path.stem + "_vision.json"))
            if pages:
                return pages, "Qwen/Qari VLM"
            engine_name = "ppocr"
        except (ImportError, OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("[OCR] %s: vision unavailable (%s); -> PP-OCRv5",
                           pdf_path.name, e)
            engine_name = "ppocr"
    try:
        pages = _paddle_ocr_pages(pdf_path, language_hint)
    except (ValueError, TypeError, AttributeError, KeyError, RuntimeError,
            OSError, ImportError) as e:
        logger.warning("[OCR] %s: PP-OCRv5 failed (%s) [%s]", pdf_path.name, e, reason)
        return None, "PP-OCRv5"
    return (pages, "PP-OCRv5") if pages else (None, engine_name)
```

Then the scanned branch and the OCR_FIRST gate each call it. Assert the call-site count in
review: `grep -c "_run_ocr_engine(" file` should return definition + one line per call site,
with no backend called directly beside it.

**Sites that stay engine-specific by design** — do not "unify" these:

- the **French** branch, which must never route through the Arabic recogniser
- each parser's own **vision rescue**, which is already the vision route and is gated by its
  own `ADALA_VISION_OCR_ENABLED` / `ADALA_QARI_OCR_ENABLED` flags
- the **PP-OCRv5 fallback inside** the vision route, which is what keeps a degraded answer
  available when the VLM is down

Unifying the fallbacks would trade away "a working degraded answer beats none" — and that
trade was explicitly declined.

## Prove which engine actually ran

Config is not evidence; the artifact is. Assert on all three:

```python
payload = json.loads(cache_file.read_text())
payload["source"]        # "vision" vs extraction
payload["mode"]          # "qari" vs "ppocr"
```

plus a log line naming the engine. A run that writes `mode: native` for a document explicitly
opted into OCR is a routing bug to trace, not a stale cache.

## Vision-output persistence

Passing `cache_path` is what makes a vision pass auditable and re-parseable; without it the
text exists only in memory, every re-parse re-OCRs every page, and the document cannot be
inspected afterwards. Emit `structure_source` ("vision"/"extraction") and
`structure_text_cache` in the output so auditing reads the text that actually built the
structure.

Key the cache by content hash, not bare stem: `{stem}_{sha256[:12]}_vision.json`. Measured
over a 4,626-file corpus, bare-stem naming gives 3 colliding keys covering 7 files; hashed
naming gives 1, and that one is a byte-identical pair — the same law filed under two domains
— so sharing an entry is correct rather than a defect.