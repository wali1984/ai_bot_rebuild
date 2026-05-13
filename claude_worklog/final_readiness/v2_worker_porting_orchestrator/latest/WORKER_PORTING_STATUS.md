# V2 worker porting status

As of: 2026-05-13T21:55:54Z

Live gate: `blocked_human_only`
Final approval token: `absent`
V2 local online state: `V2_LOCAL_ONLINE_DEGRADED_P0_INCOMPLETE`

P0 progress: 1 / 6
P1 progress: 0 / 8
P2 progress: 0 / 3

## Next action

- kind: `dispatch_claude`
- next_worker: `v2_risk_gateway_runtime_worker`
- follow_up: after_claude_artifacts_appear_dispatch_codex_review_v2_risk_gateway_runtime_worker

## Worker states

| priority | worker | state | cli | tests | report | status | codex |
|---|---|---|---|---|---|---|---|
| P0 | `v2_feature_snapshot_builder` | **CODEX_PASS** | ✓ | ✓ | ✓ | ✓ | ✓ |
| P0 | `v2_risk_gateway_runtime_worker` | **QUEUED** | · | · | · | · | · |
| P0 | `v2_paper_execution_worker` | **QUEUED** | · | · | · | · | · |
| P0 | `v2_execution_ledger_worker` | **QUEUED** | · | · | · | · | · |
| P0 | `v2_signal_lineage_worker` | **QUEUED** | · | · | · | · | · |
| P0 | `v2_account_position_monitor` | **QUEUED** | · | · | · | · | · |
| P1 | `v2_market_ingestor` | **QUEUED** | · | · | · | · | · |
| P1 | `v2_coinank_liquidation_bridge` | **QUEUED** | · | · | · | · | · |
| P1 | `v2_trainer_bridge` | **QUEUED** | · | · | · | · | · |
| P1 | `v2_orchestrator_adapter` | **QUEUED** | · | · | · | · | · |
| P1 | `v2_signal_publisher` | **QUEUED** | · | · | · | · | · |
| P1 | `v2_replay_worker` | **QUEUED** | · | · | · | · | · |
| P1 | `v2_script_monitor` | **QUEUED** | · | · | · | · | · |
| P1 | `v2_config_admin_manager` | **QUEUED** | · | · | · | · | · |
| P2 | `v2_p2_default_blocked_execution_adapter_stub` | **QUEUED** | · | · | · | · | · |
| P2 | `v2_p2_binance_usdm_adapter_stub` | **QUEUED** | · | · | · | · | · |
| P2 | `v2_p2_deployment_helpers` | **QUEUED** | · | · | · | · | · |

