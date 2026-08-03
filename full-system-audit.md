# Full Legacy → V2 System Audit
**Generated:** 2026-05-15  
**Method:** Live filesystem scan + process enumeration  
**Legend:** ✅ Migrated natively | ⚠️ Partial/stub only | 🔁 Bridge/wrapper (legacy still does the work) | ❌ Not started

---

## 1. CODEBASE SIZE COMPARISON

| Metric | Legacy (`AI BOT/`) | V2 (`AI BOT REBUILD/v2/backend/`) |
|---|---|---|
| Total Python files | ~16,773 (incl. debug/test) | ~590 source + 1,159 test files |
| Production source LOC | **216,127** | **42,791** (20% of legacy) |
| Test LOC | ~8,000 (legacy tests) | **1,159 test files** (modern unit tests) |
| Empty stub files | 0 | **34 empty .py stubs** (not yet implemented) |
| Running processes (legacy) | **13 core services** + 128 subprocess workers | 4 v2 workers (paper_online, feature_snapshot, v2ctl workers) |

---

## 2. CURRENTLY RUNNING PROCESSES

### Legacy (all from `/home/wali/Desktop/AI BOT/`):
| PID | Service | Status |
|---|---|---|
| 46149 | `monitoring/oom_monitor.py` | ✅ Running |
| 46218 | `ingest/live_binance.py` | ✅ Running |
| 46365 | `ingest/live_binance_liquidations.py` | ✅ Running |
| 46559 | `ingest/live_coinank.py` | ✅ Running |
| 47157 | `ingest/live_kucoin.py` | ✅ Running |
| 47348 | `ingest/live_technical_analysis.py` | ✅ Running |
| 47589 | `ingest/realtime_price_provider.py` | ✅ Running |
| 48066 | `feature_pipeline.py` | ✅ Running |
| 48623 | `rl.hybrid_trainer` (+ 128 subprocess workers) | ✅ Running |
| 49067 | `trading/opportunity_tracker.py` | ✅ Running |
| 54017 | `rl.orchestrator_worker` | ✅ Running |
| 54905 | `ingest/live_coinapi_v1.py` | ✅ Running |
| 55369 | `ingest/live_coinapi_wsds.py` | ✅ Running |

### V2 (from `/home/wali/Desktop/AI BOT REBUILD/`):
| PID | Service | Status |
|---|---|---|
| 1456707 | `app.cli.paper_online_runtime --loop` | ✅ Running (paper shadow) |
| 73368 | `app.cli.v2_feature_snapshot_builder --loop` | ✅ Running (reads legacy) |
| 430848 | `tools/v2_worker_porting_orchestrator.py --daemon` | ✅ Running |
| 859673 | `tools/agent_supervisor.py --daemon` | ✅ Running |
| 1506056 | `tools/codex_legacy_v2_realtime_decision_observatory.py` | ✅ Running |
| 1506099 | `tools/codex_legacy_shutdown_readiness_takeover.py` | ✅ Running |
| 559209 | `tools/codex_non_live_watchdog.py --daemon` | ✅ Running |

**Key observation:** ALL production trading is still 100% legacy. V2 is running in shadow/paper/observation mode only.

---

## 3. SUBSYSTEM-BY-SUBSYSTEM AUDIT

