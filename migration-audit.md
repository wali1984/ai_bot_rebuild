# Migration Audit: Legacy Bot → V2 Rebuild

**Generated:** 2026-05-15  
**Legacy source:** `/home/wali/Desktop/AI BOT`  
**V2 destination:** `/home/wali/Desktop/AI BOT REBUILD/v2`

---

## Summary

| Category | Legacy Files | V2 Native | V2 Bridge/Adapter Only | Not Started |
|---|---|---|---|---|
| **Trainer (core)** | 1 (57,250 lines) | ❌ | ✅ subprocess wrapper | ❌ |
| **RL Environment** | 5 files | ❌ | ❌ | ❌ |
| **MASA/PPO Architecture** | 3 files | ❌ | ❌ | ❌ |
| **Reward Functions** | 6 files | ❌ | ❌ | ❌ |
| **Feature Pipeline** | 1 (1,437 lines) | ❌ | ✅ legacy_adapter (reads Redis) | ❌ |
| **Feature Builder / Observation** | 4 files | ✅ domain models only | — | ⚠️ logic missing |
| **Ingestors** | 13 live ingestors | ❌ | ✅ cli workers bridge data | ❌ |
| **Trainer health/liveness** | ❌ (legacy had none) | ✅ full domain | — | — |
| **Orchestrator / Proposal bus** | 2 files (10,523 lines) | ⚠️ partial | — | ⚠️ |
| **Trading execution** | 35 files | ❌ | ✅ paper/intent models only | ❌ |
| **Risk management** | 8 files | ✅ risk gateway domain | — | ⚠️ depth missing |
| **Config** | 1 (6,006 lines) | ⚠️ partial settings | — | ⚠️ |
| **Utils / Redis client** | 21 files | ✅ redis_v2, logger | — | ⚠️ some missing |
| **API** | 9 routes | ✅ full v2 REST API | — | — |
| **Frontend** | None (old dashboard only) | ✅ Vite/React built | — | — |

---

## 1. TRAINER — Core ML Engine

### Legacy: `rl/hybrid_trainer.py`
- **57,250 lines** — the largest single file in the system
- PPO + MASA ensemble with dual-head actor-critic policy
- RTX 5080 GPU-optimized training loop
- Live real-time training on incoming Redis features
- Stable-Baselines3 SubprocVecEnv with 8+ parallel envs
- Checkpoint save/load every N loops
- Mixed-precision autocast (CUDA AMP)
- Heartbeat + kill-switch support
- Adaptive confidence gates, MASA weighting

### Direct Dependencies of hybrid_trainer:
| Module | File | Lines | Status |
|---|---|---|---|
| `rl.agents.masa_agent` | `rl/agents/masa_agent.py` | 520 | ❌ Not migrated |
| `rl.gymnasium_wrapper` | `rl/gymnasium_wrapper.py` | 343 | ❌ Not migrated |
| `rl.environment` | `rl/environment.py` | 1,455 | ❌ Not migrated |
| `rl.execution_overlay` | `rl/execution_overlay.py` | ~300 | ❌ Not migrated |
| `rl.fastlane_detector` | `rl/fastlane_detector.py` | ~200 | ❌ Not migrated |
| `rl.position_context` | `rl/position_context.py` | ~250 | ❌ Not migrated |
| `rl.increase_signal_validator` | `rl/increase_signal_validator.py` | ~200 | ❌ Not migrated |
| `rl.CRITICAL_HEDGE_AND_PORTFOLIO_FIX` | `rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py` | ~400 | ❌ Not migrated |
| `utils.redis_client` | `utils/redis_client.py` | ~150 | ✅ V2 has `redis_v2` adapter |
| `utils.logger` | `utils/logger.py` | ~80 | ✅ V2 has logger |
| `config` | `config.py` | 6,006 | ⚠️ V2 has partial settings only |

