---
name: legal-corpus-pipeline
description: "Build Mizan legal-corpus scrapers and RAG providers."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [rag, corpus, scraper, legal, pipeline, browser-exec, mizan]
    related_skills: [test-driven-development]
---

# Legal Corpus Pipeline

## Overview

Class of work: evaluate a legal provider website, build a standalone scraper, test iteratively, dispatch to background, and update the rollout tracker so Mizan can corpus-compare across ADALA / SGG / JuriThèque at ingest time.

Active scrapers: `fetching/adala/`, `fetching/sgg/`, `fetching/dgssi/`, `fetching/juritheque/` (standalone). A huquqai scraper does NOT yet exist — the sitemap is available but no `fetching/huquqai/` module has been built.

The deliverable is a working scraper plus a committed rollout-plan entry. A partial submission (like "sitemap downloaded but scraper untested") is committed tech debt.

## Cross-Reference Ingestion

When ingesting legal cross-reference relations (e.g., REPEALS, MODIFIES from a provider's `legal_relations` table), the endpoint laws MUST already exist in Mizan's `documents` table for the edges to resolve. Relations reference source/target law IDs; these map to Mizan doc_ids via the `ref` column in `documents`. If the relation endpoints are not yet ingested, the edges cannot be inserted.

**Workflow:** Ingest the law corpus first → then ingest cross-references. If cross-references are fetched before the laws, store them in a staging table keyed by provider law ID and resolve during ingestion.

## Post-Ingestion Corpus Merge & Deduplication

When two ingested legal corpora (JSON) overlap on `ref` values, produce one clean corpus by comparing, deduplicating, or merging them. See the `corpus-quality-audit` skill for the full workflow and code recipes in `references/corpus-merge-dedup.md`.

### Cross-Provider Comparison

Index both corpora by `ref` (law reference number), compute overlap via set intersection. Typical overlap: ~1,256 refs (~45% of ADALA, ~19% of JurThèque). For each overlap, choose between:
- **Deduplication:** pick one copy, flag/delete the other
- **SOTA merge:** field-level best-of + structure-aware article merge + apply parser fixes to output

### Index Naming

When indexing after a scrape, use `<domain>/<lang>/index.json` for cross-provider comparison. The index stores {reference, instrument_type, title_fr, title_ar, date, source_url, file_path} per law. This is what enables finding overlaps between ADALA and JurThèque after both are ingested.

## Always-On Rules

1. **Test before Dispatch** — never dispatch a background batch run before at least one local test against the real site. Validate that the target URL renders and the scraper captures the fields you need.
2. **Code + rollout plan commit together** — when code changes, update the rollout plan (`ROLLOUT_MASTER_PLAN.md` or equivalent) in the same commit.
3. **Reference parse from title area only** — scanning the first ~500 chars of page text for a numeric reference prevents body dates and related-law card numbers from being picked as the primary reference.
4. **Bilingual split only when both languages are significant** — `content_fr` / `content_ar` fields are set only when BOTH are non-empty. Monolingual content stays in `full_text` only.
5. **Website disclaimer ≠ law disclaimer** — strip cookie-consent banners and site footer descriptions, NOT law-text metadata embedded in the posts themselves.
6. **Background daemon verification** — always confirm the subagent is live (via `delegate_task action=list` or tailing the live transcript) before declaring a dispatch success.
7. **Check for existing scraper first** — before building a new provider scraper, check `fetching/<provider>/scrape.py` and the terminal session map. The user may reference a scraper that already exists under a different name.
8. **Always set `workdir` on terminal() calls** — the terminal daemon initializes a stale cwd from a previous session. Every `terminal()` call MUST pass `workdir=/home/mohammed/Mizan` or the relevant project root. The shell-init `cd` failure is environmental noise, not a blocker — work around it, don't fight it.
9. **Don't chase unrelated local processes** — when the user asks about a hermes terminal session, look at `terminal-sessions/` metadata and `ps aux`. Do NOT start investigating freebuff, manicode, or other unrelated local services unless the user explicitly named them.
10. **API-first scraping** — before building a browser scraper, check if the site uses a backend API (Supabase, REST, GraphQL). The JS bundle often contains API keys and endpoint URLs. Direct API access is 10-100x faster than browser scraping and avoids WebSocket instability entirely. Look for `createClient(` patterns, `supabase` references, and `from("table_name")` calls in the JS bundle.
11. **Memory-efficient batch processing** — for large datasets (>1000 records), NEVER accumulate all records in memory. Process one batch at a time, save to disk, then fetch the next batch. Use `del batch` to explicitly free memory between iterations.
12. **Resume via progress file** — for long-running scrapes, persist processed IDs to a JSON progress file after each batch. On restart, load the progress file and skip already-processed IDs. This makes scrapes resumable across subagent timeouts and interruptions.
13. **Subagent timeout reality** — subagents exit after ~5 minutes. For long-running tasks, the script itself must be resilient (progress file, batch processing, resume support). Don’t rely on the subagent to iterate — rely on the script's own loop.
14. **Never grade one extraction against another.** When an extracted text layer is under suspicion, hand—checking it against itself inverts the evidence and will make a working engine look broken. Verify counts and legal references against the printed or rendered page, or against an independent OCR of that page.
15. **Scope OCR to the providers that need it.** OCR costs orders of magnitude more per page than a text layer. Enable it per provider, only where a defect is verified. Record unmeasured providers as "unverified" — never as "healthy", or the exclusion hardens into a false clean bill of health.
16. **Prove structure—preserving parser fixes with a test before keeping them.** A fix that stops dropping articles is invisible to the article count alone; assert the recovered count AND that the fix’s own rejection rules still fire, or the loosened matcher will silently admit cross-references. **A synthetic fixture must reproduce the document-level decision it is meant to exercise.** This parser decides once per document whether a keyword family is the article unit, from a median test over its headers' resolved numbers; a fixture with one or two headers fails that test, the keyword is classified as a chapter container instead of the article unit, and the test fails for a reason that has nothing to do with your change. When a structure test fails, first rebuild the tree over a real cached document — if it is correct there, the defect is the fixture's shape, not the production code. Give a fixture at least the handful of low-numbered headers the real document has.
17. **Test the composed change first.** When the hypothesis is that two adjustments combine, build the combined version before testing them apart — running A-vs-B first answers the weaker question and burns the expensive calls.
18. **A setting read through `getattr(settings, ..., default)` is a setting that does not exist.** If the field is absent from `Settings`, the expression is constant: `.env` can say `true`, the operator can verify the file, and every call resolves to the default while the log reports the route that was asked for. Declare the field, assert it resolves under the real `.env`, and add a test that every non-comment key in `.env` exists in `Settings.model_fields`. A key present only in `.env` is dead config. See `references/ocr-routing-and-config.md`.
19. **Keep three OCR settings separate: resource availability, route, and engine.** Whether a backend may *load* (a boolean host-capacity gate), whether a document bypasses its *text layer* (route), and which *engine* runs the pass (selector) are three questions. Availability gates are independent and may both be true; a gate is never an engine selector. Conflating them makes "which engine ran this page" unanswerable from configuration alone.
20. **A policy gate placed inside one branch of a dispatch governs only that branch.** Before trusting a flag, read the dispatch as a table: for each branch, which engine does it call, and does any gate actually precede it. A branch that hardcodes its own engine makes that choice unreachable by any setting — measured on an image-only branch covering 77 of 195 queued documents, where the hardcoded engine was also the one measured to misread article digits. Extract one shared selector and call it from every branch.
21. **Rename a configuration key in code and `.env` in the same commit, and check for substring collisions first.** Splitting them leaves the old key unread and silently defaults the model, base URL and timeout — self-inflicting rule 18. A blanket replace of `QARI_OCR_` also rewrites `ADALA_QARI_OCR_ENABLED` into a duplicate field that pydantic drops without error; `mypy`'s `no-redef` is what catches it. Assert the *code* default in tests, not the value visible in `.env` — they differ.
22. **Say which decision is lost when two flags collapse into one.** Two OR-ed flags may encode two separable choices; merging them removes the ability to choose separately. Confirm the merge before making it, and name what it takes with it.
23. **Audit every reader of a renamed key, including prefix-probing helpers.** A helper of the form `getattr(settings, f"PROV_{name}", getattr(settings, f"OTHER_{name}", default))` breaks on rename: when the new name carries neither prefix the chain ends at `default` and the route goes dark with no log line. After a rename, resolve the setting *through each reader* — declaring it is not enough. See `references/ocr-routing-and-config.md`.
24. **A test that compares a lookup against the value it reads is vacuous.** `assert _lookup("X") == settings.X` passes when the lookup itself is broken, because both sides come from the same defect. Assert the resolved value equals the intended truth (e.g. `is True`), not that two views of one source agree.
25. **Keep renamed keys working with `validation_alias=AliasChoices`, not a `mode="before"` validator.** A before-validator receives init kwargs and `.env` already merged, so its own "new key wins" rule overrides the framework's documented source precedence. AliasChoices resolves per source. A type change (bool→str) additionally needs a `field_validator(mode="before")` to translate the value, or the alias yields `"True"` and silently selects the wrong engine.
26. **Classify every undeclared `.env` key before touching it.** An undeclared key is either **dead** (no reader anywhere — delete it) or **live-but-inert** (read via `getattr(settings, X, None)` and applied only when not `None` — declare it, keeping the `None` default). Conflating the two either deletes live config or re-declares dead config. See `references/ocr-routing-and-config.md`.
27. **Never delete or degrade a working code path to make a build pass.** When your own edit breaks a file, revert that edit (`git checkout <commit> -- <file>`) and redo it as one clean change. Deleting the surrounding feature to get green trades a broken build for lost functionality and forces the user to reconstruct work they had already finished. Removing or disabling an existing capability requires the user's explicit permission, every time — a "cleanup" that quietly drops a feature is the failure mode, not the fix. **When you realise you have broken something, stop editing and produce a complete damage report before changing anything further**: `git status`/`git diff` against the last good commit, every file touched, what each change did, and the exact revert point — then wait. "Analyze the damage first, do not fix yet" is a literal instruction: report and stop, do not start repairing mid-report.
28. **A fallback that is not recorded is indistinguishable from success.** When a required engine fails and a degraded one produces the output, both write the same provenance field, so a silently degraded parse reads as a good one. Emit an explicit degraded flag plus a reason alongside the existing source field, surface it on the success log line, and give the run a distinct status. A `structure_source: "extraction"` value cannot carry this on its own — it is also the correct value for a clean native layer. See `references/ocr-routing-and-config.md`.
29. **Check which text produced the structure before touching the matcher.** On an article-count regression, read the output's provenance field and rebuild the tree from the cached engine text (`build_tree(vision_pages)`). If the tree is correct there, the matcher is fine and the text that reached it is not — a correct matcher over the wrong text is indistinguishable from a broken matcher, and chasing the regex wastes the session. See `references/ocr-provider-quirks.md`.
30. **Liveness, readiness, and generation are three separate checks.** A health probe that only confirms the model server *answers* (e.g. Ollama's `/api/tags`, which lists models and loads none) reports `model_loaded: true` with an empty VRAM; the next real request pays the cold load. Warm at startup with the same `keep_alive`/`num_ctx` the real requests use, because the server keys a loaded instance on those parameters. See `references/vision-ocr-service-ops.md`.
31. **Measure throughput; never infer it from a duration subtraction.** `total_duration - load_duration` also contains warmup and prompt-eval on a cold call, so it overstates slowness and produces confident wrong diagnoses. Read `eval_count`/`eval_duration` and run it twice to separate load from generation. A response truncated before those fields is not a measurement. See `references/vision-ocr-service-ops.md`.
32. **A module nothing imports can be broken for a long time without anyone noticing.** This tree carries deliberately-divergent parallel copies of the same parser (`adala/parser/`, `ism/parser/`, and the `parser_base/` facade). A defect in one copy is invisible to the others, and a facade that no live path imports stays broken until someone imports it explicitly — an import-time `re.error` (a stray `)` in a regex literal) took the whole facade down with no test or runtime signal. So: verify a facade by importing it, not by reading it, and when one parallel copy fails while its siblings import, diff it against the canonical copy rather than debugging it in isolation. Locate a bad regex by compiling each `re.compile(...)` in the file separately (a string-level paren-balance scan gives false positives on multi-line string literals).
33. **Isolate an OCR failure per page, never per document.** One rejected page must not discard the whole pass — an exception raised from the transcribe helper (a job-polling `RuntimeError` sat outside the caught tuple) propagated through the page loop and abandoned every page to a cheap fallback engine that mangles article digits, so the count was wrong *everywhere*, not just where the page was. Catch inside the page loop, record the failed page, return the rest: partial output beats a wholesale fallback. Fail a *deterministic* rejection (repeated / degenerate output) immediately rather than spending the retry budget on it.
34. **Compare the native text layer against the OCR before calling a document unparseable — their gaps are disjoint.** On a long Arabic code the native layer recovered more article numbers than the vision pass, and the union recovered more than either, while only the pages truly blank in both held the remainder. Diff the two per page. Before accepting a page as empty, render it and measure ink coverage — pages the OCR returned nothing for can hold clean native text. A provider-level OCR-first gate overrides a clean-looking layer by design, so measure the union instead of trusting either source's own verdict. **When you act on that, choose the source per page, and score the page by DISTINCT article identities — never by raw header matches.** Cross-references in body text (`وفقا للفصل 25`) match the header pattern, so a page that merely *cites* articles scores as richer than one that *defines* them; a raw count picks the wrong source on exactly the pages where the two disagree. Key the identity as `(number, compound label)`. **Also require the candidate source to compensate for the structure it cannot represent**: the native layer shreds compound headers (`الفصل 1-35`) across lines and could represent 4 of 137 compounds present in the OCR text, so it must beat the incumbent by *more* than the number of compounds it would drop — otherwise a page wins on one extra ordinary article while silently discarding several real provisions. Ties go to the incumbent OCR engine (cleaner word-level text). Measure the change across many cached documents, not one: report mean coverage, mean phantom nodes, and the win/lose/tie counts. See `references/ocr-provider-quirks.md`.

35. **A new identity field must reach every consumer that keys on the old identity.** Adding `number_label` to article nodes stopped the parser collapsing compound provisions — and then the quality validator, which still keyed duplicates on `(chapter, number, bis)`, flagged the correctly-distinguished provisions as duplicates. A parser-side identity change is not complete until every downstream key, audit, and check has been found and widened: grep the tree for the identity fields (`number`, `bis`) across `ingestion/`, `tools/`, and the audits, not just the module you edited. Widening a key can surface a *second*, independent false positive in the same check — here the container scope, keyed on the container's number alone, collapsed four distinct `الجزء الأول` parts that share the number `1`. Fix both, and assert the negative case too (a genuine duplicate must still be flagged), or the widened key silently stops detecting the defect it exists for.

36. **An absent header is a measurement of the text you searched, never a fact about the document.** "N articles are missing" is a statement about the string in hand; the article may be genuinely absent from the source, or present but dropped by one of the parser's rejection rules (a cross-reference guard firing on a body line that happens to open with `من`). Before reporting a shortfall, re-search the *exact* text the parser consumed for each missing number and split it into two lists: present-in-text-but-not-parsed (a parser defect) versus absent-from-text-entirely (a source or OCR gap). Report them separately. Never let a measurement failure read as a corpus fact — and when the file holds a pre-existing defect you did not cause, say so with the evidence (it fails in unmodified siblings too).

37. **Locate a missing unit by its neighbours before proposing a recovery for its page.** A shortfall has two independent causes needing different fixes: the page was *unreadable*, or the engine *read it and skipped content on it*. For each missing number, find the nearest present article before and after it in document order and note their pages — if both neighbours sit on pages that transcribed normally, the content was readable and the engine dropped it, so re-scanning that page recovers nothing. Measure this before building any split-and-merge recovery: on one code all 47 missing articles fell between pages that had transcribed fine (page 14 returned `19, 24, 25, 26`, skipping `20–23`), while the three genuinely unreadable pages held only boundary articles already captured from their neighbours. Splitting and re-scanning those pages would have recovered ~4 articles and none of the 47. See `references/ocr-provider-quirks.md`.

38. **An image on every page is a template, not content — fingerprint before you scan it.** When a page carries its text as an embedded raster, hash every image on the page: an image whose sha1 repeats across the whole document is a background template or masthead, and the page's real content is the image unique to that page. Compute the placed raster's effective DPI (`image_pixels / (placement_box_points / 72)`) — a large pixel count stretched over a bigger box is low-DPI and may be a distorted duplicate of the preceding page rather than new content. Also compare the suspect pages across the instrument's sibling copies (`raw/ar`, `raw/org`, …): if every copy is identical there, no re-download can rescue it. Note that `extract_vision_pages(pdf_path, pages=[...])` already accepts a 1-based page subset and returns one string per requested page in order, so "scan these pages separately and merge" needs no new capability — the only question is whether the measurement says it will help.

39. **`--force` opens the parse-state gate, not the text cache.** A force run deletes the output JSONs and reparses every document, then rebuilds each article tree from the *same* cached page text — no OCR, no VLM, no extraction. "Force" and "re-extract" are different operations, and conflating them produces a fix that verifiably changes nothing. Before promising that a run re-read a document, or before concluding a parser change had no effect, read the extraction cache's provenance `mode` (`native` / `vl` / `docling` / `ocr_forced`): an unchanged mode after a force run means nothing was re-extracted. Re-extract one document by deleting `data/corpus/<provider>/cache/<stem>_<hash12>.json` **and** `cache_vision/<stem>_<hash12>_vision.json` — the key is the first 12 hex of sha256 over the PDF's first 4 KB, so it changes when the PDF itself changes, but not when the cache format or the parser does. The cache is not unconditional: a hit is validated and a rejected one unlinked, but the gates are quality signals only, so "stale yet plausible" text passes them and is exactly what `--force` cannot fix. And before advertising any bypass or path override, grep for the parameter's *read* sites: a `cache_dir` accepted by the signature and never passed down to the extractor is a dead override (a local variable whose only occurrence is its own assignment). See `references/ocr-routing-and-config.md`.

40. **A provider is onboarded only when every registry that enumerates providers exposes it — and the admin manifest is GENERATED, not declarative.** Adding the `Settings` field and the provider-registry entry makes a provider *look* wired while it is not ingestible, is not scanned by the hierarchy index, and is invisible to the operator. The full registry table (parser route, ingest trigger, bulk-ingestion maps, provider registry, corpus hierarchy roots, corpus domain filter, log list, settings whitelist + generated manifest, admin fields, both panels), the generated-manifest pitfall, and the frontend-panel wiring are in `juritheque-scraper`'s `references/provider-wiring.md`. Read it before declaring a provider onboarded, and verify **end-to-end** — does `discover_documents(INGEST_PATH_<P>, provider=<p>)` actually return the corpus? — rather than by registry membership alone. Deliberately omit a crawler-panel entry for a provider with no crawler, and pin that omission with a test so it reads as a decision.

## Workflow

### Phase 1 — Provider Evaluation

1. **Check robots.txt and terms of use** — a public-domain platform with no specific prohibition is a clean target.
2. **Explore content via `browser_exec`** — the JS-rendered SPA requires a real browser.
3. **Download the sitemap** — typically 5-10 MB XML. Cache it both for the scraper and for later delta comparison.
4. **Classify document types** — Dahir, Loi, Décret, Arrêté, Circulaire, Ordonnance — one subfolder per type.

### Phase 2 — Scraper Construction

1. **Architecture** — `fetching/<provider>/scrape.py` as a standalone module runnable from `browser_exec` context. The browser helpers (`new_tab`, `wait_for_load`, `js`) are auto-imported into the browser_exec namespace only; importing them elsewhere fails.
2. **Metadata extraction** — always include: `reference`, `title_fr`, `title_ar` (where available), `instrument_type`, `domain`, `language`, `date`, `article_count`, `pdf_url`, `source_link`.
3. **Content expansion** — many JS-rendered pages hide the full law text behind a button (JuriThèque uses `عرض النص` / `Lire le texte intégral`). The scraper MUST click the expand button before reading `innerText`. `el.click()` is primary; `dispatchEvent` is fallback.
4. **Bilingual split** — line-by-line script detection with a sliding-window gap tolerance captures Arabic blocks even when digits and Latin citations are interspersed. Merge back to `full_text` when only one language is significant.
5. **Reference detection** — first 500 chars only. Use instrument-keyword-aware patterns (e.g. `Loi n° <digits>` not `\d+ anywhere`).
6. **Index file per (domain, language) pair** — `<domain>/<lang>/index.json` stores a flat list of {reference, instrument_type, title_fr, title_ar, date, source_url, file_path} for cross-provider comparison.
7. **Politeness and resilience** — `request_delay` >= 3s, `max_retries` >= 3, periodic browser reopen (every ~50 URLs) to prevent stale-tab leaks.

### Phase 3 — Iterative Debug Cycle

1. **Test locally** before dispatching full batch. Use `browser_exec` with the module loaded via `exec(open(...).read())`.
2. **If a page fails**, inspect the page structure live: what buttons exist, what the first 500 chars contain, whether article markers are present.
3. **Patch, re-test, commit with rollout update.**
4. **Don't loop patches** — if 3 consecutive patches yield no behavior change, stop and read the file fresh before the next edit.

### Phase 4 — Background Dispatch

1. **Interactive batch size: 10 URLs** — with 3s delays + browser navigate/read per URL, 10 URLs takes ~60-90s, safely within the browser_exec 300s timeout. Batch size 40 (the old guidance) ALWAYS times out and forces a restart. Use `batch_size=10` for interactive runs.
2. **Background dispatch for large scrapes** — for anything >50 URLs, use `delegate_task` to run the full scraper in a background subagent. The subagent has its own browser context and can run the full sitemap to completion without the 300s constraint.
3. **Resumable loop** — pass `start_index` from the previous batch's stats. The scraper re-reads the sitemap and skips already-indexed laws.
4. **Verify daemon** — confirm the background subagent is live (poll list or tail transcript) before declaring progress.
5. **Commit code + update rollout** after each feature-complete batch.
6. **Wipe-and-restart with explicit user confirmation** — `data/corpus/<provider>` deletion is irreversible. Always confirm before `rm -rf` on corpus data, even if the user's intent seems clear from context.

### Phase 5 — Rollout Tracking

- **ROLLOUT_MASTER_PLAN.md** — one section per data provider. Mark implementation status, known limitations, cross-provider comparison.
- **CHANGELOG.md** — every code change lands here.

## CLI Tools

The `mizan` CLI (`bin/mizan`) provides shortcuts for common operations:
- `mizan parse <provider> <file>` — run parser on a PDF
- `mizan audit [path]` — audit corpus quality
- `mizan search-debug <query>` — debug retrieval
- `mizan status` — corpus file counts, recent parses
- `mizan commit` — stage, verify (pytest + mypy), commit with docs

Full reference: `docs/MIZAN_CLI.md`

## Coding Workflow

When implementing changes, follow the generic coding workflow (adapted from freebuff patterns):
- Specialize agents by task type (parser-debugger, corpus-auditor, search-debugger)
- Propose edits before applying them
- Track progress with todo lists
- Verify changes with tests before committing
- Update CHANGELOG.md and affected docs in the same commit

Reference: `.mimocode/skills/coding-workflow/SKILL.md`

## References

- `references/browser-exec-scraper.md` — browser_exec context patterns, auto-imported helpers, pitfalls when running browser scrapers in subagent contexts.
- `references/api-first-scraping.md` — check for backend APIs (Supabase REST) before building browser scrapers; memory-efficient batch processing and resume patterns.
- `references/ocr-provider-quirks.md` — corrupted text layers (digit glyph transposition), OCR returning one line per page, transient model-runner failures, GGUF vs transformers runtime selection, endpoint config that must move base URL and wire format together, per-page failure isolation (a single rejected page discarding the whole pass), deterministic degenerate transcription that must not be retried, vision-hallucinated page furniture, compound Arabic article numbers truncated by the header matcher, page folios and mastheads becoming article nodes, and locating where missing content actually is (neighbour mapping, image fingerprinting, effective DPI, sibling-copy comparison, page-subset OCR). Read this when ingestion output looks plausible but counts are wrong, when numbers are unreliable, when a required engine is reported unavailable after one bad page, when article numbers repeat at low values while real provisions are missing, or before building a recovery path for a shortfall.
- `references/vision-ocr-service-ops.md` — operating a notebook-hosted vision-OCR service behind a tunnel: liveness vs readiness vs generation, warming the model with the request's own keying parameters, bounding the job store and the model's context, mapping malformed requests to 400 instead of 500, measuring throughput directly, and what `llamacpp` in `ollama ps` does and does not mean. Read this when an OCR endpoint looks healthy but produces nothing, when jobs sit `pending` then time out, or before reporting an endpoint as working.
- `references/ocr-routing-and-config.md` — the three OCR config layers (availability / route / engine), why `getattr(settings, ...)` means the setting does not exist, prefix-probing reader helpers that go dark on rename, gates trapped inside one dispatch branch, one shared engine selector with two-level fallback, content-hash OCR cache keys, what `--force` does and does not bypass (parse state vs the extraction/vision text caches), and the discipline for renaming a config key, backward-compatible aliases via `AliasChoices`, and classifying dead vs live-but-inert `.env` keys. Read this before adding an OCR engine or flag, when one provider's documents reach a different engine than another's, when renaming a setting, when a setting appears configured but behaves otherwise, or when a force run appears to change nothing.
- `references/sgg-bo-container-parsing.md` — SGG BO container parsing patterns: OCR-garbled references (digit reversal), cross-reference vs header disambiguation, variable Arabic TOC length detection, Arabic month name date parsing, and re-parse from cache without OCR. Read this when BO container JSONs are missing documents, articles are attributed to wrong documents, or `effective_date` is empty despite dates in titles.
