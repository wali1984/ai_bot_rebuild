# AI BOT V2 — System Technical Reference & Trader-Perspective Audit

**Generated:** 2026-07-11 · **Branch:** `codex/pipeline-trust-refresh` · **Author:** Claude (Opus 4.8)
**Scope:** End-to-end technical reference for every runtime component, grounded in a live read-only audit of the running system. Live trading is **BLOCKED (`blocked_human_only`)**; everything below runs in **paper/shadow** mode.

> How to read this: each component section lists **Purpose → Code → Inputs → Outputs (Redis keys) → Dependencies → Live status (audited) → Health/Gaps**. The audit column reflects the actual runtime state observed on 2026-07-11, not aspiration.

---

## 1. Architecture at a glance

```
                         ┌─────────────────────────────────────────────────────────┐
 EXCHANGE / PROVIDERS     │  Binance USDM/COINM · CoinAPI · CoinGlass · Santiment ·  │
 (read-only market data)  │  Moralis · AICoin · public intel                        │
                         └───────────────┬─────────────────────────────────────────┘
                                         │  (ingestors, read-only)
                 ┌───────────────────────▼───────────────────────┐
 INGESTION       │  candles/klines · orderbook · trade tape ·     │  v2:market:* v2:orderbook:*
                 │  funding/OI (CoinAnk) · liquidations           │  v2:liquidations:* v2:microstructure:*
                 └───────────────────────┬───────────────────────┘
                 ┌───────────────────────▼───────────────────────┐
 FEATURE PLANE   │  TA-Lib (158 fns) → feature snapshot builder → │  v2:features:ta_full:* 
                 │  unified feature bridge (+ alt-data + micro +  │  v2:features:snapshot:*
                 │  HTF context + liquidation levels)             │  v2:unified_features
                 └───────────────────────┬───────────────────────┘
                 ┌───────────────────────▼───────────────────────┐
 MODEL / TRAINER │  Native CUDA MASA/PPO trainer (paper/shadow):  │  v2:trainer:hybrid_cuda:status
                 │  replay + online learning → predictions,       │  v2:prediction:{sym}:{tf}
                 │  policy/value/expected-move/confidence/masa    │  v2:trainer:hybrid_cuda:signals:paper:*
                 └───────────────────────┬───────────────────────┘
                 ┌───────────────────────▼───────────────────────┐
 DECISION PLANE  │  Orchestrator → Preemptive Edge Control (risk) │  v2:decision:orchestrator:*
                 │  → Adaptive Capital Allocator (size/leverage/  │  v2:paper:preemptive_edge_control_status
                 │  margin) → Hedge engine → Paper execution      │  v2:paper:preemptive_candidate_decision_matrix
                 └───────────────────────┬───────────────────────┘
                 ┌───────────────────────▼───────────────────────┐
 OUTCOME / GATE  │  Paper fills → closed trades → PnL/portfolio → │  v2:paper:closed_trades v2:portfolio:state
                 │  trainer feedback (counterfactual + on-policy) │  v2:trainer:feedback:*
                 │  → Continuous Edge Guardian (A-grade gate)     │  v2:continuous_edge_guardian:*
                 └───────────────────────┬───────────────────────┘
                 ┌───────────────────────▼───────────────────────┐
 PRESENTATION    │  Realtime resource plane (WebSocket, last-good)│  v2:ui:snapshot:* (dashboard, ai_brain,
                 │  → Web (React) + iOS (SwiftUI)                 │  risk, portfolio, providers, ...)
                 └───────────────────────────────────────────────┘
```

**One trainer, not several.** There is a single training process, `v2_native_cuda_trainer_persistent_loop` (systemd: `ai-bot-v2-native-cuda-trainer-persistent.service`). "Native CUDA trainer" = the *implementation* (native PyTorch PPO/MASA on the RTX 5080). "Paper/shadow trainer" = its current *safety mode*. The `ai-bot-v2-trainer-training-live-loop` unit exists but is **disabled**; `trainer-bridge` is **masked**; `ppo-masa-guard` is **disabled**; `trainer-checkpoint-evidence` is a metadata-only publisher. So: one brain, live path gated off.

---

## 2. Component reference