### V2 Status:
- `v2/backend/app/adapters/trainer/subprocess_adapter.py` — 227 lines. **Wraps legacy trainer as subprocess** (argv contract, audit emission, timeout, safety blocks). Does NOT reimplement the trainer.
- `v2/backend/app/adapters/trainer/default_runner.py` — actual subprocess runner
- `v2/backend/app/cli/v2_trainer_bridge.py` — observes legacy trainer output (predictions/proposals) from Redis, bridges to v2 domain. Read-only bridge, no mutation.
- `v2/legacy_preserved/full_runtime_closure/rl/hybrid_trainer.py` — snapshot copy preserved for reference

**⛔ VERDICT: The trainer itself (PPO+MASA, GPU env, SB3 loop) is NOT migrated. V2 runs the legacy trainer via subprocess and bridges its output.**

---

## 2. RL Environment & Observation Space

### Legacy files:
| File | Lines | Purpose |
|---|---|---|
| `rl/environment.py` | 1,455 | Core Gymnasium trading env — state, step, reset, reward |
| `rl/gymnasium_wrapper.py` | 343 | `TradingEnvironmentWrapper`, `make_env` factory |
| `rl/gpu_environment.py` | ~400 | GPU-batched variant |
| `rl/gpu_batch_env.py` | ~300 | Batched env for SubprocVecEnv |
| `rl/obs_schema.py` | ~150 | Observation tensor schema |
| `rl/unified_feature_builder.py` | 710 | Builds obs tensor from 2000+ Redis features |

### V2 Status:
- `v2/backend/app/domain/features/` — domain models (FeatureSnapshot, manifest, freshness, validation, completeness). **Schema/contracts only — no tensor building logic.**
- `v2/backend/app/services/feature_assembly.py` — partial assembly service
- `v2/backend/app/services/feature_snapshots/` — snapshot storage/retrieval

**⛔ VERDICT: The actual environment (step/reset/action/reward loop) is NOT migrated. Feature domain models exist but `unified_feature_builder` tensor assembly logic is not ported.**

---

## 3. MASA Agent & PPO Architecture

### Legacy files:
| File | Lines | Purpose |
|---|---|---|
| `rl/agents/masa_agent.py` | 520 | MASAAgent, MASAConfig, HybridPPO, DualHeadActorCriticPolicy |
| `rl/enhanced_architectures.py` | ~600 | CNN/attention feature extractor for policy |
| `rl/gpu_cnn_policy.py` | ~400 | GPU-optimized CNN policy |
| `rl/gpu_forced_ppo.py` | ~350 | GPU-forced PPO variant |
| `rl/stable_gpu_trainer.py` | ~800 | Stable GPU training utilities |
| `rl/moe_router.py` | ~300 | Mixture-of-experts routing |

### V2 Status:
- **None of these are migrated.** V2 has no PyTorch model definitions, no SB3 policy, no custom CNN extractor.

**⛔ VERDICT: 0% migrated.**

---

## 4. Reward Functions & Training Signals

### Legacy files:
| File | Lines | Purpose |
|---|---|---|
| `rl/reward_functions.py` | 902 | Core reward shaping: PnL, fee-adjusted, risk-penalized |
| `rl/constrained_reward.py` | ~250 | Constrained reward with safety penalties |
| `rl/fee_ratio_reward_shaping.py` | ~200 | Fee-ratio-aware reward modifier |
| `rl/hedge_reward_functions.py` | ~300 | Hedge-specific reward components |
| `rl/metrics_tracker.py` | ~400 | Tracks training metrics and reward decomposition |
| `rl/continuous_learner.py` | ~500 | Online learning loop with replay |

### V2 Status:
- **None migrated.** V2 has paper edge scoring (`composition/paper_edge_scoring`) but this is outcome measurement, not reward shaping for RL.

**⛔ VERDICT: 0% migrated.**

---

## 5. Feature Pipeline

### Legacy: `feature_pipeline.py`
- **1,437 lines** — runs as a live daemon
- Reads raw data from Redis (from all ingestors)
- Computes derived features, cross-timeframe aggregations
- Normalizes and writes `features:*` keys to Redis (2000+ features)
- Currently **running** at legacy bot

