# V2 vs Legacy Full Audit — State Comparison
**Audit Date:** 2026-05-31
**Previous Audit:** 2026-05-22 (see `LEGACY_SYSTEM_FULL_AUDIT.md`)

---

## 🔴 EXECUTIVE SUMMARY

**Legacy processes stopped ~2026-05-26 (5 days ago).** All 14 legacy ingestors from
`/home/wali/Desktop/AI BOT/` are no longer running. V2 has partially filled the gap
but **critical data categories are missing or degraded**. The AI prediction engine
produces no real predictions. Feature depth collapsed from 562 → 14 fields.

---

## 1. PROCESS AUDIT — WHAT IS RUNNING NOW

### 1.1 Legacy Processes — ALL DEAD

| Legacy Script | Last Heartbeat | Status |
|--------------|---------------|--------|
| `ingest/live_binance.py` | 2026-05-26 01:24 UTC | ❌ STOPPED |
| `ingest/live_binance_liquidations.py` | 2026-05-26 | ❌ STOPPED |
| `ingest/live_coinank.py` | 2026-05-26 01:24 UTC | ❌ STOPPED |
| `ingest/live_kucoin.py` | 2026-05-26 01:23 UTC | ❌ STOPPED |
| `ingest/live_technical_analysis.py` | 2026-05-26 01:24 UTC | ❌ STOPPED |
| `ingest/realtime_price_provider.py` | 2026-05-26 01:24 UTC | ❌ STOPPED |
| `ingest/live_coinapi_v1.py` | Unknown | ❌ STOPPED |
| `ingest/live_coinapi_wsds.py` | Unknown | ❌ STOPPED |
| `feature_pipeline.py` | 2026-05-26 01:24 UTC | ❌ STOPPED |
| `rl/hybrid_trainer.py` | 2026-05-26 01:51 UTC | ❌ STOPPED |
| `rl/orchestrator_worker.py` | 2026-05-13 20:17 UTC (signals stream) | ❌ STOPPED |
| `trading/opportunity_tracker.py` | Unknown | ❌ STOPPED |
| `ingest/live_tokenmetrics.py` | Unknown | ❌ STOPPED |
| `monitoring/oom_monitor.py` | Unknown | ❌ STOPPED |

> **Evidence:** `pgrep -a python3 | grep "AI BOT[^R]"` returns empty. All legacy heartbeat
> keys (`heartbeat:IngestBinance`, `heartbeat:FeaturePipeline`, `heartbeat:KuCoin`,
> `heartbeat:Trainer`) last written **5.1 days ago** at 2026-05-26 01:xx UTC.

### 1.2 V2 Processes — CURRENTLY RUNNING

| PID | V2 Process | Role | Produces Data? |
|-----|-----------|------|----------------|
| 2354 | `v2_legacy_log_intelligence_observer` | Monitors legacy logs | ❌ Observer only |
| 2357 | `v2_continuous_legacy_log_to_rebuild_remediation` | Remediation daemon | ❌ Admin only |
| 2360 | `v2_native_ingestors_live_loop` | Fetches price/funding/OI from Binance REST | ✅ Writes `v2:market:*` |
| 2364 | `v2_feature_pipeline_native_loop` | Computes features from V2 market data | ⚠️ 14-field features only |
| 2370 | `v2/legacy_owned_runtime/ingest/liquidation_bridge.py` | Liquidation level bridge | ✅ Writes `v2:unified_features:*` liq fields |
| 2380 | `v2_rl_core_inference_loop` | RL inference loop | ❌ 0/6 components — no predictions |
| 2391 | `v2_orchestrator_arbitration_loop` | Signal orchestration | ⚠️ No input predictions |
| 2393 | `v2_trade_management_paper_loop` | Paper trade management | ⚠️ 8/18 components |
| 2400 | `v2_legacy_v2_production_comparator` | Comparator daemon | ❌ Observer only |
| 2415 | `v2_production_replacement_runtime_guard` | Runtime guard | ❌ Admin only |
| 2426 | `uvicorn app.main:create_app` (port 5173) | FastAPI backend | ✅ Running |
| 3226 | `paper_online_runtime` | Paper loop | ⚠️ No new signals in 17+ days |
| 3294 | `v2_worker_porting_orchestrator` | Porting daemon | ❌ Admin only |
| 3460 | `v2_feature_snapshot_builder` | Feature snapshot builder | ⚠️ Partial |
| 3499 | `agent_supervisor` | Agent supervisor | ❌ Admin only |
| 3722 | `codex_non_live_watchdog` | Watchdog | ❌ Admin only |
| 3766 | `codex_legacy_shutdown_readiness_takeover` | Shutdown readiness | ❌ Admin only |
| 3769 | `v2_parallel_spark_automation_runner` | Automation runner | ❌ Admin only |
| 3771 | `codex_legacy_v2_realtime_decision_observatory` | Observatory | ❌ Observer only |
| 5847 | `v2/legacy_owned_runtime/ingest/liquidation_levels_engine.py` | Liq levels | ✅ Writes liq fields |
| 1334453 | `v2_position_history_persistent_tracker` | Position history | ✅ Writes `v2:paper:position_history:*` |
| 1334941 | `v2_liquidation_wss_loop` | Liquidation WS | ✅ Writes `v2:liquidations:events` |
| 1341294 | `v2_post_hoc_replay_outcome_miner` | Replay miner | ❌ Analysis only |

