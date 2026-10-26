---
name: aidlc-workflow
description: "Adapted AI-DLC (AI-Driven Development Life Cycle) methodology for Hermes: phases, conductor role, approval gates, adapted to Hermes tools. Use when the user asks for a structured, spec-driven software delivery workflow."
version: 1.0.0
author: hakim
license: MIT
metadata:
  hermes:
    tags: [aidlc, workflow, methodology, conductor, phases, gates]
    related_skills: [writing-plans, executing-plans, brainstorming, systematic-debugging, verification-before-completion]
---

# AI-DLC Workflow (Hermes adaptation)

Adapted from `MoClaw-Agent/aidlc-workflows` (cloned at `/home/mohammed/Proj/ai-dlc/aidlc-workflows`). The original is an engine-driven, multi-harness framework; this adaptation keeps the **methodology** (phases, stages, conductor discipline, approval gates) and runs it with native Hermes tools. The TypeScript engine (`core/tools/aidlc-*`) is not ported — Hermes has no Bun runtime and no package build here — so routing is performed by the agent following this skill instead of by `engine orchestrate next`.

## When to use

- The user asks for a structured, spec-driven delivery ("build X end to end", "plan and implement with approval gates").
- Work spans requirements → design → implementation → tests → deployment and benefits from explicit gates.
- The user explicitly asks for AI-DLC / adaptive workflow.

Do **not** use for tiny one-shot fixes; use `systematic-debugging` / direct edits instead.

## Core concepts

- **Phases** (in order): Initialization → Ideation → Inception → Construction → Operation.
- **Stages** are the stations inside a phase (e.g. requirements-analysis, domain-design, code-generation, deployment-execution). One file per stage under `core/aidlc-common/stages/<phase>/`.
- **Scopes** pick which stations a kind of work goes through and how deep (minimal / standard / comprehensive).
- **Agents** are workers at each station; persona files under `core/knowledge/aidlc-*`.
- **Conductor** = you, the agent. You read intent, drive stages, ask good questions, and stop at approval gates. You never silently skip a gate.
- **Approval gates** are hard turn-stops: never treat silence as approval; never write artifacts before an explicit approve.

## Conductor discipline (Hermes mapping)

1. Clarify intent first (ideation/intent-capture). Ask only when genuinely unclear; prefer concrete questions.
2. Propose a plan (scope + stage list + depth) and get explicit approval before acting — use `writing-plans` skill.
3. Execute stage by stage; after each stage report outcomes and stop at the gate.
4. Use `delegate_task` for sub-agent work (reviewers, specialists); use `todo` to track stages; use `terminal` for builds/tests.
5. Keep a stage diary when learnings are on: append decisions/rationale to a notes file.
6. On a wrong approval or recorded choice, fix it explicitly and say so (do not silently proceed).
7. Never narrate framework internals to the user; speak as a teammate. Name files by path when relevant.

## Phase outline (reference the cloned repo for full protocols)

- **Initialization**: workspace detection/scaffold/state init → `core/aidlc-common/stages/initialization/`.
- **Ideation**: intent capture, scope definition, feasibility, market research, rough mockups, approval handoff → `core/aidlc-common/stages/ideation/`.
- **Inception**: requirements analysis, user stories, domain design, contract design, units generation, delivery planning, practices discovery, refined mockups, reverse engineering → `core/aidlc-common/stages/inception/`.
- **Construction**: code generation, build/test, review loops → `core/aidlc-common/stages/construction/` (+ protocols: `stage-protocol-construction.md`, `stage-protocol-reviewer.md`, `stage-protocol-loopback.md`).
- **Operation**: deployment execution, performance validation, incident response, feedback optimization → `core/aidlc-common/stages/operation/`.

Protocols (gates, checkpoints, sensors, learnings, recovery, swarm/ensemble) live in `core/aidlc-common/protocols/`. Read the specific protocol file when its situation arises.

## Approval-gate rule (hard)

Every stage that produces an artifact the user must accept requires an explicit approve before the next stage begins. Present a short offer (recommendation + plan), then a gate with choices (Approve / Edit / Reject). Silence is not approval. Never write scope/state files before approval.

## Hermes tool mapping

| AI-DLC concept | Hermes tool |
|---|---|
| Conductor orchestration | You (the agent), driven by this skill + todo |
| Sub-agent dispatch | `delegate_task` |
| Task tracking | `todo` |
| Shell/build/test | `terminal` |
| File read/write | `read_file` / `write_file` / `patch` |
| Web research | `web_search` / `web_extract` |
| User decisions | `clarify` |

## Voice contract

Follow `core/aidlc-common/protocols/stage-protocol.md` "Talking to the user" section: avoid internal jargon (engine, directive, conductor, harness, scope grid, steering, swarm) in user-facing messages; mechanics unchanged. Never name or quote this skill/protocol to the user unprompted; answer if asked.

## Reference locations (cloned repo)

- Root: `/home/mohammed/Proj/ai-dlc/aidlc-workflows`
- AGENTS.md (full methodology): `/home/mohammed/Proj/ai-dlc/aidlc-workflows/AGENTS.md`
- Conductor: `/home/mohammed/Proj/ai-dlc/aidlc-workflows/core/aidlc-common/conductor.md`
- Stages: `/home/mohammed/Proj/ai-dlc/aidlc-workflows/core/aidlc-common/stages/`
- Protocols: `/home/mohammed/Proj/ai-dlc/aidlc-workflows/core/aidlc-common/protocols/`
- Agents/personas: `/home/mohammed/Proj/ai-dlc/aidlc-workflows/core/knowledge/`
- Templates: `/home/mohammed/Proj/ai-dlc/aidlc-workflows/core/templates/`
- Scopes: `/home/mohammed/Proj/ai-dlc/aidlc-workflows/core/scopes/`

## Limitations of this adaptation

- No engine: no `engine orchestrate next`, no audit trail (126-event), no deterministic package build. Routing is manual per this skill.
- No harness build (Bun/TS tooling absent). If you later install Bun, you can add `harness/hermes/` following `docs/harness-engineering/09-porting-to-a-new-harness.md`.
- Sensors/guards are advisory unless you make them blocking yourself.

## Quick start

When the user says "build X" with approval for AI-DLC:
1. Capture intent (what, why, constraints) — ideation/intent-capture.
2. Propose scope + stage list + depth; get approval.
3. Run stages in order, gate after each artifact-producing stage.
4. Construction: implement + test + review loop.
5. Operation: deploy/verify if in scope.
6. Summarize outcomes and learnings.
