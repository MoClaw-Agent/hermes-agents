---
# PDF CMap ToUnicode Auto-Repair

## Problem

Arabic PDFs with broken Identity-H ToUnicode CMaps produce mojibake text extraction regardless of which extraction backend is used (fitz native, PaddleOCR-VL, PP-OCRv5). The font's glyph-to-Unicode mapping is wrong, so every extraction path reads the same garbage.

Example: `الإيداع القضائي ظهير شريف` becomes `اإليداع القاوىوي ظهيز شزيف` — the text looks like Arabic but reads as nonsense.

OCR is the wrong fix here: OCR transcribes rendered page images, which is slow (minutes per page) and produces different garbage. The correct fix is to repair the PDF's CMap at the source.

## When to Use

- PDF has Type0 fonts with Identity-H CID mapping (standard for Arabic PDFs)
- Extraction produces mojibake Arabic despite having a text layer
- `is_arabic_cmap_corrupt(pages)` returns True OR supplemental ISM check flags it
- `needs_cmap_repair(pdf_path)` returns True (fast pre-check for repairable font structure)
- PDF has embedded TrueType FontFile2 with a reversible cmap table

## When NOT to Use

- French PDFs (no Arabic CMap to repair)
- PDFs without embedded TrueType fonts (Type1/CFF fonts can't be repaired this way)
- PDFs where the font's cmap table is missing or unreversible
- Image-only/scanned PDFs (need OCR, not CMap repair)

## The Repair Algorithm

The repair works by extracting the CORRECT glyph→Unicode mapping from the font's internal TrueType cmap table and rebuilding the PDF's broken ToUnicode stream.

### Step 1: Discover repairable fonts

```python
from fetching.pipeline_base.repair import discover_font_maps, RepairNotApplicable

pdf_bytes = pdf_path.read_bytes()
try:
    maps = discover_font_maps(pdf_bytes)
except RepairNotApplicable:
    # PDF has no repairable font structure
    maps = {}
```

`discover_font_maps()` walks the PDF's indirect objects looking for:
1. Type0 font subtypes with `/ToUnicode` streams
2. Identity-H CID-to-GID mapping (the broken mapping we'll replace)
3. FontFile2 entries pointing to embedded TrueType fonts
4. Extract the TrueType cmap table from the font binary

Returns `dict[int, dict[int, list[int]]]` mapping ToUnicode object numbers to glyph→codepoints mappings.

### Step 2: Rebuild the ToUnicode stream

```python
from fetching.pipeline_base.repair import make_tounicode_cmap

for obj_num, glyph_map in maps.items():
    new_cmap = make_tounicode_cmap(glyph_map)
    # new_cmap is the replacement ToUnicode stream bytes
```

`make_tounicode_cmap()` converts the glyph mapping into a valid CIDFontToUnicode stream in AFM format:
- Normalizes Arabic presentation forms via NFKC (e.g. فתי→فتי)
- Preserves ligatures like لا
- Outputs standard `/CIDInit` CMap structure

### Step 3: Write the repaired PDF

```python
from fetching.pipeline_base.repair import repair_cmap

repaired_path = pdf_path.parent / f"{pdf_path.stem}_mapping_repaired{pdf_path.suffix}"
repair_cmap(pdf_path, repaired_path, force=True)
```

`repair_cmap()`:
1. Reads the original PDF
2. Appends new ToUnicode objects to the end
3. Rebuilds the xref table with `mutool clean -gg`
4. Writes the repaired PDF

Requires `mutool` (available at `/usr/bin/mutool` on this system).

### Full workflow

```python
from fetching.pipeline_base.repair import auto_repair_pdf

repaired = auto_repair_pdf(pdf_path)
if repaired:
    # Re-extract from repaired PDF — should give clean native text
    from fetching.pipeline_base.extraction import extract_pages
    pages, mode, tables = extract_pages(repaired, cache_dir, language_hint="ar")
    # mode should be "native" now, not "ocr_forced"
else:
    # Not repairable — fall through to normal OCR path
    pass
```

`auto_repair_pdf()` is the convenient single-call version: discovers maps, repairs, returns the path to the repaired PDF or None.

## Integration into the Parser Fleet

The repair is integrated as an opt-in hook in `fetching/pipeline_base/extraction.py`:

```python
# In extract_pages(), after CID fonts probing shows native text is corrupt:
_cmap_repair_enabled = getattr(settings, "CMAP_REPAIR_ENABLED", False)
if _cmap_repair_enabled and language_hint != "fr":
    try:
        from fetching.pipeline_base import auto_repair_pdf
        repaired_path = auto_repair_pdf(pdf_path)
        if repaired_path is not None:
            # Re-extract from repaired PDF
            repaired_pages = extract_native(repaired_path, language_hint=language_hint)
            if repaired_pages:
                pages = [_clean_identity_h_fragmentation(p) for p in repaired_pages]
                if _text_layer_has_arabic_content(pages):
                    mode = "native"
    except Exception:
        pass  # repair failed, fall through to OCR
```

Each parser also has a CMap repair GATE that runs when OCR mode is detected:

```python
# In parser pipeline.py, after extract_pages() returns with mode=ocr_forced:
if (getattr(settings, "CMAP_REPAIR_ENABLED", False)
        and mode in ("ocr_forced", "ocr", "ocr_forced_cmap")
        and language != "fr"):
    try:
        from fetching.pipeline_base import auto_repair_pdf, needs_cmap_repair
        if needs_cmap_repair(pdf_path):
            repaired_path = auto_repair_pdf(pdf_path)
            if repaired_path:
                logger.info(f"[CMAP_REPAIR] {pdf_path.name}: CMap repaired")
    except Exception:
        pass
```

The gate does NOT re-extract in the same run (the repaired PDF is for the NEXT run). It repairs the source PDF so future parses get clean native text.

## Activation

Both repair features are opt-in via settings. CMap repair requires `mutool`.

```yaml
# .env or settings override:
CMAP_REPAIR_ENABLED: true    # Enables CMap ToUnicode repair
```

Masthead repair is ALWAYS ON — it's a cheap string scan with no external dependencies. It runs automatically after every Arabic PDF extraction.

## Standalone CLI Usage

The repair library is also available as standalone CLI tools (thin wrappers around the library):

```bash
# CMap repair — repair one PDF or a wildcard
python scripts/repair_pdf_mapping.py 'data/corpus/ism/raw/ar/droit_civil/8.pdf' repaired/
python scripts/repair_pdf_mapping.py 'data/corpus/ism/raw/ar/droit_*/*.pdf' repaired/

# Masthead repair — scan and repair garbled headers in JSON files
python scripts/repair_ar_adala_garbled_headers.py [json_dir]
```

The CLI tools delegate to `pipeline_base.repair._cmap_repair_cli` and `_masthead_repair_cli` respectively.

## Pitfalls

- **`mutool` must be available** — `repair_cmap()` calls `mutool clean -gg` to rebuild xref tables. If `mutool` is not installed, the repair writes a raw appended-PDF that some readers won't open correctly.
- **CMap repair is not a silver bullet** — it only fixes PDFs with Type0 Identity-H fonts + embedded TrueType FontFile2. PDFs with Type1/CFF fonts, or without embedded fonts, raise `RepairNotApplicable`.
- **Repaired PDFs persist on disk** — `_mapping_repaired.pdf` files accumulate next to originals. Clean them up periodically or set a retention policy.
- **Don't re-extract from repaired PDF in the same parse run** — the CMap gate in the parser only repairs the source for next time. The extraction-time hook IS the re-extract path, but it only activates when `CMAP_REPAIR_ENABLED` is set. Without it, the repaired PDF sits unused.
- **Test with `pdftotext` after repair** — verify the repaired PDF actually produces clean text:
  ```bash
  pdftotext -layout repaired.pdf - | head -20
  ```
  If the text is still garbled, the font's cmap table may not contain the correct mapping (the embedded cmap could itself be wrong).
- **ISM stem collision risk during re-parse** — after repairing a PDF and re-parsing, the repaired copy has `_mapping_repaired` in its name, so it won't collide with the original. But if you rename it back to the original name, be aware that ISM PDFs share short numeric stems across domains (e.g. `7.pdf` exists in 5 domains). Always re-parse into the correct domain folder. See `references/arabic-corruption-detection.md` for the full ISM re-parse recovery procedure.
