# V2 worker porting status

As of: 2026-05-13T22:11:28Z

Live gate: `blocked_human_only`
Final approval token: `absent`
V2 local online state: `V2_LOCAL_ONLINE_DEGRADED_P0_INCOMPLETE`

P0 progress: 1 / 6
P1 progress: 0 / 8
P2 progress: 0 / 3

## Next action

- kind: `dispatch_legacy_baseline_analysis`
- next_worker: `v2_risk_gateway_runtime_worker`
- follow_up: claude_must_read_legacy_reference_and_emit_baseline_analysis_before_implementation

## Worker states

| priority | worker | state | cli | tests | report | status | codex |
|---|---|---|---|---|---|---|---|
| P0 | `v2_feature_snapshot_builder` | **CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_risk_gateway_runtime_worker` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P0 | `v2_paper_execution_worker` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P0 | `v2_execution_ledger_worker` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P0 | `v2_signal_lineage_worker` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P0 | `v2_account_position_monitor` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P1 | `v2_market_ingestor` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P1 | `v2_coinank_liquidation_bridge` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P1 | `v2_trainer_bridge` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P1 | `v2_orchestrator_adapter` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P1 | `v2_signal_publisher` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P1 | `v2_replay_worker` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P1 | `v2_script_monitor` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P1 | `v2_config_admin_manager` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P2 | `v2_p2_default_blocked_execution_adapter_stub` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P2 | `v2_p2_binance_usdm_adapter_stub` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |
| P2 | `v2_p2_deployment_helpers` | **LEGACY_BASELINE_REQUIRED** | · | · | · | · | · |

