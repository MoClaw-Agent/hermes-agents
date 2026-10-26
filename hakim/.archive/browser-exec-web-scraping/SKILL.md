---
name: browser-exec-web-scraping
description: "Browser-exec web scraping with resumable batches."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [scraping, browser, javascript, resumable, metadata, legal]
    related-skills: [test-driven-development, requesting-code-review]
---

# Browser-Exec Web Scraping

## Overview

Many modern sites (Next.js, React SPAs) require a real browser to render content. The `browser_exec` tool auto-imports browser helpers (`new_tab`, `goto_url`, `wait_for_load`, `js`, `page_info`) into its execution namespace. Scrapers that use these helpers must run inside `browser_exec` — they work via dynamic injection, not via Python imports.

**Core principle:** The scraper module defines functions; the `browser_exec` context supplies the browser. Keep them separate.

## When to Use

- Scraping JavaScript-rendered pages (Next.js, React SPAs) where `curl`/`requests` returns empty shells
- Building a resumable corpus from a sitemap with thousands of URLs
- Extracting structured metadata (titles, references, dates, language) from legal/government sites
- Bilingual (Arabic/French) content that needs language-separated fields
- Any scraping task where the user may interrupt and re-run later

## Pitfalls

### P1: Helpers are namespace-injected, not importable
```python
# WRONG — helpers is not a Python module
import helpers as bh
bh.new_tab(url)

# CORRECT — call directly in browser_exec namespace
new_tab(url)
wait_for_load()
page_text = js("document.body.innerText")
```
If you `import helpers` inside browser_exec, you get `ModuleNotFoundError`. Always call helpers directly.

### P2: Background subagents hit browser_exec's 300s timeout
Design for interruption:
- **Resumable**: skip already-processed entries via index file
- **Idempotent**: overwriting same page is harmless
- **Persist after every page**: write JSON + update index.json

### P3: Reference extraction — title area only
Regex like `(\d{1,3}(?:[-.]\d{1,3})+)` matches dates and related-law numbers in body text. Restrict to first ~500 chars:

```python
title_area = page_text[:500]
ref_patterns = [
    r"(?:Loi|Dahir|Décret)\s*(?:n°|nº)?\s*(\d{1,3}(?:[-.]\d{1,3})+)",
    r"n°\s*(\d{1,3}(?:[-.]\d{1,3})+)",
]
```

### P4: Arabic navigation cards pollute full_text
"قراءة المزيد" begins related-law recommendation cards. Strip everything after:

```python
for nav_marker in ["قراءة المزيد", "nقراءة المزيد"]:
    m = re.search(nav_marker, full_text)
    if m:
        full_text = full_text[:m.start()].rstrip()
        break
```

### P5: French quality-header prefixes
Strip "Texte brut extrait du PDF — qualité variable" before law text:

```python
full_text = re.sub(r"^Texte brut extrait du PDF\s*[—-]\s*_qualité variable\s*\n*", "", full_text, flags=re.IGNORECASE)
```

### P6: Bilingual splitting
Detect Arabic-script lines (any char in \u0600-\u06FF). Find contiguous Arabic blocks allowing gaps of up to 2 non-Arabic lines. Store as `content_fr`/`content_ar` alongside `full_text`.

### P7: External link cleanup
Filter out CDNs, fonts, Supabase, analytics. Keep only meaningful legal sources (sgg.gov, adala, bulletin, justice.gov, gov.ma).

## Workflow

1. Define scraper module (pure parsing + `scrape_page` calling `js()` directly)
2. Test inline with limit=2-5 first
3. Clean output directory before full runs
4. Dispatch background via `delegate_task`; user can re-dispatch on timeout
5. Persist index.json after every page for resumability
6. Commit before full runs

## References

- `references/multilingual-legal-corpus.md` — Moroccan legal text patterns, instrument/domain classification, bilingual edge cases
