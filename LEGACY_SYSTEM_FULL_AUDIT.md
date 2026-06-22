# Legacy System Full Audit — Redis Keys, Ingestors & Scripts
**Purpose:** Complete inventory of every running legacy process, Redis key namespace, and data product.
This document is the shutdown baseline — used to verify the V2 rebuild produces equivalent data before legacy is killed.

**Audit Date:** 2026-05-22
**Total Redis Keys at Audit Time:** 12,637
**Legacy Process Count:** 14 Python processes
**V2 Process Count:** 11 Python processes

---

## 1. RUNNING LEGACY PROCESSES (from `/home/wali/Desktop/AI BOT/`)

These are the processes generating all live data in Redis right now.

| PID | Script | Role | Redis Keys Written |
|-----|--------|------|--------------------|
| 46218 | `ingest/live_binance.py` | Binance REST + WS OHLCV/mark-price/funding ingestor | `ohlcv:list:binance:*`, `latest:binance:ohlcv:*`, `latest:binance:mark_price:*`, `ingest:binance:last_ts`, `heartbeat:IngestBinance` |
| 46365 | `ingest/live_binance_liquidations.py` | Binance WS liquidation order stream | `binance:force` (stream), `heartbeat:IngestLiquidations` |
| 46559 | `ingest/live_coinank.py` | CoinAnk API poller — all market-intelligence endpoints | `coinank:*` (200+ raw keys), `features:coinank:*` (2,403 keys), `features:coinank_endpoint:*` (3,054 keys), `cursor:coinank:*` (2,150 keys), `latest:coinank:*` (1,039 keys), `latest:coinank_endpoint:*` (1,527 keys), `features:global_coinank:*` (19 keys), `raw:coinank:*` (19 keys), `lock:live_coinank`, `heartbeat:CoinAnkIngest`, `heartbeat:IngestCoinAnk`, `heartbeat:writer:coinank`, `ingest:coinank:last_ts` |
| 47157 | `ingest/live_kucoin.py` | KuCoin REST/WS klines, OI, funding, orderbook | `kc:kline:*` (90 keys), `kc:orderbook20:*` (18 keys), `kc:latest:*` (18 keys), `kc:funding:*` (8 keys), `kc:mark_index:*` (8 keys), `kc:open_interest:*` (8 keys), `features:kucoin:*` (90 keys), `heartbeat:KuCoin` |
| 47348 | `ingest/live_technical_analysis.py` | TA indicator computation (RSI, MACD, BB, ATR, etc.) | `ta:{SYMBOL}:{TF}` (hash, 160 fields each × 25 symbols × 6 TFs = 150 keys), `latest:ta:*` (150 keys), `heartbeat:OrderBook:*` |
| 47589 | `ingest/realtime_price_provider.py` | Real-time price aggregator + orderbook snap | `price:realtime:{SYMBOL}` (25 keys), `price:last:{SYMBOL}` (25 keys), `price:{SYMBOL}` (25 keys), `orderbook:top:{SYMBOL}` (25 keys), `orderbook:depth:{SYMBOL}` (25 keys), `orderbook:bids:{SYMBOL}` (25 keys), `orderbook:asks:{SYMBOL}` (25 keys), `instant:{SYMBOL}:spread` (5 keys), `metrics:price_provider:*` (25 keys), `heartbeat:OrderBook` |
| 48066 | `feature_pipeline.py` | Unified feature builder (merges OHLCV + TA + CoinAnk + KuCoin) | `unified_features:{SYMBOL}:{TF}` (hash, 562 fields × 25 symbols × 10 TFs = 250 keys), `features:fast_lane` (stream), `features:slow_lane` (stream), `features:resampler`, `heartbeat:FeaturePipeline` |
| 48623 | `rl/hybrid_trainer.py` (--mode hybrid --epochs 1000) | PPO+MASA RL trainer, GPU-accelerated | `prediction:{SYMBOL}:{TF}` (hash, 18 fields × 25 symbols × up to 6 TFs), `trainer:intent:{SYMBOL}` (hash × 22 symbols), `rl:metrics:{TF}` (6 timeframe keys), `rl:metrics:loop_summary`, `rl:metrics:continuous`, `rl:episodes:total`, `rl:obs_length`, `rl:eval:pending`, `heartbeat:trainer`, `heartbeat:Trainer`, `status:trainer` |
| 49067 | `trading/opportunity_tracker.py` | Opportunity scanner + signal overlay | `opportunity:latest` (string), `signals:overlay:intents` (stream), `signals:proactive:alerts` (stream) |
| 54017 | `rl/orchestrator_worker.py` | Signal orchestrator — merges predictions into trading signals | `signals:trading:primary` (stream, 50,000 entries), `signals:trading:asjad` (stream, 200 entries), `signals:ensemble:diagnostic` (stream, 10,000 entries), `signals:debug` (stream), `wma:proposals` (stream, 1,556 entries), `wma:decisions` (stream, 50,000 entries), `wma:predictions_qc` (stream, 36,183 entries), `wma:drift_alerts` (stream, 515 entries), `executed_signals` (stream, 1,552 entries), `orchestrator:leader_lock` |
| 54905 | `ingest/live_coinapi_v1.py` | CoinAPI REST OHLCV backfill + live klines | `ohlcv:list:coinapi:{SYMBOL}:{TF}` (list, 2,000 candles × 25 symbols × up to 5 TFs = 25 keys active), `latest:coinapi:ohlcv:*`, `coinapi:symbolmap:*` (25 keys), `metrics:coinapi:*` (21 keys) |
| 55369 | `ingest/live_coinapi_wsds.py` | CoinAPI WebSocket trades → microstructure features | `microfeat:{SYMBOL}:{TF}` (hash, 27 fields × 25 symbols × up to 5 TFs), `msnap:coinapi_wsds:{SYMBOL}` (hash, 46 fields × 25 symbols), `normalized:ohlcv:{SYMBOL}:{TF}` (hash × 25 symbols × TFs) |
| 46149 | `monitoring/oom_monitor.py` | OOM watchdog (monitor only, no Redis writes) | — |
| 57289 | `scripts/monitor_trainer_prices.py` | Monitor script (read-only) | — |
| 57478 | `scripts/monitor_trainer_predictions.py` | Monitor script (read-only) | — |
| 57884 | `monitor_portfolio_primary.py` | Portfolio monitor (read-only, Telegram alerts) | — |