### 3.1 DATA INGESTORS

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `ingest/live_binance.py` | 2,642 | Binance WS: OHLCV, trades, depth | `services/binance_usdm_adapter/service.py` (242 LOC) | ⚠️ Stub only — reads legacy Redis keys |
| `ingest/live_binance_liquidations.py` | 921 | Liquidation feeds | `services/coinank_bridge/service.py` (1,013 LOC) | ⚠️ Bridge — reads legacy stream |
| `ingest/live_coinank.py` | 2,754 | CoinAnk sentiment + funding + OI | `services/coinank_bridge/service.py` | ⚠️ Bridge |
| `ingest/live_coinank_global_aggregator.py` | 376 | Global CoinAnk aggregation | None | ❌ |
| `ingest/live_kucoin.py` | 896 | KuCoin alt data WS | None | ❌ |
| `ingest/live_coinapi_v1.py` | 739 | CoinAPI REST polling | None | ❌ |
| `ingest/live_coinapi_wsds.py` | 1,735 | CoinAPI WS deep stream | None | ❌ |
| `ingest/live_technical_analysis.py` | 158 | TA trigger | None | ❌ |
| `ingest/live_alphavantage_news.py` | 255 | News sentiment | None | ❌ |
| `ingest/live_tokenmetrics.py` | 998 | TokenMetrics AI scores | None | ❌ |
| `ingest/realtime_price_provider.py` | 1,146 | Real-time price aggregation | None | ❌ |
| `ingest/liquidation_levels_engine.py` | 492 | Liquidation level calc | None | ❌ |
| `ingest/ccxt_historical.py` | 1,209 | CCXT historical backfill | None | ❌ |
| `ingest/technical_analysis.py` | 762 | Full TA library | `services/feature_pipeline_and_ta/service.py` (771 LOC) | ⚠️ Partial — TA computed but not replicated identically |

**Ingestor migration: ~10% complete**

---

### 3.2 FEATURE PIPELINE

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `feature_pipeline.py` | 1,437 | Master feature assembler | `cli/v2_feature_pipeline_and_ta_worker.py` (586 LOC) | 🔁 Reads legacy Redis keys |
| `rl/unified_feature_builder.py` | 710 | 2000+ feature obs vector | `app/adapters/feature_pipeline/legacy_adapter.py` (15 LOC) | ❌ Stub only |
| `rl/obs_schema.py` | 468 | Observation space schema | `domain/features/models.py` (82 LOC) | ⚠️ Schema only |
| `rl/tf_aggregator.py` | 188 | Multi-TF feature aggregation | None | ❌ |
| `rl/microstructure_features.py` | 588 | Orderbook/vol/liq features | None | ❌ |
| `rl/microstructure_aggregator.py` | 470 | Multi-TF microstructure agg | None | ❌ |
| `rl/microstructure_overlay.py` | 1,127 | Pre-trade quality filter | None | ❌ |
| `rl/microstructure_proactive.py` | 1,434 | Proactive microstructure | None | ❌ |
| `rl/microstructure_source_router.py` | 561 | Microstructure source routing | None | ❌ |
| `rl/microstructure_tf_modifier.py` | 322 | TF-based modification | None | ❌ |
| `rl/portfolio_aware_features.py` | 505 | Portfolio-level features | `domain/features/models.py` | ⚠️ Schema only |
| `rl/portfolio_risk_features.py` | 464 | Portfolio risk features | None | ❌ |

**Feature pipeline migration: ~5% complete**

---

### 3.3 ML TRAINING ENGINE

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `rl/hybrid_trainer.py` | **57,250** | PPO+MASA training loop, GPU engine, all prediction/signal logic | `adapters/trainer/subprocess_adapter.py` (227 LOC) | 🔁 Subprocess wrapper only |
| `rl/environment.py` | 1,455 | Gymnasium trading env | None | ❌ |
| `rl/gpu_environment.py` | 1,249 | GPU-optimized env | None | ❌ |
| `rl/gpu_batch_env.py` | 240 | GPU-batched vec env | None | ❌ |
| `rl/gpu_forced_ppo.py` | 295 | PPO GPU subclass | None | ❌ |
| `rl/agents/masa_agent.py` | 520 | MASA supervised agent | None | ❌ |
| `rl/supervised_trainer.py` | 1,083 | MASA supervised pretraining | None | ❌ |
| `rl/reward_functions.py` | 902 | 5 reward function classes | None | ❌ |
| `rl/constrained_reward.py` | 298 | Safety-constrained reward | None | ❌ |
| `rl/fee_ratio_reward_shaping.py` | 519 | Fee-aware reward shaping | None | ❌ |
| `rl/hedge_reward_functions.py` | 451 | Hedge-specific reward | None | ❌ |
| `rl/checkpoint_manager.py` | 359 | Checkpoint lifecycle | None | ❌ |
| `rl/continuous_learner.py` | 662 | Online/continuous learning | None | ❌ |
| `rl/enhanced_architectures.py` | 611 | Custom NN architectures | None | ❌ |
| `rl/moe_router.py` | 385 | Mixture of Experts router | None | ❌ |