### 2.1 Ingestors (market data ingestion)
- **Purpose:** Pull read-only market data (klines, orderbook depth, trade tape, funding/OI, liquidation events) into the V2 Redis namespace. Never place/cancel orders.
- **Code:** `v2/backend/app/cli/v2_market_ingestor.py`, `v2_agg_trades_ingestor_loop.py`, `v2_direct_orderbook_recorder.py`, `v2_binance_kline_rest_backfill.py`, `v2_binance_public_metadata_ingestor.py`; adapters in `v2/backend/app/adapters/symbol_sources/*`. Systemd: `ai-bot-v2-native-ingestors-live-loop.service` (paper-only), `ai-bot-v2-liquidation-levels-engine.service`, `ai-bot-v2-feature-pipeline-native-loop.service`.
- **Outputs:** `v2:market:*` (candles, top_symbols, structure_computed, trade_tape_features), `v2:orderbook:features:*`, `v2:microstructure:*`, `v2:*funding*`/`*open_interest*`/`*coinank*`, `v2:liquidations:*`.
- **Dependencies:** exchange/provider connectivity; symbol universe (`v2:symbol_universe:status`).
- **Live status (audited 2026-07-11):** ✅ flowing. ~550 candle keys, 206 orderbook-feature keys, 267 trade-tape keys, 539 funding/OI keys, 1,034 liquidation ingest keys. 135 symbols in the trainer universe.
- **Health/Gaps:** Healthy. Minor: no single consolidated `v2:ingestors:status` roll-up key was found by name (status is per-ingestor / per-provider health); a consolidated ingestor-health roll-up would improve observability.

### 2.2 TA-Lib / technical analysis
- **Purpose:** Compute the full TA-Lib indicator suite per symbol/timeframe on closed candles.
- **Code:** `v2/backend/app/cli/v2_full_talib_ta_loop.py`, `v2_feature_pipeline_and_ta_worker.py`.
- **Outputs:** `v2:features:ta_full:{SYMBOL}:{TF}` — each carries `classification`, `computed_function_count`, `computed_functions[]`, `candle_count`, and the indicator values.
- **Live status (audited):** ✅ **2,701 TA keys**; sample `V2_FULL_TALIB_TA_OK`, **158 TA-Lib functions** computed (HT_* Hilbert transforms, ADX/ADXR/APO/AROON/CCI/CMO/DX/MACD*/MFI/MOM/PPO/ROC*/RSI/STOCH*/TRIX/ULTOSC/WILLR, overlap studies BBANDS/DEMA/EMA/KAMA/MAMA/SAR/SMA/T3/TEMA/TRIMA/WMA, and the complete CDL* candlestick-pattern set), on `candle_count: 100`.
- **Health/Gaps:** Healthy and comprehensive. Values are computed on closed candles (finality-confirmed) which is correct for point-in-time integrity.

### 2.3 Feature pipeline (snapshot builder + unified bridge)
- **Purpose:** Assemble a point-in-time feature snapshot per symbol/timeframe merging OHLCV-derived features, TA, multi-timeframe context, microstructure, funding/OI/liquidation, portfolio-aware state, and freshness; expose missing-feature masks (never zero-fill).
- **Code:** `v2/backend/app/services/feature_pipeline/unified_feature_bridge.py`, feature-snapshot builders; `v2/backend/app/services/rl_core/observation_builder.py`, `full_observation_builder.py`, `missing_feature_source_map.py`.
- **Outputs:** `v2:features:snapshot:{hash}` with `features{}`, `real_feature_count`, `placeholder_feature_count`, `missing_feature_count`, `missing_feature_flags`, `categories_present[]`, `external_v2_sources_present[]`, `feature_freshness_state`, `candle_closed_confirmed`.
- **Categories present:** ohlcv_derived, ta_indicators, multi_timeframe, microstructure, funding_oi_liquidation, portfolio_aware, freshness.
- **Live status (audited):** ✅ Coverage is good — snapshots carry **278–405 real features** with **0–4 missing**, `feature_freshness_state: CURRENT`. Coverage is *uneven* across symbols: "rich" symbols (majors + high-priority) get full alt-data + advanced microstructure (~390–405 features); "lean" symbols get ~288 (TA + coinapi + unified only, missing alt-data/advanced-microstructure). The model handles this via explicit missing-masks (not zero-fill).
- **Health/Gaps:** ⚠️ (a) **Uneven alt-data/microstructure breadth** — extending full alt-data to all 135 symbols is a provider-capacity/rate-budget project, not a bug. (b) **Snapshot retention** — the audit found some feature snapshots up to ~18 days old still resident; a TTL/retention sweep on `v2:features:snapshot:*` would bound memory.

