# 00 — V2 Scaffold Implementation Queue Overview

## 1. Purpose
This package is the milestone-B preparation queue produced by supervisor task `015_create_v2_scaffold_implementation_queue`. It enumerates the six implementation tasks (`015A`–`015F`) that, once unblocked, will materialize the V2 scaffold defined in `claude_worklog/v2_scaffold_planning/01-08`. The queue does NOT execute any implementation work. Every task in the queue is created with `status=blocked_approval` so the agent supervisor refuses dispatch until a human (after Codex review of this queue) explicitly unblocks each task individually.

This document is L1 (planning text). The downstream tasks it enumerates are L2 (scaffold-tier code) and remain BLOCKED until the conditions in §6 are satisfied.

## 2. Queue scope
The queue covers exactly six work packages, mirroring the deliverables enumerated in supervisor task `015`:

| ID | Name | Maps to milestone | Authority planning file |
|----|------|-------------------|-------------------------|
| 015A | Repo / package skeleton | B (skeleton) | `claude_worklog/v2_scaffold_planning/02_PACKAGE_AND_MODULE_MAP.md` |
| 015B | Database migration skeleton | C (Alembic harness only) | `claude_worklog/v2_scaffold_planning/03_DATABASE_MIGRATION_PLAN.md` |
| 015C | API route skeleton | D (empty routers + middleware shells) | `claude_worklog/v2_scaffold_planning/04_API_ROUTE_SCAFFOLD_PLAN.md` |
| 015D | Enterprise frontend shell | E (routable shell + 26 placeholder pages) | `claude_worklog/v2_scaffold_planning/05_ENTERPRISE_GUI_SCAFFOLD_PLAN.md` |
| 015E | Test / CI skeleton | B–E (lint, type, import-cycle, schema-drift, contract harness) | `claude_worklog/v2_scaffold_planning/07_TEST_AND_CI_PLAN.md` |
| 015F | Agent supervisor / dashboard integration | cross-cutting (queue visibility, evidence packets, governance) | `claude_worklog/v2_scaffold_planning/06_AGENT_SUPERVISED_BUILD_SEQUENCE.md` + `09_ENTERPRISE_IMPLEMENTATION_GUARDRAILS.md` |

Materialization of any task above requires (a) the `gate_evidence_ref` to resolve to all listed artifacts and (b) human L2 approval flipping `status` from `blocked_approval` to `pending`.

## 3. Hard prohibitions inherited from `CLAUDE.md`
These prohibitions apply to every task in the queue and override any per-task instruction:

- No live execution. `LIVE TRADING: BLOCKED` is the persistent default. No scaffold task may enable live mode; live mode is gated by milestones N and O.
- No mutation of the legacy bot at `/home/wali/Desktop/AI BOT`.
- No writes to the legacy Redis namespace. V2 writes only to `${V2_REDIS_PREFIX}*` (default `v2:*`).
- No restart of legacy services (trainer, trader, orchestrator, Redis, VPN).
- No Dockerization of the trainer; no upgrades to trainer-side packages.
- No direct import of legacy trainer modules into the FastAPI process. Subprocess boundary only.
- No `.env` writes; no secret material in commits.
- No order placement, leverage change, margin change, or kill-switch toggle from any scaffold-tier code.
- No "tiny fix" exceptions. Per `09_ENTERPRISE_IMPLEMENTATION_GUARDRAILS.md` §2, every change must carry timeout handling, state handling, error classification, dashboard implication, supervisor implication, and a test/validation artifact.

## 4. Default-deny posture
Every task in this queue is created with `status=blocked_approval`. The agent supervisor's `select_next_task_file` (`claude_worklog/tools/agent_supervisor.py`) refuses to dispatch any task whose status is `blocked_approval`. Unblocking requires:

1. Codex adversarial review of THIS queue (input file: `claude_worklog/v2_scaffold_queue/04_CODEX_QUEUE_REVIEW_INPUT.md`).
2. Human L2 approval recorded in `claude_worklog/agent_supervisor/state/tasks/<task_id>.json` flipping `status` from `blocked_approval` to `pending`.
3. The task's individual `gate_evidence_ref` resolving to all required closure files and prior-milestone validation artifacts.

A task that is unblocked but whose dependencies have not completed remains in `blocked_dependency` automatically per supervisor logic.