**Training engine migration: ~0% (subprocess wrapper only)**

---

### 3.4 CONFIDENCE & PREDICTION SYSTEM

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `rl/calibrated_confidence.py` | 263 | Temperature scaling / Platt | None | ❌ |
| `rl/confidence_gates.py` | 583 | Per-symbol confidence gating | None | ❌ |
| `rl/threshold_ramper.py` | 301 | Auto-ramp confidence thresholds | None | ❌ |
| `rl/confidence_logger.py` | 224 | Confidence tracking/logging | None | ❌ |
| `rl/temperature_calibration.py` | 144 | Temperature calibration util | None | ❌ |
| `rl/uncertainty.py` | 306 | Uncertainty estimation | None | ❌ |
| In `hybrid_trainer.py` | embedded | MTF confidence, calibration, gating | `domain/trainer_parity/` (schema only) | ⚠️ Schema only |

**Confidence system migration: ~0%**

---

### 3.5 SIGNAL GENERATION & ORCHESTRATION

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `rl/orchestrator_worker.py` | **10,523** | Full signal orchestration loop | `cli/v2_orchestrator_adapter.py` (1,111 LOC) | 🔁 Reads legacy signals, wraps them |
| `rl/signal_state_manager.py` | 554 | Per-symbol signal state | None | ❌ |
| `rl/proposal_schema.py` | 501 | Signal proposal format | `domain/orchestrator_decision/record.py` (204 LOC) | ⚠️ Schema only |
| `rl/proposal_bus.py` | 70 | Proposal publication bus | None | ❌ |
| `rl/tradeplan_orchestrator.py` | 1,427 | Trade plan orchestration | None | ❌ |
| `rl/intent_engine.py` | 164 | Intent generation | None | ❌ |
| `rl/action_ontology.py` | 521 | Action space definition | None | ❌ |
| `rl/hybrid_action_space.py` | 458 | Hybrid action space | None | ❌ |
| `rl/hedge_action_space.py` | 360 | Hedge action space | None | ❌ |
| `rl/ta_direction_oracle.py` | 653 | TA direction signal | None | ❌ |
| `rl/fastlane_detector.py` | 422 | Fast-move detection | None | ❌ |
| `rl/move_shock_engine.py` | 224 | Move shock detection | None | ❌ |
| `rl/mtf_position_builder.py` | 341 | MTF position building | None | ❌ |
| `rl/ingestor_quality_router.py` | 538 | Ingestor quality routing | None | ❌ |

**Signal/orchestration migration: ~10% (adapter reads legacy output)**

---

