# Planner Directive — Phase 2E1.C.α Validation Dispatch (REQ_0006)

This is a Master Non-Live Rebuild Planner directive. It does not execute
code, write Redis, restart live services, or modify legacy. It records
the next safest non-live rebuild milestone for REQ_0006 and orders the
agent_supervisor to dispatch the already-defined validation chain.

## Source of authority

- Active requirement:
  `claude_worklog/requirements_inbox/REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`.
- Allowed-write boundaries: `v2/`, `claude_worklog/`, `requirements/`,
  `.claude/`, `tools/`, `ollama/`, `raw_evidence/` (per CLAUDE.md
  "Read/Write Boundaries").
- Planner output policy: BEGIN_FILE / END_FILE blocks only; the harness
  materializes files. The planner does NOT itself run pytest, py_compile,
  rg, or import the V2 packages.

## Current 2E1.C.α state — verified evidence

| Artifact | Path | Verified value |
| --- | --- | --- |
| Alpha implementation report | `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/47_2E1C_ALPHA_IMPLEMENTATION_REPORT.md` | `PHASE2E1C_ALPHA_IMPLEMENTATION_REPORT_READY` |
| Alpha implementation GO/NO-GO | `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/46_2E1C_ALPHA_GO_NO_GO.md` | `PHASE2E1C_ALPHA_TRAINER_LIVENESS_READY_FOR_LOCAL_VALIDATION` |
| Alpha source package | `v2/backend/app/domain/trainer_liveness/` | 6 files present (`__init__.py`, `errors.py`, `signal_snapshot.py`, `sla_config.py`, `alert.py`, `evaluator.py`) — verified via filesystem listing |
| Alpha test package | `v2/backend/tests/unit/domain/trainer_liveness/` | present (per 47_2E1C_ALPHA_IMPLEMENTATION_REPORT.md, 23 tests passed during recovery validation) |

## Missing markers blocking 2E1.C.β dispatch

The β GO/NO-GO request (`55_PHASE_2E1C_BETA_GO_NO_GO_REQUEST.md`)
requires `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` at
`trainer_gpu_parity_impl/51_2E1C_ALPHA_CODEX_GO_NO_GO.md`. None of
48 / 49 / 50 / 51 exist on disk.

These four files are produced by the already-pending supervisor tasks:

- `claude_worklog/agent_supervisor/tasks/061_trainer_parity_2e1c_alpha_local_validation.json`
  — emits 48 and 49.
- `claude_worklog/agent_supervisor/tasks/062_trainer_parity_2e1c_alpha_codex_review.json`
  — emits 50 and 51.

Both task definitions were verified read by the planner and are spec-faithful.

## Next safest milestone — dispatch sequence

The agent_supervisor SHOULD execute, in this exact order, halting on any FAIL:

1. Dispatch `061_trainer_parity_2e1c_alpha_local_validation` (agent: claude, L1).
   Predecessor marker already satisfied. This task runs pytest,
   py_compile, forbidden-token grep, public-surface check, and
   sys.modules import-leak check against the alpha trainer-liveness
   package. It emits 48 and 49.
2. On `48_2E1C_ALPHA_VALIDATION_GO_NO_GO.md` =
   `PHASE2E1C_ALPHA_LOCAL_VALIDATION_PASSED`, dispatch
   `062_trainer_parity_2e1c_alpha_codex_review` (agent: codex, L1).
   It emits 50 and 51.
3. On `51_2E1C_ALPHA_CODEX_GO_NO_GO.md` =
   `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`, dispatch
   `064_trainer_parity_2e1c_beta_implementation` (agent: claude, L1).
4. On `56_2E1C_BETA_GO_NO_GO.md` =
   `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`,
   dispatch `065_trainer_parity_2e1c_beta_local_validation`.
5. On `58_2E1C_BETA_VALIDATION_GO_NO_GO.md` =
   `PHASE2E1C_BETA_LOCAL_VALIDATION_PASSED`, dispatch
   `066_trainer_parity_2e1c_beta_codex_review`.

## Stop conditions (planner-binding)

The supervisor MUST halt this chain and surface to the planner if any of:

- Any FAIL marker is written by 061 / 062 / 064 / 065 / 066.
- Any forbidden-token hit (`redis`, `subprocess`, `socket`, `numpy`,
  `torch`, `tensorflow`, `XLEN`, `xlen`, `time.time(`, `datetime.now(`,
  `datetime.utcnow(`, `legacy_reference`, `/home/wali/Desktop/AI BOT/`,
  `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `asyncio`, `async def`,
  `from v2.backend.app.domain.trainer_liveness` inside β source/tests,
  `from v2.backend.app.domain.trainer_parity` inside α/β packages).
- Any `END_FILE: <path>` marker leak inside any authored Python file
  (the 2E1.B regression class).
- Any write attempt outside the per-task `allowed_output_prefixes`.
- Any Codex finding indicating live behavior, Redis writes, legacy
  mutation, deployment intent, or exposure of secret material.
- Any predecessor-marker mismatch between the dispatched task's
  `predecessor_required_marker` and the file content on disk.
- L4 / L5 promotion attempt by any task in this chain.

A safe-path-remap autorecovery (per
`requirements_inbox/REQ_0010_SAFE_PATH_REMAP_AUTORECOVERY.md`) is
permitted only for the canonical paths enumerated in REQ_0010 and only
when the canonical target is in the dispatched task's
`required_output_files`. Every safe remap MUST be logged as
`safe_path_remap_materialized` in the supervisor task log.

## Hard non-live constraints (planner-binding for the entire chain)

- No modification of `/home/wali/Desktop/AI BOT/`.
- No Redis read or write.
- No exchange order placement, cancellation, leverage change, or
  margin-mode change.
- No live trainer or live trader restart.
- No deployment.
- No production migration.
- No exposure or commit of secret material.
- `LIVE TRADING: BLOCKED` remains unchanged.
- α package (`v2/backend/app/domain/trainer_liveness/`) MUST NOT be
  modified by 064 / 065 / 066 (β must stay isolated from α; the
  composition that joins β output into α is deferred to 2E1.C.δ).

## Planner accountability

The planner records this directive instead of authoring 48/49/50/51
directly because:

1. 48/49 require executing pytest, python -c, and grep against the V2
   package — this is the supervisor's authority, not the planner's.
2. 50/51 require Codex adversarial review — this is the codex agent's
   authority, not the planner's.
3. The two task definitions already exist and are spec-faithful; the
   only remaining action is to dispatch them in order.

The planner will re-engage on either of:
- `51_2E1C_ALPHA_CODEX_GO_NO_GO.md` reaches PASS (planner advances to
  REQ_0006 β closure and follow-on phases).
- Any FAIL marker is written by tasks in this chain (planner emits a
  remediation directive scoped to REQ_0007 autofix boundaries).

PLANNER_2E1C_ALPHA_VALIDATION_DISPATCH_DIRECTIVE_READY
END_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/70_PLANNER_2E1C_ALPHA_VALIDATION_DISPATCH_DIRECTIVE.md
