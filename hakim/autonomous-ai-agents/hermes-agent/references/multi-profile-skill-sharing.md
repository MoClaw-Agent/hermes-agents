# Multi-Profile Skill Sharing

How to share one skill library across multiple Hermes profiles without breaking skill loading.

## Pattern

One git repo holds a subfolder per profile. Each profile's `skills/` directory is a symlink to its subfolder.

```
# Repo layout
hermes-agents/
  default/
  hakim/
  <profile>/

# Per profile
~/.hermes/profiles/<name>/skills -> /path/to/hermes-agents/<name>
```

## Setup steps

1. Create the shared repo with one subfolder per profile.
2. Copy each profile's existing skills into its subfolder (exclude `.git`).
3. Commit and push from the repo root (changes land under the profile subfolder).
4. Replace the profile's `skills/` directory with a symlink to the subfolder. Keep a backup (`skills.<name>-backup`) until verified.
5. Verify Hermes still loads skills through the symlink (`skill_view` a known skill).
6. Only then remove the backup and the old standalone repo.

## Commit workflow after setup

- Edit files under the symlinked `skills/` path.
- Run git commands from the repo root, not from the symlinked directory (the symlink has no `.git`).
- Commit messages should scope by profile: `feat(hakim): ...`, `fix(default): ...`.

## Pitfalls

- A "move" is not a copy: leaving the old repo in place means two sources of truth. Finish the move by deleting the old repo only after the new location is verified working — and only with explicit permission, since repo deletion is destructive and needs the `delete_repo` scope.
- Git operations must run from the repo root; the symlinked skills dir has no `.git`, so `git status` there reports "not a git repository".
- When a cloned reference repo moves, update every path that pointed at it (skill SKILL.md files, `config.yaml` `framework_path`, AGENTS.md). Verify the new path actually contains the expected file (`AGENTS.md`) before trusting the update — do not assume the folder was renamed vs. nested.
- Do not repoint a profile whose skills are bundled Hermes skills (the default profile's `~/.hermes/skills`) without first copying them into the shared repo; otherwise the profile loses its bundled skill set.
- Deleting a GitHub repo requires the `delete_repo` OAuth scope; if `gh auth refresh` times out (browser step), complete it in a local terminal or delete via the web UI.