### 3.6 TRADING EXECUTION

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `trading/trader.py` | **24,277** | Main execution engine (2 accounts, hedge mode, order management) | `cli/v2_paper_execution_worker.py` (1,367 LOC) | 🔁 Paper execution only |
| `trading/base_executor.py` | 2,132 | Order execution primitives | None | ❌ |
| `trading/maker_execution.py` | 661 | Maker order strategy | None | ❌ |
| `trading/execution_engine.py` | 348 | Execution routing | `services/default_blocked_execution_adapter/` | ⚠️ Blocked (no-op) |
| `trading/signal_router.py` | 349 | Signal → execution routing | `cli/v2_signal_publisher.py` (403 LOC) | ⚠️ Paper only |
| `trading/smart_entry_gate.py` | 865 | Smart entry gating | `services/risk_gateway/evaluators.py` (341 LOC) | ⚠️ Partial gates only |
| `trading/adaptive_edge_gate.py` | 1,569 | Edge quality gate | None | ❌ |
| `trading/adaptive_threshold_engine.py` | 794 | Adaptive TP/SL thresholds | None | ❌ |
| `trading/depth_execution_gate.py` | 458 | Orderbook depth gate | None | ❌ |
| `trading/fee_ratio_gate.py` | 412 | Fee-ratio filter | None | ❌ |
| `trading/churn_prevention.py` | 572 | Anti-churn at trade layer | None | ❌ |
| `trading/exit_coordinator.py` | 489 | Exit signal coordination | None | ❌ |
| `trading/market_intelligence.py` | 1,806 | Market intel for execution | None | ❌ |
| `trading/market_regime_detector.py` | 799 | Regime at execution layer | None | ❌ |
| `trading/dynamic_margin_manager.py` | 393 | Margin management | None | ❌ |
| `trading/redesign_v2_helpers.py` | 903 | V2 trading helpers | None | ❌ |
| `trading/opportunity_tracker.py` | 211 | Opportunity tracking | None | ❌ |
| `trading/position_reporter.py` | 429 | Position reporting | `cli/v2_account_position_monitor.py` (484 LOC) | ⚠️ Read-only |

**Trading execution migration: ~5% (paper-only, no live execution)**

---

### 3.7 STOP LOSS / TAKE PROFIT

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `trading/stealth_stops.py` | **6,972** | Full stealth SL/TP daemon | None | ❌ |
| `trading/stealth_dynamic_integration.py` | 222 | Stealth+Dynamic integration | None | ❌ |
| `trading/dynamic_adaptive_stops.py` | 1,063 | Regime-adaptive stops | None | ❌ |
| `trading/dynamic_tp_engine.py` | 1,468 | Dynamic TP engine | None | ❌ |

**SL/TP migration: 0%**

---

### 3.8 HEDGE SYSTEMS (4 layers)

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `rl/hedge_manager_v3.py` | 2,244 | Main hedge decision engine | None | ❌ |
| `rl/hedge_harvest_engine.py` | 327 | Harvest profitable hedges | None | ❌ |
| `rl/hedge_budget_governor.py` | 107 | Hedge margin budget | None | ❌ |
| `rl/dynamic_runner_hedge.py` | 791 | Runner-mode hedge | None | ❌ |
| `rl/hedge_position_manager.py` | 584 | Hedge position lifecycle | None | ❌ |
| `rl/hedge_rule_engine.py` | 543 | Rule-based hedge decisions | None | ❌ |
| `trading/adaptive_hedge_builder.py` | 610 | Adaptive hedge construction | None | ❌ |
| `trading/dynamic_adaptive_hedge.py` | 1,126 | Dynamic adaptive hedge | None | ❌ |
| `trading/hedge_context.py` | 1,308 | Hedge context tracking | None | ❌ |
| `trading/hedge_intelligence_engine.py` | 947 | Hedge intelligence | None | ❌ |
| `trading/hedge_pair_coordinator.py` | 337 | Hedge pair management | None | ❌ |
| `trading/leg_manager.py` | 629 | Trade leg management | None | ❌ |
| `trading/lifecycle_controller.py` | 104 | Trade lifecycle control | None | ❌ |

**Hedge systems migration: 0%**

---

### 3.9 ANTI-CHURN / TOXICITY / VETO

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `rl/anti_churn_manager.py` | 341 | Per-symbol rate limiting | None | ❌ |
| `rl/churn_veto.py` | 160 | ML churn veto model | None | ❌ |
| `rl/toxicity_shield.py` | 163 | Toxicity blocking | None | ❌ |
| `rl/minimum_hold_time.py` | 490 | Minimum hold enforcement | None | ❌ |

**Anti-churn migration: 0%**

---

### 3.10 REGIME DETECTION

| Legacy File / Function | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `trading/market_regime_detector.py` | 799 | Execution-layer regime | None | ❌ |
| `rl/market_context.py` | 639 | Market context builder | None | ❌ |
| `_classify_market_regime()` in trainer | embedded | 5-axis regime (trend/vol/sentiment/liquidity/cross-market) | None | ❌ |
| `_analyze_regime_with_lstm()` | embedded | LSTM regime classification | None | ❌ |

