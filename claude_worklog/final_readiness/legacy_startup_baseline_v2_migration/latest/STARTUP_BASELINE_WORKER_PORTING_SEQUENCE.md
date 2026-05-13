# STARTUP_BASELINE_WORKER_PORTING_SEQUENCE — Phase G

Updated worker porting sequence, anchored to the legacy startup script. Encoded once in [v2_worker_porting_orchestrator.py](../../../tools/v2_worker_porting_orchestrator.py) `WORKER_SEQUENCE`.

## Ingestor-first ordering (P0)

| # | worker | what it ports / lifts | depends on |
|---|---|---|---|
| 1 | `v2_feature_snapshot_builder` | already shipped (V2 extraction; backfill task queued) | — |
| 2 | `v2_market_ingestor_from_legacy_baseline` | Phase 1 ingestors: binance / kucoin / realtime_price_provider / CoinAPI WS DS + V1 | preserved baseline + closure scan |
| 3 | `v2_coinank_and_liquidation_bridge_from_legacy_baseline` | Phase 1 ingestors: coinank / coinank_global_aggregator / binance_liquidations / liquidation_bridge / liquidation_levels_engine | preserved baseline + Plan-3 contracts |
| 4 | `v2_feature_pipeline_and_ta_worker_from_legacy_baseline` | Phase 2 + 2.5 + 2.9: ohlcv_resampler + feature_pipeline + TA + universe validation + paralysis detectors | preserved baseline; depends on #2 / #3 outputs |
| 5 | `v2_risk_gateway_runtime_worker` | V2-native fail-closed risk gates (existing library lift) | — |
| 6 | `v2_paper_execution_worker` | V2 paper trader (existing library lift) | #5 |
| 7 | `v2_execution_ledger_worker` | append-only V2 ledger (existing library lift) | #6 |
| 8 | `v2_signal_lineage_worker` | full chain lineage (existing library + placeholder replacement) | #4–#7 |
| 9 | `v2_account_position_monitor` | read-only account/position (Tier-1 missing in V2 today) | exchange read-only credentials per operator |

## P1

| # | worker | source |
|---|---|---|
| 10 | `v2_trainer_bridge` | legacy rl/hybrid_trainer.py (subprocess wrapper or V2-native service) |
| 11 | `v2_orchestrator_adapter` | legacy rl/orchestrator_worker.py (read-only consume + V2-namespaced publish) |
| 12 | `v2_signal_publisher` | broadcast layer above signal_lineage |
| 13 | `v2_replay_worker` | CLI lift of existing V2 library |
| 14 | `v2_script_monitor` | Monitor Center backend (placeholder replacement) |
| 15 | `v2_config_admin_manager` | runtime config CRUD with approval workflow |

## P2 (fail-closed stubs)

| # | worker | rule |
|---|---|---|
| 16 | `v2_p2_default_blocked_execution_adapter_stub` | every mutation method raises `BLOCKED_GATE_NOT_APPROVED` |
| 17 | `v2_p2_binance_usdm_adapter_stub` | read-only paths only; mutating endpoints raise `BLOCKED_GATE_NOT_APPROVED` |
| 18 | `v2_p2_deployment_helpers` | preflight + start + stop scripts; refuse to start if approval token present |

## Why this order

Legacy startup script proves the data plane begins with **monitoring → ingestors → feature pipeline / TA → trainer → orchestrator → trader**. V2 ports follow the same dependency-order so the downstream gates (risk gateway, paper execution, signal lineage) consume real V2-namespaced ingestor data rather than synthetic fixtures. The two trader files (`trading/trader.py`, `trading/trader-asjad.py`) are **never started by V2**; they exist in `v2/legacy_preserved/startup_baseline/` only so the P2 fail-closed stub can be authored from the legacy baseline with correct method signatures.

## What counts as "complete" per the orchestrator

A worker is `CODEX_PASS` only when on disk:

1. CLI under `v2/backend/app/cli/<worker>.py`
2. Tests under `v2/backend/tests/integration/cli/test_<worker>.py`
3. Worker report at `claude_worklog/.../workers/<worker>_report.md`
4. Worker status JSON at `claude_worklog/.../workers/<worker>_status.json`
5. `LEGACY_BASELINE_ANALYSIS.md` — must cite SHA256 from `copied_baseline_manifest.json` for baseline-named workers
6. `legacy_behavior_mapping.json`
7. Paired Codex GO/NO-GO file containing the `<WORKER_UPPER>_CODEX_PASS` marker

The orchestrator currently classifies the new baseline-named workers (#2, #3, #4) as `LEGACY_BASELINE_REQUIRED` until items 5 and 6 land for each.