### V2 Status:
- `v2/backend/app/adapters/feature_pipeline/legacy_adapter.py` — 15 lines. Thin adapter that converts dict payloads to `FeatureSnapshot` domain objects. **Does not compute features.**
- `v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py` — CLI worker (bridges legacy Redis output to v2)
- `v2/backend/app/services/feature_pipeline_and_ta/service.py` — service stub

**⚠️ VERDICT: V2 reads legacy feature pipeline output from Redis. No native v2 feature computation yet.**

---

## 6. Ingestors (Data Sources)

### Legacy running ingestors:
| Script | Data Source | Redis Keys | Status |
|---|---|---|---|
| `ingest/live_binance.py` | Binance USDM WebSocket | OHLCV, orderbook, funding | ✅ Running |
| `ingest/live_binance_liquidations.py` | Binance liquidations | `liq:*` | ✅ Running |
| `ingest/live_coinank.py` | CoinAnk API (long/short, CVD, net pos) | `coinank:*`, `features:coinank_*` | ✅ Running |
| `ingest/live_kucoin.py` | KuCoin orderbook | `kc:*` | ✅ Running |
| `ingest/live_technical_analysis.py` | Computed TA indicators | `ta:*` | ✅ Running |
| `ingest/realtime_price_provider.py` | Price aggregation | `price:*` | ✅ Running |
| `ingest/live_coinapi_v1.py` | CoinAPI REST v1 | `coinapi:*` | ✅ Running |
| `ingest/live_coinapi_wsds.py` | CoinAPI WebSocket | `coinapi:ws:*` | ✅ Running |
| `ingest/live_tokenmetrics.py` | TokenMetrics grades/scores | `tm:*` | ❌ Stopped (user) |
| `ingest/live_alphavantage_news.py` | AlphaVantage news sentiment | `av:*` | ❌ Not running |
| `ingest/liquidation_bridge.py` | Liquidation level engine | `liq_levels:*` | ❌ Not running |
| `ingest/live_ccxt.py` | CCXT multi-exchange | various | ❌ Not running |

### V2 Status:
- `v2/backend/app/cli/v2_market_ingestor.py` — CLI worker that bridges **existing** legacy ingestor data from Redis to v2 domain
- `v2/backend/app/adapters/symbol_sources/` — symbol universe adapters for Binance, KuCoin, CoinAnk, CoinAPI (symbol lists only, not data ingestors)
- `v2/backend/app/services/market_ingest/service.py` — service stub

**⛔ VERDICT: V2 has no native WebSocket/REST ingestors. All live data comes from legacy ingestors. V2 workers read from the same Redis.**

---

## 7. Orchestrator / Proposal Bus

### Legacy:
| File | Lines | Purpose |
|---|---|---|
| `rl/orchestrator_worker.py` | 10,523 | Signal arbitration, proposal scoring, entry/exit decisions |
| `rl/proposal_bus.py` | ~400 | Redis stream pub/sub for trade proposals |
| `rl/tradeplan_orchestrator.py` | ~600 | Trade plan assembly and lifecycle |
| `rl/proposal_schema.py` | ~300 | Proposal data schema |
| `rl/trade_proposal.py` | ~400 | Proposal construction |
| `rl/intent_engine.py` | ~500 | Intent generation from signals |

### V2 Status:
- `v2/backend/app/composition/orchestrator_decision/` — domain record + runtime composition for orchestrator decisions
- `v2/backend/app/adapters/orchestrator/adapter.py` — orchestrator adapter
- `v2/backend/app/api/v1/decisions.py` — decision API
- `v2/backend/app/domain/execution/intent.py` — execution intent model

**⚠️ VERDICT: V2 has the decision record schema and API layer. The arbitration logic (10,523 lines of proposal scoring, signal routing, regime filtering) is NOT ported.**

---

## 8. Trading Execution

