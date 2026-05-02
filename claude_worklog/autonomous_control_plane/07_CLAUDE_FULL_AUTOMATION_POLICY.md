# Claude Full Automation Policy

## Objective

Stop manual Copilot-driven task design.

The local system must operate as:

requirements_inbox
-> Claude Master Rebuild Planner
-> agent_supervisor
-> Claude implementation
-> Codex review
-> automatic remediation
-> validation
-> commit/push
-> next task

## Human role

Human provides:
- new requirements
- final live approval
- explicit approval for L4/L5
- emergency intervention only

Human should not need to provide:
- file lists
- path allowlists for known safe non-live work
- per-task implementation instructions
- Codex review task definitions
- remediation task definitions

## Claude role

Claude must:
- read requirements_inbox
- read legacy service map
- read preservation policies
- read architecture/requirements
- read V2 codebase
- decide next safe non-live task
- generate task definitions
- execute via agent_supervisor
- validate outputs
- commit/push safe artifacts
- request Codex review
- remediate Codex findings
- continue until final live gate

## Codex role

Codex must:
- review each milestone
- identify blockers
- enforce safety boundaries
- confirm no live/legacy/Redis/exchange/deploy behavior
- produce PASS/FAIL marker

## Ollama role

Ollama may:
- summarize large legacy docs
- summarize audit logs
- compress evidence packets
- never receive raw secrets

## Hard stop conditions

Stop for:
- attempted mutation of /home/wali/Desktop/AI BOT
- Redis write/delete
- service restart
- exchange action
- live trading enablement
- deployment
- production migration
- secret exposure
- L4/L5 action
- Codex hard fail with no safe remediation
- repeated auth/quota failure that cannot auto-resume

## Allowed autonomous scope

Allowed:
- L1/L2/L3 non-live local rebuild work
- local tests
- offline fixtures
- read-only legacy audit
- code generation inside AI BOT REBUILD
- documentation
- Codex review/remediation
- Git commit/push

Forbidden:
- live trading
- legacy mutation
- Redis writes/deletes
- exchange orders
- deployment
- secrets exposure

CLAUDE_FULL_AUTOMATION_POLICY_READY