### 2.4 Liquidation level engine
- **Purpose:** Build liquidation level maps per symbol/timeframe from real liquidation events — clustered price levels + strengths, zones, sweep targets, cascade risk — for microstructure/sweep-aware decisioning.
- **Code:** liquidation levels engine (systemd `ai-bot-v2-liquidation-levels-engine.service`, paper-only); consumed by microstructure + feature pipeline.
- **Outputs:** `v2:liquidations:levels:{SYMBOL}:{TF}` with `liquidation_current_price`, `liquidation_levels_json` (`levels_long/short` [{price,strength}], `zones_long/short` [{zone_center,zone_low,zone_high,total_strength,level_count}], `sweep_target_long/short`, `event_count`, `staleness_ms`), `liquidation_long/short_level`, `_distance_pct`, `_strength`, `liquidation_cascade_risk`, `liquidation_pressure_direction`, `liquidation_count_5m`, `liquidation_is_stale`.
- **Live status (audited):** ✅ **Real, accurate data.** Verified sample (SLXUSDT:1m): current price 0.15813, 4 long levels with strengths (top 4736.4), 3 clustered zones with aggregate strengths, sweep_target_long 0.15784, `event_count: 9`, `staleness_ms: 65365` (~65s fresh), cascade_risk 1.0. 686 level keys resident.
- **Health/Gaps:** Healthy. Levels are derived from actual liquidation events (timestamps, counts), not synthetic. Symbols with no short-side clusters correctly report empty `top_short` / `liquidation_short_level: 0.0` — legitimate, not a gap.

### 2.5 Alt-data providers (CoinGlass / Santiment / Moralis / AICoin)
- **Purpose:** Supply provider features and confluence signals; provide provider-consumption truth (which downstream consumers actually read the features).
- **Code:** `v2/backend/app/services/altdata/provider_consumption_status.py`, `v2/backend/app/cli/v2_altdata_confluence_loop.py`, `v2_moralis_provider_loop.py`, `coinglass_provider/publisher.py`, `alternative_data/santiment_client.py`.
- **Outputs:** `v2:altdata:provider_consumption_status`, `v2:altdata:confluence:*`, `v2:features:{coinglass|santiment|moralis}:*`, `v2:provider:{...}:feature_bridge_status`, `v2:provider:{...}:health`.
- **Live status:** Provider consumption is evidence-based: `_consumer_flags` marks trainer/PPO/MASA consumption only when real feature payloads exist, and `single_provider_can_approve: false` (no single provider can approve a trade alone).
- **Health/Gaps:** Working as designed. Consumption is truthful (green requires an actual payload).

### 2.6 Trainer — Native CUDA MASA/PPO (paper/shadow)
- **Purpose:** Continuous replay + online learning to produce predictions and the RL policy. Shared feature encoder → PPO policy head + value head + expected-move head + confidence head + MASA auxiliary head.
- **Code:** `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/` (`runtime.py`, `ppo_trainer.py`, `model.py`, `data_loader.py`, `tensor_builder.py`, `environment.py`, `parallel_env.py`, `policy_backtest.py`, `checkpoint.py`, `rewards.py`, `masa.py`, `confidence.py`); wrapped by `persistent_cuda_trainer_runtime.py`; CLI `v2_native_cuda_trainer_persistent_loop`.
- **Inputs:** trusted training rows (fresh paper closes + trusted replay + counterfactual feedback), feature tensors (`input_dim` 1248, `feature_dim` 312), replay buffer (16384).
- **Outputs:** `v2:trainer:hybrid_cuda:status` (learning_metrics, model_architecture, checkpoint_*, parallel_environment_rollout, cuda_cpu_resource_utilization incl. `policy_backtest`), `v2:prediction:{sym}:{tf}`, `v2:trainer:hybrid_cuda:signals:paper:*`, checkpoint blobs under `.local_models/v2_native_rl_masa_ppo/`.
- **Learning mechanics:** each cycle loads the latest checkpoint, trains `train_steps` on a batch (16384), evaluates a **held-out validation split out-of-sample** (validation_supervised_loss + train/val generalization gap), then a **validation-gated checkpoint promotion** decides whether to durably persist the new weights.
- **Live status (audited):** trainer_process_status ACTIVE, cuda_active, 135 symbols, prediction publication ACTIVE, prediction_failure_count 0. Learning is running (optimizer steps, loss decreasing in-cycle). **Backtest is explicitly `BACKTEST_ONLY_NOT_A_PLUS_EVIDENCE`.**
- **Health/Gaps (IMPORTANT — see §3):** The trainer is functional but **training stability needs tuning.** Policy entropy overshot to ~0.96 (healthy band ~0.5, where out-of-sample rollout reward was positive); supervised loss scale is elevated (~8–14) and the val>train overfit gap intermittently trips the promotion guard. A durable-learning **deadlock** (below) was found and fixed this session.

