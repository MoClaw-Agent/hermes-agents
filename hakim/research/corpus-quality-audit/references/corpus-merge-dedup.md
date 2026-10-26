# Corpus Merge & Deduplication Reference

## Overview

When two ingested legal corpora share overlapping laws (same `ref` values), produce one clean corpus that combines the best of both. This reference covers the full merge workflow: indexing, overlap detection, SOTA merging per overlapping ref, copying non-overlapping files, and verification.

## Indexing Both Corpora

Build a `ref → path` dict for each corpus:

```python
adala_index = {}
for jf in ADALA_DIR.rglob("*.json"):
    d = json.loads(jf.read_text(encoding="utf-8"))
    ref = d.get("ref", "")
    if ref:
        adala_index[ref] = jf

jur_index = {}
for jf in JURITHEQUE_DIR.rglob("*.json"):
    d = json.loads(jf.read_text(encoding="utf-8"))
    ref = d.get("ref", "")
    if ref:
        jur_index[ref] = jf
```

Then compute the sets:
```python
common_refs = set(adala_index) & set(jur_index)
adala_only = set(adala_index) - set(jur_index)
jur_only = set(jur_index) - set(adala_index)
```

**Pitfall:** `adala_index` and `jur_index` are dicts, not sets. Use `set(adala_index)` to get the set of keys before doing set arithmetic. Writing `adala_index - common_refs` fails with `TypeError: unsupported operand type(s) for -: 'dict' and 'set'`.

## SOTA Merge per Overlapping Ref

For each `ref` in `common_refs`, load both JSONs and produce one merged file.

### Step 1: Metadata merge (best-of field by field)

```python
def merge_metadata(da, dj):
    merged = {}
    merged["ref"] = da.get("ref") or dj.get("ref", "")
    ta, tj = da.get("title","") or "", dj.get("title","") or ""
    merged["title"] = ta if len(ta) >= len(tj) else tj

    ea, ej = da.get("extraction_mode","") or "", dj.get("extraction_mode","") or ""
    if "native" in ea.lower():
        merged["extraction_mode"] = ea
    elif "native" in ej.lower():
        merged["extraction_mode"] = ej
    elif ea:
        merged["extraction_mode"] = ea
    else:
        merged["extraction_mode"] = ej

    merged["source_file"] = da.get("source_file") or dj.get("source_file","")
    merged["source_provider"] = da.get("source_provider") or dj.get("source_provider","")
    merged["source_url"] = da.get("source_url") or dj.get("source_url","")

    for f in ["parsed_at","effective_date","timestamp"]:
        merged[f] = da.get(f) or dj.get(f,"")

    merged["full_text_in_cache"] = bool(da.get("full_text_in_cache") or dj.get("full_text_in_cache"))

    na, nb = da.get("num_articles_detected"), dj.get("num_articles_detected")
    merged["num_articles_detected"] = max(
        na if isinstance(na,(int,float)) else 0,
        nb if isinstance(nb,(int,float)) else 0)

    ha, hb = da.get("has_article_structure"), dj.get("has_article_structure")
    if ha is True or hb is True:
        merged["has_article_structure"] = True
    elif ha is False and hb is False:
        merged["has_article_structure"] = False
    else:
        merged["has_article_structure"] = None

    # Copy remaining fields from better-quality source
    merged["language"] = da.get("language") or dj.get("language","ar")
    merged["document_type"] = da.get("document_type") or dj.get("document_type","")
    for f in ["collection_title","collection_path"]:
        merged[f] = da.get(f) or dj.get(f,"")
    for f in ["norm_rank","norm_level","normative_weight",
               "source_authority","legal_domain","is_amendment",
               "amends_document_ref","amendment_note"]:
        merged[f] = da.get(f) if da.get(f) is not None else dj.get(f)

    # List fields: merge with dedup via JSON normalization
    for f in ["tables","references","relationships","camel_entities","related_refs"]:
        va, vb = da.get(f), dj.get(f)
        if va and isinstance(va,list) and vb and isinstance(vb,list):
            merged[f] = [json.loads(x) for x in
                         {json.dumps(x,sort_keys=True) for x in va+vb}]
        elif va:
            merged[f] = va
        elif vb:
            merged[f] = vb
    return merged
```

