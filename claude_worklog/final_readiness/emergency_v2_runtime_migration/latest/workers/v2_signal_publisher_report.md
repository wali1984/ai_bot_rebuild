# V2 Signal Publisher Report

Generated: 2026-05-14

`v2_signal_publisher` is implemented as a V2-only broadcast worker. It reads V2 signal-lineage/orchestrator evidence and fans out file-based envelopes for `webhook`, `gui`, and `admin_ai`.

## Invariants

- Live gate: `blocked_human_only`
- Execution route: disabled
- `route_to_execution`: `false`
- Old Redis writes: none
- Legacy mutation: none
- Exchange action: none
- Leverage/margin changes: none
- `live_symbols`: `[]`

## Files

- `v2/backend/app/cli/v2_signal_publisher.py`
- `v2/backend/tests/integration/cli/test_v2_signal_publisher.py`
- `v2/frontend/public/operator_runtime/v2_signal_publisher/latest/v2_signal_publisher_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_signal_publisher_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_signal_publisher_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_signal_publisher_legacy_behavior_mapping.json`

## Validation

- `py_compile`: passed
- `pytest v2/backend/tests/integration/cli/test_v2_signal_publisher.py`: 11 passed

The worker is allowed to emit fail-closed status while upstream signal lineage is missing, stale, incomplete, or fail-closed.
