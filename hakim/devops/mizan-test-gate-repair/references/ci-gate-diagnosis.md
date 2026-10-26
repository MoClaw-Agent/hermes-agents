# CI gate diagnosis recipes

Concrete commands for "which gate is red, why, and is it mine".

## Per-workflow status sweep

```bash
for w in "admin-field-drift" "CI" "mypy type-check" "Dead-File Audit (v1.105.0, strict since v1.106.0)"; do
  printf "%-55s " "$w"
  gh run list --workflow="$w" --limit 1 --json conclusion,createdAt \
    -q '.[0] | .conclusion + " @ " + .createdAt'
done
```

A workflow with no runs is a workflow that never triggers — check its `paths:`
filter against the files you actually changed before concluding it is green.

## Has this gate EVER been green?

```bash
gh run list --workflow="mypy type-check" --limit 100 \
  --json conclusion,createdAt,headSha \
| python3 -c "
import json,sys,collections
d=json.load(sys.stdin); d.sort(key=lambda r:r['createdAt'])
print('runs',len(d),'first',d[0]['createdAt'],d[0]['conclusion'])
print(collections.Counter(r['conclusion'] for r in d))
"
```

`failure: N` with **zero** successes means the gate has been mis-configured from
birth. Do not attribute it to the change under review.

## Read the failing job's log

```bash
run_id=$(gh run list --workflow="<name>" --limit 1 --json databaseId -q '.[0].databaseId')
job_id=$(gh api repos/<owner>/<repo>/actions/runs/$run_id/jobs --jq '.jobs[0].id')
gh api repos/<owner>/<repo>/actions/jobs/$job_id/logs | strings \
  | grep -iE "error|Traceback|exit code|Process completed"
```

`gh run view --log-failed` returning an empty file is common; the
`actions/jobs/<id>/logs` endpoint is the reliable source. Pipe through
`strings` or `grep` reports "binary file matches" and prints nothing.

## The two scopes of the mypy gate

```bash
# pre-commit hook scope (core only) — what a local `make mypy` proves
MYPYPATH=. venv/bin/python -m mypy api core retrieval reasoning ingestion graph ontology query billing services

# CI scope (core + ancillary) — what the gate actually requires
MYPYPATH=. venv/bin/python -m mypy api core retrieval reasoning ingestion graph ontology query billing services \
  fetching scripts tools ner evaluation
```

The CI scope checks a larger file set and can report errors the hook never
sees. Always report the scope you ran.

## Common CI failure classes in the ancillary scope

| Symptom in the log | Cause | Fix |
|---|---|---|
| `Library stubs not installed for "X"` / `Cannot find implementation or library stub for module named "X"` | package ships no stubs and is not in the `[[tool.mypy.overrides]]` `ignore_missing_imports` list | add the module to the override list, or add `# type: ignore[import-not-found]` at the import |
| `Cannot find implementation or library stub for module named "X"` where X ships a stub package | stub package not installed in the CI job | add `types-X` to the workflow's `pip install` line |
| `No module named 'pydantic'` / exit code 2 from a settings-importing script | `pip install -e .` installs no runtime deps (`dependencies = []`) | install the deps the script imports in the workflow |
| `attr-defined` on a settings field | the setting was renamed; the caller still uses the old name | update the caller to the canonical name (do not re-add the old alias) |
| `name-defined` for a type imported only in a TYPE_CHECKING block | a runtime-used symbol was never imported at module level | import it for real, or move the usage under `TYPE_CHECKING` |
