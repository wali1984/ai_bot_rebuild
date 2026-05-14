# Legacy Baseline Analysis - v2_p2_deployment_helpers

Worker ID: `v2_p2_deployment_helpers`
Task: `claude_port_v2_p2_deployment_helpers`
Generated: 2026-05-14 (UTC)
Status: BASELINE_COMPLETE

## legacy_source_paths

The legacy startup/stop surface is cited from the copied baseline manifest:

| Legacy path | Preserved copy | SHA256 | Role |
| --- | --- | --- | --- |
| `scripts/start_all_services_production.sh` | `v2/legacy_preserved/startup_baseline/scripts/start_all_services_production.sh` | `2b5a9a63fc76487b3a6f46cdbb8060044aeab69c5f8117bbf30e7efdb8a10ca9` | Full legacy production startup order, health checks, staged service launch |
| `scripts/stop_all_services_production.sh` | `v2/legacy_preserved/startup_baseline/scripts/stop_all_services_production.sh` | `7db37564a3677d5e9e8b2f4f4ad8171fda99d3fcf163ccf23dd0c7e45dbc06d8` | Legacy production stop flow |
| `scripts/stop_ingestors.sh` | `v2/legacy_preserved/startup_baseline/scripts/stop_ingestors.sh` | `83d6eb161b23b3bd748870be4440b8c6d1dfd0ae339b41a087eac2e0575fc50b` | Legacy ingestor stop helper |

## legacy_functions_preserved

No live production start behavior is preserved. The V2 helper preserves only these safe ideas from the legacy baseline:

- staged startup order exists.
- preflight runs before local worker launch.
- stop helper is idempotent.
- health/safety checks precede runtime execution.

## legacy_inputs

- Copied baseline manifest.
- V2 worker-porting state payload.
- V2 Symbol Universe service/public payload.
- Approval marker absence checks.

## legacy_outputs

The V2 helper emits command output only. It does not write old Redis, does not emit legacy process state, and does not create live approval markers.

## legacy_redis_keys

Legacy startup scripts included Redis health and service coordination. The V2 helper does not read or write old Redis keys.

## legacy_config_dependencies

- `.venv/bin/python3`
- `claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json`
- `v2/backend/app/services/symbol_universe/service.py`

## legacy_edge_cases

- legacy production scripts could start live trader paths.
- legacy stop scripts could stop broad process sets.
- legacy startup could rely on old Redis.
- operator might pass a real/live flag by mistake.

## legacy_failure_modes

The V2 helper fails closed when:

- final live approval marker exists.
- Redis trim approval marker exists.
- mode is not paper.
- `--paper-only` is missing.
- live gate is not `blocked_human_only`.
- venv Python is missing.

## legacy_tests_or_expected_behavior

Expected V2 behavior is intentionally narrower than legacy production startup:

- `start_local_paper_runtime.sh --paper-only --dry-run` succeeds safely.
- `start_local_paper_runtime.sh --real` fails.
- `stop_all_workers.sh --dry-run` is idempotent.
- `stop_all_workers.sh --legacy` fails.
- preflight fails if the final live approval token exists.

## V2_mapping

| Concern | Legacy baseline | V2 helper |
| --- | --- | --- |
| Startup order | `start_all_services_production.sh` | `start_local_paper_runtime.sh` starts only local V2 paper/shadow helpers |
| Preflight | health/memory checks | `preflight_check.py` blocks live/real mode and approval-token drift |
| Stop flow | `stop_all_services_production.sh`, `stop_ingestors.sh` | `stop_all_workers.sh` defaults to dry-run and only targets V2 paper helper patterns |
| Symbol scope | `legacy_reference/config.py SYMBOLS` | V2 Symbol Universe contract; canonical `legacy_active_symbols` is not the full universe |

## intentional_changes

- Removed live trader startup.
- Removed old Redis startup dependency.
- Removed exchange startup path.
- Removed broad legacy process termination.
- Added Symbol Universe contract classification.

## removed_deprecated_behavior

All legacy production/live startup behavior is deliberately excluded from this P2 helper. Live remains `blocked_human_only`.
