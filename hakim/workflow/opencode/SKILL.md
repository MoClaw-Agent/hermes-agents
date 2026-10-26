---
name: opencode
description: "Run and drive the OpenCode coding agent from Hermes: binary, flags, 4-question run pattern (model+variant, working path, command/task, agent plan/build), and MCP management. Use when the user says 'use opencode'."
version: 1.0.0
author: hakim
license: MIT
metadata:
  hermes:
    tags: [opencode, agent, cli, mcp]
    related_skills: [aidlc-workflow, aidlc-agents, freebuff]
---

# OpenCode — Hermes run recipe

OpenCode is a coding-agent CLI. Unlike freebuff (TUI-only), it supports a one-shot
run mode via `opencode run "..."` or `--prompt`, plus an interactive TUI.

## Binary

- `/home/mohammed/.opencode/bin/opencode` (v2.1.4), on PATH.
- Subcommands: `run`, `session`, `mcp`, `models`, `auth`, `plugin`, `service`, etc.

## Run pattern (4 questions)

When the user says "use opencode", ask these 4 questions before executing:

1. **Model + variant** — format `Model:variant`, variant ∈ {default, low, high, max}
   (e.g. `GLM-5.3-Flash Free:high`). Pass as `--model` if supported.
2. **Working path** — directory to start OpenCode in (positional arg or `--cwd`).
3. **Command / task** — the prompt or task to run.
4. **Agent** — `plan` or `build` (passed as `--agent <agent>`).

Then run via `~/.opencode/bin/opencode` with the chosen model, path, and agent.

## Common invocations

- One-shot run: `opencode run "<task>" --agent build --model "<model>" <directory>`
- Interactive TUI: `opencode <directory>` (or `opencode --prompt "<task>"`)
- Continue last session: `opencode -c` / `opencode --continue`
- Resume session: `opencode -s <session-id>`
- Auto-approve: `opencode --auto`
- Standalone (private server): `opencode --standalone`
- Connect to server: `opencode --server <url>`

## Useful subcommands

- `opencode models` — list available models.
- `opencode mcp` — manage MCP servers.
- `opencode session` — manage sessions.
- `opencode auth` — manage integrations/credentials.
- `opencode run --help` for run-specific flags.

## MCP wiring

OpenCode supports MCP servers (see `opencode mcp`). Config discovery and trust
follow its own rules (distinct from freebuff's `.agents/mcp.json`). Check
`opencode mcp --help` for the exact config location on this machine.

## Working directory

OpenCode takes an optional positional `<directory>` argument; if omitted it uses
the current working directory. Always confirm the working path (question 2).

## Notes

- `--prompt` sets the initial prompt for the TUI; `run` executes a one-shot task.
- Use `--print-logs` + `--log-level` for debugging.
- `--auto` auto-approves permissions not explicitly denied — use with care.
