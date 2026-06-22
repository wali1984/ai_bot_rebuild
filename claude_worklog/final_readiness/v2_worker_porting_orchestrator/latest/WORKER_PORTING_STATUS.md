# V2 worker porting status

As of: 2026-06-22T00:28:27Z

Live gate: `blocked_human_only`
Final approval token: `absent`
V2 local online state: `V2_LOCAL_ONLINE_P0_READY_PAPER_SHADOW_ONLY`

P0 progress: 9 / 9
P1 progress: 6 / 6
P2 progress: 3 / 3

## Next action

- kind: `all_workers_complete`
- follow_up: proceed_to_v2_local_online_bootstrap_paper_shadow_only

## Worker states

| priority | worker | state | cli | tests | report | status | codex |
|---|---|---|---|---|---|---|---|
| P0 | `v2_feature_snapshot_builder` | **CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_market_ingestor_from_legacy_baseline` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_coinank_and_liquidation_bridge_from_legacy_baseline` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_feature_pipeline_and_ta_worker_from_legacy_baseline` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_risk_gateway_runtime_worker` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_paper_execution_worker` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_execution_ledger_worker` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_signal_lineage_worker` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_account_position_monitor` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P1 | `v2_trainer_bridge` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P1 | `v2_orchestrator_adapter` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P1 | `v2_signal_publisher` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P1 | `v2_replay_worker` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P1 | `v2_script_monitor` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P1 | `v2_config_admin_manager` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P2 | `v2_p2_default_blocked_execution_adapter_stub` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P2 | `v2_p2_binance_usdm_adapter_stub` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P2 | `v2_p2_deployment_helpers` | **CODEX_PASS** | · | ✓ | ✓ | · | ✓ |