**Only 2 legacy-origin scripts still running:** `liquidation_bridge.py` and
`liquidation_levels_engine.py` — both from `v2/legacy_owned_runtime/ingest/`.

---

## 2. REDIS KEY COMPARISON — MAY 22 vs MAY 31

| Metric | May 22 (Legacy Running) | May 31 (Legacy Stopped) | Change |
|--------|------------------------|------------------------|--------|
| **Total Redis keys** | 12,637 | 5,408 | **-57%** (-7,229 keys) |
| `features:coinank:*` | 2,403 | 961 | -60% (stale, expiring) |
| `cursor:coinank:*` | 2,150 | 2,101 | ~same (no new writes) |
| `latest:coinank:*` | 1,039 | 972 | -6% (expiring) |
| `latest:coinank_endpoint:*` | 1,527 | 0 | ❌ GONE |
| `ta:BTCUSDT:5m` | ✅ hash 160 fields | ❌ MISSING | LOST |
| `unified_features:BTCUSDT:5m` | ✅ hash 562 fields | ❌ MISSING | LOST |
| `prediction:BTCUSDT:5m` | ✅ hash 18 fields | ❌ MISSING | LOST |
| `microfeat:BTCUSDT:*` | ✅ hash 27 fields | ❌ MISSING | LOST |
| `toxicity:BTCUSDT` | ✅ string | ❌ MISSING | LOST |
| `regime:BTCUSDT` | ✅ string | ❌ MISSING | LOST |
| `volatility:BTCUSDT` | ✅ string | ❌ MISSING | LOST |
| `heartbeat:IngestBinance` | ✅ Live | ❌ 5 days stale | DEAD |
| `signals:trading:primary` | ✅ stream 50,000 entries, active | stream 50,000 entries, **last entry 2026-05-13** | FROZEN |
| `v2:market:prices:*` | 3 symbols | **25 symbols** | ✅ GREW |
| `v2:market:funding:*` | 3 symbols | **25 symbols** | ✅ GREW |
| `v2:market:open_interest:*` | 3 symbols | **25 symbols** | ✅ GREW |
| `v2:unified_features:*` | ~30 keys | **170 keys** | ✅ GREW (but only 14 fields) |
| `v2:technical_analysis:*` | ~5 keys | **25 keys** | ✅ GREW |
| `v2:prediction:*` | ~5 keys | **52 keys** | ⚠️ Status objects, no real predictions |

---

## 3. DATA CATEGORY — DETAILED V2 vs LEGACY COMPARISON

### 3.1 Price & OHLCV

