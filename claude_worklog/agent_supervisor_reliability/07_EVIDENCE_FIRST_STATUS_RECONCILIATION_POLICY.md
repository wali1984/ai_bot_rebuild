# Evidence-First Status Reconciliation Policy

## Objective

Prevent stale queue/current_status/dashboard fields from overriding completed runtime evidence.

## Problem

The system sometimes shows old task state even after newer evidence proves completion or Codex PASS.

Examples:
- stale `025_codex_review_015f_agent_dashboard_integration`
- stale unsplit `060_trainer_parity_2e1c_alpha_implementation`
- stale `060c_trainer_liveness_validation_docs` retry
- stale scaffold/build-gate fail after later PASS markers

## Source-of-truth priority

Use this order:

1. Explicit safety violation or human_attention_required with active unresolved state
2. Latest GO/NO-GO marker files
3. Latest Codex PASS/FAIL evidence
4. Runtime state under `claude_worklog/agent_supervisor/state/tasks/`
5. Task run summary under `claude_worklog/agent_supervisor/runs/`
6. Queue/current_status files
7. Historical dashboard summaries

Queue/current_status must not override newer committed evidence.

## Evidence markers that supersede stale states

A PASS marker should mark related older task failures as superseded, not active.

Current known examples:

- `CODEX_PARALLEL_TRAINER_LIVENESS_AUTOFIX_PASS`
  supersedes stale old unsplit 060 / 060C retry view for trainer liveness autofix.

- `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`
  supersedes stale 056 retry_scheduled view.

- `015F_CODEX_REVIEW_PASS`
  supersedes stale 025 pending/retry view.

- `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`
  supersedes stale scaffold queue fail markers for current build-state display, while preserving historical record.

## Dashboard behavior

Dashboard must show:
- authoritative current phase
- latest evidence marker
- stale/noisy fields separately
- superseded task states as `superseded_by_evidence`
- no red/blocked state from old tasks if newer PASS evidence exists

## Planner behavior

Master planner must:
- read evidence markers before selecting next task
- avoid re-running superseded stale tasks
- mark old task states as superseded runtime state when safe
- advance to next requirement if evidence proves completion

## Safety boundary

Evidence reconciliation cannot bypass:
- live gate
- Redis write block
- legacy mutation block
- exchange action block
- deployment block
- secret scan failure
- active unresolved Codex FAIL

EVIDENCE_FIRST_STATUS_RECONCILIATION_POLICY_READY