### Legacy `trading/` — 35 files:
| File | Purpose |
|---|---|
| `trader.py` | Main execution engine (~18,000+ lines) |
| `stealth_stops.py` | Stealth stop management |
| `stealth_dynamic_integration.py` | Dynamic stealth TP/SL integration |
| `dynamic_adaptive_stops.py` | Regime-adaptive stop distances |
| `dynamic_tp_engine.py` | Dynamic take-profit engine |
| `execution_engine.py` | Order placement and fill tracking |
| `leg_manager.py` | Multi-leg position management |
| `adaptive_hedge_builder.py` | Hedge construction |
| `dynamic_adaptive_hedge.py` | Adaptive hedge sizing |
| `hedge_pair_coordinator.py` | Hedge pair lifecycle |
| `exit_coordinator.py` | Coordinated exit logic |
| `maker_execution.py` | Maker-order execution |
| `market_intelligence.py` | Pre-trade market context |
| `market_regime_detector.py` | Regime detection for execution |
| `churn_prevention.py` | Anti-churn position management |
| `adaptive_edge_gate.py` | Edge quality gate before entry |
| `fee_ratio_gate.py` | Fee-to-expected-move ratio guard |
| `smart_entry_gate.py` | Multi-factor entry quality gate |
| `depth_execution_gate.py` | Orderbook depth gate |
| `opportunity_tracker.py` | Opportunity scanning |
| `signal_router.py` | Signal routing to execution |

### V2 Status:
- `v2/backend/app/domain/execution/intent.py` — `ExecutionIntent` dataclass (paper only)
- `v2/backend/app/domain/execution/paper.py` — paper fill model
- `v2/backend/app/composition/paper_mode/` — paper trade composition
- `v2/backend/app/composition/paper_execution_ledger/` — paper ledger
- `v2/backend/app/api/v1/paper.py` — paper trade API
- Live execution adapters: `v2/backend/app/adapters/exchanges/binance/__init__.py` — **empty stub**
- `v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py` — blocked by design

**⛔ VERDICT: Live trading execution is 0% migrated. V2 is paper/shadow only. All exchange adapters are empty stubs. This is intentional — live execution is gated behind human approval.**

---

## 9. Risk Management

### Legacy:
| File | Purpose |
|---|---|
| `rl/advanced_risk_management.py` | Portfolio-level risk controls |
| `rl/liquidation_prevention.py` | Liquidation distance monitoring |
| `rl/global_safety_checks.py` | Global circuit breakers |
| `rl/dynamic_position_sizing.py` | Kelly/volatility-based sizing |
| `rl/hedge_budget_governor.py` | Hedge budget allocation |
| `trading/assert_governor.py` | Assertion-level risk gates |
| `circuit_breaker.py` | Emergency circuit breaker |
| `emergency_brake.py` | Hard emergency stop |

### V2 Status:
- `v2/backend/app/composition/risk_gateway/` — risk gateway domain + runtime ✅
- `v2/backend/app/api/v1/risk.py` + `risk_decisions.py` — risk API ✅
- `v2/backend/app/domain/governance/` — governance + approval chain ✅
- Liquidation prevention, dynamic position sizing, Kelly criterion: **❌ Not migrated**

**⚠️ VERDICT: Risk gateway framework exists. Deep risk logic (liquidation prevention, dynamic sizing, Kelly) is not ported.**

---

## 10. Config

### Legacy: `config.py` — 6,006 lines
Contains: SYMBOLS list, TIMEFRAMES, feature flags, all API keys, confidence thresholds, position sizing parameters, account configs, GPU settings, every tunable parameter.

### V2 Status:
- `v2/backend/app/cli/v2_config_admin_manager.py` — config admin CLI ✅
- `v2/backend/app/api/v1/config_admin.py` — config API ✅
- `v2/backend/app/domain/` — no central config equivalent
- **Legacy `config.py` is still the source of truth** for all running services

**⚠️ VERDICT: V2 config management is scaffolded. The 6,006-line `config.py` parameter set is not formally ported/validated in v2.**

---

## 11. Utils