| Category | Legacy Key | Legacy State | V2 Key | V2 State |
|----------|-----------|-------------|--------|---------|
| Real-time price | `price:{SYM}` (25 keys) | ❌ GONE | `v2:market:prices:{SYM}` (25 keys) | ✅ LIVE — Binance 24hr ticker |
| OHLCV candles (2000 deep) | `ohlcv:list:coinapi:{SYM}:{TF}` (25 keys, list 2000) | ⚠️ Stale (CoinAPI stopped) | `v2:market:ohlcv:binance:{SYM}:{TF}` (37 keys, partial) | ⚠️ Partial — not all symbols/TFs |
| Orderbook top | `orderbook:top:{SYM}` (25 keys) | ❌ GONE | None | ❌ MISSING |
| Funding rate | `kc:funding:{SYM}` via KuCoin | ❌ GONE | `v2:market:funding:{SYM}` (25 keys) | ✅ LIVE |
| Open interest | `kc:open_interest:{SYM}` | ❌ GONE | `v2:market:open_interest:{SYM}` (25 keys) | ✅ LIVE |
| KuCoin klines | `kc:kline:{SYM}:{TF}` (90 keys) | ⚠️ Stale | `v2:market:kucoin:*` | ⚠️ Partial (V2 kucoin status: `approves_legacy_shutdown=false`) |
| Microstructure | `microfeat:{SYM}:1m` (27 fields) | ❌ GONE | None | ❌ **MISSING — No V2 equivalent** |

### 3.2 Technical Analysis

| | Legacy | V2 |
|--|--------|-----|
| **Key pattern** | `ta:{SYM}:{TF}` | `v2:technical_analysis:{SYM}:{TF}` |
| **Key count** | 150 (25 symbols × 6 TFs) | 25 keys (partial TF coverage) |
| **Field depth** | **160 fields** (RSI, MACD, BB, ATR, OBV, VWAP, EMA 5/10/21/50, Stoch, CCI, ADX, etc.) | **11 meta-fields** (families_present, indicators, schema_version, etc.) — indicators are nested JSON, not flat hash |
| **Status** | ❌ GONE | ⚠️ Running but structurally different — V2 TA is JSON blob, not flat 160-field hash |

### 3.3 Unified Features (Master Feature Vector)

| | Legacy | V2 |
|--|--------|-----|
| **Key pattern** | `unified_features:{SYM}:{TF}` | `v2:unified_features:{SYM}:{TF}` |
| **Key count** | 250 (25 symbols × 10 TFs) | 170 keys |
| **Field depth** | **562 fields** — merged OHLCV+TA+CoinAnk+KuCoin+microstructure | **14 fields** — liquidation levels only (`liquidation_long_level`, `liquidation_short_level`, `liquidation_long_strength`, `liquidation_short_strength`, `liquidation_long_distance_pct`, `liquidation_short_distance_pct`, `liquidation_volume`, `liquidation_levels_json`, `liquidation_updated_ts`, `liquidation_last_event_ts`) |
| **Gap** | | **⚠️ CRITICAL: 97.5% field loss** — V2 unified features only contain liquidation bridge data. All 548 other features (TA, CoinAnk, microstructure, regime, etc.) are absent. |
| **V2 Status** | — | `components_missing: ['full_legacy_unified_feature_builder_2000_plus_features', 'regime_state_machine_hysteresis', 'ingestor_layer_native_websocket_rest', 'cross_exchange_aggregation', 'tokenmetrics_alphavantage_derived_features']` |

### 3.4 AI Predictions

| | Legacy | V2 |
|--|--------|-----|
| **Key pattern** | `prediction:{SYM}:{TF}` | `v2:prediction:{SYM}:{TF}` |
| **Key count** | ~150 (25 symbols × 6 TFs) | 52 keys (25 symbols × 2 TFs) |
| **Key type** | hash — 18 live fields | string — **gate/status JSON** |
| **Actual prediction** | ✅ `direction=HOLD/LONG/SHORT`, `confidence=0.95`, `ppo_confidence`, `masa_confidence` | ❌ `confidence_raw: null`, `model_blockers: ['no_baseline_signal_available_from_v2_features_or_ta', 'native_trainer_not_implemented']` |
| **Trainer status** | ✅ PPO+MASA hybrid running on GPU, 19,771 loops | ❌ V2 RL Core: **0/6 components ported** — no PPO, no MASA, no gymnasium env, no GPU loop, no checkpoint loader |
| **`approves_legacy_shutdown`** | — | `false` |

