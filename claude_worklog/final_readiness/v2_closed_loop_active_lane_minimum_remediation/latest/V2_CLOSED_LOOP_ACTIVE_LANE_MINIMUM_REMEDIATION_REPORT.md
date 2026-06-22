# V2 Closed-Loop Execution Engine — Active-Lane Minimum Remediation Report

Marker: `V2_CLOSED_LOOP_ACTIVE_LANE_MINIMUM_REMEDIATION_BLOCKED`
Generated: 2026-05-24T04:54:37Z

## Utilization

| metric | value |
| --- | --- |
| active_claude_jobs | 1 |
| active_codex_jobs | 0 |
| active_lane_count | 1 |
| target_active_lanes | 3 |
| automatable_work_count_current | 7 |
| automatable_work_count_historical_excluded | 706 |
| utilization_percent | 33.3 |
| real_dispatch_count | 0 |
| dry_run | False |
| blocker | ACTIVE_LANES_BELOW_MINIMUM |

## Root Cause

- code: `CLAUDE_RUNNER_DISPATCH_LIMIT_BUG`
- detail: 7 current automatable items and 1 pending-safe items exist, but the runner has only 1 real lane(s). The runner is not topping up to the minimum. 3 zombie running descriptor(s) (dead pid) are not being reset.

## Active Lanes (real pids only, probes excluded)

| task_id | task_type | pid | log_path | heartbeat | last_log_bytes |
| --- | --- | --- | --- | --- | --- |
| claude_continuous_remediation_review_governor_blocker_fix | REMEDIATION | 903546 | /home/wali/Desktop/AI BOT REBUILD/claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/claude_continuous_remediation_review_governor_blocker_fix.log | 2026-05-24T04:52:38Z | 0 |

## Zombies Reset

- 003_reconcile_actual_codex_architecture_review -> pending
- 005_fix_risk_gateway_architecture -> pending
- claude_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract -> pending

## Third Lane Dispatch

- dispatched: False
- candidate: 003_reconcile_actual_codex_architecture_review
- reason: allow_real_dispatch_false

## Codex Real-Job Proof

- dispatched: False
- candidate: None
- no_current_codex_work: True
- reason: no pending current Codex review work; active_codex_jobs may stay 0

## Safety

- live_gate=blocked_human_only
- live_symbols=[]
- approves_live=false
- approves_canary=false
- approves_legacy_shutdown=false
- approves_redis_trim=false