### Step 1.5: Prune French subtrees from JurThèque structure

When merging Arabic corpora, the JurThèque side may contain structure nodes whose `language` field is `"fr"` (French sections). These must be stripped before merging so the output is purely Arabic.

```python
def _prune_fr_subtrees(tree):
    """Deep-copy ``tree``, removing any node whose ``language == "fr"``
    and all its descendants. Returns the pruned tree (or None if the
    root itself is French)."""
    if tree is None:
        return None
    if isinstance(tree, dict):
        if tree.get("language") == "fr":
            return None
        prune = {k: _prune_fr_subtrees(v)
                 for k, v in tree.items() if k != "children"}
        ch = _prune_fr_subtrees(tree.get("children"))
        if ch:
            prune["children"] = ch
        return prune
    if isinstance(tree, list):
        return [c for c in (_prune_fr_subtrees(x) for x in tree)
                if c is not None]
    return tree
```

Apply to the JurThèque structure before `merge_structures`:

```python
struct_a = da.get("structure")
struct_b = _prune_fr_subtrees(dj.get("structure"))
merged["structure"] = merge_structures(struct_a, struct_b)
```

Also apply in `copy_and_fix` for JurThèque-only files so single-copy output is clean. Without pruning, French articles leak into the Arabic merged corpus — in this project 1,087 of 7,037 JurThèque files carry French subtrees.

```python
def merge_structures(base_tree, other_tree):
    base = deepcopy(base_tree) if base_tree else []
    other = deepcopy(other_tree) if other_tree else []
    if not base: return other
    if not other: return base

    arts_a = flatten_articles(base)
    arts_b = flatten_articles(other)
    all_nums = set(arts_a) | set(arts_b)

    merged_arts = {}
    for num in all_nums:
        na, nb = arts_a.get(num), arts_b.get(num)
        if na and nb:
            ca = len(na.get("content","") or "")
            cb = len(nb.get("content","") or "")
            merged_arts[num] = deepcopy(nb if cb > ca else na)
        elif na:
            merged_arts[num] = deepcopy(na)
        elif nb:
            merged_arts[num] = deepcopy(nb)

    qa, qb = tree_quality(base), tree_quality(other)
    if qb > qa:
        base = deepcopy(other)

    base_arts = flatten_articles(base)

    def replace_articles(nodes):
        for n in (nodes or []):
            if not isinstance(n, dict): continue
            if n.get("type") == "article" and n.get("number") is not None:
                num = n["number"]
                if num in merged_arts:
                    n.clear()
                    n.update(merged_arts[num])
                    merged_arts.pop(num)
            replace_articles(n.get("children"))
    replace_articles(base)

    if merged_arts:
        remaining = list(merged_arts.values())
        def attach(nodes):
            for n in (nodes or []):
                if not isinstance(n, dict): continue
                if n.get("type") in {"book","chapter","section","title"} and n.get("children"):
                    n["children"].extend(remaining)
                    remaining.clear()
                    return True
                if attach(n.get("children")): return True
            return False
        if not attach(base):
            if isinstance(base, list): base.extend(remaining)
            elif isinstance(base, dict): base.setdefault("children",[]).extend(remaining)

    # ── Post-merge: strip empty containers ──────────────────────────────
    def _strip_empty(tree):
        """Drop container nodes with no content and no children; drain their
        titles into the next non-empty sibling's content. Returns the count of
        empty containers that could not be stripped (leaf empties are counted
        but dropped). """
        if not tree:
            return 0
        if isinstance(tree, dict):
            tree = [tree]
        total_unstripable = 0
        for parent in (tree or []):
            if not isinstance(parent, dict):
                continue
            ch = parent.get("children")
            if not ch:
                continue
            cleaned = []
            pending_title = ""
            for child in (ch or []):
                if not isinstance(child, dict):
                    cleaned.append(child)
                    continue
                ct = (child.get("content") or "").strip()
                is_container = child.get("type") in {"section","chapter","title","book","part"}
                children = child.get("children")
                is_empty_leaf = is_container and not ct and not children
                is_empty_parent = is_container and not ct and children
                if is_empty_leaf:
                    t = (child.get("title") or "").strip()
                    if t:
                        pending_title = (pending_title + "\n" + t).strip() if pending_title else t
                    total_unstripable += 1
                    continue
                if is_empty_parent:
                    t = (child.get("title") or "").strip()
                    if t:
                        pending_title = (pending_title + "\n" + t).strip() if pending_title else t
                    total_unstripable += _strip_empty(children)
                    # After recursion: if container is now empty, drop it
                    if not child.get("children"):
                        continue
                    child["children"] = children
                    cleaned.append(child)
                    continue
                if is_container and (ct or child.get("children")):
                    if pending_title:
                        child["content"] = (pending_title + "\n" + ct).strip() if ct else pending_title
                        pending_title = ""
                    total_unstripable += _strip_empty(child.get("children"))
                    # After recursion: if container is now empty, drop it
                    if not child.get("children"):
                        continue
                    cleaned.append(child)
                else:
                    if pending_title:
                        ct2 = (child.get("content") or "").strip()
                        child["content"] = (pending_title + "\n" + ct2).strip() if ct2 else pending_title
                        pending_title = ""
                    cleaned.append(child)
            if pending_title and cleaned:
                first = cleaned[0]
                if isinstance(first, dict):
                    ct = (first.get("content") or "").strip()
                    first["content"] = (pending_title + "\n" + ct).strip() if ct else pending_title
            parent["children"] = cleaned
        return total_unstripable

    warn_count = _strip_empty(base if isinstance(base, list) else [base])
    if warn_count > 0:
        logger.warning(
            f"{out_path}: {warn_count} empty containers remain after stripping — "
            "likely unfixable by tree surgery (nested-empty chains). "
            "Manual review or re-OCR recommended."
        )

    return base
```