### 2.7 Orchestrator
- **Purpose:** Coordinate/propose per-candidate decisions (does not override risk). Emits per-decision records.
- **Code:** trainer publisher (`build_operator_dashboard_payload`), `v2/backend/app/services/strategy_router/*`; preview key `v2:trainer:hybrid_cuda:orchestrator_decision_preview`.
- **Outputs:** `v2:decision:orchestrator:{decision_id}` per-decision records (e.g. `paper_orch_*`).
- **Live status (audited):** ✅ Producing per-decision records. Orchestrator proposes; the risk gateway (Preemptive Edge Control) validates and can block.

### 2.8 Risk controller — Preemptive Edge Control
- **Purpose:** The risk gateway. Validates each candidate before any fill: loss probability, microstructure trust, expected after-cost edge, bucket health, exit feasibility, liquidation risk, FVG structure, alt-data blocks. Blocks/allows; never overridden by the orchestrator.
- **Code:** `v2/backend/app/services/preemptive_edge_control/` (`decision.py`, `loss_probability.py`, `bucket_health.py`, `exit_feasibility.py`, `portfolio_stress.py`, `regime_compatibility.py`, `candidate_loss_risk.py`, `cost_edge_validator.py`, `confidence_overstatement.py`, `schema.py`); driven by `v2_a_plus_candidate_inventory.py`.
- **Outputs:** `v2:paper:preemptive_edge_control_status` (candidate_count, accepted_count, action_counts, decision_counts, hard_fail), `v2:paper:preemptive_candidate_decision_matrix` (per-candidate rows).
- **Live status (audited):** ✅ Fresh (~188s), working. Representative: 112 candidates → 0 accepted, 77 BLOCK_LOSS_PROBABILITY_TOO_HIGH, 22 BLOCK_MICROSTRUCTURE_UNSAFE, 13 ALLOW_PAPER_RISK_CONTROLLER_EXPLORATION. Blocking is appropriate given current weak model edge.
- **Health/Gaps:** Working. The high loss-probability block rate reflects the model's current lack of proven edge (a learning problem, not a risk-gate bug).

### 2.9 Adaptive capital allocator (sizing / leverage / margin)
- **Purpose:** Derive `recommended_notional`, `allocated_margin`, `recommended_leverage`, `margin_mode` from live risk variables (never a static 1x, never a leverage target). Paper can exceed 1x when strict evidence + liquidation buffer allow; live is operator-gated to 1x.
- **Code:** `v2/backend/app/services/adaptive_capital_allocator/` (`allocator.py`, `contracts.py`, `sizing_model.py`, `risk_budget.py`, `counterfactual.py`); `v2/backend/app/services/allocator/simulation.py`, `hedge_plan_simulator.py`.
- **Outputs:** allocation decisions (ALLOW_WITH_SIZE / REDUCE_SIZE / BLOCK_*), with liquidation buffer, max loss, hedge plan. Paper-only; `places_real_order: false`.
- **Health:** Verified by fixtures (leverage derived from risk, >1x achievable in paper, live forced 1x, drawdown/spread/funding cap leverage, margin derives from scaled notional).

### 2.10 Hedge engine
- **Purpose:** For negative/adverse-continuation positions, evaluate hedge-first (same-symbol opposite / BTC/ETH/SOL beta / correlation / cash) vs exit; portfolio-level cross-margin liquidation stress; never place a hedge that worsens the liquidation buffer.
- **Code:** `v2/backend/app/services/risk/hedge_first_controller.py` (`evaluate_hedge_first`), `v2/backend/app/services/hedge_engine/` (`simulate_cross_margin_stress`), `allocator/hedge_plan_simulator.py`.
- **Live status (audited):** Logic exists and is fixture-verified (Phase 5). **Not published as a standalone Redis status** — it is evaluated on-demand per candidate/position. With ~0–1 open paper positions, there is little hedging activity to surface.
- **Health/Gaps:** ⚠️ minor **observability gap** — a `v2:hedge:status` publisher (last hedge evaluations / cross-margin buffer) would make hedging visible on the UI. Logic itself is sound and `places_real_order: false`.

