# Signal And Orchestrator Freshness Report

Generated: `2026-05-15T21:20:00Z`

Status: `SIGNAL_ORCHESTRATOR_SOURCE_LIMITED_COMPARE_BLOCKED`

## Result

The observatory is running and read-only. Current evidence shows:

- legacy trainer process state: `RUNNING_READONLY_OBSERVED`
- orchestrator process state: `RUNNING_READONLY_OBSERVED`
- observed signal count: `9`
- latest signal id: `null`
- latest signal reason: `SOURCE_LIMITED_LOG_READONLY_OBSERVATION`
- comparison classification: `MISSING_EVIDENCE_CANNOT_COMPARE`
- exchange action taken: `false`
- live gate: `blocked_human_only`
- live symbols: `[]`

This means legacy/V2 decision comparison is useful for monitoring, but source-limited signal evidence cannot be treated as fresh actionable parity. No outcomes are invented.

Evidence paths:

- `v2/frontend/public/operator_runtime/legacy_runtime_observer/latest/legacy_runtime_observer_status.json`
- `v2/frontend/public/operator_runtime/legacy_v2_decision_comparator/latest/legacy_v2_decision_comparator_status.json`
- `claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/operator_dashboard_payload.json`