### 3.5 CoinAnk Intelligence

| | Legacy | V2 |
|--|--------|-----|
| **Keys** | `features:coinank:*` (2,403) + `coinank:*` raw (200+) | `features:coinank:*` (961, stale — was 2,403) |
| **Fresh data** | ✅ Updated every cycle by `live_coinank.py` | ❌ Legacy keys expiring — no new writes since May 26 |
| **V2 native** | — | `coinank_market_intelligence` worker exists but: `freshness_seconds: 0`, `funding_freshness: -1`, `approves_legacy_shutdown: false` |
| **What's alive** | — | Residual stale keys in Redis. `features:global_coinank:*` (18 keys) present but stale. |

### 3.6 Trading Signals

| | Legacy | V2 |
|--|--------|-----|
| `signals:trading:primary` | ✅ stream, 50,000 entries, last write: continuous | ❌ FROZEN — last entry: **2026-05-13 20:17 UTC** (17+ days ago) |
| `v2:orchestrator:proposals` | — | stream, exists |
| `v2:signals:paper` | — | stream, exists |
| `executed_signals` | ✅ stream 1,552 entries | Unknown — no legacy process to execute |
| Signal source | `orchestrator_worker.py` (legacy) | V2 orchestrator arbitration loop (running, 5/5 components ported) but **no prediction inputs** |

### 3.7 Portfolio & Positions

| | Legacy | V2 |
|--|--------|-----|
| `positions:live:accounts` | set, members=["primary"] | set, members=["primary"] (stale) |
| `pnl:decomp` | stream 634 entries | Unknown — likely stale |
| `v2:paper:positions` | — | hash, present |
| `v2:paper:position_history:{SYM}` | — | stream, BTCUSDT/ETHUSDT/SOLUSDT, being written |
| Live trading | Legacy trade loop | ❌ `v2_trade_management_paper_loop` — 8 ported / 10 MISSING: stealth stops, TP ladders, adaptive hedging, leg manager, exit coordinator, live order routing |

### 3.8 Tokenmetrics

| | Legacy | V2 |
|--|--------|-----|
| `tm:last_run:*` | 18 endpoint keys | 6 keys remaining (partially expired) |
| `tm:universe` | set 10 symbols | present (stale) |
| Writer | `live_tokenmetrics.py` | ❌ Not running — `heartbeat:writer:tokenmetrics` stale |

---

## 4. WHAT V2 NATIVELY PRODUCES (CONFIRMED LIVE)

These are the data categories where V2 is **actively writing fresh data right now**:

| Data | V2 Key Pattern | Coverage | Update Freq | Quality |
|------|---------------|----------|-------------|---------|
| Spot price / 24hr ticker | `v2:market:prices:{SYM}` | **25 symbols** | ~60s (REST poll) | ✅ Good |
| Funding rate | `v2:market:funding:{SYM}` | **25 symbols** | ~60s | ✅ Good |
| Open interest | `v2:market:open_interest:{SYM}` | **25 symbols** | ~60s | ✅ Good |
| OHLCV (Binance REST) | `v2:market:ohlcv:binance:{SYM}:{TF}` | 37 keys (partial) | ~60s | ⚠️ Partial |
| Liquidation events | `v2:liquidations:events` | stream | Live WS | ✅ Good |
| Liquidation levels | `v2:unified_features:{SYM}:{TF}` (14 liq fields) | 170 keys | Per event | ✅ Good |
| Paper positions | `v2:paper:positions`, `v2:paper:position_history:*` | 3 symbols | Per tick | ✅ Good |
| TA indicators (partial) | `v2:technical_analysis:{SYM}:{TF}` | 25 keys | ~60s | ⚠️ Nested JSON, 11 meta-fields |
| Feature snapshots | `v2:features:latest:{SYM}:{TF}` | 38 keys | ~60s | ⚠️ Shallow |

