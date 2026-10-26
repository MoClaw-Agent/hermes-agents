---
name: workflow-infrastructure
description: "Set up agent-based coding workflows for a project."
---

# Workflow Infrastructure Setup

## When to Use

- Adapting an external agent framework's patterns to a project
- Setting up agent-based coding workflows for a new project
- Creating CLI wrappers for common project operations
- Adding trust gates for agent definition directories
- User asks to "rip" or "adapt" patterns from another tool

## Core Principle

**Always generic, never project-specific.** The user works on multiple projects. Agent definitions, skills, and workflow patterns must be reusable across any project. Project-specific details go in skill `references/` files, never in the core agent/skill definitions.

## Procedure

### 1. Research the Source Framework

```
1. Check if the framework is installed locally (which, npx, find config dirs)
2. Read type definitions and config files to understand the agent model
3. Fetch the GitHub repo README and docs for architecture overview
4. Identify the key patterns: agent definitions, skills, tools, trust gates
```

### 2. Create Generic Agent Definitions

Place in `.agents/` directory. Each agent must have:
- `id` — kebab-case, generic (e.g., `parser-debugger`, not `mizan-parser`)
- `displayName` — human-readable
- `model` — appropriate for the task
- `toolNames` — minimal set needed for the task
- `spawnerPrompt` — when/why to spawn this agent
- `instructionsPrompt` — how to do the task (generic, no project paths)
- `systemPrompt` — role definition

Remove project-specific paths from agent definitions. Project details go in skill references.

### 3. Create Skills

Place in `.mimocode/skills/` (or equivalent). Structure:
- `coding-workflow/SKILL.md` — generic workflow patterns (always project-agnostic)
- `<domain>-<task>/SKILL.md` — domain-specific reference (can have project paths)

Each skill needs: frontmatter (name, description), when-to-use, procedure, verification.

### 4. Create CLI Wrapper

For common project operations, create a CLI wrapper script:
- Place in `bin/` directory, symlink to `~/.local/bin/`
- Commands: parse, audit, search-debug, status, commit
- Each command routes to the correct module/tool
- Include --help flag
- Write documentation in `docs/`

### 5. Set Up Trust Gate

Create trust store at `~/.config/agents/trusted-agent-dirs.json`:
```json
{
  "_schema_version": 1,
  "trusted_agent_dirs": {
    "/path/to/project": "YYYY-MM-DD"
  }
}
```

Before loading `.agents/` from a directory, check the trust store. If untrusted:
- TTY present → prompt user
- No TTY → skip with warning (never auto-trust in CI)

### 6. Document Everything

- Update `CHANGELOG.md` under `[Unreleased]`
- Create `docs/` entry for any new CLI/tool
- Update `README.md` docs map if one exists
- Commit message follows conventional format

## Patterns to Adapt from External Frameworks

### From freebuff
- **Agent definitions** — TypeScript files in `.agents/` with `AgentDefinition` interface
- **Skills** — markdown files in `.mimocode/skills/` with frontmatter
- **Trust gate** — per-directory trust store for `.agents/` loading
- **Task completed signal** — structured summary (accomplished, files changed, verification, limitations, next steps)
- **Suggest followups** — 2-3 concrete followup suggestions after each task
- **Propose-then-apply** — show diff before applying, wait for confirmation
- **Truncated-write guard** — never repair cut-off edits by guessing

### From Claude Code
- **CLAUDE.md** — project conventions and rules
- **Sub-agents** — delegate isolated tasks to subagent contexts
- **Skills** — procedural memory for recurring task types

### From Codex
- **AGENTS.md** — repository-level agent instructions
- **Thread management** — parallel vs sequential task execution

## Verification Checklist

Before handing over workflow infrastructure:
- [ ] Agent definitions are generic (no project-specific paths in core definitions)
- [ ] Skills follow when-to-use → procedure → verification structure
- [ ] CLI wrapper has --help and is symlinked to PATH
- [ ] Trust store exists and has the project directory
- [ ] CHANGELOG.md updated
- [ ] README.md docs map updated (if exists)
- [ ] All files committed and pushed

## Pitfalls

- **Don't put project paths in agent definitions** — agents must be reusable. Project details go in skill references.
- **Don't skip the trust gate** — `.agents/` files can inject instructions into the agent. Always check trust before loading.
- **Don't create project-specific names** — use generic names like `parser-debugger` not `mizan-parser`.
- **Don't forget documentation** — every push must include CHANGELOG.md and affected docs.
- **Don't auto-trust in CI** — if no TTY, skip with warning. Never auto-approve in non-interactive contexts.