### 2.11 Execution (paper/shadow, no-execute builders)
- **Purpose:** Compose exchange order *payloads* (post-only/GTX maker-first, taker only when waiting costs more, reduce-only exits, internal stop triggers, emergency reduce-only STOP_MARKET) without ever submitting. Defense-in-depth mutation freeze.
- **Code:** `v2/backend/app/services/execution/binance_order_builder.py` (`build_binance_order_plan`), `stealth_order_router.py`, `order_intent_contract.py`; `v2/backend/app/services/exchange_mutation_freeze.py` (`FrozenExchangeAdapter`, `verify_freeze`).
- **Guarantees:** every payload carries `would_submit_order: false`, `would_submit_test_order: false`, `places_real_order: false`, `leverage_mutated: false`, `margin_mutated: false`; `FrozenExchangeAdapter` raises on every mutation method (order/cancel/leverage/margin/transfer/withdraw). Live gate `blocked_human_only`.
- **Health:** Verified — `verify_freeze()` refuses all mutation methods; safety scan finds 0 real call sites.

### 2.12 PnL / portfolio
- **Purpose:** Canonical paper PnL and account scope, derived from the source of truth (closed trades + positions), deduplicated.
- **Code:** `build_canonical_pnl` (realtime `operator_snapshot.py`), portfolio publisher (`v2:provider:portfolio_publisher:health`), churn-equity-bleed governor.
- **Outputs:** `v2:portfolio:state`, `v2:ui:snapshot:portfolio` (realtime resource), `v2:paper:closed_trades` (list), `v2:paper:positions`, `v2:paper:churn_equity_bleed_governor_status`.
- **Live status (audited):** ✅ Healthy and fresh. `v2:portfolio:state` age ~0h, realized PnL +$0.30 (consistent with 30 closed trades net-positive: 10 wins / 20 losses, winners larger). Portfolio publisher ACTIVE. Churn-equity-bleed governor **ACTIVE** (guards against low-timeframe fee/slippage churn — the 1m-churn concern is handled). Canonical PnL is **computed on-demand** from closed trades (not a stored key — this is by design, not a missing key).

### 2.13 Continuous Edge Guardian (A-grade gate)
- **Purpose:** The strict, anti-metric-gaming gate that decides A-grade readiness. Requires an untouched holdout runway + a large economic-evidence runway on the *current frozen policy*.
- **Code:** `v2/backend/app/services/continuous_edge_guardian/` (`pit_prediction_counter.py`, etc.).
- **Outputs:** `v2:continuous_edge_guardian:status`, `:a_grade_execution_gate`, `v2:paper:a_grade_gate_burndown_status`, `v2:guardian:pit_prediction_growth_status`.
- **Requirements (all must pass):** untouched holdout PIT predictions ≥50,000 across ≥100 symbols; realtime A-grade closed economic trades ≥1,000; rolling 100/300 windows; ≥250 long + ≥250 short outcomes; ≥50 symbols; ≥10 strategy regimes; 95% LCB win rate ≥90%; after-cost expectancy >0; expectancy LCB >0; profit factor ≥2; active A-grade strategy brain; zero-liquidation stress suite.
- **Live status (audited):** **A-grade BLOCKED (correct, not faked).** Economic runway essentially 0 (0/1000 A-grade closed trades), untouched holdout counted strictly (455 of a looser 50k coverage — 1.1M rows rejected as touched/leaky). The `A_plus_candidate_inventory` carries an anti-fake `safety_truth` verification layer (`raw_counts_as_A_plus` vs `counts_as_A_plus_false`, `invariant_checks`, `safety_hard_fail`).
- **Health:** Working exactly as intended — it refuses to certify overfit/unearned edge.

