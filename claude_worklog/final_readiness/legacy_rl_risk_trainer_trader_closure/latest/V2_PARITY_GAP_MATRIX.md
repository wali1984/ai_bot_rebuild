# V2_PARITY_GAP_MATRIX — Phase G

Per-V2-worker parity assessment against the legacy behavior mapped in Phases D/E/F.

## Matrix

| V2 worker | legacy source files | parity classification | blocker / note |
|---|---|---|---|
| `v2_trainer_bridge` | rl/hybrid_trainer.py + ~120 rl/* helpers | **BLOCKED_BY_TRAINER_PARITY** | V2 paper mode uses momentum stub; full rl/ tree now preserved; trainer-bridge port must subprocess-wrap or re-implement + enumerate every rl/ helper in LEGACY_BASELINE_ANALYSIS.md; torch + stable_baselines3 + cloudpickle + gymnasium not installed |
| `v2_orchestrator_adapter` | rl/orchestrator_worker.py + rl/tradeplan_orchestrator.py + rl/proposal_hedge_preflight.py + rl/decision_trace.py | **PARTIALLY_MIGRATED** | Existing V2 library covers deterministic routing; legacy MoE / scenario engine / walk-forward not yet ported; CLI lift pending |
| `v2_signal_publisher` | utils/signal_publish.py + utils/signal_schema.py + trading/signal_router.py + trading/coinank_signal_adapter.py | **MISSING_IN_V2** | Placeholder service file only; legacy field schema not yet adopted; per-account routing not implemented |
| `v2_signal_lineage_worker` | rl/decision_trace.py + utils/signal_publish.py | **PARTIALLY_MIGRATED** | Lineage built inline in `paper_online_runtime`; CLI lift pending |
| `v2_risk_gateway_runtime_worker` | risk/* (22 files) + trading/{depth_execution_gate,fee_ratio_gate,adaptive_edge_gate}.py | **PARTIALLY_MIGRATED + NEEDS_TEST** | V2 library implements fail-closed live-blocked gate; legacy-equivalent denials enumerated in Phase E require 9+ new tests |
| `v2_paper_execution_worker` | trading/{execution_engine,maker_execution}.py + base_executor.py | **READONLY_BRIDGED + PAPER_ONLY** | Paper simulation in V2 library; real execution intentionally fail-closed |
| `v2_execution_ledger_worker` | trading/position_reporter.py + utils/decision_bus.py | **PARTIALLY_MIGRATED** | Paper-only ledger present; legacy attribution semantics need backfill into `LEGACY_BASELINE_ANALYSIS.md` |
| `v2_account_position_monitor` | services/portfolio_state.py + services/portfolio_publisher.py + monitor_portfolio_*.py + utils/unified_position_loader.py | **MISSING_IN_V2** | Tier-1 missing; no V2 implementation yet; LEGACY_BASELINE_REQUIRED for the upcoming port |
| `v2_market_ingestor_from_legacy_baseline` | ingest/live_binance.py + live_kucoin.py + realtime_price_provider.py + live_coinapi_* | **NEEDS_CODE_PORT** | Task descriptor queued from prior turn; baseline files preserved in startup_baseline tree |
| `v2_coinank_and_liquidation_bridge_from_legacy_baseline` | ingest/live_coinank* + live_binance_liquidations + liquidation_bridge + liquidation_levels_engine | **NEEDS_CODE_PORT** | Task descriptor queued; baseline preserved |
| `v2_feature_pipeline_and_ta_worker_from_legacy_baseline` | feature_pipeline.py + ohlcv_resampler_hotfix.py + ingest/live_technical_analysis.py + scripts/validate_symbol_universe_data.py + scripts/paralysis_detectors.py + rl/unified_feature_builder.py + rl/obs_schema.py | **NEEDS_CODE_PORT** | Task descriptor queued |
| `v2_feature_snapshot_builder` | rl/unified_feature_builder.py + rl/obs_schema.py + (legacy feature pipeline) | **CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED** | Shipped; backfill task `claude_backfill_v2_feature_snapshot_builder_legacy_analysis` queued |
| `v2_replay_worker` | rl/replay_store.py + rl/walk_forward_validation.py | **PARTIALLY_MIGRATED** | V2 library exists; CLI lift pending |
| `v2_script_monitor` | scripts/* + scripts/health_probe.py + scripts/paralysis_detectors.py | **MISSING_IN_V2** | Placeholder service file |
| `v2_config_admin_manager` | config.py + config_accounts.py + utils/runtime_flags.py + utils/preflight.py | **MISSING_IN_V2** | OPTIONS skeletons only |
| `v2_p2_default_blocked_execution_adapter_stub` | trading/base_executor.py (signature reference) + risk/assertions.py (gate reference) | **FAIL_CLOSED_STUB** | Task descriptor queued; must raise BLOCKED_GATE_NOT_APPROVED for every mutation method |
| `v2_p2_binance_usdm_adapter_stub` | utils/binance_rate_limiter.py + trading/dynamic_margin_manager.py (signature reference) | **FAIL_CLOSED_STUB** | Task descriptor queued |

## Aggregate counts

| classification | count |
|---|---|
| FULLY_MIGRATED | 0 |
| PARTIALLY_MIGRATED | 5 |
| READONLY_BRIDGED + PAPER_ONLY | 1 |
| FAIL_CLOSED_STUB | 2 |
| MISSING_IN_V2 | 4 |
| INTENTIONALLY_DEPRECATED_WITH_REASON | 0 |
| BLOCKED_BY_TRAINER_PARITY | **1 (trainer_bridge)** |
| BLOCKED_BY_PAPER_EDGE | (paper edge tightening reported in prior task) |
| BLOCKED_BY_TRADE_PERMISSION | (account/position monitor; trade-permission evidence pending) |
| NEEDS_TEST | 1 (risk gateway expansion) |
| NEEDS_CODE_PORT | 3 (market_ingestor, coinank, feature_pipeline_ta — baseline-anchored) |
| CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED | 1 (feature_snapshot_builder) |

## Why "FULLY_MIGRATED" is zero

No V2 worker today carries a `LEGACY_BASELINE_ANALYSIS.md` that cites SHA256 from the just-produced `full_runtime_copied_source_manifest.json` AND enumerates every legacy responsibility from Phases D/E/F. This is the correct outcome: the prior orchestrator-level baseline-enforcement patch (`cf22a10`) was tied to the smaller startup-baseline tree; this larger closure makes it visible that 4–5 workers thought to be "library-only mappable" actually depend on 100+ uncovered helper files.

## Implications for the live gate

`live_gate` must remain `blocked_human_only`. No worker is in a state where it could safely place a real order even hypothetically.

## What this matrix changes for the orchestrator

The orchestrator's `legacy_baseline_required_workers` and `legacy_backfill_required_workers` arrays should now include the rl/risk/trading dependency closure as a precondition for the bigger-scope workers (trainer_bridge, orchestrator_adapter, signal_publisher, risk_gateway_runtime_worker, account_position_monitor). The orchestrator code does not need a behavioral change; the per-worker `claude_port_v2_*` task descriptors must each cite the SHAs from `full_runtime_copied_source_manifest.json` in addition to the prior startup-baseline manifest.
