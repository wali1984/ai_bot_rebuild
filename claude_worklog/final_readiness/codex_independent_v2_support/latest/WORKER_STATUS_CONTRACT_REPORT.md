# Worker Status Contract Report

Generated: 2026-05-13T21:18:35Z

Implemented: `v2/backend/app/runtime_contracts/worker_status.py`

The contract defines strict status classifications for V2 worker migration evidence:
- `MIGRATED_AND_RUNNING`
- `MIGRATED_NOT_RUNNING`
- `WRAPPED_READONLY_ONLY`
- `PAPER_ONLY`
- `BACKLOG_ONLY`
- `MISSING_IN_V2`
- `LEGACY_ONLY`
- `DEPRECATED_WITH_EVIDENCE`
- `BLOCKED`

Required fields are enforced for source/freshness, evidence status, legacy dependency mode, runtime process evidence, runnable command, public payload, test status, Codex status, blockers, and next action.

Safety behavior:
- `MIGRATED_AND_RUNNING` cannot be created without runnable command, public payload path, and passing/present test status.
- `BACKLOG_ONLY` is explicitly not migration.
- `WRAPPED_READONLY_ONLY` is explicitly not independent runtime.
- `MISSING_IN_V2` is allowed as an honest gap.
- JSON writing validates required fields before replacing the destination payload.

Artifacts:
- `worker_status_schema.json`
- `worker_status_example.json`
- `worker_status_contract_test_results.json`
