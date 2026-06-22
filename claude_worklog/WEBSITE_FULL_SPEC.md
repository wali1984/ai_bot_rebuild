# 🌐 AI Trading Bot — Public Website Full Data Specification
**Prepared for Developer Handoff — May 15, 2026**  
**Source System:** Legacy Bot (`/home/wali/Desktop/AI BOT`)  
**Data Layer:** Live Redis + Python Backend  
**Target:** Public-facing website displaying all real-time bot data

---

## TABLE OF CONTENTS

1. [System Overview & Architecture](#1-system-overview--architecture)
2. [Redis Key Master Map (Every Key → Script)](#2-redis-key-master-map)
3. [Data Source Ingestors](#3-data-source-ingestors)
4. [Website Pages — Full Spec](#4-website-pages)
   - [4.1 Home / Dashboard](#41-home--dashboard)
   - [4.2 Live Signals & Predictions](#42-live-signals--predictions)
   - [4.3 Market Intelligence (Orderbook & Microstructure)](#43-market-intelligence)
   - [4.4 Technical Analysis (TA-Lib)](#44-technical-analysis-ta-lib)
   - [4.5 Open Interest & Funding Rates](#45-open-interest--funding-rates)
   - [4.6 Long/Short Ratios & Sentiment](#46-longshort-ratios--sentiment)
   - [4.7 Liquidation Intelligence](#47-liquidation-intelligence)
   - [4.8 Market Regime & Volatility](#48-market-regime--volatility)
   - [4.9 Microstructure Toxicity & Anti-Spoofing](#49-microstructure-toxicity--anti-spoofing)
   - [4.10 Hedge System & Risk Budget](#410-hedge-system--risk-budget)
   - [4.11 Stealth Stops & Dynamic TP/SL](#411-stealth-stops--dynamic-tpsl)
   - [4.12 PnL & Performance](#412-pnl--performance)
   - [4.13 TokenMetrics Intelligence](#413-tokenmetrics-intelligence)
   - [4.14 AI Trainer Status & RL Metrics](#414-ai-trainer-status--rl-metrics)
   - [4.15 Trade Proposals & Orchestrator](#415-trade-proposals--orchestrator)
   - [4.16 Portfolio & Position Monitor](#416-portfolio--position-monitor)
   - [4.17 System Health Monitor](#417-system-health-monitor)
5. [API Route Map](#5-api-route-map)
6. [Supported Symbols](#6-supported-symbols)

---

## 1. System Overview & Architecture

The bot is a multi-source, multi-timeframe crypto trading system with the following data pipeline:

```
External APIs → Ingestors → Redis → Feature Pipeline → RL Trainer → Trader → Execution
     ↑                                    ↓                ↓
  Binance                          TA-Lib indicators    Signals
  CoinAPI                          Microstructure       Predictions
  CoinAnk                          Toxicity             Proposals
  KuCoin                           Regime               PnL
  TokenMetrics                     OI / L/S             Positions
  AlphaVantage                     Orderbook
```

**Timeframes active:** `1m`, `5m`, `15m`, `1h`, `4h` (cross_tf also available)  
**Symbols active (25):** See [Section 6](#6-supported-symbols)  
**Trading accounts:** `primary` + `asjad`

---

## 2. Redis Key Master Map

### Legend
> Format: `redis_key_pattern` → **Script(s) that WRITE this key**

---

### 2.1 Price Data

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `price:{SYMBOL}` | `ingest/live_binance.py` | string/JSON | Current Binance WS price tick |
| `price:last:{SYMBOL}` | `ingest/live_binance.py` | string/JSON | Last confirmed price |
| `price:realtime:{SYMBOL}` | `ingest/realtime_price_provider.py` | string/JSON | Real-time aggregated price |
| `market:{SYMBOL}:{TF}` | `ingest/live_binance.py` | JSON | OHLCV candle data per timeframe |
| `market:{SYMBOL}:price` | `ingest/live_binance.py` | JSON | Price with volume/spread |
| `ohlcv:list:binance:{SYMBOL}:{TF}` | `ingest/live_binance.py` | list | Historical OHLCV candle list |
| `ohlcv:list:coinapi:{SYMBOL}:{TF}` | `ingest/live_coinapi_v1.py` | list | CoinAPI OHLCV history |
| `latest:coinapi:ohlcv:{SYMBOL}:{TF}` | `ingest/live_coinapi_v1.py` | JSON | Latest CoinAPI OHLCV |
| `normalized:ohlcv:{SYMBOL}:{TF}` | `ingest/live_coinapi_v1.py` | JSON | Normalized/cleaned OHLCV |
| `msnap:coinapi_wsds:{SYMBOL}` | `ingest/live_coinapi_wsds.py` | JSON | CoinAPI WebSocket data snapshot |
| `metrics:coinapi:*` | `ingest/live_coinapi_v1.py` + `live_coinapi_wsds.py` | string | CoinAPI health/metrics |
| `metrics:price_provider:{SYMBOL}` | `ingest/realtime_price_provider.py` | JSON | Price provider health per symbol |

---

### 2.2 Technical Analysis (TA-Lib)

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `ta:{SYMBOL}:{TF}` | `ingest/live_technical_analysis.py` | JSON | Full TA-Lib indicator set (300+ fields) |
| `ta:{SYMBOL}:cross_tf` | `ingest/live_technical_analysis.py` | JSON | Cross-timeframe TA confluence |
| `latest:ta:{SYMBOL}:{TF}` | `ingest/live_technical_analysis.py` | JSON | Latest TA snapshot |
| `latest:ta:{SYMBOL}:cross_tf` | `ingest/live_technical_analysis.py` | JSON | Latest cross-TF TA |

**TA indicators included per symbol/timeframe:**
- **Moving Averages:** SMA(5,10,20,50,100,200), EMA(5,10,20,50,100,200), WMA, TEMA, TRIMA, KAMA, MAMA/FAMA, T3, HT_TRENDLINE
- **Momentum:** RSI(14,21,28), STOCH, STOCHF, STOCHRSI, MACD, MACDEXT, ADX, ADXR, APO, AROON, BOP, CCI
- **Volume:** OBV, AD, ADOSC, MFI
- **Volatility:** ATR, NATR, TRANGE, BBANDS
- **Pattern:** Candlestick patterns (CDLDOJI, CDLHAMMER, etc.)

---

### 2.3 Microstructure Features

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `microfeat:{SYMBOL}:{TF}` | `rl/microstructure_features.py` + `feature_pipeline.py` | JSON | Raw microstructure features |
| `orderbook:bids:{SYMBOL}` | `ingest/live_binance.py` | JSON | Top N orderbook bids |
| `orderbook:asks:{SYMBOL}` | `ingest/live_binance.py` | JSON | Top N orderbook asks |
| `orderbook:depth:{SYMBOL}` | `feature_pipeline.py` | JSON | Aggregated depth in USD |
| `orderbook:top:{SYMBOL}` | `ingest/live_binance.py` | JSON | Top of book (BBO) |

**Microstructure fields include:**
- Bid/ask spread (absolute + normalized)
- Orderbook imbalance (depth-weighted)
- Trade flow (buy/sell pressure)
- Price impact estimation
- Tick-level velocity

---

### 2.4 Toxicity & Anti-Spoofing

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `toxicity:{SYMBOL}` | `risk/microstructure_toxicity.py` | JSON | Composite toxicity score |

**Fields per symbol:**
```json
{
  "symbol": "BTCUSDT",
  "score": 0.16,           // 0.0-1.0 composite toxicity
  "is_toxic": false,       // threshold flag
  "is_extreme": false,     // extreme flag (>0.75)
  "components": {
    "spoof": 0.23,         // spoofing detection score
    "churn": 0.01,         // churn/flip frequency
    "spread_norm": 0.0001, // normalized spread
    "depth_thin": 0.0,     // thin orderbook flag
    "imbalance": 0.80,     // book imbalance
    "fast_move": 0.2,      // rapid price movement
    "snapback": 0.0,       // price snapback detection
    "quality_inv": 0.0     // data quality inverse
  },
  "execution_hint": "NORMAL",  // NORMAL / CAUTIOUS / AVOID
  "updated_ts_ms": 1778886129093
}
```

---

### 2.5 Market Regime & Volatility

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `regime:{SYMBOL}` | `rl/market_context.py` + `feature_pipeline.py` | JSON | Per-symbol composite regime |
| `regime:{SYMBOL}:{TF}` | `rl/market_context.py` | JSON | Per-symbol per-timeframe regime |
| `regime:global:{TF}` | `risk/global_breadth.py` | JSON | Global market regime |
| `regime:structural:{SYMBOL}:{TF}:closes` | `trading/market_regime_detector.py` | list | Close prices for structural regime |
| `regime:structural:{SYMBOL}:{TF}:ts` | `trading/market_regime_detector.py` | list | Timestamps for structural regime |
| `regime:structural:state:{SYMBOL}` | `trading/market_regime_detector.py` | JSON | Structural state (TRENDING/RANGING) |
| `regime:structural:last_ts:{SYMBOL}:{TF}` | `trading/market_regime_detector.py` | string | Last structural update |
| `volatility:{SYMBOL}` | `feature_pipeline.py` + `rl/market_context.py` | JSON | Volatility composite |

**Regime fields:**
```json
{
  "move_score": 0.10,
  "move_regime": "CALM",          // CALM / TRENDING / VOLATILE / CHAOTIC
  "market_regime": "CALM",
  "trend_direction": "NEUTRAL",   // BULLISH / BEARISH / NEUTRAL
  "volatility_score": 0.09,
  "fast_move_score": 0.20,
  "liq_risk": 0.14,
  "liquidity_score": 0.75,
  "tf_alignment": 0.0,            // 0-1, how aligned timeframes are
  "tf_conflict": 0.5,             // timeframe conflict score
  "tf_entropy": 0.95,             // signal entropy
  "liq_imbalance": -1.05,
  "regime_version": "v1"
}
```

---

### 2.6 Unified Features (ML Input Vector)

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `unified_features:{SYMBOL}:{TF}` | `rl/unified_feature_builder.py` | list | Rolling feature list |
| `unified_features:{SYMBOL}:{TF}:latest` | `rl/unified_feature_builder.py` | hash | Latest feature vector |

**Content:** 200-400 normalized features combining TA, microstructure, orderbook, funding, OI, L/S ratio, regime, volatility — the full ML input fed to the PPO/MASA trainer.

---

### 2.7 AI Predictions

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `prediction:{SYMBOL}:{TF}` | `rl/hybrid_trainer.py` | hash | Per-timeframe PPO prediction |
| `prediction:{SYMBOL}:multi` | `rl/hybrid_trainer.py` | hash | Multi-TF ensemble prediction |

**Fields:**
```json
{
  "action": "OPEN_LONG",
  "action_name": "OPEN_LONG",
  "direction": "LONG",
  "confidence": 0.957,          // 0.0-1.0
  "model_confidence": 0.957,
  "ppo_confidence": 0.957,
  "masa_confidence": 0.0036,    // MASA supervised head
  "price_target": 79153.6,
  "entry_price": 79096.85,
  "predicted_return": 0.0718,   // % expected return
  "ts_ms": 1778886176580
}
```

---

### 2.8 CoinAnk Data (Derivatives Intelligence)

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `raw:coinank:fundingRate_current:global` | `ingest/live_coinank.py` | JSON | Live funding rates all exchanges |
| `raw:coinank:fundingRate_accumulated:global` | `ingest/live_coinank.py` | JSON | Accumulated 8h funding |
| `raw:coinank:fundingRate_frHeatmap:global` | `ingest/live_coinank.py` | JSON | Funding rate heatmap |
| `raw:coinank:fund_fundReal:global` | `ingest/live_coinank.py` | JSON | Real funding settlement data |
| `raw:coinank:liquidation_orders:global` | `ingest/live_coinank.py` | JSON | Recent liquidation order feed |
| `raw:coinank:instruments_liquidationRank:global` | `ingest/live_coinank.py` | JSON | Symbols ranked by liquidation volume |
| `raw:coinank:instruments_longShortRank:global` | `ingest/live_coinank.py` | JSON | Global long/short ranking |
| `raw:coinank:instruments_oiRank:global` | `ingest/live_coinank.py` | JSON | OI ranking across instruments |
| `raw:coinank:instruments_oiVsMarketCap:global` | `ingest/live_coinank.py` | JSON | OI vs market cap comparison |
| `raw:coinank:instruments_priceRank:global` | `ingest/live_coinank.py` | JSON | Price performance ranking |
| `raw:coinank:instruments_volumeRank:global` | `ingest/live_coinank.py` | JSON | Volume ranking |
| `raw:coinank:instruments_visualScreener:global` | `ingest/live_coinank.py` | JSON | Visual screener data |
| `raw:coinank:hyper_topAction:global` | `ingest/live_coinank.py` | JSON | Top trader actions (Hyperliquid) |
| `raw:coinank:hyper_topPosition:global` | `ingest/live_coinank.py` | JSON | Top trader positions (Hyperliquid) |
| `raw:coinank:liqMap_getLiqHeatMapSymbol:global` | `ingest/live_coinank.py` | JSON | Liquidation heatmap |
| `raw:coinank:rsiMap_list:global` | `ingest/live_coinank.py` | JSON | RSI heatmap across symbols |
| `raw:coinank:trades_count:global` | `ingest/live_coinank.py` | JSON | Trade count metrics |
| `raw:coinank:baseCoin_list:global` | `ingest/live_coinank.py` | JSON | Base coin universe |
| `raw:coinank:baseCoin_symbols:global` | `ingest/live_coinank.py` | JSON | Symbol mapping |
| `latest:coinank:open_interest:{SYMBOL}:{TF}` | `ingest/live_coinank_global_aggregator.py` | JSON | Per-symbol OI history |
| `latest:coinank:long_short:{SYMBOL}:{TF}` | `ingest/live_coinank_global_aggregator.py` | JSON | Per-symbol L/S ratio history |
| `latest:coinank:market_order_flow:{SYMBOL}:{TF}` | `ingest/live_coinank_global_aggregator.py` | JSON | Buy/sell order flow |
| `meta:coinank:last_update` | `ingest/live_coinank.py` | string | Last CoinAnk sync time |
| `lock:live_coinank` | `ingest/live_coinank.py` | string | Distributed lock |

---

### 2.9 Liquidation System

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `raw:coinank:liquidation_orders:global` | `ingest/live_coinank.py` | JSON | Real-time liquidation feed |
| `raw:coinank:instruments_liquidationRank:global` | `ingest/live_coinank.py` | JSON | Liquidation rank per coin |
| `raw:coinank:liqMap_getLiqHeatMapSymbol:global` | `ingest/live_coinank.py` | JSON | Liq heatmap by price level |
| `ingest/live_binance_liquidations.py` | (writes stream) | stream | Binance liquidation websocket feed |
| `ingest/liquidation_levels_engine.py` | (writes to feature_pipeline) | — | Computes clustered liq levels |
| `ingest/liquidation_bridge.py` | (bridge connector) | — | Bridges liq data between sources |

---

### 2.10 Trading Signals & Proposals

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `signals:trading:primary` | `rl/tradeplan_orchestrator.py` | stream | Approved trade signals for primary account |
| `signals:trading:asjad` | `rl/tradeplan_orchestrator.py` | stream | Approved signals for asjad account |
| `signals:proactive:alerts` | `rl/microstructure_proactive.py` | JSON | Proactive microstructure alerts |
| `signals:debug` | `rl/hybrid_trainer.py` | JSON | Debug signal dump |
| `signals:ensemble:diagnostic` | `rl/hybrid_trainer.py` | JSON | Ensemble model diagnostic |
| `signals:execution:skips` | `trading/execution_engine.py` | JSON | Skipped signals log |
| `signals:overlay:intents` | `rl/intent_engine.py` | JSON | Overlay intent signals |
| `signals:trainer:heartbeat` | `rl/hybrid_trainer.py` | string | Trainer alive heartbeat |
| `wma:proposals` | `rl/tradeplan_orchestrator.py` | JSON | Pending trade proposals |
| `wma:decisions` | `rl/tradeplan_orchestrator.py` | JSON | Executed decisions log |
| `wma:drift_alerts` | `rl/drift_monitor.py` | JSON | Model drift alerts |
| `wma:predictions_qc` | `rl/hybrid_trainer.py` | JSON | Prediction quality control |
| `opportunity:latest` | `trading/opportunity_tracker.py` | JSON | Latest detected opportunity |
| `proactive:dedupe:{SYMBOL}:{TF}:{EVENT}` | `rl/microstructure_proactive.py` | string | Dedup key for proactive events |

---

### 2.11 Trainer Intent & Brain

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `trainer:intent:{SYMBOL}` | `risk/trainer_intent.py` | JSON | Trainer's intended position per symbol |
| `trainer:brain:status` | `rl/hybrid_trainer.py` | JSON | Brain/model status |
| `trainer:critical_fixes:initialized` | `rl/hybrid_trainer.py` | string | Fix-set init flag |
| `trainer:critical_fixes:stats` | `rl/hybrid_trainer.py` | JSON | Critical fix statistics |
| `trainer:liq_prevention:status` | `rl/liquidation_prevention.py` | JSON | Liquidation prevention status |
| `trainer:heartbeat:{HOST}:{PID}` | `rl/hybrid_trainer.py` | string | Per-process heartbeat |
| `status:trainer` | `rl/hybrid_trainer.py` | JSON | Trainer overall status |
| `rl:episodes:total` | `rl/hybrid_trainer.py` | string | Total training episodes |
| `rl:eval:pending` | `rl/hybrid_trainer.py` | string | Episodes pending evaluation |
| `rl:obs_length` | `rl/hybrid_trainer.py` | string | Observation vector length |
| `rl:metrics:{TF}` | `rl/metrics_tracker.py` | JSON | Per-timeframe RL metrics |
| `rl:metrics:continuous` | `rl/continuous_learner.py` | JSON | Continuous learning metrics |
| `rl:metrics:loop_summary` | `rl/hybrid_trainer.py` | JSON | Training loop summary |

---

### 2.12 Risk & Portfolio

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `risk_budget:state:primary` | `risk/risk_budget_allocator.py` | JSON | Risk budget state |
| `risk_budget:state:asjad` | `risk/risk_budget_allocator.py` | JSON | Asjad account risk budget |
| `portfolio:combined:state` | `rl/portfolio_policy_manager.py` | JSON | Combined portfolio state |
| `portfolio:state:stream:primary` | `rl/portfolio_policy_manager.py` | stream | Portfolio state events |
| `positions:live:accounts` | `trading/trader.py` | JSON | All live positions across accounts |

**Risk budget fields:**
```json
{
  "state": "DEFENSIVE",
  "risk_mult": 0.65,
  "max_risk_symbols": 8,
  "cadence_min_sec": 60,
  "hedge_policy": "HEDGE_FIRST",
  "reason": "LOW_BREADTH|HIGH_ENTROPY",
  "breadth_snapshot": {
    "breadth_dir": 1,
    "breadth_strength": 0.40,
    "breadth_entropy": 0.98,
    "n_long": 10, "n_short": 6, "n_neutral": 9
  }
}
```

---

### 2.13 Profit Bank & PnL

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `profit_bank:state:primary` | `rl/profit_bank.py` | JSON | Primary account profit bank |
| `profit_bank:state:asjad` | `rl/profit_bank.py` | JSON | Asjad account profit bank |
| `profit_bank:last_id:primary` | `rl/profit_bank.py` | string | Last event ID processed |
| `profit_bank:last_id:asjad` | `rl/profit_bank.py` | string | Last event ID asjad |
| `pnl:decomp` | `trading/position_reporter.py` | JSON | Decomposed PnL (live vs canary) |
| `pnl:decomp:1d:primary:{YYYYMMDD}` | `trading/position_reporter.py` | JSON | Daily PnL decomposition |
| `pnl:decomp:1d:primary:{YYYYMMDD}:symbols` | `trading/position_reporter.py` | JSON | Per-symbol daily PnL |

**Profit bank fields:**
```json
{
  "account_id": "primary",
  "balance_usd": 5230.57,
  "credited_usd": 5230.57,
  "debited_usd": 0.0,
  "last_update_ts": 1778735107.6
}
```

---

### 2.14 Stealth Stops & Dynamic TP/SL

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `stealth_tp:last:primary:{SYMBOL}:{SIDE}` | `trading/stealth_stops.py` | JSON | Last stealth TP placed |

**Fields:**
```json
{
  "symbol": "BTCUSDT",
  "side": "LONG",
  "tp_price": 80145.56,
  "qty": 0.024,
  "close_side": "SELL",
  "source": "signal",
  "account_id": "primary"
}
```

Also written by:
- `trading/dynamic_adaptive_stops.py` — dynamic stop loss engine
- `trading/dynamic_tp_engine.py` — dynamic take-profit levels
- `trading/stealth_dynamic_integration.py` — integrates stealth + dynamic

---

### 2.15 TokenMetrics Intelligence

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `tm:health:last_err` | `ingest/live_tokenmetrics.py` | string | Last error |
| `tm:health:stats` | `ingest/live_tokenmetrics.py` | JSON | Health statistics |
| `tm:last_run:{ENDPOINT}` | `ingest/live_tokenmetrics.py` | string | Last run timestamp per endpoint |
| `tm:token_map` | `ingest/live_tokenmetrics.py` | JSON | Symbol → TM token ID map |
| `tm:tooltips` | `ingest/live_tokenmetrics.py` | JSON | Token metadata/tooltips |
| `tm:universe` | `ingest/live_tokenmetrics.py` | JSON | Full tradeable universe |
| `tokenmetrics:universe` | `ingest/live_tokenmetrics.py` | JSON | Universe snapshot |

**Endpoints tracked via `tm:last_run:{endpoint}`:**
- `ai_reports` — AI-generated market reports
- `correlation` — Cross-asset correlation matrix
- `crypto_investors` — Institutional investor data
- `fund_grades` + `fund_grades_hist` — Fund performance grades
- `hourly_trading_signals` — Hourly AI signals
- `indices` — Market indices
- `market_metrics` — Macro market metrics
- `moonshot_tokens` — High-potential token list
- `price_prediction` — TM price prediction
- `quantmetrics` — Quantitative metrics
- `resistance_support` — S/R levels
- `tech_grades` + `tech_grades_hist` — Technical grade scores
- `tm_grades` + `tm_grades_hist` — Overall TM grades
- `top_market_cap` — Top market cap tokens
- `trading_signals` — Core trading signals

---

### 2.16 Promotion & Orchestrator

| Redis Key Pattern | Written By | Type | Notes |
|---|---|---|---|
| `promotion:status` | `rl/promotion_controller.py` | JSON | Model promotion status |
| `orchestrator:leader_lock` | `rl/orchestrator_worker.py` | string | Leader election lock |
| `market:state:contract` | `risk/market_state_contract.py` | JSON | Market state contract |

---

## 3. Data Source Ingestors

| Script | Source | What it ingests | Frequency |
|---|---|---|---|
| `ingest/live_binance.py` | Binance WebSocket | Price ticks, OHLCV candles, orderbook, trades | Real-time |
| `ingest/live_binance_liquidations.py` | Binance WS liquidation stream | Live forced liquidations | Real-time |
| `ingest/live_coinapi_v1.py` | CoinAPI REST | OHLCV bars (all TFs), normalized data | 5s-60s |
| `ingest/live_coinapi_wsds.py` | CoinAPI WebSocket DSWS | Real-time quotes, trades | Real-time |
| `ingest/live_coinapi_rest.py` | CoinAPI REST | Supplemental REST polling | 60s |
| `ingest/live_coinank.py` | CoinAnk API | Funding rates, OI, L/S, liquidations, heatmaps | 30s-5m |
| `ingest/live_coinank_global_aggregator.py` | CoinAnk (aggregated) | Per-symbol OI, L/S, order flow timeseries | 5m |
| `ingest/coinank_pipeline_monitor.py` | Redis (monitor) | CoinAnk pipeline health check | 60s |
| `ingest/live_kucoin.py` | KuCoin WebSocket | Price, trades, orderbook cross-validation | Real-time |
| `ingest/live_tokenmetrics.py` | TokenMetrics API | AI grades, signals, predictions, metrics | 1h-24h |
| `ingest/clients/tokenmetrics_client.py` | TokenMetrics API | Low-level client wrapper | — |
| `ingest/live_alphavantage_news.py` | AlphaVantage API | News sentiment, macro data | 15m |
| `ingest/alphavantage_client.py` | AlphaVantage | Client wrapper | — |
| `ingest/live_technical_analysis.py` | Redis (OHLCV) → TA-Lib | 300+ TA indicators per symbol/TF | 1m |
| `ingest/technical_analysis.py` | OHLCV data → TA-Lib | Core TA calculation engine | — |
| `ingest/realtime_price_provider.py` | Multi-source aggregation | Best-bid-offer price aggregation | Real-time |
| `ingest/liquidation_levels_engine.py` | Orderbook + liq data | Clustered liquidation levels | 5m |
| `ingest/liquidation_bridge.py` | Redis bridge | Connects liq data sources | — |
| `ingest/ccxt_backfill.py` / `ccxt_historical.py` | CCXT (Binance) | Historical data backfill | On-demand |
| `feature_pipeline.py` | All Redis sources | Builds unified feature vectors | 5s-30s |

---

## 4. Website Pages

---

### 4.1 Home / Dashboard

**Route:** `/`  
**Purpose:** Overview of the entire system — live summary of what the bot is seeing and doing.

#### Data Used:
| Widget | Redis Key | Field |
|---|---|---|
| BTC/ETH/SOL Live Price | `price:realtime:BTCUSDT` etc | `price`, `ts` |
| Global Market Regime Badge | `regime:global:5m` | `move_regime`, `trend_direction` |
| Active Positions Summary | `positions:live:accounts` | count, unrealized PnL |
| Total Profit Bank | `profit_bank:state:primary` | `balance_usd`, `credited_usd` |
| AI Trainer Status | `status:trainer` | `status`, heartbeat |
| Risk Budget Status | `risk_budget:state:primary` | `state`, `risk_mult`, `reason` |
| Recent Signals Feed | `signals:trading:primary` (stream) | last 10 entries |
| Top Toxic Symbol | `toxicity:{SYMBOL}` | sort by `score` desc |
| System Health | `metrics:coinapi:ws:connected` | connected/disconnected |

**Layout:** Grid dashboard with live-updating tiles, price ticker bar at top, sidebar for system status.

---

### 4.2 Live Signals & Predictions

**Route:** `/signals`  
**Purpose:** Full signal feed — what the AI is predicting for every symbol, every timeframe.

#### Sub-pages:
- `/signals/live` — real-time signal stream
- `/signals/predictions` — AI prediction table
- `/signals` (overview) — combined

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Prediction Table (all symbols) | `prediction:{SYMBOL}:{TF}` | HGETALL per symbol/TF |
| Multi-TF Ensemble Prediction | `prediction:{SYMBOL}:multi` | direction, confidence |
| Signal Stream | `signals:trading:primary` (XRANGE) | Last 50 events |
| Proactive Alerts Feed | `signals:proactive:alerts` | Microstructure events |
| Trainer Heartbeat | `signals:trainer:heartbeat` | alive/dead |
| Ensemble Diagnostic | `signals:ensemble:diagnostic` | model breakdown |
| Execution Skips | `signals:execution:skips` | why signals skipped |
| Trainer Intent (per symbol) | `trainer:intent:{SYMBOL}` | desired position |
| Overlay Intents | `signals:overlay:intents` | risk overlay decisions |

**Display:** Symbol × Timeframe matrix. Each cell shows: direction (🟢LONG / 🔴SHORT / ⚪HOLD), confidence bar, entry price, target price. Click to drill into symbol detail.

#### API Routes:
```
GET /api/signals/predictions              → all symbols, all TFs
GET /api/signals/predictions/{symbol}     → single symbol all TFs
GET /api/signals/stream?limit=50          → recent signal stream
GET /api/signals/alerts                   → proactive alerts
GET /api/signals/skips                    → execution skip log
```

---

### 4.3 Market Intelligence

**Route:** `/market`  
**Purpose:** Orderbook depth, bid/ask spread, real-time OHLCV chart data.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Orderbook Depth Heatmap | `orderbook:bids:{SYMBOL}`, `orderbook:asks:{SYMBOL}` | Per symbol |
| Best Bid/Ask | `orderbook:top:{SYMBOL}` | BBO spread |
| Depth in USD | `orderbook:depth:{SYMBOL}` | `depth_usd` |
| OHLCV Candle Chart | `market:{SYMBOL}:{TF}` | OHLCV per TF |
| Price Feed | `price:realtime:{SYMBOL}` | Live price |
| CoinAPI Quality | `metrics:coinapi:ws:staleness_p50_ms`, `p95_ms` | latency metrics |
| Multi-source price | `msnap:coinapi_wsds:{SYMBOL}` | WS snapshot |

#### API Routes:
```
GET /api/market/orderbook/{symbol}        → bids + asks + depth
GET /api/market/ohlcv/{symbol}/{tf}       → OHLCV candles
GET /api/market/price/{symbol}            → realtime price
GET /api/market/prices                    → all symbols latest price
```

---

### 4.4 Technical Analysis (TA-Lib)

**Route:** `/ta`  
**Purpose:** Full TA-Lib indicator dashboard per symbol and timeframe.

#### Sub-pages:
- `/ta/{symbol}` — all timeframes for one symbol
- `/ta/{symbol}/{tf}` — specific timeframe detail

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Indicator Table | `latest:ta:{SYMBOL}:{TF}` | 300+ fields |
| Cross-TF Confluence | `latest:ta:{SYMBOL}:cross_tf` | Multi-TF signal agreement |
| RSI Grid | `latest:ta:{SYMBOL}:{TF}` → `ta_RSI_14_{TF}` | RSI per symbol/TF |
| MACD Chart | `latest:ta:{SYMBOL}:{TF}` → MACD fields | MACD line/signal/hist |
| Bollinger Bands | `latest:ta:{SYMBOL}:{TF}` → BBANDS fields | Upper/mid/lower |
| ADX Strength | `latest:ta:{SYMBOL}:{TF}` → `ta_ADX_14_{TF}` | Trend strength |
| Moving Average Stack | `latest:ta:{SYMBOL}:{TF}` → SMA/EMA fields | All MA values |
| Candlestick Patterns | `latest:ta:{SYMBOL}:{TF}` → CDL* fields | Pattern detection |

#### Key Indicator Fields (selected):
```
ta_SMA_5_{TF}, ta_SMA_20_{TF}, ta_SMA_50_{TF}, ta_SMA_200_{TF}
ta_EMA_5_{TF}, ta_EMA_20_{TF}, ta_EMA_50_{TF}, ta_EMA_200_{TF}
ta_RSI_14_{TF}, ta_RSI_21_{TF}
ta_MACD_macd_{TF}, ta_MACD_signal_{TF}, ta_MACD_hist_{TF}
ta_ADX_14_{TF}, ta_AROON_down_14_{TF}, ta_AROON_up_14_{TF}
ta_BBANDS_upper_{TF}, ta_BBANDS_middle_{TF}, ta_BBANDS_lower_{TF}
ta_ATR_14_{TF}, ta_OBV_{TF}, ta_CCI_14_{TF}
ta_STOCH_k_{TF}, ta_STOCH_d_{TF}
ta_BOP_{TF}, ta_MFI_14_{TF}
```

#### API Routes:
```
GET /api/ta/{symbol}                      → all TF summaries
GET /api/ta/{symbol}/{tf}                 → full indicator set
GET /api/ta/{symbol}/cross_tf             → cross-TF analysis
GET /api/ta/rsi_grid                      → RSI for all symbols all TFs
```

---

### 4.5 Open Interest & Funding Rates

**Route:** `/derivatives/oi` and `/derivatives/funding`  
**Purpose:** CoinAnk-powered open interest history and funding rate data.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| OI Chart per symbol/TF | `latest:coinank:open_interest:{SYMBOL}:{TF}` | Time series OI |
| OI Ranking (all coins) | `raw:coinank:instruments_oiRank:global` | Ranked list |
| OI vs Market Cap | `raw:coinank:instruments_oiVsMarketCap:global` | Leverage proxy |
| Funding Rate (Current) | `raw:coinank:fundingRate_current:global` | Per exchange, per symbol |
| Funding Rate (Accumulated) | `raw:coinank:fundingRate_accumulated:global` | 8h accumulated |
| Funding Heatmap | `raw:coinank:fundingRate_frHeatmap:global` | Matrix heatmap |
| Real Funding Settlement | `raw:coinank:fund_fundReal:global` | Actual paid funding |

**Funding data structure includes:**
- `fundingRate` — current rate
- `estimatedRate` — predicted next rate
- `fundingTime` — last settlement timestamp
- `nextFundingTime` — next settlement timestamp
- `frCap` / `frFloor` — bounds
- `interval` — hours between settlements
- Covers exchanges: Binance, Bitget, OKX, Bybit, dYdX

#### API Routes:
```
GET /api/derivatives/funding/current      → all symbols current funding
GET /api/derivatives/funding/heatmap      → funding heatmap matrix
GET /api/derivatives/oi/{symbol}/{tf}     → OI timeseries
GET /api/derivatives/oi/ranking           → OI rank all coins
GET /api/derivatives/oi/vs_mcap           → OI vs market cap
```

---

### 4.6 Long/Short Ratios & Sentiment

**Route:** `/derivatives/sentiment`  
**Purpose:** Long/short ratios, market order flow, and trader positioning.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| L/S Ratio Chart | `latest:coinank:long_short:{SYMBOL}:{TF}` | Time series |
| L/S Global Ranking | `raw:coinank:instruments_longShortRank:global` | `longShortPerson`, change % |
| Order Flow (Buy/Sell) | `latest:coinank:market_order_flow:{SYMBOL}:{TF}` | Taker buy/sell ratio |
| Top Trader Actions | `raw:coinank:hyper_topAction:global` | Hyperliquid whale actions |
| Top Trader Positions | `raw:coinank:hyper_topPosition:global` | Hyperliquid whale positions |
| RSI Heatmap | `raw:coinank:rsiMap_list:global` | RSI across all coins |
| Trade Count | `raw:coinank:trades_count:global` | Volume of trades |

**L/S fields include:**
- `longShortPerson` — ratio of long to short accounts
- `lsPersonChg5m`, `lsPersonChg15m`, `lsPersonChg1h`, `lsPersonChg4h` — rate of change
- Hyperliquid whale data: address, side, positionValue, unrealizedPnl, leverage, entryPx

#### API Routes:
```
GET /api/sentiment/long_short/{symbol}/{tf}   → L/S timeseries
GET /api/sentiment/long_short/ranking         → global ranking
GET /api/sentiment/order_flow/{symbol}/{tf}   → buy/sell flow
GET /api/sentiment/whales                     → top trader actions
GET /api/sentiment/rsi_map                    → RSI heatmap all coins
```

---

### 4.7 Liquidation Intelligence

**Route:** `/liquidations`  
**Purpose:** Real-time and historical liquidation data, levels, and heatmap.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Liquidation Feed (live) | `raw:coinank:liquidation_orders:global` | Exchange, coin, side, amount, price |
| Liquidation Rank | `raw:coinank:instruments_liquidationRank:global` | By H1/H4/H12/H24 |
| Liq Heatmap (by price) | `raw:coinank:liqMap_getLiqHeatMapSymbol:global` | Price levels at risk |
| Binance Liq Stream | `ingest/live_binance_liquidations.py` → stream | Real-time Binance liq feed |

**Liquidation order fields:**
```json
{
  "exchangeName": "Binance",
  "baseCoin": "BTC",
  "contractCode": "BTCUSDT",
  "posSide": "long",       // long or short
  "amount": 0.024,         // contracts
  "price": 79000.0,        // execution price
  "avgPrice": 79100.0,     // average fill
  "tradeTurnover": 1896.0, // USD value
  "ts": 1778886000000
}
```

**Liquidation rank fields:**
```json
{
  "baseCoin": "BTC",
  "price": 79096.8,
  "liquidationH1": 454822.81,
  "liquidationH1Long": 454665.39,
  "liquidationH1Short": 157.42,
  "liquidationH4": 876733.88,
  "liquidationH12": 62783259.36,
  "liquidationH24": 81534854.21
}
```

#### API Routes:
```
GET /api/liquidations/feed?limit=100      → recent liquidation events
GET /api/liquidations/ranking             → coins by liquidation volume
GET /api/liquidations/heatmap             → price-level liq heatmap
GET /api/liquidations/stats               → H1/H4/H12/H24 totals
```

---

### 4.8 Market Regime & Volatility

**Route:** `/regime`  
**Purpose:** Market regime classification per symbol and globally.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Global Regime Badge | `regime:global:5m`, `regime:global:15m` | Broad market state |
| Per-Symbol Regime Grid | `regime:{SYMBOL}` | All symbols at a glance |
| Per-TF Regime Detail | `regime:{SYMBOL}:{TF}` | Breakdown by timeframe |
| Structural State | `regime:structural:state:{SYMBOL}` | TRENDING / RANGING / VOLATILE |
| Volatility Score Grid | `volatility:{SYMBOL}` | `composite_index` per symbol |
| Regime Risk Budget | `risk_budget:state:primary` | How regime affects trading |
| Breadth Metrics | `risk_budget:state:primary` → `breadth_snapshot` | Market breadth |

**Regime classes:**
- `CALM` — low volatility, low move score
- `TRENDING` — directional, high alignment
- `VOLATILE` — high volatility, erratic moves
- `CHAOTIC` — extreme entropy, all systems defensive

**Breadth snapshot:**
```json
{
  "breadth_strength": 0.40,    // 0-1 directional conviction
  "breadth_entropy": 0.98,     // 0-1 signal confusion
  "n_long": 10, "n_short": 6, "n_neutral": 9,
  "n_symbols_fresh": 25
}
```

#### API Routes:
```
GET /api/regime/global                    → global regime current
GET /api/regime/all                       → all symbols regime summary
GET /api/regime/{symbol}                  → single symbol all TFs
GET /api/regime/structural/{symbol}       → structural state
GET /api/volatility/all                   → volatility scores all symbols
```

---

### 4.9 Microstructure Toxicity & Anti-Spoofing

**Route:** `/microstructure`  
**Purpose:** Real-time orderbook quality, spoofing detection, and execution hint per symbol.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Toxicity Score Grid | `toxicity:{SYMBOL}` | Color-coded 0-1 score |
| Spoof Score | `toxicity:{SYMBOL}` → `components.spoof` | Anti-spoofing signal |
| Execution Hints | `toxicity:{SYMBOL}` → `execution_hint` | NORMAL/CAUTIOUS/AVOID |
| Microstructure Features | `microfeat:{SYMBOL}:{TF}` | Raw micro features |
| Orderbook Imbalance | `toxicity:{SYMBOL}` → `components.imbalance` | Bid/ask imbalance |
| Depth Thin Alert | `toxicity:{SYMBOL}` → `components.depth_thin` | Thin book flag |
| Proactive Alerts | `signals:proactive:alerts` | Post-squeeze, breakout events |

**Toxicity component definitions:**
| Component | Description | Source Script |
|---|---|---|
| `spoof` | Spoofing detection (large orders placed/cancelled) | `risk/microstructure_toxicity.py` |
| `churn` | Flip frequency (rapid long/short flips) | `rl/anti_churn_manager.py` |
| `spread_norm` | Normalized bid/ask spread | `ingest/live_binance.py` |
| `depth_thin` | Orderbook thinness indicator | `feature_pipeline.py` |
| `imbalance` | Bid vs ask depth imbalance | `feature_pipeline.py` |
| `fast_move` | Rapid price movement score | `rl/move_shock_engine.py` |
| `snapback` | Price snapback after spike | `rl/microstructure_overlay.py` |
| `quality_inv` | Inverse data quality signal | `ingest/realtime_price_provider.py` |

#### API Routes:
```
GET /api/microstructure/toxicity/all      → all symbols toxicity
GET /api/microstructure/toxicity/{symbol} → single symbol detail
GET /api/microstructure/features/{symbol}/{tf} → raw micro features
GET /api/microstructure/alerts            → proactive alerts feed
```

---

### 4.10 Hedge System & Risk Budget

**Route:** `/risk/hedge`  
**Purpose:** Hedge system status, risk budget allocation, and portfolio defense mode.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Risk Budget State | `risk_budget:state:primary` | NORMAL / DEFENSIVE / CRISIS |
| Risk Multiplier | `risk_budget:state:primary` → `risk_mult` | Position size multiplier |
| Hedge Policy | `risk_budget:state:primary` → `hedge_policy` | HEDGE_FIRST / NORMAL / NONE |
| Max Risk Symbols | `risk_budget:state:primary` → `max_risk_symbols` | Active symbol cap |
| Portfolio State | `portfolio:combined:state` | Combined portfolio view |
| Trainer Intent vs Actual | `trainer:intent:{SYMBOL}` | Desired vs actual position |
| Market State Contract | `market:state:contract` | System-wide market contract |

**Key scripts that WRITE to risk/hedge system:**
| Script | Function |
|---|---|
| `risk/risk_budget_allocator.py` | Computes & writes risk budget state |
| `risk/global_breadth.py` | Computes market breadth → regime |
| `risk/hedge_cage_manager.py` | Manages hedge cage limits |
| `risk/adaptive_gate.py` | Adaptive signal gate |
| `risk/halt_manager.py` | Emergency halt logic |
| `risk/kill_switch.py` | Kill switch activation |
| `risk/margin_governor.py` | Margin limit enforcement |
| `risk/auto_deleverager.py` | Auto-deleveraging |
| `risk/shared_risk_gate.py` | Shared gate across accounts |
| `rl/hedge_manager_v3.py` | Main hedge manager |
| `rl/hedge_budget_governor.py` | Hedge budget tracking |
| `rl/hedge_rule_engine.py` | Rule-based hedge decisions |
| `rl/dynamic_runner_hedge.py` | Dynamic hedge runner |
| `trading/adaptive_hedge_builder.py` | Builds hedge positions |
| `trading/dynamic_adaptive_hedge.py` | Dynamic hedge adjustments |
| `trading/hedge_intelligence_engine.py` | Intelligent hedge selection |
| `trading/hedge_pair_coordinator.py` | Coordinates hedge pairs |

#### API Routes:
```
GET /api/risk/budget                      → current risk budget state
GET /api/risk/hedge/status                → hedge system status
GET /api/risk/portfolio                   → portfolio combined state
GET /api/risk/intent/{symbol}             → trainer intent per symbol
```

---

### 4.11 Stealth Stops & Dynamic TP/SL

**Route:** `/risk/stops`  
**Purpose:** Show active stealth stop and dynamic TP/SL levels across positions.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Active Stealth TPs | `stealth_tp:last:{ACCOUNT}:{SYMBOL}:{SIDE}` | All active stealth TPs |
| Dynamic Stop State | Written by `trading/dynamic_adaptive_stops.py` | — |
| Trade Proposals | `wma:proposals` | Current pending proposals |
| Recent Decisions | `wma:decisions` | Executed proposal history |

**Stealth TP fields:**
```json
{
  "symbol": "BTCUSDT",
  "side": "LONG",
  "tp_price": 80145.56,
  "qty": 0.024,
  "close_side": "SELL",
  "ts_ms": 1778702473740,
  "source": "signal",
  "account_id": "primary"
}
```

**Key scripts:**
| Script | Function |
|---|---|
| `trading/stealth_stops.py` | Places stealth stop orders (hidden from exchange until trigger) |
| `trading/stealth_dynamic_integration.py` | Integrates stealth stops with dynamic signals |
| `trading/dynamic_adaptive_stops.py` | Volatility-adaptive stop placement |
| `trading/dynamic_tp_engine.py` | Dynamic take-profit calculation |
| `rl/liquidation_prevention.py` | Prevents liquidation by auto-closing |
| `risk/intelligent_close_guard.py` | Guards against premature closes |
| `risk/reduce_only_latch.py` | Reduce-only mode enforcement |
| `rl/minimum_hold_time.py` | Prevents churning exits |

#### API Routes:
```
GET /api/stops/active                     → all active stealth TPs
GET /api/stops/active/{account}           → by account
GET /api/stops/history                    → recent TP/SL triggers
GET /api/stops/proposals                  → pending trade proposals
```

---

### 4.12 PnL & Performance

**Route:** `/performance`  
**Purpose:** Live and historical PnL, trade performance attribution, profit bank.

#### Sub-pages:
- `/performance/live` — live open position PnL
- `/performance/history` — closed trade history
- `/performance/daily` — daily decomposition

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Live PnL vs Canary | `pnl:decomp` | `live_pnl`, `canary_pnl`, `delta` |
| Profit Bank Balance | `profit_bank:state:primary` | `balance_usd`, `credited_usd` |
| Daily PnL Breakdown | `pnl:decomp:1d:primary:{YYYYMMDD}` | Day-by-day P&L |
| Per-Symbol Daily PnL | `pnl:decomp:1d:primary:{YYYYMMDD}:symbols` | Attribution by symbol |
| Episode Win Rate | `rl:metrics:loop_summary` → `win_rate` | RL episode win rate |
| Portfolio State | `portfolio:combined:state` | Account-level totals |

**PnL decomp fields:**
```json
{
  "live_pnl": 34940.0,
  "canary_pnl": 52410.0,
  "delta": {
    "live_pnl_pct": 0.2798,
    "canary_pnl_pct": 0.2797,
    "delta_pct": -0.0001,     // live vs shadow model gap
    "alert": false
  }
}
```

#### API Routes:
```
GET /api/performance/pnl                  → live PnL decomp
GET /api/performance/pnl/daily/{date}     → daily PnL
GET /api/performance/profit_bank/{account} → profit bank state
GET /api/performance/history?days=30      → trade history
```

---

### 4.13 TokenMetrics Intelligence

**Route:** `/intelligence/tokenmetrics`  
**Purpose:** AI grades, signals, predictions, and institutional intelligence from TokenMetrics.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Universe (all tokens) | `tm:universe` / `tokenmetrics:universe` | Full TM universe |
| Token Map | `tm:token_map` | Symbol → TM ID mapping |
| Endpoint Health | `tm:health:stats` | API health/rate limit stats |
| Last Run Times | `tm:last_run:{endpoint}` | Freshness per data type |
| Tooltips/Metadata | `tm:tooltips` | Token descriptions |

**Data available via TM (fetched by `ingest/live_tokenmetrics.py`):**
| Endpoint | Content | Refresh |
|---|---|---|
| `trading_signals` | Buy/hold/sell signals | 1h |
| `hourly_trading_signals` | Hourly granularity signals | 1h |
| `price_prediction` | 7-day price predictions | 24h |
| `tech_grades` | Technical grade (A-F) | 24h |
| `tm_grades` | Overall TM grade | 24h |
| `fund_grades` | Fundamental grade | 24h |
| `quantmetrics` | Quant metrics | 24h |
| `market_metrics` | Global market metrics | 1h |
| `resistance_support` | Key S/R levels | 4h |
| `correlation` | Cross-asset correlation | 24h |
| `ai_reports` | Full AI market reports | 24h |
| `moonshot_tokens` | High-potential picks | 24h |
| `top_market_cap` | Top 100 by market cap | 1h |
| `indices` | Crypto indices | 1h |
| `crypto_investors` | Institutional positions | 24h |

#### API Routes:
```
GET /api/intelligence/tm/signals          → trading signals all tokens
GET /api/intelligence/tm/grades/{symbol}  → grades for symbol
GET /api/intelligence/tm/prediction/{symbol} → price prediction
GET /api/intelligence/tm/market_metrics   → macro metrics
GET /api/intelligence/tm/correlation      → correlation matrix
GET /api/intelligence/tm/moonshots        → moonshot tokens
GET /api/intelligence/tm/health           → TM API health
```

---

### 4.14 AI Trainer Status & RL Metrics

**Route:** `/ai/trainer`  
**Purpose:** Deep insight into the PPO/MASA reinforcement learning trainer.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Trainer Status | `status:trainer` + `trainer:brain:status` | Online/offline/training |
| Heartbeat | `trainer:heartbeat:{HOST}:{PID}` | Process alive check |
| Total Episodes | `rl:episodes:total` | Cumulative training count |
| Pending Evals | `rl:eval:pending` | Episodes queued for eval |
| Obs Vector Length | `rl:obs_length` | Feature vector size |
| RL Metrics per TF | `rl:metrics:{TF}` | Per-timeframe model performance |
| Continuous Metrics | `rl:metrics:continuous` | Online learning stats |
| Loop Summary | `rl:metrics:loop_summary` | Episode win rate, avg reward, etc |
| Drift Alerts | `wma:drift_alerts` | Model distribution drift |
| Prediction QC | `wma:predictions_qc` | Prediction quality scores |
| Critical Fix Stats | `trainer:critical_fixes:stats` | Fix-set stats |
| Liq Prevention | `trainer:liq_prevention:status` | Liq prevention active/inactive |
| Model Promotion | `promotion:status` | Live vs canary model state |

**Loop summary fields:**
```json
{
  "episodes": 12450,
  "win_rate": 0.543,
  "avg_reward": 0.0187,
  "avg_confidence": 0.72,
  "drift_score": 0.03,
  "last_update_ts": 1778886000
}
```

#### API Routes:
```
GET /api/ai/trainer/status                → trainer status
GET /api/ai/trainer/metrics               → all RL metrics
GET /api/ai/trainer/metrics/{tf}          → per-TF metrics
GET /api/ai/trainer/drift                 → drift alerts
GET /api/ai/trainer/promotion             → model promotion status
```

---

### 4.15 Trade Proposals & Orchestrator

**Route:** `/orchestrator`  
**Purpose:** View all pending and executed trade proposals from the orchestrator.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Pending Proposals | `wma:proposals` | JSON array of proposals |
| Decision History | `wma:decisions` | Executed/rejected decisions |
| Leader Lock | `orchestrator:leader_lock` | Which worker is leader |
| Signal Stream | `signals:trading:primary` (XRANGE) | Full signal history |

**Trade proposal fields (from stream sample):**
```json
{
  "proposal_id": "35e36411-...",
  "ts_ms": 1776723156888,
  "source": "dynamic_tp",
  "account_id": "primary",
  "symbol": "1000BONKUSDT",
  "action_name": "SET_TAKE_PROFIT",
  "action_category": "PROTECTIVE",
  "timeframe": "multi",
  "confidence": 1.0,
  "expected_edge_net": 0.0,
  "expected_profit_pct": 1.10,
  "urgency_score": 0.031,
  "no_loss_compliant": true,
  "recovery_mode": false,
  "reduce_only": true,
  "trigger_reason": "DYNAMIC_TP_UPDATE ...",
  "market_context": {
    "tp_price": 0.006212,
    "tp_pct": 1.10,
    "decision": "STATIC_TP",
    "volatility_regime": "HIGH",
    "momentum_score": 0.031,
    "microstructure_signal": "NEUTRAL"
  }
}
```

**Proposal `action_name` types:**
- `OPEN_LONG` / `OPEN_SHORT`
- `CLOSE_LONG` / `CLOSE_SHORT`
- `SET_TAKE_PROFIT`
- `SET_STOP_LOSS`
- `INCREASE_LONG` / `INCREASE_SHORT`
- `HEDGE_LONG` / `HEDGE_SHORT`

#### API Routes:
```
GET /api/orchestrator/proposals           → pending proposals
GET /api/orchestrator/decisions           → recent decisions
GET /api/orchestrator/stream?limit=100    → signal stream history
GET /api/orchestrator/status              → leader status
```

---

### 4.16 Portfolio & Position Monitor

**Route:** `/portfolio`  
**Purpose:** All live positions, account balances, and portfolio composition.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| Live Positions | `positions:live:accounts` | All open positions |
| Portfolio State | `portfolio:combined:state` | Totals across accounts |
| Portfolio Stream | `portfolio:state:stream:primary` | Portfolio events |
| Risk Budget | `risk_budget:state:primary` + `risk_budget:state:asjad` | Per-account risk |
| Profit Bank | `profit_bank:state:primary` + `profit_bank:state:asjad` | Per-account bank |
| Stealth TPs Active | `stealth_tp:last:primary:{SYMBOL}:{SIDE}` | Active stealth TPs |
| Trainer Intents | `trainer:intent:{SYMBOL}` | Desired positions |

#### API Routes:
```
GET /api/portfolio/positions              → all live positions
GET /api/portfolio/positions/{account}    → by account
GET /api/portfolio/state                  → combined portfolio state
GET /api/portfolio/balance/{account}      → account balance
```

---

### 4.17 System Health Monitor

**Route:** `/health`  
**Purpose:** Full system health — all ingestors, services, connections, and data freshness.

#### Data Used:
| Widget | Redis Key | Notes |
|---|---|---|
| CoinAPI WS Status | `metrics:coinapi:ws:connected` | connected/disconnected |
| CoinAPI Message Rate | `metrics:coinapi:ws:msgs_today` | Messages today |
| CoinAPI Staleness | `metrics:coinapi:ws:staleness_p50_ms` | P50 latency ms |
| CoinAPI V1 Status | `metrics:coinapi:v1:connected` | REST connected |
| Price Provider Health | `metrics:price_provider:{SYMBOL}` | Per-symbol staleness |
| TokenMetrics Health | `tm:health:stats` + `tm:health:last_err` | TM API health |
| CoinAnk Last Update | `meta:coinank:last_update` | Last CoinAnk sync |
| Trainer Heartbeat | `trainer:heartbeat:{HOST}:{PID}` | Trainer alive |
| Trainer Status | `status:trainer` | Overall trainer |
| Circuit Breaker | `circuit_breaker.py` (writes to Redis) | Breaker state |
| Emergency Brake | `emergency_brake.py` | Halt state |

**CoinAPI metrics keys:**
```
metrics:coinapi:ws:connected          → "1" / "0"
metrics:coinapi:ws:connected_ts       → timestamp
metrics:coinapi:ws:last_msg_ts        → last message
metrics:coinapi:ws:msgs_today         → count
metrics:coinapi:ws:bytes_today        → bytes
metrics:coinapi:ws:staleness_p50_ms   → median staleness
metrics:coinapi:ws:staleness_p95_ms   → P95 staleness
metrics:coinapi:ws:subscribed_count   → active subscriptions
metrics:coinapi:v1:connected          → REST health
metrics:coinapi:v1:errors_today       → error count
metrics:coinapi:v1:last_ohlcv_ts      → last OHLCV timestamp
metrics:coinapi:v1:ohlcv_msgs_today   → OHLCV message count
metrics:coinapi:v1:symbols_active     → active symbol count
metrics:coinapi:ws:msgs:{YYYYMMDD}    → historical daily msg counts
```

#### API Routes:
```
GET /api/health                           → full system health summary
GET /api/health/ingestors                 → per-ingestor status
GET /api/health/coinapi                   → CoinAPI detailed health
GET /api/health/tokenmetrics              → TM health
GET /api/health/trainer                   → trainer health
GET /api/health/redis                     → Redis key freshness audit
```

---

## 5. API Route Map

### Base URL: `https://yoursite.com/api`

```
# === PRICE & MARKET ===
GET  /api/market/prices                          → all symbols latest price
GET  /api/market/price/{symbol}                  → single symbol price
GET  /api/market/ohlcv/{symbol}/{tf}             → OHLCV candles
GET  /api/market/orderbook/{symbol}              → orderbook bids/asks/depth

# === PREDICTIONS & SIGNALS ===
GET  /api/signals/predictions                    → all predictions
GET  /api/signals/predictions/{symbol}           → single symbol
GET  /api/signals/stream                         → signal stream
GET  /api/signals/alerts                         → proactive alerts
GET  /api/signals/skips                          → skipped signals

# === TECHNICAL ANALYSIS ===
GET  /api/ta/{symbol}                            → all TF summary
GET  /api/ta/{symbol}/{tf}                       → full indicator set
GET  /api/ta/{symbol}/cross_tf                   → cross-TF analysis
GET  /api/ta/rsi_grid                            → RSI all symbols

# === DERIVATIVES ===
GET  /api/derivatives/funding/current            → current funding rates
GET  /api/derivatives/funding/heatmap            → funding heatmap
GET  /api/derivatives/oi/{symbol}/{tf}           → OI timeseries
GET  /api/derivatives/oi/ranking                 → OI ranking
GET  /api/derivatives/oi/vs_mcap                 → OI vs market cap

# === SENTIMENT ===
GET  /api/sentiment/long_short/{symbol}/{tf}     → L/S ratio timeseries
GET  /api/sentiment/long_short/ranking           → global ranking
GET  /api/sentiment/order_flow/{symbol}/{tf}     → buy/sell flow
GET  /api/sentiment/whales                       → top trader actions
GET  /api/sentiment/rsi_map                      → RSI heatmap

# === LIQUIDATIONS ===
GET  /api/liquidations/feed                      → recent liq events
GET  /api/liquidations/ranking                   → coins by liq volume
GET  /api/liquidations/heatmap                   → price-level heatmap
GET  /api/liquidations/stats                     → H1/H4/H12/H24

# === REGIME & VOLATILITY ===
GET  /api/regime/global                          → global regime
GET  /api/regime/all                             → all symbols
GET  /api/regime/{symbol}                        → single symbol
GET  /api/regime/structural/{symbol}             → structural state
GET  /api/volatility/all                         → volatility scores

# === MICROSTRUCTURE ===
GET  /api/microstructure/toxicity/all            → all toxicity scores
GET  /api/microstructure/toxicity/{symbol}       → single symbol detail
GET  /api/microstructure/features/{symbol}/{tf}  → raw micro features
GET  /api/microstructure/alerts                  → proactive alerts

# === RISK & HEDGE ===
GET  /api/risk/budget                            → risk budget state
GET  /api/risk/hedge/status                      → hedge status
GET  /api/risk/portfolio                         → portfolio state
GET  /api/risk/intent/{symbol}                   → trainer intent

# === STOPS & PROPOSALS ===
GET  /api/stops/active                           → active stealth TPs
GET  /api/stops/active/{account}                 → by account
GET  /api/stops/history                          → TP/SL history
GET  /api/stops/proposals                        → pending proposals

# === PERFORMANCE / PNL ===
GET  /api/performance/pnl                        → live PnL decomp
GET  /api/performance/pnl/daily/{date}           → daily PnL (YYYYMMDD)
GET  /api/performance/profit_bank/{account}      → profit bank
GET  /api/performance/history                    → trade history

# === TOKENMETRICS ===
GET  /api/intelligence/tm/signals                → TM signals
GET  /api/intelligence/tm/grades/{symbol}        → TM grades
GET  /api/intelligence/tm/prediction/{symbol}    → TM price prediction
GET  /api/intelligence/tm/market_metrics         → macro metrics
GET  /api/intelligence/tm/correlation            → correlation matrix
GET  /api/intelligence/tm/moonshots              → moonshot tokens
GET  /api/intelligence/tm/health                 → TM API health

# === AI TRAINER ===
GET  /api/ai/trainer/status                      → trainer status
GET  /api/ai/trainer/metrics                     → all RL metrics
GET  /api/ai/trainer/metrics/{tf}                → per-TF metrics
GET  /api/ai/trainer/drift                       → drift alerts
GET  /api/ai/trainer/promotion                   → model promotion

# === ORCHESTRATOR ===
GET  /api/orchestrator/proposals                 → pending proposals
GET  /api/orchestrator/decisions                 → recent decisions
GET  /api/orchestrator/stream                    → signal stream history
GET  /api/orchestrator/status                    → leader status

# === PORTFOLIO ===
GET  /api/portfolio/positions                    → all live positions
GET  /api/portfolio/positions/{account}          → by account
GET  /api/portfolio/state                        → combined state
GET  /api/portfolio/balance/{account}            → account balance

# === SYSTEM HEALTH ===
GET  /api/health                                 → full health summary
GET  /api/health/ingestors                       → ingestor status
GET  /api/health/coinapi                         → CoinAPI health
GET  /api/health/tokenmetrics                    → TM health
GET  /api/health/trainer                         → trainer health
GET  /api/health/redis                           → Redis freshness
```

---

## 6. Supported Symbols

### Core Symbols (25 active):
| Symbol | Category |
|---|---|
| BTCUSDT | Large Cap |
| ETHUSDT | Large Cap |
| SOLUSDT | Large Cap |
| XRPUSDT | Large Cap |
| DOGEUSDT | Large Cap Meme |
| LINKUSDT | DeFi |
| LTCUSDT | Large Cap |
| UNIUSDT | DeFi |
| WIFUSDT | Meme |
| PENGUUSDT | Meme |
| 1000PEPEUSDT | Meme |
| 1000BONKUSDT | Meme |
| 1000FLOKIUSDT | Meme |
| 1000SHIBUSDT | Meme |
| FARTCOINUSDT | Meme |
| BANKUSDT | Alt |
| BARDUSDT | Alt |
| HIGHUSDT | Alt |
| ALICEUSDT | Alt |
| ASTERUSDT | Alt |
| AUCTIONUSDT | Alt |
| AVNTUSDT | Alt |
| PIPPINUSDT | Alt |
| RAVEUSDT | Alt |
| RIVERUSDT | Alt |

### Timeframes Available:
`1m` · `5m` · `15m` · `1h` · `4h` · `cross_tf`

Additionally for CoinAnk data: `30m` · `1d`

### Accounts:
- `primary` — main trading account
- `asjad` — secondary/mirror account

---

## Notes for Developer

1. **Redis Connection:** `localhost:6379`, no auth by default (check `config.py` for production settings)
2. **Data types:** Mix of `string` (JSON), `hash` (HGETALL), `stream` (XRANGE), `list` (LRANGE) — must handle each properly
3. **Freshness:** Most keys update every 5-30 seconds. Check `updated_ts_ms` or `ts_ms` field in each key to detect stale data
4. **Public vs Private:** Trading signals, PnL, and positions may need auth before exposing publicly — discuss with owner
5. **Polling vs WebSocket:** For real-time display, use server-sent events (SSE) or WebSocket from your backend that polls Redis; don't directly expose Redis to frontend
6. **All TA keys use TA-Lib** (C library) calculated by `ingest/live_technical_analysis.py` — output is a flat dict of 300+ fields per symbol/timeframe
7. **CoinAnk data** is raw API passthrough stored in `raw:coinank:*` — parse the nested `.data.data` structure
8. **Signal stream** (`signals:trading:primary`) is a Redis Stream — use `XRANGE` to read, `XREAD` to tail live
9. **Prediction hash** — use `HGETALL prediction:BTCUSDT:5m` — key/value pairs (not JSON string)

---
*Generated: May 15, 2026 | Source audit of `/home/wali/Desktop/AI BOT` system*