This reduces empty containers in merged files like the 2025 finance law (ref 1.24.65) from 28 to 0 (or near-0).

### Step 2: Apply parser fixes to merged output

```python
# Masthead repair on page texts (pass doc_ref for issue number fallback)
if merged.get("page_texts_sample"):
    merged["page_texts_sample"] = [
        repair_masthead(p, merged.get("ref","")) if isinstance(p, str) else {
            **p, "text": repair_masthead(p.get("text",""), merged.get("ref",""))
        }
        for p in merged["page_texts_sample"]
    ]

# Masthead repair on full text
if merged.get("full_text"):
    merged["full_text"] = repair_masthead(merged["full_text"], merged.get("ref",""))

# Set flags from actual structure
if merged.get("structure"):
    articles = flatten_articles(merged["structure"])
    merged["has_article_structure"] = len(articles) > 0
    merged["num_articles_detected"] = len(articles)

# Recompute hash
merged["content_hash"] = content_hash(merged)
```

### Step 3: Copy non-overlapping files — preserve ADALA subfolder structure

```python
for ref in sorted(set(adala_index) - common_refs):
    copy_and_fix(adala_index[ref], OUT_DIR / f"{ref}.json", ref)

for ref in sorted(set(jur_index) - set(adala_index)):
    copy_and_fix(jur_index[ref], OUT_DIR / f"{ref}.json", ref)
```

Where `copy_and_fix` applies the same masthead repair (with doc_ref passed through), flag setting, French pruning, and hash recompute to single-file copies.
```python
# Masthead repair on page texts
if merged.get("page_texts_sample"):
    merged["page_texts_sample"] = [
        repair_masthead(p) if isinstance(p, str) else {
            **p, "text": repair_masthead(p.get("text",""))
        }
        for p in merged["page_texts_sample"]
    ]

# Masthead repair on full text
if merged.get("full_text"):
    merged["full_text"] = repair_masthead(merged["full_text"])

# Set flags from actual structure
if merged.get("structure"):
    articles = flatten_articles(merged["structure"])
    merged["has_article_structure"] = len(articles) > 0
    merged["num_articles_detected"] = len(articles)

# Recompute hash
merged["content_hash"] = content_hash(merged)
```

