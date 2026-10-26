---
# Empty Section Merging — Tree Surgery for Legal Document Structure

## Problem

When parsing legal documents into structured trees, some sections are created with titles but no content. The content is usually in an adjacent sibling section — the parser split the content incorrectly.

Example from Arabic ADALA finance law:
```
{
  "type": "section",
  "title": "-كلغ 200 من القسم الأول 1 محتوية على مكونات القنب الهندي الموصوفة في",
  "content": "",
  "children": []
}
```
The actual product descriptions are in sibling sections.

## Repair Strategy

**Merge empty section titles into the next sibling with content.** Do not drop them — the title contains meaningful structural information.

### Algorithm (Chained Accumulator)

When empty sections alternate with non-empty ones (common in tariff grids and list-style legislation), merging only the immediately preceding empty section is insufficient — every other empty section would be lost. Use a chained accumulator instead:

1. Walk the structure tree depth-first
2. Maintain a `_pending_empty_titles` list (accumulates consecutive empty section titles)
3. When encountering an empty section with a title, append the title to `_pending_empty_titles`
4. When encountering a non-empty section, prepend ALL accumulated titles joined by `; ` to its content, then clear the list
5. If `_pending_empty_titles` is non-empty at the end of a container's children, drop them (no next sibling)
6. Recurse into `children` of all node types (section, chapter, title, book, part)

```python
_pending_empty_titles: list[str] = []
prev_section = current["section"]
if prev_section and not prev_section.get("content"):
    prev_title = prev_section.get("title", "")
    if prev_title:
        _pending_empty_titles.append(prev_title)
if _pending_empty_titles and n.get("content"):
    n["content"] = "; ".join(_pending_empty_titles) + ": " + n["content"]
    _pending_empty_titles.clear()
elif _pending_empty_titles:
    pass  # keep accumulating
```

Apply the same pattern to all container types (section, chapter, title, book, part) — each has its own `current` slot and its own pending accumulator.

## Edge Cases

1. Walk the structure tree depth-first
2. Track a `pending_empty_title` variable
3. When encountering an empty section with a title, save the title to `pending_empty_title`
4. When encountering a non-empty section, prepend `pending_empty_title` to its content
5. Chain multiple empty sections: `title1 — title2 — title3`
6. If the tree ends with pending empty titles (no next sibling), drop them

### Python Implementation

```python
def fix_empty_sections(structure) -> tuple[list, int]:
    """Merge empty section titles into next sibling's content."""
    if not structure:
        return structure, 0
    
    fixed = []
    pending_empty_title = None
    num_fixed = 0
    
    for item in structure:
        if item.get("type") == "section":
            content = item.get("content", "")
            if not content or not content.strip():
                # Empty section — save title for merging
                title = item.get("title", "")
                if title:
                    pending_empty_title = (
                        f"{pending_empty_title} — {title}"
                        if pending_empty_title else title
                    )
                continue
            else:
                # Non-empty section — prepend pending titles
                if pending_empty_title:
                    existing = item.get("content", "")
                    item["content"] = f"{pending_empty_title}: {existing}"
                    pending_empty_title = None
                    num_fixed += 1
                
                # Recurse into children
                if item.get("children"):
                    fixed_children, child_fixes = fix_empty_sections(item["children"])
                    item["children"] = fixed_children
                    num_fixed += child_fixes
                
                fixed.append(item)
        else:
            # Non-section item
            if pending_empty_title:
                pending_empty_title = None  # Drop trailing empty sections
            
            if item.get("children"):
                fixed_children, child_fixes = fix_empty_sections(item["children"])
                item["children"] = fixed_children
                num_fixed += child_fixes
            
            fixed.append(item)
    
    return fixed, num_fixed
```

## Edge Cases

## When NOT to Use This

- If the empty section's content exists elsewhere in the document (not in a sibling), a different merge strategy is needed
- If sections are genuinely empty by design (e.g. placeholder sections in draft laws), investigate before merging
