# Multilingual Legal Corpus Patterns

## Instrument Type Detection

Moroccan legal instruments follow predictable name patterns. Detect from URL slug first (most reliable), then page text:

| Pattern | Instrument slug |
|---|---|
| Dahir, ظahir | dahir |
| Décret, مرسوم | decree |
| Loi, قانون | law |
| Arrêté, قرار | arrete |
| Circulaire, منشور | circulaire |
| Ordonnance | ordonnance |
| Convention | convention |
| Traité / Traite | treaty |
| Décision / Decision | decision |
| Code | code |

## Domain Classification

Common legal domains for Moroccan/French corpora:

| French name | Arabic name | Slug |
|---|---|---|
| Droit administratif | القانون الإداري | droit_administratif |
| Droit civil | القانون المدني | droit_civil |
| Droit commercial | القانون التجاري | droit_commercial |
| Droit du travail | قانون الشغل | droit_du_travail |
| Droit pénal | القانون الجنائي | droit_penal |
| Droit fiscal | القانون الجبائي | droit_fiscal |
| Droit constitutionnel | القانون الدستوري | droit_constitutionnel |
| Droit international | القانون الدولي | droit_international |
| Droit bancaire & financier | — | droit_bancaire_financier |

## Bilingual Edge Cases

### Arabic text detection
A line is Arabic-script if ANY character is in \u0600-\u06FF. For mixed lines (digits, punctuation), use char-count threshold > 50% of alphabetic chars.

### French quality headers
Common prefixes to strip:
- "Texte brut extrait du PDF — qualité variable"
- "Texte brut"
- "Lire le texte intégral (N blocs)"

### Arabic navigation cards
"قراءة المزيد" (read more) begins related-law recommendation sections. Everything after is unrelated to the target law:
```python
for marker in ["قراءة المزيد", "nقراءة المزيد"]:
    m = re.search(marker, text)
    if m:
        text = text[:m.start()].rstrip()
        break
```

## Metadata Extraction Order

1. **Title**: First line matching "Loi n°" / "Dahir n°" / "Décret n°" (FR), next line (AR)
2. **Reference**: From title area only (first ~500 chars), prefer instrument-name-adjacent matches
3. **Date**: First YYYY-MM-DD pattern in page
4. **Article count**: "N articles" pattern
5. **Source authority**: SGG / ADALA / Bulletin Officiel
6. **BO number**: "Bulletin Officiel n° N"
7. **PDF URL**: First .pdf link in HTML source
8. **Source link**: "Visiter la source" anchor
9. **External links**: Filtered to meaningful legal domains only

## Common Pitfalls

- **Reference**: Body text contains dates and related-law numbers. Restrict regex to title area.
- **Full text**: Includes related-law cards after Arabic "read more" markers. Strip at marker.
- **Quality headers**: French "Texte brut extrait du PDF — qualité variable" precedes actual law text.
- **External links**: CDNs (fonts.gstatic.com, googlesyndication), Supabase API, analytics must be filtered out.