### Step 4: Copy non-overlapping files

```python
for ref in sorted(set(adala_index) - common_refs):
    copy_and_fix(adala_index[ref], OUT_DIR / f"{ref}.json")

for ref in sorted(set(jur_index) - set(adala_index)):
    copy_and_fix(jur_index[ref], OUT_DIR / f"{ref}.json")
```

Where `copy_and_fix` applies the same masthead repair, flag setting, and hash recompute to single-file copies.

## Verification

```python
total = len(list(OUT_DIR.rglob("*.json")))
expected = (len(common_refs) +
            len(set(adala_index) - common_refs) +
            len(set(jur_index) - set(adala_index)))
assert total == expected, f"Expected {expected}, got {total}"

missing_hash = sum(1 for jf in OUT_DIR.rglob("*.json")
                   if not json.loads(jf.read_text()).get("content_hash"))
assert missing_hash == 0, f"{missing_hash} files missing content_hash"

garbled = 0
for jf in OUT_DIR.rglob("*.json"):
    d = json.loads(jf.read_text())
    for p in (d.get("page_texts_sample") or []):
        txt = p.get("text", p) if isinstance(p, dict) else p
        if "((19 ( مسيد" in txt or "يدامج" in txt:
            garbled += 1
print(f"Garbled mastheads remaining: {garbled}")
```

## CLI Interface

```python
parser = argparse.ArgumentParser(
    description="SOTA Merge: ADALA + JurThèque Arabic law corpora")
parser.add_argument("--output", "-o", type=Path,
    default=Path("/home/mohammed/Mizan/data/corpus/merged_ar"),
    help="Output directory (default: %(default)s)")
parser.add_argument("--adala", type=Path,
    default=Path("/home/mohammed/Mizan/data/corpus/adala/json/backup/ar"),
    help="ADALA corpus root (default: %(default)s)")
parser.add_argument("--jurtheque", type=Path,
    default=Path("/home/mohammed/Mizan/data/corpus/juritheque"),
    help="JurThèque corpus root (default: %(default)s)")
args = parser.parse_args()
```

## Python Scoping Pitfall

When a nested function reassigns a variable from the enclosing scope, Python treats it as local unless declared `nonlocal`:

```python
def count_nonempty_containers(tree):
    count = 0
    def walk(nodes):
        nonlocal count  # REQUIRED — without this, UnboundLocalError
        for n in (nodes or []):
            if n.get("type") in {"section","chapter","title","book","part"} and n.get("content"):
                count += 1
            walk(n.get("children"))
    walk(tree)
    return count
```

Without `nonlocal count`, the `count += 1` line raises `UnboundLocalError: cannot access local variable 'count' where it is not associated with a value`. This bit the merge script during development.

## f-String Variable Name Typos

A typo like `ada_only_count` vs `adala_only_count` in an f-string produces a `NameError` at runtime. The typo is invisible in review because both names look similar. Always run:

```bash
python -m py_compile script.py
```

before executing a new script. This catches syntax errors and undefined-name errors at compile time, before the first run.

## Garbled Masthead Variants

The masthead repair regex handles one OCR garble variant. When merging two corpora, test both copies' pages. The JurThèque copy of a finance law may have a slightly different garble on pages 2+ than the ADALA copy:

- ADALA copy: `((19 (مسيد 91(1( 17 ج 1 خالا يدامج 717 - 7362 عدد 9754 الجريدة الرسمية`
- JurThèque copy: `((19 (مسيد 91(1( 17 ج 1 خالا يدامج 717 - 7362 عدد الجريدة الرسمية` (number and "الجريدة الرسمية" run together without space)

If some pages survive with garble after the merge, expand the regex to cover the additional variant, or add a second repair pass targeting the specific variant.