---

## 2. ADDITIONAL LEGACY INGESTORS (in `/home/wali/Desktop/AI BOT/ingest/`)

These exist in the codebase but may not currently be running as standalone processes:

| Script | Role | Redis Keys / Output |
|--------|------|---------------------|
| `live_tokenmetrics.py` | TokenMetrics API — AI grades, price predictions, trading signals | `tm:last_run:*` (18 keys), `tm:health:*`, `tm:token_map`, `tm:tooltips`, `tm:universe`, `tokenmetrics:universe`, `heartbeat:writer:tokenmetrics` |
| `live_coinapi_rest.py` | CoinAPI REST fallback (backup to v1) | `ohlcv:list:coinapi:*`, `latest:coinapi:*` |
| `live_ccxt.py` | CCXT multi-exchange OHLCV | Various exchange OHLCV keys |
| `live_coinank_global_aggregator.py` | CoinAnk global metrics aggregator | `features:global_coinank:*`, `coinank:*` global keys |
| `liquidation_bridge.py` | Liquidation level engine bridge | `cursor:liq_bridge:*` |
| `live_alphavantage_news.py` | AlphaVantage news sentiment (stale / not active) | Alt-data namespace |
| `technical_analysis.py` | TA computation library (imported, not standalone) | (library) |

---

## 3. COMPLETE REDIS KEY NAMESPACE INVENTORY

### 3.1 Price & OHLCV Data

| Key Pattern | Type | Count | Fields/Length | Source Script | Update Freq |
|-------------|------|-------|---------------|---------------|-------------|
| `ohlcv:list:coinapi:{SYMBOL}:{TF}` | list | 25 | 2,000 candles | `live_coinapi_v1.py` | Per candle close |
| `ohlcv:list:binance:{SYMBOL}:{TF}` | list | ~50 | 2,000 candles | `live_binance.py` | Per candle close |
| `normalized:ohlcv:{SYMBOL}:{TF}` | hash | ~60 | varies | `live_coinapi_wsds.py` | Per candle |
| `price:{SYMBOL}` | string | 25 | JSON (bytes=36) | `realtime_price_provider.py` | ~1s |
| `price:realtime:{SYMBOL}` | string | 25 | JSON | `realtime_price_provider.py` | ~1s |
| `price:last:{SYMBOL}` | string | 25 | JSON | `realtime_price_provider.py` | ~1s |
| `latest:binance:ohlcv:{SYMBOL}:{TF}` | string | ~155 | JSON | `live_binance.py` | Per candle |
| `latest:binance:mark_price:{SYMBOL}` | string | ~25 | JSON | `live_binance.py` | ~1s |
| `latest:coinapi:ohlcv:{SYMBOL}:{TF}` | string | 25 | JSON | `live_coinapi_v1.py` | Per candle |
| `msnap:coinapi_wsds:{SYMBOL}` | hash | 25 | 46 fields | `live_coinapi_wsds.py` | ~1s tick |
| `metrics:coinapi:{SYMBOL}` | hash | 21 | varies | `live_coinapi_v1.py` | Per run |
| `metrics:price_provider:{SYMBOL}` | hash | 25 | varies | `realtime_price_provider.py` | Per cycle |
| `coinapi:symbolmap:{SYMBOL}` | string | 25 | JSON | `live_coinapi_v1.py` | Startup |
| `ingest:binance:last_ts` | string | 1 | epoch ms | `live_binance.py` | Per write |
| `ingest:coinank:last_ts` | string | 1 | epoch ms | `live_coinank.py` | Per write |

---

### 3.2 Order Book

| Key Pattern | Type | Count | Fields/Length | Source Script | Update Freq |
|-------------|------|-------|---------------|---------------|-------------|
| `orderbook:top:{SYMBOL}` | string | 25 | JSON 480B (bid/ask/spread/mid) | `realtime_price_provider.py` | ~1s |
| `orderbook:depth:{SYMBOL}` | string | 25 | JSON | `realtime_price_provider.py` | ~1s |
| `orderbook:bids:{SYMBOL}` | string | 25 | JSON | `realtime_price_provider.py` | ~1s |
| `orderbook:asks:{SYMBOL}` | string | 25 | JSON | `realtime_price_provider.py` | ~1s |
| `instant:{SYMBOL}:spread` | string | 5 | float | `realtime_price_provider.py` | ~1s |
| `kc:orderbook20:{SYMBOL}` | string | 18 | JSON | `live_kucoin.py` | ~1s |

---

### 3.3 Technical Analysis

| Key Pattern | Type | Count | Fields | Source Script | Update Freq |
|-------------|------|-------|--------|---------------|-------------|
| `ta:{SYMBOL}:{TF}` | hash | 150 | **160 fields** (RSI, MACD, BB, ATR, OBV, VWAP, EMA/SMA, Stoch, CCI, ADX, etc.) | `live_technical_analysis.py` | Per candle |
| `latest:ta:{SYMBOL}:{TF}` | string | 150 | JSON (timestamp metadata) | `live_technical_analysis.py` | Per write |
| `regime:structural:{SYMBOL}:{TF}:ts` | string | ~175 | epoch ts | `live_technical_analysis.py` | Per candle |
| `regime:structural:last_ts:{SYMBOL}:{TF}` | string | ~175 | epoch ts | `live_technical_analysis.py` | Per candle |
| `regime:structural:{SYMBOL}:{TF}:closes` | list | ~175 | price series | `live_technical_analysis.py` | Per candle |

---

### 3.4 Microstructure Features