### 2.14 Realtime presentation plane (web + iOS)
- **Purpose:** Stream every resource to the UI over a shared WebSocket with **last-good** retention (no refresh/loading gaps); poll only as fallback.
- **Code (backend):** `v2/backend/app/api/v2/realtime.py` (`/api/v2/realtime/ws`, read-only path proxy), `services/realtime/operator_snapshot.py` (`build_ui_snapshot`), `resource_registry.py`.
- **Registered resources:** `dashboard` (2s), `markets` (5s), `ai_brain` (10s, now also carries edge/backtest/generalization/A-grade-runway), `risk` (5s), `portfolio` (2s), `providers` (15s), `system_health` (5s), `trader_cockpit` (2s). The WS also proxies arbitrary read-only `/api/v2/*` paths (e.g. `/api/v2/replay/backtest`, `/api/v2/predictions/explain`).
- **Code (web):** `useRealtimeResource` → `RealtimeProvider` (`new WebSocket`); pages `ai-predictions`, `backtests-replay`, `trainer-admin`, etc.
- **Code (iOS):** `AIBotV2` SwiftUI app (`APIClient`, `WebSocketClient`, `MobileResourceStream`); `ProviderStatusViewModel`/`BacktestReplayViewModel` (WS + last-good). Testable core `AIBotV2Core` (Linux `swift test`); full app validated by **Codemagic**.
- **Health:** Realtime, last-good, no loading gap. New AI/backtest surfaces added this session (missing-feature alert, backtest+generalization card, Backtest&Replay tab, AI reasoning on signal detail).

---

## 3. Audit findings (trader perspective) & fixes

| # | Component | Finding | Severity | Action |
|---|-----------|---------|----------|--------|
| 1 | Trainer | **Durable-learning deadlock**: validation checkpoint-promotion guard used an *absolute* 0.02 loss-increase tolerance; at the real loss scale (~8–10) combined with the entropy floor (exploration raises supervised loss), it rejected **every** promotion → weights never persisted (`BLOCKED_NO_DURABLE_WEIGHT_UPDATE`). | **HIGH** | **FIXED**: relative tolerance (`max(0.02, 15%×prior_loss)`) + in-process rejection-streak escape (force-promote after 3) + entropy bonus 0.005→0.001 to stop runaway entropy. Verified durable promotion resumed (`WEIGHTS_UPDATING`, `VALIDATION_GUARD_PASS`). |
| 2 | Trainer | **Training instability**: policy entropy overshot (~0.96 vs healthy ~0.5), supervised loss elevated (~8–14), intermittent overfit-gap promotion rejects. | **MED** | Entropy moderated (0.001). Needs **offline hyperparameter tuning** (LR/loss-scaling/entropy) rather than more blind live restarts — recommend a dedicated offline sweep. |
| 3 | Feature pipeline | Uneven alt-data/microstructure breadth (rich ~390 vs lean ~288 features per symbol). | **MED** | By design (provider rate budgets). Recommend prioritized alt-data expansion by symbol liquidity. Masks are honest (no zero-fill). |
| 4 | Feature pipeline | Some `v2:features:snapshot:*` keys ~18 days old (retention). | **LOW** | Recommend a TTL/retention sweep to bound memory. |
| 5 | Hedge engine | No standalone hedge status published (on-demand only). | **LOW** | Recommend a `v2:hedge:status` publisher for UI visibility. |
| 6 | Ingestors | No consolidated ingestor-health roll-up key. | **LOW** | Recommend a single `v2:ingestors:status` roll-up. |

**Verified healthy (no action):** ingestion flow, TA-Lib (158 fns), liquidation levels (real), orchestrator, risk controller, allocator, execution no-execute safety, PnL/portfolio, churn governor, realtime plane, A-grade gate (correctly blocking).

---

## 4. Recommendations (priority order)

1. **Trainer offline tuning (highest ROI):** run an offline hyperparameter sweep on entropy coefficient/bonus, learning rate, and loss-head scaling using the replay archive. Goal: entropy stabilized ~0.4–0.5, supervised loss trending down, promotions passing naturally. This is the single lever most likely to convert the (currently weak, honest) edge into a generalizing edge that can begin filling the A-grade runway.
2. **Regime-gated timeframe filter:** suppress 1m entries except in high-volatility/sweep conditions (fee/slippage churn) — complements the already-active churn-equity-bleed governor.
3. **Alt-data breadth expansion** by symbol liquidity, to raise feature coverage on lean symbols.
4. **Observability roll-ups:** ingestor-health and hedge-engine status keys.
5. **Retention sweep** on stale feature snapshots.

---

## 5. Safety posture (unchanged, verified)

- Live gate: **`blocked_human_only`** everywhere. Trainer **paper_shadow_only**.
- No order / test-order / leverage / margin / transfer / withdraw endpoint is called anywhere (safety scan: 0 real call sites; only no-op freeze defs and status fields).
- Exploration/probation/bootstrap rows **never** count as A+ or live-ready.
- The A-grade gate refuses to certify overfit/unearned edge; backtest is explicitly not A+ evidence.

*This document reflects the audited runtime on 2026-07-11. Component code paths and Redis keys are current as of branch `codex/pipeline-trust-refresh`.*
