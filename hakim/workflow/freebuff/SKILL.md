---
name: freebuff
description: "Run and drive the freebuff (Codebuff) interactive coding agent from Hermes: launch recipe, flags, MCP wiring, and trust gate. Use when the user says 'use freebuff' or asks to run the freebuff agent."
version: 1.0.0
author: hakim
license: MIT
metadata:
  hermes:
    tags: [freebuff, codebuff, agent, mcp, tui]
    related_skills: [aidlc-workflow, aidlc-agents]
---

# freebuff (Codebuff) — Hermes run recipe

freebuff is Codebuff's free-tier coding agent. It is **interactive TUI only** — there is
no non-interactive one-shot prompt mode (only `login` is a positional command). So
unlike opencode, I cannot pass a command/task string; I launch it in a pty and the
user (or I) drives it interactively.

## Binary

- Native ELF: `~/.config/manicode/freebuff` (v0.2.26 on this machine)
- Wrapper: `npx freebuff` (uses `~/.npm/_npx/.../node_modules/.bin/freebuff`)
- Version: `freebuff --version` (or `-v`)

## Flags (observed on this machine)

- `--cwd <dir>` — set the project directory (important; see #957 below).
- `--continue` — resume the last session.
- `--trust-agents` — one-run trust for a repo's `.agents/` dir (writes nothing).
- `-v` — verbose.
- Positional: `login` only.

There is **no model flag** — freebuff uses its own model routing.

## Launch recipe (Hermes)

Because it is TUI-only, launch with a pseudo-terminal in the background:

```
terminal(command="freebuff", background=True, pty=True, workdir="<project dir>")
```

Then drive it with `process_manage` write/submit, or hand control to the user. Set
`notify_on_complete=True` only if you want an exit notification; for an interactive
session, omit it (the process runs until the user quits).

## Working directory matters (#957)

MCP config (`mcp.json`) is loaded **once at boot from `process.cwd()`**. Launching
from an ancestor and picking the project via the picker exposes zero MCP servers.
Always launch from inside the project directory, or pass `--cwd <dir>`.

## MCP wiring (Mizan)

Mizan's `.agents/` directory is already trusted by freebuff on this machine
(`/home/mohammed/Mizan/.agents`). To expose Mizan tools to freebuff, add
`/home/mohammed/Mizan/.agents/mcp.json` (stdio + http entries per
`doc/mcp/freebuff_mcp_report.md` §2.2). freebuff merges `mcpServers` from
`.agents/mcp.json` into every agent whose id starts with `base`.

Trust gate: a dir holding an executable agent file or `mcp.json` requires a
`[y/N]` prompt on first interactive launch (or `CODEBUFF_TRUST_AGENT_DIRS=1` /
`--trust-agents` in CI). A dir with only `skills/` does not trigger it;
`~/.agents` never does.

## Known constraints

- No non-interactive one-shot mode → cannot be used for CI/eval automation via
  the CLI binary; use `@codebuff/sdk` (`CodebuffClient`) or another MCP client.
- Launch from the project dir (or `--cwd`) to avoid #957.
- `mcpServers` from non-`codebuff` publishers are refused at publish/GET.
- Server stderr is captured (8 KB) for handshake diagnostics; stdout must carry
  only JSON-RPC (Mizan is print-heavy — force `logging` to stderr in any shim).

## When the user says "use freebuff"

1. Ask the working path (project directory).
2. Ask whether to `--continue` (resume last session) and whether to `--trust-agents`.
3. Launch with a pty in the background and hand off, or drive it if the user asks.
4. Remind: freebuff has no model flag; model routing is internal.
