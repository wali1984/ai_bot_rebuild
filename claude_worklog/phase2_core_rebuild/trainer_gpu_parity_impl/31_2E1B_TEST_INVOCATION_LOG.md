# Phase 2E1.B — Test Invocation Log

## Emitter Test-Run Status

The Phase 2E1.B implementation was emitted in headless emit-only mode
during the master rebuild planner turn that picked up Phase 2E1.B after
the spec revision. The emitter session did not invoke pytest. This file
therefore does not report a test result; it specifies the exact local
validation command the operator must run.

## Required Local Validation Command

pytest v2/backend/tests/unit/domain/trainer_parity/ -q

Run from the repository root after materialization of all emitted files,
using the V2 control-plane Python interpreter (the protected legacy
trainer venv must NOT be used).

## Pre-flight Checklist (Operator)

1. Verify the materialized source files are present at:
   - `v2/backend/app/domain/trainer_parity/__init__.py`
   - `v2/backend/app/domain/trainer_parity/errors.py`
   - `v2/backend/app/domain/trainer_parity/feature_status_flags.py`
   - `v2/backend/app/domain/trainer_parity/freshness_metadata.py`
   - `v2/backend/app/domain/trainer_parity/stage_a_record.py`
   - `v2/backend/app/domain/trainer_parity/stage_b_record.py`
   - `v2/backend/app/domain/trainer_parity/lineage_validator.py`
   - `v2/backend/app/domain/trainer_parity/explainability_validator.py`
2. Verify the materialized test files are present at:
   - `v2/backend/tests/unit/domain/trainer_parity/__init__.py`
   - `v2/backend/tests/unit/domain/trainer_parity/conftest.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_stage_a_record_invariants.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_stage_b_record_invariants.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_feature_status_flags.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_feature_freshness_envelope.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_freshness_metadata.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_lineage_validator_stage_a.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_lineage_validator_stage_b.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_explainability_validator.py`
   - `v2/backend/tests/unit/domain/trainer_parity/test_public_surface.py`
3. Verify `v2.backend.app.domain.trainer_parity` is importable from the
   repository root.
4. Run the validation command above.
5. Run the forbidden-token grep set listed in
   `28_PHASE_2E1B_SAFETY_BOUNDARIES.md` against the new source and
   test paths and confirm each grep returns zero hits. The Codex
   reviewer at gate 057 will record the raw grep output for each
   token.

## Expected Outcome

All tests pass, zero warnings, zero errors, zero failures. No legacy
trainer process is spawned during the run. No Redis client is
constructed. No `.env` file is read. No subprocess is started by the
domain layer or its tests.

## Result Recording

The operator records the pytest exit code and full summary line in this
file under the heading `## Operator Run Result` once executed.

## Operator Run Result

Local validation was run after materialization and cleanup of stray
planner `END_FILE` marker lines.

Command:

```bash
.venv/bin/pytest -q v2/backend/tests/unit/domain/trainer_parity
```

Result:

```text
83 passed in 0.04s
```

The run completed with zero failures, zero errors, and zero warnings.

PHASE2E1B_LOCAL_VALIDATION_PASSED
