# V2 Closed-Loop Claude/Codex Execution Engine Report

Marker: `V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_READY`
Generated: 2026-06-22T00:27:59Z

## Utilization Summary

| metric | value |
| --- | --- |
| active_claude_jobs | 0 |
| active_codex_jobs | 0 |
| pending_claude | 0 |
| pending_codex | 0 |
| stale_claude | 0 |
| stale_codex | 0 |
| automatable_work_count | 0 |
| active_lane_count | 0 |
| target_active_lanes | 3 |
| utilization_percent | 0.0 |
| status | MONITOR_ONLY |
| blocker | None |

## Executors

- Claude: available=True (claude_cli)
- Codex:  available=True (codex_cli)

## Blockers

- (none)

## Safety

- live_gate=blocked_human_only
- live_symbols=[]
- approves_live=false
- approves_canary=false
- approves_legacy_shutdown=false
- approves_redis_trim=false

## Validation

Tests under `v2/backend/tests/unit/tools/closed_loop_execution/` and the
report-center registry tests must pass. See README in the same
`v2_closed_loop_execution/latest/` directory for the exact command.