| Key Pattern | Type | Count | Fields | Source Script | Update Freq |
|-------------|------|-------|--------|---------------|-------------|
| `microfeat:{SYMBOL}:{TF}` | hash | 25+ | **27 fields** (trade_count, buy/sell volume ratio, aggressor ratio, bid/ask imbalance, vwap_dev, etc.) | `live_coinapi_wsds.py` | Per WS tick |

---

### 3.5 Unified Features (Master Feature Vector)

| Key Pattern | Type | Count | Fields | Source Script | Update Freq |
|-------------|------|-------|--------|---------------|-------------|
| `unified_features:{SYMBOL}:{TF}` | hash | 250 | **562 fields** (full merged feature vector: OHLCV + TA + CoinAnk + KuCoin + microstructure) | `feature_pipeline.py` | Per cycle (~30s) |

---

### 3.6 CoinAnk Intelligence Data

> **2,403 `features:coinank:*` keys** + **3,054 `features:coinank_endpoint:*` keys** — this is the largest namespace.

#### Sub-namespaces under `features:coinank:{CATEGORY}:{SYMBOL}:{EXCHANGE}:{TF}:{latest|series}`

| Category | Description | TFs Available |
|----------|-------------|---------------|
| `long_short` | Long/short ratio (accounts + positions + top traders) | 5m, 15m, 1h, 4h, 1d |
| `open_interest` | Open interest klines + aggregated | 5m, 15m, 1h, 4h, 1d |
| `funding` | Funding rate history + klines + indicators | 5m, 15m, 1h, 4h, 1d |
| `liquidations` | Liquidation history per exchange per interval | 5m, 1h, 4h, 1d |
| `instruments` | Visual screener, OI vs MC, price rank, volume rank | 5m, 15m, 1h, 4h, 1d |
| `market_order_flow` | Buy/sell count/value/volume, CVD (cumulative volume delta) | 5m, 1h, 4h, 1d |
| `advanced` | Net positions, RSI map, big orders | 5m, 1h, 4h |

#### Direct `coinank:*` Raw Keys (single-instance globals)

| Key Pattern | Type | Description |
|-------------|------|-------------|
| `coinank:openInterest_all` | string | Aggregated OI across all exchanges |
| `coinank:openInterest_kline:{TF}` | string | OI klines per TF (5m, 1h, 4h) |
| `coinank:openInterest_aggKline:{TF}` | string | Aggregated OI klines |
| `coinank:openInterest_v2_chart:{TF}` | string | OI chart data |
| `coinank:openInterest_symbol_Chart:{TF}` | string | Per-symbol OI chart |
| `coinank:ls_buy_sell:{TF}` | string | Buy/sell L/S ratio |
| `coinank:ls_kline:{TF}` | string | L/S ratio klines |
| `coinank:ls_global_account_ratio:{TF}` | string | Global account L/S ratio |
| `coinank:ls_toptrader_accounts:{TF}` | string | Top trader account ratio |
| `coinank:ls_toptrader_positions:{TF}` | string | Top trader position ratio |
| `coinank:ls_exchange_realtimeAll:{TF}` | string | Exchange real-time L/S |
| `coinank:fundingRate_current` | string | Current funding rate |
| `coinank:fundingRate_accumulated` | string | Accumulated funding |
| `coinank:fundingRate_history` | string | FR history |
| `coinank:fundingRate_kline:{TF}` | string | FR klines per TF |
| `coinank:fundingRate_indicator:{TF}` | string | FR indicator |
| `coinank:fundingRate_getWeiFr:{TF}` | string | Weighted FR |
| `coinank:fundingRate_frHeatmap` | string | FR heatmap |
| `coinank:liquidation_history` | string | Liquidation history |
| `coinank:liquidation_history_{TF}` | string | Liq history per TF |
| `coinank:liquidation_aggregated_history_{TF}` | string | Aggregated liq history |
| `coinank:liquidation_orders` | string | Active liq orders |
| `coinank:liquidation_allExchange_intervals` | string | Cross-exchange liq intervals |
| `coinank:liqMap_getLiqHeatMapSymbol` | string | Liquidation heatmap |
| `coinank:marketOrder_getAggBuySellCount:{TF}` | string | Aggregated buy/sell count |
| `coinank:marketOrder_getAggBuySellValue:{TF}` | string | Aggregated buy/sell value |
| `coinank:marketOrder_getAggBuySellVolume:{TF}` | string | Aggregated buy/sell vol |
| `coinank:marketOrder_getAggCvd:{TF}` | string | Aggregated CVD |
| `coinank:marketOrder_getBuySellCount:{TF}` | string | Buy/sell order count |
| `coinank:marketOrder_getBuySellValue:{TF}` | string | Buy/sell order value |
| `coinank:marketOrder_getBuySellVolume:{TF}` | string | Buy/sell volume |
| `coinank:marketOrder_getCvd:{TF}` | string | CVD |
| `coinank:netPositions_getNetPositions:{TF}` | string | Net positions |
| `coinank:instruments_visualScreener:{TF}` | string | Visual screener |
| `coinank:instruments_longShortRank` | string | L/S rank |
| `coinank:instruments_oiRank` | string | OI rank |
| `coinank:instruments_oiVsMc:{TF}` | string | OI vs market cap |
| `coinank:instruments_oiVsMarketCap` | string | OI vs MC (alt key) |
| `coinank:instruments_priceRank` | string | Price rank |
| `coinank:instruments_volumeRank` | string | Volume rank |
| `coinank:instruments_liquidationRank` | string | Liquidation rank |
| `coinank:instruments_getCoinMarketCap` | string | CMC data |
| `coinank:hyper_topPosition` | string | Top trader positions (hyper) |
| `coinank:hyper_topAction` | string | Top trader actions (hyper) |
| `coinank:rsiMap_list:{TF}` | string | RSI heatmap (1h, 4h, 12h, 24h) |
| `coinank:bigOrder_queryOrderList` | string | Big order list |
| `coinank:indicator_smc:{TF}` | string | SMC indicator |
| `coinank:indicator_getAltcoinSeason` | string | Altcoin season index |
| `coinank:fund_fundReal` | string | Real funding rate |
| `coinank:fund_getFundHisList:{TF}` | string | Fund history list |
| `coinank:trades_count` | string | Trade count |
| `coinank:trades_largeTrades` | string | Large trades |
| `coinank:orderFlow_lists:{TF}` | string | Order flow lists |
| `coinank:basic` | string | Basic market data |
| `coinank:endpoints` | string | Endpoint manifest |
| `coinank:endpoint_manifest` | string | Endpoint manifest v2 |
| `coinank:feature_manifest` | string | Feature manifest |
| `coinank:runtime` | string | Runtime metadata |
| `coinank:metrics` | string | CoinAnk metrics |
| `coinank:cycle_log` | string | Cycle log |
| `coinank:cycle_complete` | string | Cycle complete flag |
| `coinank:call_log` | string | API call log |
| `coinank:last_endpoint` | string | Last endpoint hit |
| `coinank:series` | (missing) | Series index |

