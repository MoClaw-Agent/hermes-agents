---
name: hermes-skills-repo-management
description: "Manage the shared Hermes skills repo (hermes-agents) across profiles: per-profile subfolders, symlink adaptation, commit/push hygiene, and auto-wire cleanup. Use when creating, moving, or maintaining the shared skills repo."
version: 1.0.0
author: hakim
license: MIT
metadata:
  hermes:
    tags: [hermes, skills, repo, profiles, symlink, git]
    related_skills: [mizan-repo-delivery, hermes-agent-skill-authoring]
---

# Hermes Skills Repo Management

Manages the shared `hermes-agents` repo that holds per-profile skill sets under subfolders (`default/`, `hakim/`, ...), so multiple Hermes profiles share one repo with isolated commit paths.

## Structure

- Repo root: `/home/mohammed/hermes-agents`
- One subfolder per profile: `hermes-agents/<profile>/` (e.g., `hakim/`, `default/`)
- Skill categories live directly under the profile subfolder: `workflow/`, `devops/`, `evaluation/`, etc. (NOT under a `skills/` subdir)
- Origin: `github.com/MoClaw-Agent/hermes-agents`

## Adapting a profile to the shared repo (symlink)

To make a profile load skills from the shared repo without breaking Hermes:

1. Back up the existing skills dir: `mv ~/.hermes/profiles/<name>/skills ~/.hermes/profiles/<name>/skills.bak`
2. Symlink: `ln -s /home/mohammed/hermes-agents/<name> ~/.hermes/profiles/<name>/skills`
3. Verify a skill still loads (`skill_view`).
4. Remove the backup only after verification.

Hermes reads skills through the symlink fine. Git operations happen in the parent repo (`/home/mohammed/hermes-agents`).

## Pitfalls

- **Mode-bit noise.** A blanket chmod or curator run flips every file to 100755. Before committing, revert: `find . -path ./.git -prune -o -type f -exec chmod 644 {} +`, then restore exec bits only on files that were originally 100755 (`git ls-files -s | awk '$1==100755{print $4}' | xargs chmod +x`). Otherwise the diff is 600+ mode-only changes.
- **Auto-wire stray dirs.** When Hermes auto-wires a skill (e.g., ai-dlc), it may create `hakim/skills/<name>/` (a nested `skills/` subdir) instead of the standard category layout, because it treats the skills root as a profile root. Relocate the stray skill into the proper category folder, remove the empty `skills/` dir, verify it doesn't duplicate an existing skill, then commit+push so the relocated skill isn't lost. Re-check for a recreated stray `skills/` dir after any auto-wire or Hermes update.
- **Default profile is off-limits.** Never commit or push the default profile's repo unless explicitly authorized. Only touch the hakim subfolder.
- **Default profile skills are not version-controlled.** The default profile's skills live in plain directories (`~/.hermes/profiles/default/skills/` and `~/.hermes/skills/`), not a git repo. Copy skills there for availability, but they won't be tracked — do not attempt git operations on them.
- **Auto-wire duplicates.** When relocating a stray skill, check it doesn't duplicate an existing skill in the target category (e.g., `workflow/ai-dlc-workflow` vs `workflow/ai-dlc-workflow`). Compare content before committing.
- **Deleting an old repo** needs the `delete_repo` scope. Run `gh auth refresh -h github.com -s delete_repo` (device flow — complete the browser step), then `gh repo delete <owner>/<repo> --yes`.
- **Moving a clone:** update every reference to the old path (skill files, `config.yaml` `framework_path`, `AGENTS.md`). Search the whole home tree for the old path string before declaring done.
- **Cron script paths.** The cron tool only accepts script paths relative to `~/.hermes/profiles/<profile>/scripts/` — absolute or `~/`-relative paths are rejected. If the real script lives elsewhere, create a small wrapper (`exec /path/to/real/script.sh`) in the profile's scripts dir and pass just the filename.
- **Memory is bounded.** When adding a standing rule, batch-remove a stale entry in the same call to stay under the char limit.

## Commit/push workflow

1. Edit skills under `~/.hermes/profiles/hakim/skills/...` (resolves into `hermes-agents/hakim/...`).
2. From `/home/mohammed/hermes-agents`: `git add -A && git commit -m "..." && git push origin main`.
3. The `backup` remote (local bare) is optional; push to origin primarily.

## References

- None yet. Add topical depth under `references/` when a procedure needs it.
