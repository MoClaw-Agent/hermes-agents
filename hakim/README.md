# Hermes skill store

This directory is the Hermes skill store for the `hakim` profile: the agent's
procedural memory, loaded per task via `skill_view`.

## Layout

Skills are grouped by category (`devops/`, `evaluation/`, `research/`, …).  Each
is a directory with a `SKILL.md` (frontmatter + body) plus optional
`references/`, `templates/`, `scripts/` and `assets/`.

`SKILL.md` has a hard 100,000-character write limit.  A skill that grows past it
cannot be edited at all — split it, keeping the narrative in `SKILL.md` and
moving reference material into `references/` with an index.

## Version control

This directory is a git repo (branch `master`).  A `post-commit` hook pushes
every commit to two remotes:

| Remote | URL | Role |
|---|---|---|
| `origin` | `https://github.com/MoClaw-Agent/mizan-skills` | off-disk backup, private |
| `backup` | `../backups/mizan-skills.git` | same-disk mirror for fast restores |

Restore instructions are in `../backups/README.md`.  The hook is best-effort:
a push failure is logged and never blocks a commit, and the two remotes are
independent so the local mirror still updates when the network is down.

Commit skill changes with the same care as code: the skill is what makes the
next session behave correctly, so a silent edit is a real change.

## Mizan skills

| Skill | Class of work |
|---|---|
| `devops/mizan-legal-platform-debugging` | retrieval / citation / ingestion debugging |
| `devops/mizan-statutory-completeness` | an answer omits or adds statutory content |
| `devops/mizan-repo-delivery` | committing, releasing, pushing Mizan |
| `devops/mizan-pipeline-audit` | audit a pipeline layer, deliver fixes in waves |
| `devops/mizan-test-gate-repair` | fix a red CI test gate |
| `evaluation/mizan-retrieval-benchmark` | one-question-at-a-time retrieval benchmark |

All six point at `doc/workflow/` in the Mizan repository — `RULES.md` is the
standing contract and is read before code changes.