#### Global CoinAnk Aggregates (`features:global_coinank:*`)

| Key | Type | Description |
|-----|------|-------------|
| `features:global_coinank:instruments_longShortRank:latest` | string | Global L/S rank |
| `features:global_coinank:baseCoin_list:latest` | string | Base coin list |
| `features:global_coinank:liquidation_orders:latest` | string | Global liq orders |
| `features:global_coinank:hyper_topAction:latest` | string | Top actions |
| `features:global_coinank:instruments_priceRank:latest` | string | Price rank |
| `features:global_coinank:*` | string | 19 keys total |

#### Raw CoinAnk (`raw:coinank:*`)

| Key Pattern | Description |
|-------------|-------------|
| `raw:coinank:rsiMap_list:global` | Raw RSI map |
| `raw:coinank:fundingRate_current:global` | Raw current FR |
| `raw:coinank:fund_fundReal:global` | Raw real funding |
| `raw:coinank:baseCoin_list:global` | Raw base coin list |
| `raw:coinank:hyper_topPosition:global` | Raw top positions |
| (19 total) | Various raw API responses |

#### Cursor Keys (`cursor:coinank:*` — 2,150 keys)

Used by `live_coinank.py` to track pagination/last-fetch state per endpoint per symbol per TF.
Pattern: `cursor:coinank:{CATEGORY}:{SYMBOL}:{EXCHANGE}:{TF}:{ENDPOINT_FUNCTION}`

---

### 3.7 KuCoin Data

| Key Pattern | Type | Count | Description | Source |
|-------------|------|-------|-------------|--------|
| `kc:kline:{SYMBOL}:{TF}` | string | 90 | OHLCV klines | `live_kucoin.py` |
| `kc:latest:{SYMBOL}:{TF}` | string | 18 | Latest kline metadata | `live_kucoin.py` |
| `kc:funding:{SYMBOL}` | string | 8 | Funding rate | `live_kucoin.py` |
| `kc:mark_index:{SYMBOL}` | string | 8 | Mark/index price | `live_kucoin.py` |
| `kc:open_interest:{SYMBOL}` | string | 8 | Open interest | `live_kucoin.py` |
| `kc:orderbook20:{SYMBOL}` | string | 18 | 20-level orderbook | `live_kucoin.py` |
| `features:kucoin:{SYMBOL}:{TF}` | hash | 90 | Derived KuCoin features | `live_kucoin.py` |

---

### 3.8 AI Predictions (Hybrid Trainer Output)

| Key Pattern | Type | Count | Fields | Description |
|-------------|------|-------|--------|-------------|
| `prediction:{SYMBOL}:{TF}` | hash | **~150** (25 symbols × 6 TFs) | **18 fields** | PPO+MASA model output per symbol per TF |

**Fields in `prediction:{SYMBOL}:{TF}`:**
- `action` — LONG / SHORT / HOLD
- `action_name` — same
- `direction` — LONG / SHORT / HOLD
- `confidence` — float 0–1
- `model_confidence` — float
- `ppo_confidence` — PPO head confidence
- `masa_confidence` — MASA head confidence
- `price_target` — predicted target price (0 if HOLD)
- `entry_price` — price at signal time
- `predicted_return` — expected return
- `timestamp` — Unix epoch
- `ts_ms` — Unix epoch milliseconds
- `symbol` — e.g. BTCUSDT
- `timeframe` — e.g. 5m
- `published` — 0/1 flag
- `threshold_passed` — 0/1 flag
- `why` — reason string (e.g. PASSED_CONF_FILTER)
- `action_idx` — integer action index

| Key Pattern | Type | Count | Fields | Description |
|-------------|------|-------|--------|-------------|
| `trainer:intent:{SYMBOL}` | hash | 22 | direction, confidence, action, timeframe, ts_ms, producer | Trainer directional intent (consumed by orchestrator) |
| `prediction:accuracy` | hash | 1 | per-symbol accuracy stats | Accuracy tracker |
| `rl:metrics:{TF}` | hash | 6 TFs | loop, episode_reward, training_level, timestamp | RL training metrics per TF |
| `rl:metrics:loop_summary` | hash | 1 | Summary across all TFs | Loop summary |
| `rl:metrics:continuous` | hash | 1 | Continuous training metrics | — |
| `rl:episodes:total` | string | 1 | total episode count | — |
| `rl:obs_length` | string | 1 | observation vector length | — |
| `rl:eval:pending` | string | 1 | pending eval flag | — |
| `heartbeat:trainer` | string | 1 | JSON last-seen timestamp | — |
| `heartbeat:Trainer` | string | 1 | JSON (duplicate capitalization) | — |
| `status:trainer` | string | 1 | JSON status string | — |
| `trainer:critical_fixes` | hash | 1 | Critical fix flags | — |
| `trainer:liq_prevention` | hash | 1 | Liquidation prevention state | — |
| `trainer:heartbeat` | string | 1 | Same as heartbeat:trainer | — |

---

### 3.9 Trading Signals & Orchestration