---

## 5. WHAT IS MISSING IN V2 (CRITICAL GAPS)

| # | Missing Capability | Legacy Source | V2 Status | Blocker |
|---|--------------------|--------------|-----------|---------|
| 🔴 | **AI Predictions** (PPO+MASA) | `hybrid_trainer.py` | `v2_rl_core_inference_loop` running but 0/6 components | `native_trainer_not_implemented` |
| 🔴 | **562-field Unified Feature Vector** | `feature_pipeline.py` | V2 has 14 fields (liq only) | `full_legacy_unified_feature_builder_MISSING` |
| 🔴 | **160-field TA indicators flat hash** | `live_technical_analysis.py` | V2 has 11 meta-fields JSON blob | Structural mismatch |
| 🔴 | **CoinAnk live data** | `live_coinank.py` | 961 stale keys, no new writes | Ingestor not running |
| 🔴 | **Microstructure features** (27 fields) | `live_coinapi_wsds.py` | ❌ No V2 equivalent built | Not started |
| 🔴 | **Trading signals stream** | `orchestrator_worker.py` | Stream frozen since May 13 | No prediction inputs |
| 🔴 | **Toxicity scores** | Legacy toxicity engine | ❌ Not built | Not started |
| 🔴 | **Regime detection** | `feature_pipeline.py` | ❌ `regime_state_machine_hysteresis` MISSING | Not started |
| 🔴 | **Volatility per symbol** | `feature_pipeline.py` | ❌ Not written | Not started |
| 🔴 | **KuCoin full data** (klines/OB20/mark) | `live_kucoin.py` | V2 kucoin worker exists but `approves_legacy_shutdown=false` | Partial only |
| 🔴 | **Orderbook depth** (bids/asks/depth) | `realtime_price_provider.py` | ❌ Not built | Not started |
| 🔴 | **TokenMetrics** (18 endpoints) | `live_tokenmetrics.py` | 6 stale keys | Not running |
| 🔴 | **Live trade execution** | Legacy trade loop | V2 trade management 8/18 components, `live_gate=blocked_human_only` | 10 components missing |
| 🔴 | **Cross-exchange aggregation** | `feature_pipeline.py` | ❌ `cross_exchange_aggregation` MISSING | Not started |

---

## 6. V2 WORKER COMPONENT STATUS (All workers, approves_legacy_shutdown=False)

| Worker | Ported | Missing | Last Updated | Notes |
|--------|--------|---------|-------------|-------|
| `v2_feature_pipeline_native` | 9/14 | 5 | 2026-05-31 | Running; outputs 14 fields not 562 |
| `v2_orchestrator_arbitration` | 5/5 | 0 | 2026-05-31 | Running; no prediction inputs |
| `v2_trade_management_paper` | 8/18 | 10 | 2026-05-31 | Running; blocked on missing components |
| `v2_rl_core` | 0/6 | 6 | 2026-05-31 | Running but produces nothing |
| `v2_native_ingestors` | N/A | N/A | 2026-05-31 | ✅ Writes 77 market keys, `live_gate=blocked_human_only` |
| `v2_kucoin_ingestor` | N/A | N/A | 2026-05-31 | Running; `approves_legacy_shutdown=false` |
| `v2_liquidation_ingestor` | N/A | N/A | 2026-05-31 | ✅ WS active |
| `v2_live_canary` | N/A | N/A | 2026-05-31 | Running; `approves_live=false` |
| `coinank_market_intelligence` | N/A | N/A | 2026-05-31 | Running; `freshness_seconds=0` (no writes) |
| `v2_owned_orchestrator` | 0/? | — | 2026-05-16 | Stale — legacy imports only |
| `v2_owned_trainer` | 0/? | — | 2026-05-31 | Stale output |
| `v2_feature_intelligence` | 6/10 | 4 | 2026-05-15 | Stale |
| `v2_nansen_altdata_client` | N/A | N/A | 2026-05-31 | Running; alt data |
| `v2_lunarcrush_altdata_client` | N/A | N/A | 2026-05-31 | Running; alt data |

---

