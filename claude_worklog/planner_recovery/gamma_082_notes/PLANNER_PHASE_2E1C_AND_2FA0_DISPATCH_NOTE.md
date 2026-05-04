# Planner Dispatch Note — Phase 2E1.C.α handoff + Phase 2F.A.0 open

## Active requirements

- `REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE` — in flight at
  Phase 2E1.C.α (trainer liveness DOMAIN LAYER).
- `REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM` — opening at
  Phase 2F.A.0 (frontend inventory + gap audit).
- `REQ_0007_CODEX_AUTOFIX_NON_LIVE_BLOCKERS` — meta-policy; remains
  the standing autofix charter for any Codex FAIL on either lane.

## State of the trainer parity service rebuild as of 2026-05-02

| Phase | Subject | Latest marker | File |
| --- | --- | --- | --- |
| 2E (plan) | Trainer GPU parity plan | `PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS` | `trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md` |
| 2E1.A | Subprocess adapter foundation | `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md` |
| 2E1.B | Trainer output contract / domain records | `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` |
| 2E1.B (validation) | Local pytest validation | `PHASE2E1B_LOCAL_VALIDATION_PASSED` | `trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md` |
| 2E1.C.α (planner) | Liveness domain spec + tasks 060/061/062 | dispatch chain authored, awaiting supervisor execution | `trainer_gpu_parity_impl/42..45_*.md` + `agent_supervisor/tasks/060..062` |

## 2E1.C.α planner-side completeness (no new α-artifacts this turn)

The 2E1.C.α dispatch chain authored on 2026-05-02 19:15 local time is
complete and in-tree (uncommitted). The planner has nothing further to
emit for 2E1.C.α; all subsequent action is supervisor execution:

1. Supervisor dispatches `tasks/060_trainer_parity_2e1c_alpha_implementation.json`
   once `38_2E1B_VALIDATION_GO_NO_GO.md` reads
   `PHASE2E1B_LOCAL_VALIDATION_PASSED` (already true).
2. Supervisor commits the impl artifacts and dispatches
   `tasks/061_trainer_parity_2e1c_alpha_local_validation.json` once
   `46_2E1C_ALPHA_GO_NO_GO.md` reads
   `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`.
3. Supervisor commits the validation artifacts and dispatches
   `tasks/062_trainer_parity_2e1c_alpha_codex_review.json` once
   `48_2E1C_ALPHA_VALIDATION_GO_NO_GO.md` reads
   `PHASE2E1C_ALPHA_LOCAL_VALIDATION_PASSED`.
4. On `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` (file
   `51_2E1C_ALPHA_CODEX_GO_NO_GO.md`), the next planner turn opens
   2E1.C.β (read-only Redis stream-id growth probe).
5. On any FAIL marker the supervisor opens a remediation task under
   REQ_0007 autofix scope; the planner does NOT re-spec until
   remediation closes.

The planner explicitly does NOT re-author or amend the 2E1.C.α
artifacts in this turn. Re-authoring would risk overwriting the
supervisor's predecessor markers.

## Chosen next non-live milestone (parallel lane)

**Phase 2F.A.0 — Frontend Inventory + Gap Audit (DOCUMENTATION ONLY).**

This sub-phase opens REQ_0008 in a parallel lane that does not touch
any 2E path. It writes only under
`claude_worklog/phase2_core_rebuild/frontend_design/` and reads
`v2/frontend/` strictly read-only. No code is compiled, installed, or
modified.

Rationale for choosing this as the parallel lane (Phase 2F.A.0)
instead of, say, beginning 2F.B.0 directly:

- Existing `v2/frontend/` already has ~30 page directories (read via
  `Glob` enumeration). Designing token / animation primitives without
  first auditing what exists would risk colliding with existing
  components or duplicating work already done in the scaffold lane
  (commits 2026-05-01..02). An inventory-first milestone produces the
  evidence base every later 2F sub-phase needs.
- Documentation-only scope keeps the milestone L1 (lowest risk),
  cannot enable live behavior, cannot mutate legacy, cannot write
  Redis, and cannot run any package manager.
- Mirrors the 2E1.A inventory-then-implement cadence.

## Path-overlap audit (parallelism safety)

| Lane | Writes under | Reads under |
| --- | --- | --- |
| 2E1.C.α (tasks 060/061/062) | `v2/backend/app/domain/trainer_liveness/`, `v2/backend/tests/unit/domain/trainer_liveness/`, `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` | `claude_worklog/phase2_core_rebuild/trainer_gpu_parity*/`, `claude_worklog/v2_requirements/09_*`, `v2/backend/app/domain/trainer_parity/` (style only), `v2/backend/tests/unit/domain/trainer_parity/` (style only) |
| 2F.A.0 (task 063) | `claude_worklog/phase2_core_rebuild/frontend_design/` | `claude_worklog/requirements_inbox/REQ_0008_*`, `CLAUDE.md`, `v2/frontend/` (read-only) |

No write-write conflicts. No read-of-each-other's-writes. Either lane
may complete first without affecting the other's predecessor markers.

## Stale task auto-stalled (carried forward)

`tasks/059_trainer_parity_2e1b_endfile_marker_remediation.json`
declares a predecessor marker of
`PHASE2E1B_TRAINER_PARITY_IMPL_BLOCKED`. The actual marker in
`32_2E1B_GO_NO_GO.md` reads
`PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`. The supervisor
cannot dispatch task 059. No planner action is required to retire it;
it is auto-blocked and may be archived in a later hygiene sweep. The
remediation it describes was already executed inline by the
implementer of task 056 before validation passed.

## Hard exclusions for both active lanes

- No live trading enable.
- No Redis client construction.
- No exchange API call.
- No legacy module import.
- No subprocess against the legacy trainer venv.
- No production secret read.
- No deployment script invocation.
- No production migration.
- No write under `/home/wali/Desktop/AI BOT/`.
- No write under `legacy_reference/`.

## Dispatch chain summary (this turn's net additions)

1. `tasks/063_frontend_design_2fa0_inventory.json`
   (predecessor marker:
   `PHASE2FA0_GO_NO_GO_REQUEST_RECORDED` from
   `claude_worklog/phase2_core_rebuild/frontend_design/04_PHASE_2FA0_GO_NO_GO_REQUEST.md`).

`tasks/060`, `tasks/061`, `tasks/062` carry forward unchanged from the
2E1.C.α planner turn.

PLANNER_PHASE_2E1C_AND_2FA0_DISPATCH_NOTE_RECORDED