**Regime detection migration: 0%**

---

### 3.11 POSITION SIZING & RISK

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `rl/advanced_risk_management.py` | 580 | Advanced risk management | `services/risk_legacy_gates/evaluators.py` (612 LOC) | ⚠️ Some gates only |
| `rl/global_safety_checks.py` | 553 | Global safety gates | `services/risk_gateway/evaluators.py` (341 LOC) | ⚠️ Basic gates only |
| `rl/liquidation_prevention.py` | 779 | Liquidation prevention | None | ❌ |
| `rl/dynamic_position_sizing.py` | 282 | Dynamic position sizing | None | ❌ |
| `rl/target_exposure_controller.py` | 1,073 | Exposure management | None | ❌ |
| `rl/portfolio_policy_manager.py` | 1,134 | Portfolio policy | None | ❌ |
| `rl/portfolio_recovery_allocator.py` | 515 | Recovery allocation | None | ❌ |
| `rl/underwater_recovery_controller.py` | 1,136 | Underwater position recovery | None | ❌ |
| `rl/auto_contraction.py` | 569 | Auto-contraction in drawdown | None | ❌ |
| `rl/promotion_controller.py` | 920 | Position promotion control | None | ❌ |

**Position sizing/risk migration: ~10% (basic gates only)**

---

### 3.12 DRIFT MONITORING

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `rl/drift_monitor.py` | 465 | PSI/KL drift detection | None | ❌ |
| `rl/feature_health.py` | 393 | Feature health tracking | `domain/features/freshness.py` (43 LOC) | ⚠️ Freshness only |

**Drift monitoring migration: ~5%**

---

### 3.13 PROFIT TRACKING

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `rl/profit_bank.py` | 240 | Running P&L bank | `services/paper_shadow_outcome_observer/service.py` (471 LOC) | 🔁 Paper shadow only |
| `rl/profit_freespace_rebalancer.py` | 184 | Free margin rebalancing | None | ❌ |
| `rl/trade_feedback.py` | 936 | Trade outcome feedback loop | `services/signal_outcome_observer/service.py` (68 LOC) | ⚠️ Stub only |
| `rl/metrics_tracker.py` | 211 | Performance metrics | None | ❌ |

**Profit tracking migration: ~15% (paper shadow only)**

---

### 3.14 CONFIGURATION

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `config.py` | **6,006** | Monolithic config (all symbols, all params) | `services/config_admin/service.py` (235 LOC) | ⚠️ Admin API only |
| `config_accounts.py` | 328 | Account credentials config | `app/settings.py` (25 LOC) | ⚠️ Partial |
| `config/settings.py` | 58 | Settings module | `app/settings.py` | ⚠️ Partial |

**Config migration: ~20%**

---

### 3.15 API / INTERFACE

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `api/app.py` | 315 | Flask API server | `app/main.py` (131 LOC) + `app/api/v1/` | ✅ FastAPI fully built |
| `api/auth.py` | 293 | JWT auth | `app/api/v1/auth.py` | ✅ |
| `api/routes/*.py` | ~2,800 | 7 route modules | `app/api/v1/` (~30 endpoint files) | ✅ All routes present |
| `api/grpc_server.py` | 379 | gRPC server | Not migrated | ❌ |

**API migration: ~80% (REST complete, gRPC missing)**

---

### 3.16 MONITORING

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `monitoring/oom_monitor.py` | 401 | OOM monitoring | None in v2 (still runs legacy) | ❌ |
| `monitoring/deep_troubleshooter.py` | 3,943 | Deep diagnostic | `app/cli/paper_shadow_metrics_analyzer.py` (300 LOC) | ⚠️ Partial |
| `monitoring/live_system_auditor.py` | 1,834 | Live system audit | `services/monitor_runner.py` (215 LOC) | ⚠️ Partial |
| `monitoring/regression_alarms.py` | 445 | Regression detection | None | ❌ |

