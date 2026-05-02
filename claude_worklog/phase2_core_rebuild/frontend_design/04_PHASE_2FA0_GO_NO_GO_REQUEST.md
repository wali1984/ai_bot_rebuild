# Phase 2F.A.0 — GO / NO-GO Request

## Predecessor markers required

| Marker | File | Required value |
| --- | --- | --- |
| Phase 2F scope | `frontend_design/00_SCOPE.md` | `PHASE2F_FRONTEND_DESIGN_SCOPE_READY` |
| Phase 2F breakdown | `frontend_design/01_PHASE_BREAKDOWN.md` | `PHASE2F_FRONTEND_DESIGN_PHASE_BREAKDOWN_READY` |
| Phase 2F.A.0 task spec | `frontend_design/02_PHASE_2FA0_FRONTEND_INVENTORY_TASK_SPEC.md` | `PHASE2FA0_FRONTEND_INVENTORY_TASK_SPEC_READY` |
| Phase 2F.A.0 safety boundaries | `frontend_design/03_PHASE_2FA0_SAFETY_BOUNDARIES.md` | `PHASE2FA0_FRONTEND_INVENTORY_SAFETY_BOUNDARIES_READY` |

## Dispatch chain

1. `agent_supervisor/tasks/063_frontend_design_2fa0_inventory.json`
   (predecessor marker: `PHASE2FA0_GO_NO_GO_REQUEST_RECORDED` from this
   file).

The supervisor executes 063 only after this file contains the
`PHASE2FA0_GO_NO_GO_REQUEST_RECORDED` marker. On PASS the supervisor
commits the inventory artifacts and the planner picks up the next
sub-phase (2F.A.1 design-token + animation-primitive spec). On
`PHASE2FA0_FRONTEND_INVENTORY_BLOCKED` the planner does NOT advance to
2F.A.1; instead a remediation task is opened under REQ_0007 autofix
scope.

## Parallelism with REQ_0006 Phase 2E1.C.α

This sub-phase runs in parallel with the in-flight 2E1.C.α dispatch
chain (`tasks/060` → `tasks/061` → `tasks/062`) because:

- 2E1.C.α writes only under `v2/backend/app/domain/trainer_liveness/`
  and `v2/backend/tests/unit/domain/trainer_liveness/`, plus its
  worklog reports under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`.
- 2F.A.0 writes only under
  `claude_worklog/phase2_core_rebuild/frontend_design/`.

There is no path overlap, no shared module under modification, and no
shared marker file. Either supervisor lane may complete first without
affecting the other.

## Stop the chain immediately if

- any predecessor marker file does not contain its required value;
- a forbidden token (Redis, subprocess beyond the allowlist, network,
  legacy import, GPU, secret) is detected during the inventory grep;
- a write attempt is made under `v2/frontend/`;
- any Codex finding indicates live behavior, Redis writes, legacy
  mutation, or deployment intent;
- any attempt is made to install / compile / build / test the frontend
  in this sub-phase (those concerns belong to 2F.B.0+).

## Live-trading status

LIVE TRADING: BLOCKED. No Phase 2F.A.0 artifact may change this.

PHASE2FA0_GO_NO_GO_REQUEST_RECORDED