| Key | Type | Entries | Description | Source |
|-----|------|---------|-------------|--------|
| `signals:trading:primary` | stream | **50,000** (capped) | Primary trading signal stream — consumed by paper/live loops | `orchestrator_worker.py` |
| `signals:trading:asjad` | stream | 200 | Secondary signal stream (account filter) | `orchestrator_worker.py` |
| `executed_signals` | stream | 1,552 | Signals that were sent to execution | `orchestrator_worker.py` |
| `signals:ensemble:diagnostic` | stream | 10,000 | Diagnostic ensemble signal stream | `orchestrator_worker.py` |
| `signals:overlay:intents` | stream | 1,005 | Overlay/opportunity intents | `opportunity_tracker.py` |
| `signals:proactive:alerts` | stream | 1,006 | Proactive alert stream | `opportunity_tracker.py` |
| `signals:debug` | stream | 1,043 | Debug signal stream | `orchestrator_worker.py` |
| `wma:proposals` | stream | 1,556 | WMA proposal queue | `orchestrator_worker.py` |
| `wma:decisions` | stream | **50,000** (capped) | WMA decision log | `orchestrator_worker.py` |
| `wma:predictions_qc` | stream | 36,183 | Prediction quality control | `orchestrator_worker.py` |
| `wma:drift_alerts` | stream | 515 | Model drift alerts | `orchestrator_worker.py` |
| `orchestrator:leader_lock` | string | 1 | Leader election lock UUID | `orchestrator_worker.py` |
| `opportunity:latest` | string | 1 | JSON latest opportunity scan | `opportunity_tracker.py` |
| `promotion:status` | hash | 8 fields | Signal promotion state | Orchestrator |

---

### 3.10 Market Regime & Volatility

| Key Pattern | Type | Count | Description | Source |
|-------------|------|-------|-------------|--------|
| `regime:{SYMBOL}` | string | 25 | JSON regime state (trend/range/volatile/etc.) | `feature_pipeline.py` |
| `regime:global` | string | 1 | Global market regime | `feature_pipeline.py` |
| `regime:structural:*` | string/list | **175** | Structural regime data per symbol/TF (closes series, timestamps) | `live_technical_analysis.py` |
| `regime_analysis:{SYMBOL}` | hash | 25 | Detailed regime analysis hash | `feature_pipeline.py` |
| `volatility:{SYMBOL}` | string | 25 | Current volatility scalar (bytes=24) | `feature_pipeline.py` |

---

### 3.11 Health, Heartbeat & Monitoring

| Key Pattern | Type | Count | Description | Source |
|-------------|------|-------|-------------|--------|
| `heartbeat:IngestBinance` | string | 1 | Last live_binance.py heartbeat | `live_binance.py` |
| `heartbeat:IngestLiquidations` | string | 1 | Last live_binance_liquidations.py heartbeat | `live_binance_liquidations.py` |
| `heartbeat:CoinAnkIngest` | string | 1 | CoinAnk ingestor heartbeat | `live_coinank.py` |
| `heartbeat:IngestCoinAnk` | string | 1 | (duplicate — alternate key name) | `live_coinank.py` |
| `heartbeat:KuCoin` | string | 1 | KuCoin ingestor heartbeat | `live_kucoin.py` |
| `heartbeat:FeaturePipeline` | string | 1 | Feature pipeline heartbeat | `feature_pipeline.py` |
| `heartbeat:OrderBook:{SYMBOL}` | string | 25 | Per-symbol orderbook heartbeat | `live_technical_analysis.py` |
| `heartbeat:OrderBook` | string | 1 | Aggregate orderbook heartbeat | `realtime_price_provider.py` |
| `heartbeat:trainer` | string | 1 | Trainer heartbeat | `hybrid_trainer.py` |
| `heartbeat:Trainer` | string | 1 | Trainer heartbeat (capitalized alias) | `hybrid_trainer.py` |
| `heartbeat:writer:coinank` | string | 1 | CoinAnk writer heartbeat | `live_coinank.py` |
| `heartbeat:writer:tokenmetrics` | string | 1 | TokenMetrics writer heartbeat | `live_tokenmetrics.py` |
| `health:events` | stream | **53,748** | System-wide health event log | Multiple workers |
| `lock:live_coinank` | string | 1 | CoinAnk cycle lock (prevents concurrent writes) | `live_coinank.py` |

---

### 3.12 TokenMetrics Data

| Key Pattern | Type | Count | Description | Source |
|-------------|------|-------|-------------|--------|
| `tm:last_run:{ENDPOINT}` | string | 18 | Last successful fetch time per TM endpoint | `live_tokenmetrics.py` |
| `tm:health:stats` | hash | 1 | TM health stats | `live_tokenmetrics.py` |
| `tm:health:last_err` | string | 1 | Last TM error | `live_tokenmetrics.py` |
| `tm:token_map` | hash | 1 | Symbol → TM token ID mapping | `live_tokenmetrics.py` |
| `tm:tooltips` | hash | 1 | TM tooltip data | `live_tokenmetrics.py` |
| `tm:universe` | set | 10 members | Active TM symbol universe | `live_tokenmetrics.py` |
| `tokenmetrics:universe` | string | 1 | JSON universe string | `live_tokenmetrics.py` |

**TokenMetrics endpoints tracked in `tm:last_run:*`:**
`ai_reports`, `correlation`, `crypto_investors`, `fund_grades`, `fund_grades_hist`, `hourly_trading_signals`, `indices`, `market_metrics`, `moonshot_tokens`, `price_prediction`, `quantmetrics`, `resistance_support`, `tech_grades`, `tech_grades_hist`, `tm_grades`, `tm_grades_hist`, `top_market_cap`, `trading_signals`

---

### 3.13 Portfolio & Position Tracking

| Key | Type | Description | Source |
|-----|------|-------------|--------|
| `positions:live:accounts` | set | Active account IDs (members: "primary") | Trading loop |
| `pnl:decomp` | stream | 634 entries — PnL decomposition per trade | Trading loop |
| `portfolio:state` | (missing) | Portfolio state (not currently populated) | — |
| `portfolio:combined` | (missing/stale) | Combined portfolio view | — |
| `profit_bank:state` | (missing) | Profit bank state | — |
| `profit_bank:last_id` | (missing) | Last profit bank ID | — |
| `risk_budget:state` | (missing) | Risk budget state | — |