## 5. Roles and authorities
- Supervisor: enforces dispatch refusal, records audit trail, runs the per-task pre-dispatch check.
- Claude (this agent): authors planning artifacts and (after unblock) authors the scaffold code per `02-07` of the planning package.
- Codex: adversarial reviewer for THIS queue (input is `04_CODEX_QUEUE_REVIEW_INPUT.md`) and for each milestone gate per `06_AGENT_SUPERVISED_BUILD_SEQUENCE.md` §5.
- Ollama: low-risk summarization only; never approves a milestone.
- Human: L2 unblock, L3 acknowledgement, L4 approvals, L5 activation. Human review of THIS queue is required before any task `015A`–`015F` may run.

## 6. Pre-execution gate evidence (must resolve before any `015X` runs)
Each task in the queue declares the same pre-execution gate evidence floor. Adding a task to the queue does NOT lower the floor; the supervisor verifies the floor for every dispatch attempt.

Pre-execution floor (drawn from `17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md` §3 and §5.B):

1. `claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md` present (CLOSED).
2. `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` present (CLOSED).
3. `claude_worklog/v2_architecture_remediation/12C_FEATURE_EXPLAINABILITY_CLOSURE.md` present (CLOSED).
4. `claude_worklog/v2_architecture_remediation/12D_TRAINER_LIVENESS_EVIDENCE_CLOSURE.md` present (CLOSED).
5. `claude_worklog/v2_architecture_codex_review/16_ACTUAL_CODEX_RERUN_GO_NO_GO.md` resolves to `ACTUAL_CODEX_ARCHITECTURE_RERUN_PASS`.
6. `claude_worklog/v2_scaffold_planning/08_SCAFFOLD_PLANNING_GO_NO_GO.md` resolves to `V2_SCAFFOLD_PLANNING_READY`.
7. `claude_worklog/agent_supervisor_reliability/04_GO_NO_GO.md` present and ready.
8. THIS queue's `05_SCAFFOLD_QUEUE_GO_NO_GO.md` resolves to `V2_SCAFFOLD_QUEUE_READY_FOR_CODEX_REVIEW`.

Tasks `015B`/`015C`/`015D`/`015F` add per-task prior-validation requirements (e.g., `B_SCAFFOLD_VALIDATION.md` for 015B). See `01_IMPLEMENTATION_WAVES.md` for the full per-task floor.

## 7. Validation artifacts produced by the queue (when executed)
Each task produces exactly one validation artifact under `claude_worklog/v2_build/`:

| Task | Validation artifact |
|------|---------------------|
| 015A | `claude_worklog/v2_build/B_SCAFFOLD_VALIDATION.md` |
| 015B | `claude_worklog/v2_build/C_DATABASE_SKELETON_VALIDATION.md` (skeleton portion only; full materialization belongs to milestone C proper) |
| 015C | `claude_worklog/v2_build/D_API_SKELETON_VALIDATION.md` (skeleton portion only) |
| 015D | `claude_worklog/v2_build/E_GUI_SHELL_VALIDATION.md` |
| 015E | `claude_worklog/v2_build/B_TEST_CI_VALIDATION.md` |
| 015F | `claude_worklog/v2_build/B_AGENT_DASHBOARD_INTEGRATION_VALIDATION.md` |

Each artifact carries: acceptance checklist with raw evidence pointers per row, `produced_by` agent, `verified_by[]`, `confidence`, and `missing_evidence[]`. A task with non-empty `missing_evidence[]` is NOT complete (per `17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md` §6).

## 8. Failure / rollback semantics
- Per-task rollback is documented in each `015X` task JSON under `rollback`. Default rollback: "delete the materialized files under `v2/**` created by this task and remove the validation-artifact row(s) authored by this task."
- A failed task MUST NOT auto-promote downstream. Every queue task has `next_tasks_on_success: []`; the human chooses to dispatch the next task only after reviewing the validation artifact.
- A failed task with non-empty `missing_evidence[]` reopens the upstream closure file (e.g., a failing API vector reopens `12B`). Reopening is recorded in `next_recommended_action`.

## 9. Audit evidence
- Every task emits an audit-ledger row at start, on each adapter call, and at completion.
- Audit-ledger rows are append-only and hash-chained per `claude_worklog/v2_architecture/13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md`.
- Audit-chain breaks freeze the entire queue; the supervisor refuses to dispatch any further task until a human reviews the break.

## 10. Status
QUEUE: PLANNED. ALL TASKS: `blocked_approval`. AUTHORIZATION TO DISPATCH: PENDING CODEX REVIEW + HUMAN L2 APPROVAL.