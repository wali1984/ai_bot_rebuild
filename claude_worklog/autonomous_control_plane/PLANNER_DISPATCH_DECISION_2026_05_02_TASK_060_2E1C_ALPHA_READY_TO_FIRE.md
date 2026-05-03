# Planner Dispatch Decision — Task 060 (Phase 2E1.C.α Trainer Liveness Domain) Ready to Fire

Date: 2026-05-02
Planner role: Master Non-Live V2 Rebuild Planner
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE

## Decision

AUTHORIZE agent_supervisor to dispatch task `060_PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL` on next poll. This is the next safest non-live rebuild milestone for REQ_0006.

This decision closes the standby holding pattern recorded by:

- PLANNER_STANDBY_NOTE_2026_05_02_POST_2E1C_2FA0_DISPATCH.md
- PLANNER_STANDBY_NOTE_2026_05_02_POST_PREGATE_BETA_2FA1_EMISSION.md
- PLANNER_STANDBY_NOTE_2026_05_02_REAFFIRM_NO_TRIGGER.md
- PLANNER_STANDBY_NOTE_2026_05_02_REAFFIRM_NO_TRIGGER_2.md
- PLANNER_STANDBY_NOTE_2026_05_02_REAFFIRM_NO_TRIGGER_3.md
- PLANNER_STANDBY_NOTE_2026_05_02_REAFFIRM_NO_TRIGGER_4.md
- PLANNER_STANDBY_NOTE_2026_05_02_REAFFIRM_NO_TRIGGER_5.md
- PLANNER_STANDBY_NOTE_2026_05_02_REAFFIRM_NO_TRIGGER_6.md

Those notes correctly observed that downstream result markers (files 46, 48, 51, 56, 58, 61, 07, 13) had not appeared. They did not, however, advance the supervisor on the upstream task whose execution would produce file 46. That circular hold is now broken.

## Predecessor Verification (raw evidence)

Task 060 definition: `claude_worklog/agent_supervisor/tasks/060_PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL.json`

- predecessor_marker: `PHASE2E1B_LOCAL_VALIDATION_PASSED`
- predecessor_required_marker_file: `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md`
- status: `pending`

Predecessor evidence file: `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md`

- Line 1 contains the literal marker string `PHASE2E1B_LOCAL_VALIDATION_PASSED`.

Upstream gate chain (all PASS):

- Trainer GPU parity base plan: `trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md` → `PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS`
- Phase 2E1.A subprocess adapter implemented and frozen.
- Phase 2E1.B output contract domain Codex pass: `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` → `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`
- Phase 2E1.B validation pass: file 38 above.

Conclusion: predecessor satisfied. Task 060 is fully dispatchable.

## Safety Perimeter for Task 060 Execution

Task 060 must remain inside the locked-down liveness domain scope. The executor (Claude inside the supervisor) must produce only:

Source files (under `v2/backend/app/domain/trainer_liveness/`):

- `signal_snapshot.py` — value object for trainer liveness signal frame
- `sla_config.py` — SLA threshold configuration value object
- `alert.py` — liveness alert value object
- `evaluator.py` — pure-function evaluator producing alerts from signal vs SLA
- `errors.py` — domain exceptions
- `__init__.py` — public surface re-exports

Test files (under `v2/backend/tests/unit/domain/trainer_liveness/`): the eleven unit tests defined in spec file `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/42_2E1C_ALPHA_SCOPE.md` and its sibling spec chain (43, 44, 45).

Output marker file: `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/46_2E1C_ALPHA_GO_NO_GO.md` containing `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW` on success.

Task 060 must NOT:

- import from `legacy_reference/` or any path under `/home/wali/Desktop/AI BOT/`
- construct a Redis client or open a Redis connection
- spawn a subprocess (subprocess adapter is Phase 2E1.A; not exercised here)
- perform any network call (exchange, REST, websocket)
- read or write any `.env` or secrets file
- mutate any file under `/home/wali/Desktop/AI BOT/`
- mutate any file under `legacy_reference/`
- emit any deployment, Docker, or systemd artifact
- author a prediction worker (deferred to Phase 2E1.D)
- author the parity service orchestration shell (deferred to Phase 2E1.D)
- author the Phase 2E1.C.β windowing layer (gated behind file 51 PASS)
- author the Phase 2E1.C.γ Redis observer (deferred per planner narrowing of β scope)

CLAUDE.md hard stops remain in force for this task and every successor task on this cascade:

