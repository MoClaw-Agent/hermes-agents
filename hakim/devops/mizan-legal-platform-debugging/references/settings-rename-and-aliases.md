# Renaming an OCR Setting, and Wiring the Old Name

Covers the `getattr` fallback defect, prefix-chain breakage, and the compatibility
layer for renamed settings. Deep dive for the rename class of work; the one-line
version is "declare it as a typed field, land `.env` with the code, and prove it
through the settings object".

## A renamed-away prefix kills a chained lookup

A helper resolving a setting through provider-prefixed fallbacks:

```python
return getattr(settings, f"ISM_{name}", getattr(settings, f"ADALA_{name}", default))
```

works only while the field carries one of those prefixes. Collapse
`ADALA_VISION_OCR_ENABLED` and `ADALA_QARI_OCR_ENABLED` into an unprefixed
`VISION_ENGINE_ENABLED` and **neither branch matches** — the chain falls to
`default` and every caller reads `False`, silently, with no log line. The whole
provider's feature goes dark while the setting sits in `.env` set to `true`.

Add a bare-name tier last:

```python
for candidate in (f"ISM_{name}", f"ADALA_{name}", name):
    if hasattr(settings, candidate):
        return bool(getattr(settings, candidate))
return default
```

**Assert the resolved value is `True`, not merely that it equals the setting.**
Comparing the helper's output to `settings.X` proves nothing when both sides
come from the same broken chain — that test passes with the feature off. The
failure mode is "off", so name the enabled state.

```python
assert _ism_setting("VISION_ENGINE_ENABLED") is True
```

Check each provider's reader separately, not just the settings object:

```bash
venv/bin/python -c "from core.settings import settings; from fetching.ism.parser.pipeline import _ism_setting; \
  from fetching.pipeline_base.vision_pipeline import _vision_engine_enabled; \
  print(settings.FLAG, _ism_setting('FLAG'), _vision_engine_enabled())"   # all must agree
```

## A rename is one change spanning four surfaces

Splitting them leaves a silently-inert intermediate: the field is gone, so
`getattr(..., default)` returns the default and the setting reads as configured
while behaving otherwise.

1. declaration in the settings mixin
2. every consumer
3. `.env`
4. `.env.example`

**Land `.env` in the same commit as the code.** Renaming nine settings while
leaving the old keys in `.env` means all nine are unread for the length of that
commit — model and base URL silently fall back to code defaults.

Register renames in both admin registries, or `scripts/check_admin_field_drift.py`
fails: `core/settings/_admin_field_whitelist.py` and the `FIELD_META` table in
`api/routes/admin_config.py`.

## A blanket string replace corrupts longer names

Replacing `QARI_OCR_` also matches inside `ADALA_QARI_OCR_ENABLED`, collapsing
two distinct fields into one duplicate declaration. **Pydantic accepts a
duplicate and keeps one, so the second setting vanishes with no error and no test
failure.** Word-bound the pattern, and let the type checker arbitrate — it caught
this at pre-commit where Pydantic had not:

```bash
venv/bin/python -m mypy core/settings/     # pre-commit runs this zero-tolerance
```

## Sweep for undeclared keys — it finds more than the one you renamed

Add tests asserting `.env` and `.env.example` carry no key absent from
`Settings.model_fields`, no duplicates, and no drift between the two files. This
generalises the `getattr` defect. A single sweep caught three distinct classes:

- a leftover pair in `.env.example` from an earlier cleanup
- a key read via `getattr(settings, ..., None)` and applied only when not `None`,
  absent from `Settings` — so the `getattr` returned `None` and a `.env=true`
  never fired
- a `bool | None` field whose default **must stay `None`**: a `False` default
  would disable structured output for every deployment that never set it

Decide per key; do not delete in bulk:

| condition | action |
|---|---|
| no field, no reader | delete |
| read via `getattr`, live | declare it |
| not model-related, records intent for unwired work | comment out with the reason |
| genuinely undecided by the user | ask |

## Backward compatibility: AliasChoices, never a before-validator

```python
# WRONG — receives init kwargs and .env already merged, cannot tell the
# sources apart, so its "new key wins" rule overrides Pydantic's documented
# source precedence (a test proved it: the alias lost to .env).
@model_validator(mode="before")

# RIGHT — resolves per source; listing the current name first makes it win
# at every priority level.
VISION_OCR_BASE_URL: str = Field(
    "http://127.0.0.1:8888/v1",
    validation_alias=AliasChoices("VISION_OCR_BASE_URL", "QARI_OCR_BASE_URL"),
    description="...",
)
```

Two follow-ons:

**A changed *type* cannot be aliased.** Copying `True` into a `str` field yields
`"True"`, which the consuming resolver does not recognise and silently maps to
the *other* engine — an alias that looks like it works. Translate instead:

```python
@field_validator("OCR_ENGINE", mode="before")
@classmethod
def _normalize_engine_value(cls, value: object) -> object:
    if isinstance(value, bool):
        return "vision" if value else "ppocr"
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ("true", "1", "yes", "on"):
            return "vision"
        if token in ("false", "0", "no", "off"):
            return "ppocr"
    return value
```

**Assert the alias table and the `AliasChoices` wiring cannot drift apart** — a
name listed in the table but wired to no field silently does nothing:

```python
def test_every_legacy_name_is_declared_in_the_table() -> None:
    wired: set[str] = set()
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        if alias is None:
            continue
        choices = getattr(alias, "choices", None) or []
        wired.update(c for c in choices if isinstance(c, str) and c != name)
    assert set(_LEGACY_SETTING_ALIASES) <= wired
```

**Positional arguments must precede the keyword** `Field(...)` argument. Inserting
`validation_alias=` first raises `SyntaxError: positional argument follows
keyword argument`; put the default first. Every aliased field needs checking —
a scripted insertion gets most right and leaves one behind.

## Verify the migration end to end

Construction succeeding is not a migration. Write a real legacy `.env` of old key
names into a temp directory and assert the resolved values and each provider's
gate:

```bash
venv/bin/python - <<'PY'
import os, tempfile; from pathlib import Path
d = tempfile.mkdtemp()
Path(d, ".env").write_text("QARI_OCR_MODEL=legacy:q4\nVISION_OCR_ENABLED=true\n")
os.chdir(d)
from core.settings import Settings
from fetching.ism.parser.pipeline import _ism_setting
s = Settings()
print(s.VISION_OCR_MODEL, s.OCR_ENGINE, _ism_setting("VISION_ENGINE_ENABLED"))
PY
```

## A plan that schedules the config step after the code step is wrong

Sequencing `.env` edits in a later task than the code rename guarantees an inert
window. When a plan stages a rename across tasks, move the `.env` half into the
first task; likewise do not apply a later task's names inside an earlier one,
which produces phantom test failures because production still reads the old name.