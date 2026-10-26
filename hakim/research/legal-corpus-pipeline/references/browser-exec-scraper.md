# Browser Exec Scraper Patterns and Pitfalls

## Helper Availability

The browser helpers (`new_tab`, `goto_url`, `wait_for_load`, `js`, `page_info`, `click_at_xy`, `fill_input`, `scroll`, `switch_tab`, `close_tab`) are **auto-imported into the `browser_exec` namespace** at runtime. They are NOT regular Python imports.

- ✅ Works: `new_tab(url)` directly inside `browser_exec` code
- ✅ Works: `exec(open('scraper.py').read()` then call functions — because `browser_exec` already has helpers in scope
- ❌ Fails: `import helpers` — `ModuleNotFoundError: No module named 'helpers'`
- ❌ Fails: standalone `python3 scraper.py` — helpers don't exist outside `browser_exec`
- ❌ Fails: importing `helpers` from a package — it's not a regular Python module

## Scraper Architecture Pattern

```python
# fetching/<provider>/scrape.py
def scrape_law(law_id, output_base, config):
    url = f"https://<provider>.com/laws/{law_id}"
    new_tab(url)
    wait_for_load()
    time.sleep(config.browser_wait)
    
    # Click expand buttons BEFORE reading text
    _click_full_text_button()
    time.sleep(1.5)
    
    page_text = js("document.body.innerText")
    html = js("document.documentElement.outerHTML")
    metadata = parse_page(page_text, html)
    write_json(metadata, output_base)
    return metadata
```

## Button Click Pitfalls

Pages that hide full text behind a button (JuriThèque, HuQuqAI, etc.):

1. **Button text varies by language**:
   - Arabic: `قراءة النص الكامل` / `عرض النص`
   - French: `Lire le texte intégral` / `Consulter le texte`
   - Pattern: `<action> <text>` where action varies

2. **Button uses custom JS event handlers**:
   - ✅ `el.click()` — triggers the handler reliably in most cases
   - ⚠️ `dispatchEvent(new MouseEvent('click', {bubbles: true}))` — may not trigger React handlers
   - Strategy: `el.click()` first, fallback to `dispatchEvent`

3. **Button is only present after another action**:
   - Some pages show "Consulter le texte" which opens a modal
   - The modal then contains "Lire le texte intégral" for the full article
   - Chain: page → modal → full text appears in `innerText`

## Bilingual Content Splitting

Moroccan legal pages mix French and Arabic:
- URLs: `/loi/<slug>` (French) and `/ar/loi/<slug>` (Arabic)
- Metadata titles: French first, Arabic second
- Full text: the PRIMARY language of the page

**Algorithm:**
1. Line-by-line: classify as Arabic if any char in U+0600–U+06FF
2. Group consecutive Arabic lines into blocks (gap tolerance ≤ 2 non-Arabic lines)
3. `content_fr` = French lines only
4. `content_ar` = Arabic blocks joined
5. Only set both fields when BOTH are significant (>100 chars)

## URL Sitemap Pattern

```python
import xml.etree.ElementTree as ET

def extract_law_urls(sitemap_content):
    root = ET.fromstring(sitemap_content)
    urls = []
    for url_elem in root.findall(
        ".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
    ):
        url = url_elem.text
        if "/loi/" in url:
            urls.append(url)
    return urls
```

## Failure Rate Reduction

| Problem | Root Cause | Fix |
|---------|------------|-----|
| Stale tabs accumulate | Browser holds 50+ tabs | Reopen every 50 URLs (`reopen_browser_interval`) |
| Cookie consent blocks rendering | Dialog overlays page | `_dismiss_consent_dialog()` after page load |
| Rate limiting | Too many rapid requests | `request_delay` >= 3s |
| Passing reference from body | Body has dates/related-law refs | Scan only title area (first 500 chars) |
| Empty full_text after button | `el.click()` didn't fire handler | Try `el.click()` before `dispatchEvent` |