---

### 3.14 V2 Paper Loop (V2-Native Data)

These keys are written by V2 processes, not legacy.

| Key | Type | Description | V2 Process |
|-----|------|-------------|------------|
| `v2:paper:heartbeat` | string | Paper loop heartbeat | `paper_online_runtime.py` |
| `v2:paper:positions` | hash | Paper positions | `paper_online_runtime.py` |
| `v2:paper:intents` | stream | Paper trade intents | `paper_online_runtime.py` |
| `v2:paper:intents_held_by_paper_fill_gate` | stream | Intents held by fill gate | `paper_online_runtime.py` |
| `v2:paper:ledger` | stream | Paper trade ledger | `paper_online_runtime.py` |
| `v2:paper:shadow_observations` | stream | Shadow obs | `paper_online_runtime.py` |
| `v2:paper:shadow_outcome:{SYMBOL}` | hash | Shadow trade outcomes | Position tracker |
| `v2:paper:position_history:{SYMBOL}` | stream | Position history | `v2_position_history_persistent_tracker.py` |
| `v2:paper:position_price_track:{SYMBOL}` | hash | Price tracking | Position tracker |
| `v2:prediction:{SYMBOL}:1m` | hash | V2 native predictions (BTC/ETH/SOL only) | V2 feature pipeline |
| `v2:features:latest:{SYMBOL}:1m` | hash | V2 native features | `v2_feature_snapshot_builder.py` |
| `v2:features:pipeline:heartbeat` | string | Feature pipeline heartbeat | `v2_feature_snapshot_builder.py` |
| `v2:features:snapshots` | stream | Feature snapshots log | `v2_feature_snapshot_builder.py` |
| `v2:risk:decisions` | stream | Risk gateway decisions | V2 risk |
| `v2:signals:paper` | stream | V2 paper signals | Paper loop |
| `v2:market:prices:{SYMBOL}` | hash | V2 market prices (BTC/ETH/SOL) | V2 market ingestor |
| `v2:market:open_interest:{SYMBOL}` | hash | OI (BTC/ETH/SOL) | V2 market ingestor |
| `v2:market:funding:{SYMBOL}` | hash | Funding (BTC/ETH/SOL) | V2 market ingestor |
| `v2:market:ingestor:heartbeat` | string | Market ingestor HB | V2 market ingestor |
| `v2:market:ingestor:status` | hash | Market ingestor status | V2 market ingestor |
| `v2:market:liquidations:heartbeat` | string | Liquidation WS heartbeat | `v2_liquidation_wss_loop.py` |
| `v2:orchestrator:proposals` | stream | V2 orchestrator proposals | `v2_trade_management_paper_loop.py` |
| `v2:orchestrator:decisions` | stream | V2 orchestrator decisions | `v2_trade_management_paper_loop.py` |
| `v2:orchestrator:heartbeat` | string | Orchestrator heartbeat | Trade management |
| `v2:trainer:heartbeat` | string | V2 trainer heartbeat | V2 trainer bridge |
| `v2:trainer:status` | hash | V2 trainer status | V2 trainer bridge |
| `v2:live_canary:heartbeat` | string | Live canary heartbeat | `v2_live_canary` |
| `v2:live_canary:status` | hash | Live canary status | `v2_live_canary` |
| `v2:live_canary:intents` | stream | Canary trade intents | `v2_live_canary` |
| `v2:live_canary:ledger` | stream | Canary ledger | `v2_live_canary` |
| `v2:war_room:heartbeat` | string | War room heartbeat | War room process |
| `v2:legacy_log_observer:*` | hash/string | Legacy log intelligence observer | `v2_legacy_log_intelligence_observer.py` |
| `v2:altdata:candidate_publisher:status` | hash | Alt data candidate publisher status | `v2_altdata` |
| `v2:symbol_universe:altdata_candidates` | set | Candidate symbols for alt data | V2 universe |

---

### 3.15 Miscellaneous / State Keys

| Key | Type | Description | Source |
|-----|------|-------------|--------|
| `market:{SYMBOL}` | (various) | Per-symbol market state | Various |
| `market:state` | (missing) | Global market state | — |
| `instant:{SYMBOL}:spread` | string | Real-time bid-ask spread | `realtime_price_provider.py` |
| `binance:force` | (missing/empty) | Binance forced liquidation WS feed | `live_binance_liquidations.py` |
| `funding:last_ts` | (nil) | Last funding timestamp | `live_binance.py` |
| `config:symbols` | (missing) | Symbol config set | — |
| `latest:coinank:{CATEGORY}:{SYMBOL}:{EXCHANGE}:{TF}` | string | Latest CoinAnk endpoint fetch metadata | `live_coinank.py` |
| `latest:coinank_endpoint:{ENDPOINT}:{SYMBOL}:{TF}` | string | Latest endpoint fetch tracking | `live_coinank.py` |

---

## 4. SYMBOL UNIVERSE

**25 symbols** tracked across all legacy ingestors:

```
1000BONKUSDT  1000FLOKIUSDT  1000PEPEUSDT  1000SHIBUSDT
ALICEUSDT  ASTERUSDT  AUCTIONUSDT  AVNTUSDT
BANKUSDT  BARDUSDT  BTCUSDT  DOGEUSDT
ETHUSDT  FARTCOINUSDT  HIGHUSDT  LINKUSDT
LTCUSDT  PENGUUSDT  PIPPINUSDT  RAVEUSDT
RIVERUSDT  SOLUSDT  UNIUSDT  WIFUSDT  XRPUSDT
```

**KuCoin coverage:** 8 symbols (subset of above — primarily major pairs)
**V2-native coverage:** 3 symbols (BTCUSDT, ETHUSDT, SOLUSDT only)
**TokenMetrics coverage:** 10 symbols (tm:universe)

