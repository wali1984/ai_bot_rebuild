# Master Rebuild Planner — Phase 2E1.B Local Validation Dispatch

## Decision

Phase 2E1.B implementation files have been emitted. Codex review (task
057) is queued and currently gated on the marker
`PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW` in
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/32_2E1B_GO_NO_GO.md`.

That marker was emitted alongside the implementation in headless
emit-only mode. `31_2E1B_TEST_INVOCATION_LOG.md` is explicit that no
pytest run was performed in the emitting turn:

> The Phase 2E1.B implementation was emitted in headless emit-only mode
> ... The emitter session did not invoke pytest. This file therefore
> does not report a test result; it specifies the exact local
> validation command the operator must run.

Dispatching Codex review without a recorded pytest pass would violate
the Evidence Integrity Rule (no claim without raw evidence) and the
Phase 2E1.B safety-boundary check that demands the implementation log
record the exact pytest summary line.

The next safest non-live milestone is therefore a focused local
validation task that:

1. Verifies all 19 Phase 2E1.B files are present under the allowed
   prefixes.
2. Runs `pytest v2/backend/tests/unit/domain/trainer_parity/ -q` with
   the V2 control-plane interpreter.
3. Re-runs the forbidden-token grep set from
   `28_PHASE_2E1B_SAFETY_BOUNDARIES.md` and records raw output.
4. Updates `31_2E1B_TEST_INVOCATION_LOG.md` `## Operator Run Result`.
5. Emits a fresh validation run log and a fresh GO_NO_GO marker
   (`PHASE2E1B_LOCAL_VALIDATION_PASSED` or
   `PHASE2E1B_LOCAL_VALIDATION_FAILED`).
6. If FAILED, downgrades `32_2E1B_GO_NO_GO.md` to
   `PHASE2E1B_TRAINER_PARITY_IMPL_BLOCKED` so 057 cannot dispatch.

## Why this is the safest action in this turn

- The validation task is read-and-execute only on already-emitted
  source and tests; it does not modify v2 source.
- The pytest invocation runs only against the new domain layer, which
  imports nothing outside the standard library and the new package
  itself; no Redis, subprocess, GPU, or network surface is exercised.
- The legacy trainer venv is not used. The V2 control-plane
  interpreter is used.
- The task is L1 by the same risk class as the 2E1.B implementation
  itself.
- Codex review (057) cannot be re-gated correctly without an
  intervening validation step.

## Predecessors satisfied

- `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS`
- `PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW` (impl emit)

## What this turn does NOT do

- Does not run pytest from the planner. Validation is dispatched to
  task 058 under the supervisor, not executed inline by the planner.
- Does not advance Phase 2E1.C (prediction worker liveness). Phase
  2E1.C selection is deferred until 057 (Codex review) returns
  `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`.
- Does not advance REQ_0007 (Codex autofix). Autofix is invoked only
  if Codex returns FAIL on 057 (or if 058 surfaces a concrete blocker
  that fits autofix scope).
- Does not advance REQ_0008 (enterprise website). Frontend track
  remains parallel and is not opened in the same turn as a backend
  validation gate.
- Does not commit or push. Commit/push is the supervisor's
  responsibility once 058 reports
  `PHASE2E1B_LOCAL_VALIDATION_PASSED`.

## Hard stops respected

- No legacy file modified.
- No file under `/home/wali/Desktop/AI BOT/` read or modified.
- No Redis access.
- No subprocess started by the planner this turn.
- No exchange action.
- No leverage or margin change.
- No live trading flag changed.
- No deployment.
- No production migration.
- No secret value emitted.

## Artifacts dispatched in this turn

Planner control-plane note (this file):

- `claude_worklog/autonomous_control_plane/PLANNER_PHASE2E1B_VALIDATION_DISPATCH.md`

Implementation worklog request:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/36_PHASE_2E1B_VALIDATION_TASK_REQUEST.md`

Supervisor tasks:

- `claude_worklog/agent_supervisor/tasks/058_trainer_parity_2e1b_local_validation.json`
  (new)
- `claude_worklog/agent_supervisor/tasks/057_trainer_parity_2e1b_codex_review.json`
  (revised — predecessor chain now requires 058 PASS)

## Markers

- Active requirement: `REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE`
- Active slice: 2E1.B
- Slice status: implementation emitted; local validation dispatched;
  Codex review (057) re-gated on
  `PHASE2E1B_LOCAL_VALIDATION_PASSED`.

PLANNER_PHASE2E1B_VALIDATION_DISPATCH_RECORDED
