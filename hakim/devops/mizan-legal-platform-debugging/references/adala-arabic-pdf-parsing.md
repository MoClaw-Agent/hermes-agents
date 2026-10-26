# ADALA Arabic PDF parsing — text sources, numbering, and "missing" articles

## Two text sources disagree; neither wins per document

- The **native text layer** (fitz) carries article headers and numbers faithfully but shreds words (lam-alef decomposition: `اال`, `األ`, `الحاالت`) and breaks dates across lines.
- **Vision OCR** reconstructs clean words but drops or garbles article headers on dense pages.
- Choose **per page**, by distinct article identities — not per document, and not by raw match count. Ties go to the vision engine (cleaner words).
- Cross-references (`وفقا للفصل 25`) match the header pattern, so a page that merely *cites* articles outscores one that *defines* them under a raw count. Count distinct `(number, label)` identities.
- The native layer cannot represent compound identifiers (`الفصل 1-35` shreds across lines). Require it to beat the alternative by more than the compounds it would lose, or it wins on a marginal count while discarding real provisions.

## Moroccan numbering

- `المادة` numbers operative units; `الفصل` numbers them in older codes/dahirs but numbers *chapters* in modern statutes. Decide per document by density, and only when the numbering looks like an article sequence (low starting values) so code-numbered tariff grids cannot flip the document.
- **Compound provisions**: «الفصل <provision>-<code>» (`الفصل 1-35`, `الفصل 4-218-42`). Reading only the leading component collapses every provision of a code onto the same few numbers and collides with the real articles. Carry the full identity as a label *and* include it in the dedup key. Require the hyphen flush — `المادة 5 - يجب` is article 5 followed by a dash.
- Container scope is `(number, title)`, not `number` alone: a code can carry several distinct «الجزء الأول» parts all numbered 1.
- Inserted provisions: `المادة 41 مكرر` is a distinct unit from `المادة 41`; identity is `(number, qualifier)`.
- A bare 1–2 digit line is not an article when the page's headers carry the `الفصل`/`المادة` keyword — it is a date fragment (`22` then `أغسطس 2024`) or an enumeration item. Suppress it only on pages that have keyword headers; where they are absent the bare number is the only structural signal.
- A standalone number equal to its page's 1-based index, at the end of that page, is a printed folio — not an article.

## "Missing" articles are often correctly absent

Before treating an absent article as a parser defect, resolve it against the source — and **read the page, do not infer from neighbours**:

- `الفصول 19 - 23` followed by `نسخت` (repealed) means those numbers exist only as a range reference. A footnote usually names the repealing law and where the content moved.
- Block ranges (`الفصل من 494 إلى 496`) appear inside amendment notes.
- Neighbour arithmetic ("the item before is 18, the one after is 24, so 19–23 must be missing") produces a wrong fix. Verify by reading.
- A page can be genuinely blank in the native layer while carrying content as an embedded scanned image (~100 dpi). A shared background template image appears on *every* page, so filter images by hash before concluding a page is contentless.

Report the split — provably-absent vs genuinely-dropped. Fixing the whole set wastes effort, and "restoring" repealed numbers injects content the document does not contain.

## OCR endpoints

- The vision route accepts a **page subset** (`extract_vision_pages(pdf_path, pages=[...])`), returns one string per requested page in ascending order, and persists to a cache keyed by content hash. Confirm the cache exists before assuming a re-parse will re-OCR.
- A degenerate page (VLM repetition loop) raises out of the per-page call: isolate each page so one bad page cannot abandon the whole document, and treat "degenerate transcription" as a **deterministic** failure — do not retry it.
- Raising the render DPI does not recover a page the model already skipped; verify the cause (missing content vs skipped content) before treating it as a resolution problem.

## Ref extraction pitfalls

- A derivative/implementing instrument's title cites the law it implements, so a *loose* instrument-marker pattern returns the cited law's number instead of the instrument's own. The instrument word adjacent to the number is the discriminator.
- `filename.rsplit('.', 1)[0]` strips a dot-segment that may be part of the reference itself (`1.12.34` -> `1.12`). Strip the crawler timestamp first, then only a real file extension.
- BO issue numbers exist only in the `bo_<issue>_<lang>` naming convention. A bare first-digit-run search returns the instrument reference's leading digit (`1.59.413` -> `1`) — a wrong BO number, not a missing one.
- `legal_rank` is derived from the validated `doc_type`; any rank the fallback classifier can return must be a key in that mapping, or the two paths disagree silently.