**Monitoring migration: ~15%**

---

### 3.17 NOTIFICATIONS

| Legacy File | LOC | Function | V2 Equivalent | Status |
|---|---|---|---|---|
| `telegram_alerts.py` | **2,243** | Full Telegram alert system | None | ❌ |

**Notifications migration: 0%**

---

## 4. WHAT V2 HAS THAT LEGACY DOESN'T

These are **new capabilities** built only in v2 — no legacy equivalent:

| V2 Capability | Location | Maturity |
|---|---|---|
| Trainer liveness SLA (HEALTHY/DEGRADED/CRITICAL) | `domain/trainer_liveness/` | ✅ Full |
| Trainer prediction output domain model | `domain/trainer_prediction_output/` | ✅ Full |
| Orchestrator decision domain model | `domain/orchestrator_decision/` | ✅ Full |
| Paper execution ledger (full audit trail) | `domain/paper_execution_ledger/` | ✅ Full |
| Paper shadow outcome learning | `services/paper_shadow_outcome_observer/` | ✅ Full |
| Provenance / dedupe / attribution chain | `services/provenance_dedupe_attribution/` | ✅ Full |
| External manual position quarantine | `domain/external_manual_position_quarantine/` | ✅ Full |
| Degraded state fail-closed gates | `composition/degraded_state_fail_closed_gates/` | ✅ Full |
| Risk gateway domain (structured decision records) | `domain/risk_gateway/` | ✅ Full |
| Risk legacy gates (re-implements legacy checks cleanly) | `services/risk_legacy_gates/` | ✅ Full |
| Replay/backtest runner domain | `domain/replay_backtest_runner/` | ✅ Full |
| Shadow mode readiness gate | `domain/shadow_mode_readiness/` | ✅ Full |
| Symbol universe service (dynamic symbol selection) | `services/symbol_universe/` | ✅ Full |
| Hot-reload quorum state machine | `domain/hot_reload/` | ⚠️ Stubs only |
| Governance approval chain | `domain/governance/` | ⚠️ Stubs only |
| Lineage chain-of-custody | `domain/lineage/` | ⚠️ Stubs only |
| Ollama LLM integration | `adapters/ollama/` | ⚠️ Stub only |
| FastAPI REST API (30+ endpoints) | `app/api/v1/` | ✅ Built |
| React/Vite operator dashboard | `frontend/` | ✅ Built |
| 1,159 unit tests | `tests/unit/` | ✅ Full |
| Paper online runtime (continuous shadow trading) | `cli/paper_online_runtime.py` | ✅ Running |
| Non-live operational proof runner | `proof/non_live_operational_proof.py` | ✅ Full |

---

## 5. MIGRATION COMPLETION MATRIX

| Subsystem | Legacy LOC | V2 LOC (native) | % Migrated | Blocker |
|---|---|---|---|---|
| Data Ingestors | ~14,000 | ~1,800 | **~10%** | WS reconnect logic, coinank/kucoin/tokenmetrics |
| Feature Pipeline | ~8,000 | ~600 | **~5%** | 2000+ feature keys, normalization, microstructure |
| ML Training Engine | ~65,000 | 227 (wrapper) | **~0%** | 57,250-line hybrid_trainer.py |
| Confidence System | ~1,800 | 0 | **~0%** | Calibration, gating, ramping |
| Signal Generation | ~18,000 | ~1,500 | **~8%** | 10,523-line orchestrator_worker |
| Trading Execution | ~30,000 | ~1,400 | **~5%** | 24,277-line trader.py |
| Stop Loss / TP | ~9,700 | 0 | **~0%** | 6,972-line stealth_stops.py |
| Hedge Systems | ~9,000 | 0 | **~0%** | 4 independent hedge layers |
| Anti-Churn / Veto | ~1,150 | 0 | **~0%** | ChurnVetoModel + AntiChurnManager |
| Regime Detection | ~2,200 | 0 | **~0%** | 5-axis regime classification |
| Position Sizing / Risk | ~9,000 | ~1,000 | **~10%** | Sizing, leverage, portfolio policy |
| Drift Monitoring | ~860 | ~50 | **~5%** | PSI/KL divergence trackers |
| Profit Tracking | ~1,600 | ~550 | **~15%** | Paper shadow only |
| Configuration | ~6,400 | ~260 | **~20%** | 6,006-line config.py |
| API / Interface | ~3,300 | ~3,500 | **~80%** | gRPC missing |
| Monitoring | ~7,000 | ~500 | **~10%** | OOM monitor, regression alarms |
| Notifications | ~2,400 | 0 | **~0%** | Entire Telegram alert system |
| **TOTAL** | **~216,127** | **~42,791** | **~20%** | — |

