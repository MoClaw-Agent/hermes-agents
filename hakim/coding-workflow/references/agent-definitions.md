# Agent Definitions (`.agents/` TypeScript)

Adapted from freebuff's `AgentDefinition` interface. These are reusable across projects.

## Pattern

Each agent is a TypeScript file exporting an `AgentDefinition` with:
- `id` — kebab-case identifier (e.g. `parser-debugger`)
- `displayName` — human-readable name
- `model` — OpenRouter model ID
- `toolNames` — subset of built-in tools the agent can use
- `spawnerPrompt` — when/why to spawn this agent (used by parent agents)
- `instructionsPrompt` — inserted after each user input (shapes behavior)
- `systemPrompt` — background context
- `reasoningOptions` — `{ effort: 'high' | 'medium' | 'low' }`

## Generic Agents

### parser-debugger
- Spawn when: parser JSON output is malformed, containers not splitting, metadata wrong, OCR garbled
- Tools: read_files, write_file, str_replace, run_terminal_command, code_search, find_files, web_search

### corpus-auditor
- Spawn when: auditing corpus quality, checking JSON validity, verifying metadata completeness
- Tools: read_files, run_terminal_command, code_search, find_files, web_search

### search-debugger
- Spawn when: search returns no results, citations wrong, dense/sparse retrieval fails
- Tools: read_files, write_file, str_replace, run_terminal_command, code_search, find_files, web_search

### code-reviewer
- Spawn when: reviewing changes before commit, checking for security issues, verifying code quality
- Tools: read_files, code_search, find_files

### thinker
- Spawn when: complex multi-step task, architectural decision needed, multiple approaches possible
- Tools: read_files, code_search, think_deeply

## Project-Specific Agents

When creating agents for a specific project (e.g. legal RAG, data pipeline, web app):
1. Copy the generic agent pattern
2. Replace `instructionsPrompt` with project-specific file paths, commands, and conventions
3. Keep `spawnerPrompt` generic (it describes WHEN to spawn, not project specifics)
4. Remove any hardcoded paths from the agent definition — reference them indirectly
