# v2_script_monitor Legacy Baseline Analysis

generated_at: 2026-05-14
live_gate: blocked_human_only

## Legacy Source Paths

- `v2/legacy_preserved/startup_baseline/scripts/monitor_dashboard.sh`
- `v2/legacy_preserved/startup_baseline/scripts/health_probe.py`
- `v2/legacy_preserved/startup_baseline/scripts/paralysis_detectors.py`
- `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/legacy_startup_baseline_matrix.json`

## Legacy Responsibilities Preserved

| Legacy behavior | V2 mapping |
|---|---|
| process/status dashboard for running services | `v2.backend.app.services.monitor_runner.collect_script_statuses` enumerates V2 worker scripts and payloads |
| health probe classifies missing/stale components | `v2_script_monitor` classifies active, broken, unused, duplicate, and unknown V2 worker scripts |
| paralysis detector surfaces stuck/broken runtime | monitor payload emits `alerts_generated`, `scripts_broken`, `last_failure`, and `metrics_emitted` |
| startup baseline maps monitoring scripts to `v2_script_monitor` | this worker is the V2-only replacement for script health visibility |

## Legacy Inputs

- process list checks in legacy shell/Python monitors
- legacy runtime logs and pid files
- old Redis reads inside legacy health scripts
- startup matrix rows for monitoring, paralysis detection, and health validation

## V2 Inputs

- `v2/backend/app/cli/v2_*.py`
- `v2/frontend/public/operator_runtime/*/latest/*_status.json`
- `claude_worklog/agent_supervisor/tasks/claude_port_*.json`
- V2 Symbol Universe service or public symbol-universe payload

## V2 Outputs

- `v2/frontend/public/operator_runtime/v2_script_monitor/latest/v2_script_monitor_status.json`
- `v2/runtime/v2_script_monitor/latest/v2_script_monitor_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_script_monitor_status.json`

## Legacy Redis Keys

Legacy monitoring scripts read old runtime keys as reference behavior. V2 does not read or write those keys. The V2 monitor inspects V2 scripts and V2 public payloads only.

## Config Dependencies

- V2 repo root
- V2 CLI worker directory
- V2 public operator-runtime payload directory
- V2 task descriptor directory
- Symbol Universe service constants

## Edge Cases

- placeholder script: classified as `broken`
- CLI without main guard: classified as `broken`
- V2 script with no payload and no task descriptor: classified as `unused`
- task descriptor present but payload absent: classified as `unknown`
- public symbol-universe payload absent: reported as `MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD`
- public symbol-universe payload tries to override canonical legacy 25: ignored and explicitly labeled

## Intentional Changes

- V2 monitor never executes legacy scripts.
- V2 monitor does not shell out to process tools.
- V2 monitor does not read old Redis.
- V2 monitor does not start or stop any worker.
- V2 monitor does not infer live readiness.
- `live_symbols` remains empty while live is `blocked_human_only`.

## Removed Or Deprecated Behavior

- legacy terminal dashboard loops are replaced by structured V2 public payloads
- legacy direct process polling is replaced by static V2 script and payload inspection
- legacy health checks that depended on old Redis are not ported into this worker

## Test Coverage

- `test_each_monitored_script_status_captured`
- `test_broken_script_classified_correctly`
- `test_unused_script_classified_correctly`
- `test_monitor_does_not_execute_legacy_scripts_invariant`
- `test_no_old_redis_write_contract`
- `test_symbol_universe_contract_required`
- `test_public_symbol_payload_cannot_override_canonical_legacy_25`
- `test_run_once_writes_all_status_files`

Result: baseline mapped without legacy mutation, old Redis writes, exchange actions, or live enablement.