### Legacy `utils/` — 21 files:
| File | V2 Equivalent | Status |
|---|---|---|
| `utils/redis_client.py` | `adapters/redis_v2/` (full suite) | ✅ Migrated |
| `utils/logger.py` | v2 uses structlog | ✅ Migrated |
| `utils/signal_publish.py` | `adapters/redis_v2/streams.py` | ✅ Migrated |
| `utils/signal_schema.py` | `api/schemas/signal.py` | ✅ Migrated |
| `utils/data_manager.py` | ❌ | ❌ Not migrated |
| `utils/data_normalizer.py` | ❌ | ❌ Not migrated |
| `utils/symbol_manager.py` | `adapters/symbol_sources/` (partial) | ⚠️ Partial |
| `utils/ai_coins_manager.py` | ❌ | ❌ Not migrated |
| `utils/decision_bus.py` | `adapters/orchestrator/adapter.py` | ⚠️ Partial |
| `utils/healthbeat.py` | `api/v1/health.py` | ✅ Migrated |
| `utils/metrics.py` | ❌ | ❌ Not migrated |
| `utils/runtime_flags.py` | ❌ | ❌ Not migrated |
| `utils/preflight.py` | ❌ | ❌ Not migrated |
| `utils/ensemble_diagnostics.py` | ❌ | ❌ Not migrated |
| `utils/binance_rate_limiter.py` | ❌ | ❌ Not migrated |
| `utils/unified_position_loader.py` | ❌ | ❌ Not migrated |
| `utils/interrupt_lock.py` | ❌ | ❌ Not migrated |
| `utils/interpreter_guard.py` | ❌ | ❌ Not migrated |
| `utils/websocket_limits.py` | ❌ | ❌ Not migrated |

---

## 12. What IS Fully Migrated in V2 ✅

These components are **new in v2** (no legacy equivalent, purpose-built for the rebuild):

| Component | Path | Description |
|---|---|---|
| **REST API (FastAPI)** | `app/api/v1/` (30+ routes) | Full API: decisions, signals, features, governance, paper, replay, risk, universe, health, ingestors, audit |
| **DB repositories** | `app/adapters/db/repositories/` | SQLAlchemy repos: predictions, decisions, signals, evidence, accounts, sessions, governance |
| **Redis V2 adapter** | `app/adapters/redis_v2/` | Typed client, streams, retention, factory, error handling |
| **Trainer health/liveness** | `app/domain/trainer_liveness/` + `app/domain/trainer_worker_health/` | Full domain: SLA config, evaluator, alerts, snapshots — 100+ unit tests |
| **Trainer parity** | `app/domain/trainer_parity/` + `app/composition/trainer_parity/` | Feature freshness, lineage validation, stage A/B records |
| **Trainer prediction output** | `app/domain/trainer_prediction_output/` | Prediction record with invariant enforcement, confidence, direction, freshness |
| **Paper mode** | `app/composition/paper_mode/` + `app/composition/paper_execution_ledger/` | Full paper trading pipeline |
| **Governance / approvals** | `app/domain/governance/` | Approval chain, audit events, human-in-the-loop gates |
| **Risk gateway** | `app/composition/risk_gateway/` | Risk decision domain and composition |
| **Lineage** | `app/domain/lineage/` | Chain-of-custody IDs and validators |
| **Evidence packets** | `app/adapters/evidence/` | Audit evidence writer/reader |
| **Shadow mode readiness** | `app/composition/shadow_mode_readiness/` | Shadow pre-live gate |
| **Replay/backtest runner** | `app/composition/replay_backtest_runner/` | Historical replay domain |
| **Frontend (Vite/React)** | `v2/frontend/` | Operator dashboard, 189 modules, production build |
| **Ollama integration** | `app/adapters/ollama/` | Local LLM assistant |
| **Symbol universe** | `app/services/symbol_universe/` | Dynamic symbol selection |
| **External position quarantine** | `app/domain/external_manual_position_quarantine/` | Quarantine for externally placed positions |

---

## 13. Critical Gaps — Ordered by Priority

