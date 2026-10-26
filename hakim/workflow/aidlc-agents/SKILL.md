---
name: aidlc-agents
description: "AI-DLC agent roster adapted for Hermes: 14 specialist personas (11 domain + 2 review + composer) dispatchable via delegate_task for Mizan development. Use when a task benefits from a specialist persona."
version: 1.0.0
author: hakim
license: MIT
metadata:
  hermes:
    tags: [aidlc, agents, personas, delegate_task, mizan]
    related_skills: [aidlc-workflow, dispatching-parallel-agents, systematic-debugging]
---

# AI-DLC Agents (Hermes adaptation)

The 14 AI-DLC specialist personas, adapted for Hermes. Each persona's full knowledge lives in `/home/mohammed/aidlc-workflows/core/knowledge/aidlc-<name>/`. Dispatch a persona with `delegate_task`, passing the persona files as context.

## Roster

| Agent | Persona dir | Domain |
|---|---|---|
| product-agent | `core/knowledge/aidlc-product-agent/` | requirements, scope, user stories, market research |
| design-agent | `core/knowledge/aidlc-design-agent/` | UX/UI, wireframes, interaction design, accessibility |
| delivery-agent | `core/knowledge/aidlc-delivery-agent/` | team formation, capacity planning, delivery sequencing |
| architect-agent | `core/knowledge/aidlc-architect-agent/` | domain design, modelling, NFRs, decomposition |
| aws-platform-agent | `core/knowledge/aidlc-aws-platform-agent/` | AWS infra, IaC, FinOps, environment provisioning |
| compliance-agent | `core/knowledge/aidlc-compliance-agent/` | GRC, regulatory mapping, data classification, risk |
| devsecops-agent | `core/knowledge/aidlc-devsecops-agent/` | threat modelling, security pipeline, secure design review |
| developer-agent | `core/knowledge/aidlc-developer-agent/` | code generation, reverse engineering, implementation guidance |
| quality-agent | `core/knowledge/aidlc-quality-agent/` | test strategy, acceptance criteria, performance validation |
| pipeline-deploy-agent | `core/knowledge/aidlc-pipeline-deploy-agent/` | CI/CD pipelines, deployment strategy, release execution |
| operations-agent | `core/knowledge/aidlc-operations-agent/` | observability, incident response, feedback loops |
| architecture-reviewer-agent | `core/knowledge/aidlc-architecture-reviewer-agent/` | independent architecture review |
| product-lead-agent | `core/knowledge/aidlc-product-lead-agent/` | independent product review |
| composer-agent | `core/knowledge/aidlc-composer-agent/` | proposes/reshapes adaptive stage plans |

Shared knowledge: `core/knowledge/aidlc-shared/` (principles, brownfield, verification, rules-reading, audit-format, memory-template, worktree-info-schema).

## Dispatch recipe

```
delegate_task(
  goal="<the specialist task>",
  context="You are the <agent-name> persona. Read and follow the persona files at /home/mohammed/aidlc-workflows/core/knowledge/aidlc-<name>/ and shared knowledge at /home/mohammed/aidlc-workflows/core/knowledge/aidlc-shared/. <task-specific context>. Report findings; do not modify files unless asked.",
  toolsets=["terminal", "file", "search"],
  role="leaf"
)
```

For Mizan work, prepend the relevant Mizan skill context (e.g., mizan-legal-platform-debugging, mizan-pipeline-audit) to the task context so the persona operates with Mizan conventions.

## Recommended use for Mizan

- developer-agent: code generation / refactors in fetching/, ingestion/, retrieval/.
- architect-agent: domain design for new pipelines or data models.
- quality-agent: test strategy and acceptance criteria for parser/ingestion changes.
- compliance-agent: data classification / regulatory mapping (legal corpus handling).
- devsecops-agent: security review of ingestion endpoints and secrets handling.
- operations-agent: observability for the search/Qdrant pipeline.
- architecture-reviewer-agent / product-lead-agent: independent review before a risky change.
- composer-agent: propose an adaptive plan when the work doesn't fit a standard scope.

## Notes

- Personas are guidance, not code: they shape how a sub-agent reasons. Always verify outputs yourself before acting.
- Collaborators switch: in AI-DLC, stages may run lead-only (collaborators off) or with support agents (collaborators on). In Hermes, decide per task whether to dispatch support agents in parallel.
- Reviewer mechanism is independent: run architecture-reviewer-agent / product-lead-agent separately from the implementing agent.