---

## 5. RUNNING V2 PROCESSES

These are the V2 rebuild processes currently running alongside legacy:

| PID | Process | Role |
|-----|---------|------|
| 31327 | `v2.backend.app.cli.v2_trade_management_paper_loop` | Paper trade loop |
| 73368 | `v2.backend.app.cli.v2_feature_snapshot_builder` | Feature snapshot builder |
| 1456707 | `v2.backend.app.cli.paper_online_runtime` | Paper online runtime |
| 2622359 | `v2.backend.app.cli.v2_production_payload_freshness_refresher` | JSON payload freshness refresher |
| 2624946 | `v2.backend.app.cli.v2_production_replacement_soak_observer` | Soak observer |
| 2677063 | `v2.backend.app.cli.v2_legacy_log_intelligence_observer` | Legacy log observer |
| 3017876 | `v2.backend.app.cli.v2_liquidation_wss_loop` | Liquidation WS loop |
| 3228969 | `v2.backend.app.cli.v2_production_equivalence_comparator` | Equivalence comparator |
| 3909105 | `v2.backend.app.cli.v2_position_history_persistent_tracker` | Position history tracker |
| 430848 | `claude_worklog/tools/v2_worker_porting_orchestrator.py` | Worker porting orchestrator (daemon) |
| 559209 | `claude_worklog/tools/codex_non_live_watchdog.py` | Non-live watchdog (daemon) |
| 1506056 | `claude_worklog/tools/codex_legacy_v2_realtime_decision_observatory.py` | Decision observatory (daemon) |
| 2620199 | `claude_worklog/tools/v2_production_replacement_runtime_guard.py` | Runtime guard (daemon) |
| 2620203 | `claude_worklog/tools/v2_legacy_v2_production_comparator.py` | Legacy/V2 comparator (daemon) |
| 2779663/2779876 | `claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py` | Log remediation (daemon) |

---

## 6. DATA FLOW DIAGRAM

```
External APIs
    │
    ├── Binance WS/REST ──────────────► live_binance.py ──────────────► ohlcv:list:binance:*
    │                                                                    latest:binance:*
    │                                                                    ingest:binance:last_ts
    │
    ├── Binance WS Liquidations ──────► live_binance_liquidations.py ─► binance:force (stream)
    │
    ├── CoinAPI WS ───────────────────► live_coinapi_wsds.py ──────────► microfeat:*
    │                                                                    msnap:coinapi_wsds:*
    │                                                                    normalized:ohlcv:*
    │
    ├── CoinAPI REST ─────────────────► live_coinapi_v1.py ────────────► ohlcv:list:coinapi:*
    │                                                                    latest:coinapi:*
    │                                                                    coinapi:symbolmap:*
    │
    ├── CoinAnk API ──────────────────► live_coinank.py ───────────────► coinank:* (200+ raw)
    │                                                                    features:coinank:* (2,403)
    │                                                                    features:global_coinank:* (19)
    │                                                                    cursor:coinank:* (2,150)
    │
    ├── KuCoin REST/WS ───────────────► live_kucoin.py ────────────────► kc:* (232 keys)
    │                                                                    features:kucoin:* (90)
    │
    ├── TokenMetrics API ─────────────► live_tokenmetrics.py ──────────► tm:* (22 keys)
    │
    └── CoinAPI + Binance ────────────► realtime_price_provider.py ────► price:*, orderbook:*, instant:*
                                                                         metrics:price_provider:*

        ohlcv:list:* + coinapi:* ──────► live_technical_analysis.py ───► ta:* (160 fields × 150 keys)
                                                                         regime:structural:* (175)
                                                                         latest:ta:*

        All above ─────────────────────► feature_pipeline.py ──────────► unified_features:* (562 fields × 250 keys)
                                                                         regime:* (25 per-symbol + global)
                                                                         regime_analysis:* (25)
                                                                         volatility:* (25)

        unified_features:* ────────────► hybrid_trainer.py ────────────► prediction:* (18 fields × ~150 keys)
                                                                         trainer:intent:* (22)
                                                                         rl:metrics:*
                                                                         rl:episodes:total

        prediction:* + trainer:intent:* ► orchestrator_worker.py ──────► signals:trading:primary (50K stream)
                                                                         signals:trading:asjad (stream)
                                                                         executed_signals (stream)
                                                                         wma:* (4 streams)
                                                                         signals:* (5 streams)

        signals:trading:primary ────────► V2 paper_online_runtime ─────► v2:paper:* (10+ keys)
                                                                         v2:risk:decisions
                                                                         v2:signals:paper
```

---

## 7. LEGACY INGESTOR FILE INDEX (`/home/wali/Desktop/AI BOT/ingest/`)

| File | Status | Role |
|------|--------|------|
| `live_binance.py` | ✅ Running (PID 46218) | Binance OHLCV + mark price + funding |
| `live_binance_liquidations.py` | ✅ Running (PID 46365) | Binance WS liquidation stream |
| `live_coinank.py` | ✅ Running (PID 46559) | Full CoinAnk API poller |
| `live_kucoin.py` | ✅ Running (PID 47157) | KuCoin data feed |
| `live_technical_analysis.py` | ✅ Running (PID 47348) | TA indicator computation |
| `realtime_price_provider.py` | ✅ Running (PID 47589) | Real-time price + orderbook |
| `live_coinapi_v1.py` | ✅ Running (PID 54905) | CoinAPI REST OHLCV |
| `live_coinapi_wsds.py` | ✅ Running (PID 55369) | CoinAPI WS microstructure |
| `live_tokenmetrics.py` | ⚠️ Not confirmed running | TokenMetrics API poller |
| `live_alphavantage_news.py` | ❌ Not running / stale | AlphaVantage news |
| `live_ccxt.py` | ❌ Not confirmed running | CCXT multi-exchange |
| `live_coinapi_rest.py` | ❌ Replaced by v1 | CoinAPI REST backup |
| `live_coinank_global_aggregator.py` | ❓ Unknown | CoinAnk global aggregator |
| `liquidation_bridge.py` | ❓ Unknown | Liq levels bridge |
| `base_ingestor.py` | Library | Base class |
| `alphavantage_client.py` | Library | AlphaVantage client |
| `alphavantage_normalizer.py` | Library | AlphaVantage normalizer |
| `tokenmetrics_normalizer.py` | Library | TM normalizer |
| `technical_analysis.py` | Library | TA computation |
| `ccxt_backfill.py` | Utility | CCXT historical backfill |
| `ccxt_historical.py` | Utility | CCXT historical |
| `cdd_enhanced_slow.py` | Utility | CDD slow feed |
| `cdd_historical.py` | Utility | CDD historical |
| `cdd_to_jsonl.py` | Utility | CDD export |
| `load_historical.py` | Utility | Historical loader |