- LIVE TRADING: BLOCKED (default)
- no order placement, no cancellation
- no leverage change, no margin mode change
- no restart of live trader, live trainer, or any legacy service
- no writes to legacy Redis keys
- no enabling of live trading flags

## Expected Cascade After Task 060 Completes

1. Task 060 writes the six liveness domain source files, eleven unit tests, and output marker file 46.
2. Task 061 (`PHASE2E1C_ALPHA_VALIDATION`) runs `pytest v2/backend/tests/unit/domain/trainer_liveness/`. On success it writes file 48 with marker `PHASE2E1C_ALPHA_LOCAL_VALIDATION_PASSED`.
3. Task 062 (`PHASE2E1C_ALPHA_CODEX`) requests Codex adversarial review of liveness domain. On PASS it writes file 51 with marker `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`.
4. File 51 PASS automatically unblocks pre-gated task 064 (`PHASE2E1C_BETA_TRAINER_PARITY_IMPL`) — pure-function windowing layer over the freshness/liveness primitives, no Redis and no subprocess per planner narrowing.

If any of tasks 060, 061, or 062 produce a non-PASS marker, REQ_0007 (Codex autofix for non-live blockers) engages within its declared scope (`v2/`, `claude_worklog/phase2_core_rebuild/`, `claude_worklog/v2_scaffold_reviews/`, `claude_worklog/security/`, `claude_worklog/agent_supervisor/tasks/`). Autofix must respect the same hard stops above and must not bypass Codex re-review.

## Parallel Track 2F.A (Frontend) — Unchanged

Track 2F.A is independent of the trainer parity cascade and remains pre-dispatched:

- Task 063 (`PHASE2FA0_FRONTEND_INVENTORY`) — pending; produces marker file `claude_worklog/phase2_core_rebuild/frontend_design/07_FRONTEND_INVENTORY_GO_NO_GO.md`.
- Tasks 067 / 068 — pre-gated behind 2F.A.0 result.

The planner takes no new action on the 2F.A track in this decision. REQ_0008 design groundwork is recorded under `claude_worklog/phase2_core_rebuild/frontend_design/` and remains parity-stable.

## Planner Re-Engagement Trigger Map

Future planner re-runs should observe the result markers below and act per the action column. The planner does not need to write any further dispatch or REAFFIRM notes between now and the appearance of one of these markers; supervisor-driven progress is the expected forward signal.

| Result file | Success marker | Planner action on success |
|---|---|---|
| trainer_gpu_parity_impl/46_2E1C_ALPHA_GO_NO_GO.md | PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW | Confirm task 061 dispatchable |
| trainer_gpu_parity_impl/48_2E1C_ALPHA_VALIDATION_GO_NO_GO.md | PHASE2E1C_ALPHA_LOCAL_VALIDATION_PASSED | Confirm task 062 dispatchable |
| trainer_gpu_parity_impl/51_2E1C_ALPHA_CODEX_GO_NO_GO.md | PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS | Verify β scope still narrow; confirm task 064 dispatchable |
| trainer_gpu_parity_impl/56_2E1C_BETA_GO_NO_GO.md | PHASE2E1C_BETA_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW | Confirm task 065 dispatchable |
| trainer_gpu_parity_impl/58_2E1C_BETA_VALIDATION_GO_NO_GO.md | PHASE2E1C_BETA_LOCAL_VALIDATION_PASSED | Confirm task 066 dispatchable |
| trainer_gpu_parity_impl/61_2E1C_BETA_CODEX_GO_NO_GO.md | PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS | Author Phase 2E1.D composition plan (parity service shell, not prediction worker yet) |
| frontend_design/07_FRONTEND_INVENTORY_GO_NO_GO.md | PHASE2FA0_FRONTEND_INVENTORY_PASSED | Confirm task 067 (2F.A.1 design spec) dispatchable |
| frontend_design/13_2FA1_GO_NO_GO.md | PHASE2FA1_DESIGN_SPEC_PASSED | Wait for task 068 Codex result |

A non-PASS marker on any row engages REQ_0007 within allowed scope and pauses cascade until remediation Codex re-review PASSes.

## Operator Visibility Note

If supervisor execution does not pick up task 060 within the operator's normal poll window after this decision is materialized, the operator should check supervisor liveness rather than the planner re-emitting another standby note. Repeated REAFFIRM_NO_TRIGGER notes do not create forward motion and are explicitly discouraged from this point onward.

PLANNER_DISPATCH_DECISION_TASK_060_2E1C_ALPHA_AUTHORIZED
