# Phase 2E1.B — Local Validation Task Request

This document records the planner-dispatched local validation step that
must run before Codex review (task 057) is allowed to dispatch.

## Why a separate validation task

The Phase 2E1.B implementation was emitted in a planner turn that did
not invoke pytest. Per `30_2E1B_IMPLEMENTATION_REPORT.md` and
`31_2E1B_TEST_INVOCATION_LOG.md`, the GO_NO_GO marker
`PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW` in
`32_2E1B_GO_NO_GO.md` was emitted without an attached test result.

The Evidence Integrity Rule and the Phase 2E1.B safety-boundary doc
both require that the implementation log carry the exact pytest summary
line with zero failures, zero errors, zero warnings before downstream
review can proceed. Task 058 closes that gap.

## Task summary

Task ID: `058_trainer_parity_2e1b_local_validation`
Agent: claude (local)
Risk level: L1
Allowed write prefixes:
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
Allowed read surface:
- `v2/backend/app/domain/trainer_parity/` (eight source files)
- `v2/backend/tests/unit/domain/trainer_parity/` (eleven test files)
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/26..32`

## Required actions

1. Confirm presence of all 19 Phase 2E1.B files at the exact paths
   listed in `30_2E1B_IMPLEMENTATION_REPORT.md`.
2. Run, from the repository root, with the V2 control-plane Python
   interpreter (not the protected legacy trainer venv):
   ```
   pytest v2/backend/tests/unit/domain/trainer_parity/ -q
   ```
3. Capture the exact summary line and the exit code.
4. Re-run the forbidden-token grep set from
   `28_PHASE_2E1B_SAFETY_BOUNDARIES.md` against:
   - `v2/backend/app/domain/trainer_parity/`
   - `v2/backend/tests/unit/domain/trainer_parity/`
   Tokens: `redis`, `aioredis`, `redis.asyncio`, `subprocess`,
   `os.system`, `os.popen`, `pty`, `socket`, `urllib`, `requests`,
   `httpx`, `aiohttp`, `torch`, `tensorflow`, `numpy.random`, `cuda`,
   `legacy_reference`, `/home/wali/Desktop/AI BOT`,
   `v2.backend.app.adapters.trainer`, `os.environ`, `time.time`,
   `datetime.now`, `datetime.utcnow`.
5. Verify the public surface of
   `v2/backend/app/domain/trainer_parity/__init__.py` exports exactly
   nine names (per the revised spec): `FeatureFreshnessEnvelope`,
   `FeatureStatusFlags`, `FreshnessMetadata`, `StageATrainerRecord`,
   `StageBTrainerRecord`, `TrainerParityLineageError`,
   `validate_stage_a_explainability`, `validate_stage_a_lineage`,
   `validate_stage_b_lineage`. `ConfidenceExplainability` must NOT be
   in `__all__`.
6. Verify `v2.backend.app.domain.trainer_parity` is importable from
   the repository root.

## Required output files

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/31_2E1B_TEST_INVOCATION_LOG.md`
  — append the `## Operator Run Result` section with the exact pytest
  summary line and the marker `PHASE2E1B_LOCAL_VALIDATION_PASSED` or
  `PHASE2E1B_LOCAL_VALIDATION_FAILED`. Preserve the existing file body
  above that section.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/37_2E1B_VALIDATION_RUN_LOG.md`
  — fresh raw run log: pytest stdout/stderr summary, exit code, the
  full forbidden-token grep table (one row per token), the public
  surface check, and the importability check.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md`
  — exactly one line: `PHASE2E1B_LOCAL_VALIDATION_PASSED` or
  `PHASE2E1B_LOCAL_VALIDATION_FAILED`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/32_2E1B_GO_NO_GO.md`
  — preserve `PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW` if
  validation passes; overwrite with `PHASE2E1B_TRAINER_PARITY_IMPL_BLOCKED`
  if validation fails.

## Pass criteria

PASS requires ALL of:
- pytest exits 0.
- Summary line shows zero failures, zero errors, zero warnings.
- Every forbidden-token grep returns zero hits across both source and
  test trees.
- Public surface is exactly the nine names listed.
- Package is importable.

Any deviation downgrades the marker to FAILED and reverts
`32_2E1B_GO_NO_GO.md` to BLOCKED.

## Hard stops the validation task must respect

- Do not modify any file under `v2/backend/app/domain/trainer_parity/`
  or `v2/backend/tests/unit/domain/trainer_parity/`.
- Do not modify any file under `/home/wali/Desktop/AI BOT/`.
- Do not modify any file under `legacy_reference/`.
- Do not write Redis. Do not read Redis.
- Do not start the legacy trainer venv. Do not invoke any legacy
  trainer module.
- Do not start any subprocess except pytest itself and the
  forbidden-token grep tool.
- Do not enable live trading. Do not deploy. Do not run production
  migrations.
- Do not expose or commit secrets. Do not read any `.env` file.
- Do not commit or push in this task; commit/push is a separate
  supervisor step.

## Downstream gating

- Codex review task `057_trainer_parity_2e1b_codex_review` is now
  gated on this task's `PHASE2E1B_LOCAL_VALIDATION_PASSED` marker.
- If validation fails, the Codex review task must remain in
  `pending_predecessor` state and a remediation task in the Phase
  2E1.B family must be opened under REQ_0007 autofix scope before any
  re-validation.

PHASE2E1B_VALIDATION_TASK_REQUEST_RECORDED