---

## 6. CRITICAL GAPS (PRIORITY ORDER)

### P0 — System cannot run independently without these:
1. **Trading Execution** (`trader.py`, 24,277 LOC) — all live order placement, hedge mode, dual-account
2. **ML Trainer** (`hybrid_trainer.py`, 57,250 LOC) — all prediction, PPO+MASA, GPU training
3. **Data Ingestors** (Binance WS, CoinAnk, KuCoin, CoinAPI) — ~14,000 LOC of WS feeds

### P1 — Trading quality degrades severely without these:
4. **Stop Loss / TP System** (stealth_stops + dynamic_tp + adaptive_stops = ~9,700 LOC)
5. **Hedge Systems** (4 layers, ~9,000 LOC)
6. **Orchestrator Worker** (`orchestrator_worker.py`, 10,523 LOC) — signal decision loop
7. **Feature Pipeline** + microstructure (~8,000 LOC)

### P2 — Risk management degrades without these:
8. **Confidence System** (~1,800 LOC) — calibration, gating, threshold ramping
9. **Anti-Churn + Toxicity** (~1,150 LOC)
10. **Regime Detection** (~2,200 LOC)
11. **Position Sizing** (~9,000 LOC)

### P3 — Operational:
12. **Config migration** (`config.py`, 6,006 LOC of parameters)
13. **Telegram alerts** (`telegram_alerts.py`, 2,243 LOC)
14. **Monitoring** regression alarms, OOM monitor

---

## 7. STUB / PLACEHOLDER COUNT IN V2

```
34 empty .py files — these are reserved namespaces not yet implemented:
  - app/adapters/db/repositories/*.py  (10 files — all DB repos)
  - app/adapters/exchanges/*.py        (4 files — exchange adapters)  
  - app/adapters/ollama/client.py      (LLM client)
  - app/adapters/evidence/*.py         (evidence packet I/O)
  - app/domain/governance/*.py         (approval chain)
  - app/domain/hot_reload/*.py         (hot-reload state machine)
  - app/domain/lineage/*.py            (lineage validators)
  - app/services/*/stub files          (several service stubs)
```

---

## 8. OVERALL VERDICT

| Dimension | Status |
|---|---|
| **V2 runs production trading** | ❌ NO — 100% legacy |
| **V2 runs paper shadow trading** | ✅ YES (paper_online_runtime running) |
| **V2 has live data feeds** | ❌ NO — reads from legacy Redis |
| **V2 has ML inference** | ❌ NO — subprocess wrapper reads legacy |
| **V2 has stop loss / TP** | ❌ NO |
| **V2 has hedge system** | ❌ NO |
| **V2 has governance / audit** | ✅ YES — most complete subsystem |
| **V2 has REST API** | ✅ YES — 30+ endpoints |
| **V2 has frontend dashboard** | ✅ YES — Vite/React running |
| **V2 has unit tests** | ✅ YES — 1,159 test files |
| **Overall migration** | **~20%** |

The project has strong foundations in governance, observability, paper trading, and the API/frontend layer. The algorithmic core — trainer, execution, stops, hedges, and real ingestors — is entirely in legacy and represents the vast majority (~80%) of remaining work.

---

*Generated: 2026-05-15 | Legacy LOC: 216,127 | V2 source LOC: 42,791*
