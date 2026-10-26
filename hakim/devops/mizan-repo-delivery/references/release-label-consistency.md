# Release-label consistency

`VERSION` (the repository label), `pyproject.toml` (the PEP 621 canonical
source), the runtime version (derived from `pyproject.toml`), the CHANGELOG's
top entry and the packaging build are sources that drift independently.
`git status` never shows the drift.

## Check the CONSUMERS, not just the value

A label can be correct while the machinery that consumes it is broken. A build
that reads the version from a module that was moved or deleted resolves it to
the EMPTY STRING, and every artifact it names carries that empty version
(`mizan-.tar.gz`, `mizan__all.deb`) — while the runtime reports the right
version and every doc quotes the right label. Nothing surfaces it.

Find the consumers with a filename-level grep, and grep for the OLD source
path as well as the new one:

```bash
grep -rn "VERSION" --include=Makefile --include=*.sh --include=*.py . \
  | grep -vE "venv/|__pycache__|STATE_SCHEMA|CURRENT_VERSION|BACKFILL_VERSION"
```

| consumer | how it gets the version | what a broken source looks like |
|---|---|---|
| `VERSION` | the label file itself | a stale label quoted by the docs |
| `pyproject.toml` | canonical | the runtime and the build disagree |
| runtime | `core/settings/_version.py` → pyproject | — |
| `CHANGELOG.md` | the top versioned entry | the release record names another release |
| `Makefile` | `VERSION ?= …` | an EMPTY version → `mizan-.tar.gz` |
| the packager | `$VERSION` | the same, in the DEB/RPM names |
| the manual build | pyproject → runtime → `VERSION` | the manual shows another release |
| the docs | a stated label | the docs advertise a release that is not the code |

Derive every build path from `pyproject.toml` and keep the `VERSION` file as
the fallback, and make the build FAIL LOUDLY when no version resolves rather
than naming an artifact after an empty string.

## Current vs historical

A blind replace of the version string corrupts the record. These phrasings
state the CURRENT label and must be updated; the rest are records of their
time and must be left alone.

| current — update | historical — leave |
|---|---|
| `**Repository release label:** vX.Y.Z` | `## [vX.Y.Z] — release entry` (the changelog) |
| `**Current repository release label:** vX.Y.Z` | `see CHANGELOG vX.Y.Z` (a pointer to where a change was recorded) |
| `**Current release label:** vX.Y.Z` | a dated release narrative |
| `**Release label:** vX.Y.Z` | a commit message quoting a past release |
| `**Version reference:** vX.Y.Z` | an audit report's dated observation |
| `**Current checkout:** vX.Y.Z` | |
| `both report X.Y.Z` / `all report X.Y.Z` | |
| `Both currently resolve to X.Y.Z` | |

So: search for the PHRASINGS, not for the version string. A document that
quotes a historical release must not be rewritten, and a document that states
the current one must not be missed.

## Pin it with a gate test

Three facts, each a separate assertion:

1. the label file == `pyproject.toml`;
2. the label file == the newest changelog entry;
3. every document that quotes the label quotes the current one.

For (3), scan a fixed list of documents for the phrasings above rather than
for the version string.

When asserting that a file path is absent from a build script, strip comment
lines first: a comment may legitimately NAME the file that was removed, and a
naive substring check then fails on the explanation of the fix.

## Drive the sync from the GATE's file list, not a hand-made one

A hand-kept list of "the docs that quote the label" will miss one — and the
missing one is caught only by the release-label gate, after the wave's code
commit is already made, forcing a second commit for a one-line fix.

So: read the file list OUT of the gate test (`tests/test_release_label_sync.py`)
and sync exactly that list. The gate is the specification; a hand list is a
guess that drifts from it. The phrasings table above tells you WHICH lines to
edit inside each file; the gate tells you WHICH files to open.

Then run the gate before committing, not after — the release-label gate is the
cheapest check in the repo and it is the one most likely to catch a missed file.