## 7. SHUTDOWN READINESS — UPDATED SCORECARD

| # | Requirement | Required For Shutdown | May 22 Status | May 31 Status |
|---|-------------|----------------------|--------------|--------------|
| 1 | OHLCV 2000-candle depth per symbol/TF | Full coverage | ⚠️ Legacy only | ⚠️ Partial V2 (37/125 keys) |
| 2 | Real-time price all 25 symbols | Full coverage | ✅ Legacy | ✅ V2 native (25 symbols) |
| 3 | Funding rate all 25 symbols | Full coverage | ✅ Legacy (KuCoin) | ✅ V2 native (25 symbols) |
| 4 | Open interest all 25 symbols | Full coverage | ✅ Legacy (KuCoin) | ✅ V2 native (25 symbols) |
| 5 | TA 160-field flat hash per symbol/TF | AI trainer input | ✅ Legacy | ❌ MISSING (V2 has nested JSON) |
| 6 | Unified features 562-field per symbol/TF | AI trainer input | ✅ Legacy | ❌ MISSING (V2 has 14 fields) |
| 7 | CoinAnk 2,400+ feature keys | ML features | ✅ Legacy | ❌ STALE/EXPIRING |
| 8 | Microstructure 27 fields | ML features | ✅ Legacy | ❌ MISSING |
| 9 | Toxicity score per symbol | Signal filtering | ✅ Legacy | ❌ MISSING |
| 10 | Regime detection per symbol | Position sizing | ✅ Legacy | ❌ MISSING |
| 11 | AI predictions (PPO+MASA) per symbol/TF | Signal generation | ✅ Legacy | ❌ NO PREDICTIONS |
| 12 | Live trading signals stream | Trade execution | ✅ Legacy | ❌ FROZEN since May 13 |
| 13 | Live trade execution (stealth stops, TP, hedging) | Live P&L | ✅ Legacy | ❌ 10 components missing |
| 14 | TokenMetrics 18 endpoints | ML features | ✅ Legacy | ❌ STALE |
| 15 | Orderbook depth all 25 symbols | Microstructure | ✅ Legacy | ❌ MISSING |

**Shutdown readiness: 3/15 requirements met (price, funding, OI only)**
**`approves_legacy_shutdown: false` on all V2 status workers — confirmed not ready**

---

## 8. CRITICAL ACTION ITEMS TO RESTORE DATA COVERAGE

Listed by impact priority:

### 🔴 P0 — No AI signals being generated at all
1. **V2 RL Trainer** — Build PPO+MASA in V2 (`v2_rl_core`, 6 components missing). Until done, no `v2:prediction:*` real values → no signals → paper loop is idle.

### 🔴 P1 — Feature pipeline is crippled (97.5% field loss)
2. **V2 Feature Pipeline** — Build the 548 missing features:
   - `full_legacy_unified_feature_builder_2000_plus_features`
   - `regime_state_machine_hysteresis`
   - `cross_exchange_aggregation`
   - `tokenmetrics_alphavantage_derived_features`
   - `ingestor_layer_native_websocket_rest`

### 🔴 P2 — Live market intelligence going dark
3. **CoinAnk Ingestor** — Start V2-native `live_coinank.py` equivalent (still in `v2/legacy_owned_runtime/ingest/` but not launched). 961 keys expiring.
4. **TA Flat Hash** — `v2_technical_analysis:{SYM}:{TF}` needs 160 flat fields, not nested JSON.
5. **Microstructure** — Build WS trade aggregator (`live_coinapi_wsds.py` equivalent).

### 🟡 P3 — Data gaps impacting signal quality
6. **Toxicity engine** — Build V2 toxicity scorer.
7. **Regime detection** — Port regime state machine.
8. **OrderBook depth** — Port `realtime_price_provider.py` orderbook component.
9. **TokenMetrics** — Re-launch `live_tokenmetrics.py` from `v2/legacy_owned_runtime/ingest/`.

### 🟡 P4 — Trading loop incompleteness
10. **V2 Trade Management** — 10 missing components (stealth stops, TP ladders, hedge leg manager, exit coordinator, live order routing).