---

## 8. KEY COUNTS SUMMARY BY NAMESPACE

| Namespace | Key Count | Type | Primary Source |
|-----------|-----------|------|----------------|
| `features:coinank_endpoint:*` | 3,054 | string | `live_coinank.py` |
| `features:coinank:*` | 2,403 | hash/string | `live_coinank.py` |
| `cursor:coinank:*` | 2,150 | string | `live_coinank.py` |
| `latest:coinank_endpoint:*` | 1,527 | string | `live_coinank.py` |
| `latest:coinank:*` | 1,039 | string | `live_coinank.py` |
| `regime:structural:*` | 175 | string/list | `live_technical_analysis.py` |
| `latest:binance:*` | 155 | string | `live_binance.py` |
| `latest:ta:*` | 150 | string | `live_technical_analysis.py` |
| `ta:*` | 150 | hash (160 fields) | `live_technical_analysis.py` |
| `kc:kline:*` | 90 | string | `live_kucoin.py` |
| `features:kucoin:*` | 90 | hash | `live_kucoin.py` |
| `unified_features:*` | 250 | hash (562 fields) | `feature_pipeline.py` |
| `prediction:*` | ~150 | hash (18 fields) | `hybrid_trainer.py` |
| `coinank:*` (raw) | ~200 | string | `live_coinank.py` |
| `raw:coinank:*` | 19 | string | `live_coinank.py` |
| `features:global_coinank:*` | 19 | string | `live_coinank.py` |
| `microfeat:*` | 25+ | hash (27 fields) | `live_coinapi_wsds.py` |
| `msnap:coinapi_wsds:*` | 25 | hash (46 fields) | `live_coinapi_wsds.py` |
| `price:*` / `price:realtime:*` / `price:last:*` | 75 | string | `realtime_price_provider.py` |
| `orderbook:*` | 100 | string | `realtime_price_provider.py` |
| `ohlcv:list:coinapi:*` | 25 | list (2000 items) | `live_coinapi_v1.py` |
| `normalized:ohlcv:*` | ~60 | hash | `live_coinapi_wsds.py` |
| `regime:*` | ~52 | string/hash | `feature_pipeline.py` |
| `regime_analysis:*` | 25 | hash | `feature_pipeline.py` |
| `volatility:*` | 25 | string | `feature_pipeline.py` |
| `trainer:intent:*` | 22 | hash | `hybrid_trainer.py` |
| `rl:*` | 10 | hash/string | `hybrid_trainer.py` |
| `tm:*` | 22 | hash/string/set | `live_tokenmetrics.py` |
| `heartbeat:*` | 34 | string | Multiple |
| `signals:*` | 8 | stream | `orchestrator_worker.py` |
| `wma:*` | 4 | stream | `orchestrator_worker.py` |
| `health:events` | 1 | stream (53,748) | Multiple |
| `pnl:decomp` | 1 | stream (634) | Trading loop |
| `v2:*` | ~50 | mixed | V2 processes |
| `kc:*` (non-kline) | 42 | string | `live_kucoin.py` |
| **TOTAL** | **~12,637** | | |

---

## 9. SHUTDOWN READINESS CHECKLIST

Before legacy can be shut down, V2 must produce **equivalent data** for every namespace below:

| # | Legacy Namespace | Required V2 Equivalent | V2 Status |
|---|-----------------|------------------------|-----------|
| 1 | `ohlcv:list:coinapi:{SYMBOL}:{TF}` | V2 market ingestor OHLCV | ❌ Only 3 symbols, stale |
| 2 | `ta:{SYMBOL}:{TF}` (160 fields) | V2 TA computation | ❌ Not ported |
| 3 | `unified_features:{SYMBOL}:{TF}` (562 fields) | V2 feature pipeline | ⚠️ 7/12 components |
| 4 | `prediction:{SYMBOL}:{TF}` (18 fields) | V2 RL core trainer | ❌ 0/6 components |
| 5 | `signals:trading:primary` (stream) | V2 orchestrator | ⚠️ Bridge only |
| 6 | `features:coinank:*` (2,403 keys) | V2 CoinAnk ingestor | ❌ Not built |
| 7 | `microfeat:{SYMBOL}:{TF}` (27 fields) | V2 WS microstructure | ❌ Not built |
| 8 | `kc:*` + `features:kucoin:*` | V2 KuCoin ingestor | ❌ Not built |
| 9 | `regime:{SYMBOL}` + `regime_analysis:{SYMBOL}` | V2 regime engine | ❌ Not ported |
| 10 | `toxicity:{SYMBOL}` | V2 toxicity engine | ❌ Not ported |
| 11 | `tm:*` (TokenMetrics) | V2 TokenMetrics client | ❌ Not built |
| 12 | `orderbook:*` / `price:*` real-time | V2 price provider | ⚠️ Partial (3 symbols) |
| 13 | `pnl:decomp` (stream) | V2 PnL tracker | ❌ Not built |
| 14 | `positions:live:*` | V2 live trade management | ❌ 0/10 components |
| 15 | `rl:metrics:*` (training metrics) | V2 trainer | ❌ 0/6 components |

**`approves_legacy_shutdown: false` on all V2 status workers — confirmed not ready.**
