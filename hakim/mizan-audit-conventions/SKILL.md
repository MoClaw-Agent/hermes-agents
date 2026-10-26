---
name: mizan-audit-conventions
version: 1.0.0
description: Use when creating or filing Mizan audit reports.
author: hakim
license: MIT
metadata:
  hermes:
    tags: [audit, reporting, conventions, mizan]
    related_skills: []
---

# Mizan Audit Conventions

## When to Use

Use this skill when creating, filing, or naming audit reports for the Mizan project. Triggered by requests to write an audit, save an audit report, or organize audit files.

## Location

`doc/audits/` with subfolders by category:
- `retrieval/` — search and retrieval pipeline audits
- `citations/` — citation accuracy audits
- `legal-correctness/` — legal correctness audits
- `hallucinations/` — hallucination evaluation audits
- `ingestion/` — ingestion and OCR audits
- `comparative/` — comparative benchmark audits
- `general/` — uncategorized audits

## Naming

`YYYY-MM-DD_<subject>_audit_vNN.md`

- ISO 8601 date (YYYY-MM-DD)
- Lowercase kebab-case for descriptive fields
- Version suffix (v01, v02, etc.)

Examples:
- `2026-10-25_mizan-retrieval_audit_v01.md`
- `2026-10-25_citation-accuracy_audit_v01.md`
- `2026-10-25_legal-correctness_audit_labour-law_v01.md`

## Immutability

Keep original audit reports immutable. Create a new version or dated report instead of overwriting previous results.

## Stable IDs

Use `AUD-NNNN_` prefix only when tracking the same audit across multiple runs or linking to tickets:
`AUD-0042_2026-10-25_mizan_citation-accuracy_labour-law.md`

## When creating an audit

1. Determine the category and place in the correct subfolder.
2. Use the naming convention above.
3. Increment version if a prior audit of the same subject exists.
4. Never overwrite — create a new versioned file.
5. Update `doc/audits/_INDEX.md` if it exists.