| Priority | Gap | What Needs Building | Blocker For |
|---|---|---|---|
| 🔴 P1 | **Native v2 RL environment** | Port `rl/environment.py` (1,455 lines), `gymnasium_wrapper.py`, `obs_schema.py`, `unified_feature_builder.py` | Trainer running natively in v2 |
| 🔴 P1 | **MASA/PPO model architecture** | Port `rl/agents/masa_agent.py`, `enhanced_architectures.py`, `gpu_cnn_policy.py` | Native v2 trainer |
| 🔴 P1 | **Reward functions** | Port `rl/reward_functions.py` (902 lines), constrained reward, fee-ratio shaping | Native v2 trainer |
| 🔴 P1 | **GPU training loop** | Port `hybrid_trainer.py` core loop — SubprocVecEnv, AMP, checkpoint, heartbeat | Replace subprocess wrapper |
| 🟠 P2 | **Native ingestors** | Port or rebuild all 9 live ingestor scripts as v2 workers | Remove legacy dependency |
| 🟠 P2 | **Feature computation pipeline** | Port `feature_pipeline.py` (1,437 lines) to v2 native worker | Remove legacy dependency |
| 🟠 P2 | **Orchestrator arbitration** | Port `rl/orchestrator_worker.py` (10,523 lines) signal scoring logic | Decision engine in v2 |
| 🟡 P3 | **Exchange execution adapters** | Implement `adapters/exchanges/binance/`, `okx/`, etc. (currently empty stubs) | Live trading in v2 |
| 🟡 P3 | **Stop loss / TP engine** | Port `trading/stealth_stops.py`, `dynamic_tp_engine.py`, `dynamic_adaptive_stops.py` | Live trading in v2 |
| 🟡 P3 | **Config unification** | Formalize `config.py` (6,006 lines) parameters into v2 schema/env system | Clean separation |
| 🟡 P3 | **Utils remaining** | Port `data_manager.py`, `data_normalizer.py`, `symbol_manager.py`, `runtime_flags.py` | Reduce legacy coupling |
| 🟢 P4 | **Hedge system** | Port `rl/hedge_*`, `trading/adaptive_hedge_*`, `trading/dynamic_adaptive_hedge.py` | Multi-leg positions in v2 |
| 🟢 P4 | **Dynamic position sizing** | Port `rl/dynamic_position_sizing.py`, Kelly criterion | Live risk controls |

---

## 14. Current Architecture (As-Is)

```
Legacy Bot (still running)               V2 Rebuild (in progress)
─────────────────────────────────────    ──────────────────────────────────────
  Ingestors (9 live) → Redis               V2 Frontend (Vite/React) ↔ V2 API
  feature_pipeline.py → Redis              V2 FastAPI backend
  rl/hybrid_trainer.py (PPO+MASA)          └─ subprocess_adapter wraps legacy
    └─ reads Redis features                    trainer (no native RL yet)
    └─ writes predictions/proposals        └─ v2_trainer_bridge reads legacy
  rl/orchestrator_worker.py                   Redis predictions → v2 DB
    └─ arbitrates signals                  └─ Paper mode / shadow mode
    └─ gates entries/exits                 └─ Governance / approvals
  trading/trader.py (STOPPED)             └─ Risk gateway domain
    └─ stealth SL/TP (STOPPED)            └─ Feature snapshot domain
                                          └─ Trainer health/liveness monitoring
                                          └─ Legacy ingestor bridges (CLI workers)
```

---

## 15. Preserved Legacy Snapshots in V2

`v2/legacy_preserved/` contains frozen read-only copies for reference:

- `full_runtime_closure/rl/` — hybrid_trainer, environment, MASA agent, reward functions, all RL modules
- `full_runtime_closure/trading/` — action_constants, opportunity_tracker
- `startup_baseline/ingest/` — all live ingestors
- `startup_baseline/rl/` — hybrid_trainer snapshot
- `ingestors/live_coinank.py`

These are **reference copies only** — not executed.

---

*Last updated: 2026-05-15*
