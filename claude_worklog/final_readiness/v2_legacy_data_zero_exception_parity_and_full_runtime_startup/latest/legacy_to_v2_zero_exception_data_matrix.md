# Legacy -> V2 Zero-Exception Data Matrix

- Generated EST: 2026-05-31T01:10:00-0400
- Generated UTC: 2026-05-31T05:10:00Z
- Source: LEGACY_SYSTEM_FULL_AUDIT.md (633 lines, audit 2026-05-22)
- Row count: 36

Status legend: V2_VALIDATED_RUNNING / V2_RUNNING_PARTIAL / V2_ADAPTER_REQUIRED / V2_MISSING_IMPLEMENTATION / V2_CREDENTIAL_BLOCKED / V2_OPERATOR_REQUIRED / V2_NOT_REQUIRED_WITH_PROOF

| # | Legacy script | Legacy role | Legacy keys | V2 namespace | V2 writer | Status | Blocker | Next task |
|---|---|---|---|---|---|---|---|---|
| 1 | `ingest/live_binance.py` | Binance REST+WS OHLCV/mark-price/funding ingestor | ohlcv:list:binance:*, latest:binance:ohlcv:*, latest:binance:mark_price:*, ingest:binance:last_ts, heartbeat:IngestBinance | v2:market:prices:{symbol}, v2:market:funding:{symbol}, v2:market:open_interest:{symbol}, v2:market:ohlcv:binance:{symbol}:{tf} | ai-bot-v2-native-ingestors-live-loop.service | **V2_RUNNING_PARTIAL** | V2 native loop covers prices/funding/OI but NOT ohlcv bars; OHLCV list namespace unwired | Extend v2_native_ingestors loop to write candle history into v2:market:ohlcv:binance:{symbol}:{tf} (or add a dedicated v2_binance_ohlcv_worker timer). |
| 2 | `ingest/live_binance_liquidations.py` | Binance WS liquidation order stream | binance:force (stream), heartbeat:IngestLiquidations | v2:liquidations:events, v2:market:liquidations:latest:{symbol}, v2:market:liquidations:aggregate:{symbol} | ai-bot-v2-liquidation-wss-paper-shadow.service | **V2_VALIDATED_RUNNING** | Wiring complete this milestone (write_event_to_stream). Stream XLEN=0 because forceOrder is quiet (EVENT_DEPENDENT_NO_REAL_LIQUIDATION_EVENTS); not a defect. | Continue passive observation; once events flow the levels engine will populate v2:unified_features:* liquidation fields automatically. |
| 3 | `ingest/live_coinank.py` | CoinAnk API poller | coinank:*, features:coinank:*, features:coinank_endpoint:*, cursor:coinank:*, latest:coinank:*, latest:coinank_endpoint:*, features:global_c | v2:market:coinank:*, v2:features:coinank:*, v2:raw:coinank:liquidation_orders:global | v2_coinank_and_liquidation_bridge CLI (one-shot, NO systemd timer) | **V2_MISSING_IMPLEMENTATION** | CLI exists but not scheduled; global_aggregate values all 0.0; 3 missing_api_blockers; requires COINANK_API_KEY env | Add ai-bot-v2-coinank.{service,timer} 5-10min; source COINANK_API_KEY via live_credentials.env env-name; write v2:market:coinank:* and v2:raw:coinank:liquidation_orders:global. |
| 4 | `ingest/live_kucoin.py` | KuCoin REST/WS klines, OI, funding, orderbook | kc:kline:*, kc:orderbook20:*, kc:latest:*, kc:funding:*, kc:mark_index:*, kc:open_interest:*, features:kucoin:*, heartbeat:KuCoin | v2:market:kucoin:*, v2:features:kucoin:* | v2_kucoin_ingestor_worker CLI (descriptive-only stub) | **V2_MISSING_IMPLEMENTATION** | V2 worker is a stub: emits contract metadata, no public REST/WSS fetch path implemented. | Implement actual KuCoin public REST + WSS fetcher in v2_kucoin_ingestor_worker. Add ai-bot-v2-kucoin.{service,timer}. |
| 5 | `ingest/live_technical_analysis.py` | TA-Lib indicator computation (RSI, MACD, BB, ATR, OBV, VWAP, EMA/SMA, Stoch, CCI, ADX...) | ta:{SYMBOL}:{TF} (150 keys, 160 fields), latest:ta:* (150), regime:structural:* (175), heartbeat:OrderBook:* | v2:technical_analysis:{symbol}:{tf} | MISSING; native feature loop hardcodes rsi_14=50.0, macd=0.0 | **V2_MISSING_IMPLEMENTATION** | V2 has no dedicated TA worker writing v2:technical_analysis:*. Native feature loop produces stub with hardcoded TA constants. | Create v2_technical_analysis_worker that reads v2:market:ohlcv:* and writes 160-field hash per (symbol,tf) into v2:technical_analysis:{symbol}:{tf}. Replace hardcoded TA constants in v2_feature_pipeli |
| 6 | `ingest/realtime_price_provider.py` | Real-time price aggregator + orderbook snapshot | price:realtime:{SYMBOL}, price:last:{SYMBOL}, price:{SYMBOL}, orderbook:top:{SYMBOL}, orderbook:depth:{SYMBOL}, orderbook:bids:{SYMBOL}, ord | v2:market:prices:{symbol}, v2:market:orderbook:{symbol} | PARTIAL - v2_native_ingestors covers v2:market:prices but NOT v2:market:orderbook | **V2_RUNNING_PARTIAL** | Order-book (top/depth/bids/asks) and per-symbol spread not yet written to v2:market:orderbook:* | Extend v2_native_ingestors loop to consume Binance public depth and write top/depth/bids/asks/spread into v2:market:orderbook:{symbol}. |
| 7 | `feature_pipeline.py` | Unified feature builder (merges OHLCV + TA + CoinAnk + KuCoin + microstructure) | unified_features:{SYMBOL}:{TF} (250 keys x 562 fields), features:fast_lane (stream), features:slow_lane (stream), features:resampler, heartb | v2:features:latest:{symbol}:{tf}, v2:unified_features:{symbol}:{tf}, v2:features:fast_lane, v2:features:slow_lane, v2:features:resampler, v2 | ai-bot-v2-feature-pipeline-native-loop.service (writes 23-field stub) + ai-bot-v2-liquidation-levels-engine.service (wri | **V2_RUNNING_PARTIAL** | V2 writes 23 fields, not 562. fast_lane/slow_lane streams not implemented. Regime/volatility not implemented. | Port full feature_pipeline.py to V2: 562-field unified_features per (symbol,tf), fast/slow lane streams, regime detector, volatility scalar. |
| 8 | `rl/hybrid_trainer.py` | PPO+MASA RL trainer (GPU) | prediction:{SYMBOL}:{TF} (18 fields x ~150 keys), trainer:intent:{SYMBOL} (22), rl:metrics:{TF} (6), rl:metrics:loop_summary, rl:metrics:con | v2:prediction:{symbol}:{tf}, v2:trainer:intent:{symbol}, v2:trainer:rl_metrics:*, v2:trainer:heartbeat, v2:trainer:status | ai-bot-v2-trainer-bridge.service (PARITY_BRIDGE only, NOT TRAINING) | **V2_OPERATOR_REQUIRED** | V2 has NO native trainer; wrapper is v2_paper_readonly_momentum_wrapper_v1 with accepted_as_legacy_hybrid_prediction=false. CLAUDE.md forbids restarting the legacy trainer. | Operator decision: accept copied legacy hybrid_trainer to run inside V2 paper-mode under V2 namespace, OR build new V2-native trainer consuming v2:unified_features:*. Both require operator gate. |
| 9 | `trading/opportunity_tracker.py` | Opportunity scanner + signal overlay | opportunity:latest, signals:overlay:intents, signals:proactive:alerts | v2:strategy:opportunity_latest, v2:strategy:overlay_intents, v2:strategy:proactive_alerts | MISSING | **V2_MISSING_IMPLEMENTATION** | No V2 opportunity tracker. | Port opportunity_tracker.py logic to V2 paper-only worker writing v2:strategy:*. |
| 10 | `rl/orchestrator_worker.py` | Signal orchestrator - merges predictions into trading signals | signals:trading:primary (50K stream), signals:trading:asjad (200 stream), signals:ensemble:diagnostic (10K stream), signals:debug, wma:propo | v2:orchestrator:proposals, v2:orchestrator:decisions, v2:orchestrator:wma:*, v2:orchestrator:signals:*, v2:orchestrator:heartbeat, v2:orches | ai-bot-v2-orchestrator-arbitration-loop.service (shell only) | **V2_RUNNING_PARTIAL** | Arbitration only - no port of signal merge, WMA proposal pipeline, drift_alerts publishing. | Port orchestrator_worker.py merge/WMA/drift logic into V2 paper-only worker. |
| 11 | `ingest/live_coinapi_v1.py` | CoinAPI REST OHLCV backfill + live klines | ohlcv:list:coinapi:{SYMBOL}:{TF}, latest:coinapi:ohlcv:*, coinapi:symbolmap:* (25), metrics:coinapi:* (21) | v2:market:coinapi:v1:*, v2:market:ohlcv:coinapi:{symbol}:{tf} | MISSING | **V2_CREDENTIAL_BLOCKED** | No V2 CLI ported. Requires COINAPI_API_KEY (free tier strict daily quota). | Create v2_coinapi_v1_ingestor CLI sourcing COINAPI_API_KEY via live_credentials.env env-name. Add ai-bot-v2-coinapi-v1.{service,timer}. |
| 12 | `ingest/live_coinapi_wsds.py` | CoinAPI WSDS WebSocket - microstructure | microfeat:{SYMBOL}:{TF} (27 fields), msnap:coinapi_wsds:{SYMBOL} (46 fields), normalized:ohlcv:{SYMBOL}:{TF} | v2:market:microstructure:{symbol}:{tf}, v2:market:microstructure_snapshot:coinapi_wsds:{symbol}, v2:market:ohlcv:normalized:{symbol}:{tf} | MISSING | **V2_CREDENTIAL_BLOCKED** | WSDS = paid CoinAPI streaming. Requires COINAPI_API_KEY + operator approval (live_coinapi_wsds is OPERATOR_DECISION_REQUIRED in native_ingestors registry). | Operator decision on paid tier; if approved, build v2_coinapi_wsds CLI writing v2:market:microstructure:*. |
| 13 | `monitoring/oom_monitor.py` | OOM watchdog (monitor only) | - | v2:health:oom_monitor | MISSING | **V2_NOT_REQUIRED_WITH_PROOF** | Read-only OS watchdog; systemd OOMScore/Restart= already cover this. | (none) |
| 14 | `scripts/monitor_trainer_prices.py` | Monitor script (read-only) | - | (observability only) | ai-bot-v2-trainer-bridge.service produces equivalent payload | **V2_NOT_REQUIRED_WITH_PROOF** | Superseded by v2_trainer_bridge_status.json + paper_online_runtime payloads. | (none) |
| 15 | `scripts/monitor_trainer_predictions.py` | Monitor script (read-only) | - | (observability only) | ai-bot-v2-trainer-bridge.service | **V2_NOT_REQUIRED_WITH_PROOF** | Equivalent visibility in v2_trainer_bridge_status.json. | (none) |
| 16 | `monitor_portfolio_primary.py` | Portfolio monitor (read-only, Telegram alerts) | - | v2:portfolio:state (when ported) | MISSING | **V2_MISSING_IMPLEMENTATION** | No V2 portfolio monitor; Telegram alerts operator-gated. | Port read-only portfolio observer to V2 (paper-only, no Telegram); write v2:portfolio:state. |
| 17 | `ingest/live_tokenmetrics.py` | TokenMetrics API | tm:last_run:* (18), tm:health:*, tm:token_map, tm:tooltips, tm:universe, tokenmetrics:universe, heartbeat:writer:tokenmetrics | v2:altdata:tokenmetrics:* | MISSING | **V2_OPERATOR_REQUIRED** | Deferred until operator re-enable per spec. Requires TOKENMETRICS_API_KEY. | Operator decision: re-enable or retire. If re-enabled, build v2_tokenmetrics_ingestor. |
| 18 | `ingest/live_coinapi_rest.py` | CoinAPI REST fallback (backup to v1) | ohlcv:list:coinapi:*, latest:coinapi:* | (rolled into v2_coinapi_v1_ingestor) | MISSING | **V2_NOT_REQUIRED_WITH_PROOF** | Audit marks REPLACED BY v1. | (none; redundant with v2_coinapi_v1) |
| 19 | `ingest/live_ccxt.py` | CCXT multi-exchange OHLCV | Various exchange OHLCV keys | v2:market:ccxt:{exchange}:{symbol}:{tf} | MISSING | **V2_OPERATOR_REQUIRED** | Operator-required (rate limits / per-exchange keys). | Operator decision on exchanges + symbols. If approved, build v2_ccxt_ingestor. |
| 20 | `ingest/live_coinank_global_aggregator.py` | CoinAnk global metrics aggregator | features:global_coinank:*, coinank:* global keys | v2:market:coinank:global:* | PARTIAL via v2_coinank_and_liquidation_bridge.global_aggregate_result (all 0.0) | **V2_RUNNING_PARTIAL** | Bridge runs but global aggregate fields all 0.0 (no real API data). | Same as live_coinank - fix API key + scheduling; aggregator already inside bridge. |
| 21 | `ingest/liquidation_bridge.py` | Liquidation level engine bridge | cursor:liq_bridge:* | v2:cursor:liq_bridge:*, v2:liquidations:events | ai-bot-v2-liquidation-bridge.service (LABELLED_FALLBACK after WSS became canonical producer) | **V2_VALIDATED_RUNNING** | (none - by-design fallback) | Optional: wire CoinAnk REST adapter to populate v2:raw:coinank:liquidation_orders:global for secondary input. |
| 22 | `ingest/live_alphavantage_news.py` | AlphaVantage news sentiment | Alt-data namespace | v2:altdata:alphavantage:news:* | MISSING | **V2_CREDENTIAL_BLOCKED** | Requires ALPHAVANTAGE_API_KEY. Audit marks legacy as stale/not active already. | Operator decision on AlphaVantage; if approved, port to v2_alphavantage_news_ingestor. |
| 23 | `ingest/technical_analysis.py` | TA computation library (imported, not standalone) | - | - | (library) | **V2_ADAPTER_REQUIRED** | Library exists in copied tree but no V2 worker imports it. | Import in future v2_technical_analysis_worker. |
| 24 | `ingest/base_ingestor.py` | Base class | - | - | (library only) | **V2_NOT_REQUIRED_WITH_PROOF** | Library only. | (none) |
| 25 | `ingest/alphavantage_client.py` | AlphaVantage client library | - | - | (library) | **V2_ADAPTER_REQUIRED** | Library only; needed only if AlphaVantage worker is built. | (see AlphaVantage news row) |
| 26 | `ingest/alphavantage_normalizer.py` | AlphaVantage normalizer library | - | - | (library) | **V2_ADAPTER_REQUIRED** | Library only. | (see AlphaVantage news row) |
| 27 | `ingest/tokenmetrics_normalizer.py` | TokenMetrics normalizer library | - | - | (library) | **V2_ADAPTER_REQUIRED** | Library only. | (see TokenMetrics row) |
| 28 | `ingest/ccxt_backfill.py` | CCXT historical backfill utility | - | v2:market:ccxt:backfill:* | MISSING | **V2_OPERATOR_REQUIRED** | Same as ccxt - operator approval required. | (see ccxt row) |
| 29 | `ingest/ccxt_historical.py` | CCXT historical utility | - | v2:market:ccxt:historical:* | MISSING | **V2_OPERATOR_REQUIRED** | Same as ccxt. | (see ccxt row) |
| 30 | `ingest/load_historical.py` | Historical loader utility | - | - | MISSING | **V2_NOT_REQUIRED_WITH_PROOF** | Not on live data path. | (none) |
| 31 | `ingest/cdd_enhanced_slow.py` | CDD slow feed utility | - | - | MISSING | **V2_NOT_REQUIRED_WITH_PROOF** | CDD utility - not on critical path. | (none) |
| 32 | `ingest/cdd_historical.py` | CDD historical utility | - | - | MISSING | **V2_NOT_REQUIRED_WITH_PROOF** | Utility only. | (none) |
| 33 | `ingest/cdd_to_jsonl.py` | CDD export utility | - | - | MISSING | **V2_NOT_REQUIRED_WITH_PROOF** | Export utility only. | (none) |
| 34 | `trading/trader.py + trader-asjad.py` | Portfolio & position tracking (live trading) | positions:live:accounts (set), pnl:decomp (stream, 634) | v2:paper:positions, v2:paper:pnl, v2:portfolio:state | ai-bot-v2-paper-online-runtime.service (paper-only) | **V2_RUNNING_PARTIAL** | Paper PnL exists; portfolio:state and profit_bank not yet ported; live trading deliberately blocked. | Port portfolio:state + profit_bank:state into v2:portfolio:* (paper-only). |
| 35 | `(misc/state keys)` | Per-symbol market state + global config | market:{SYMBOL}, market:state, binance:force, funding:last_ts, config:symbols | v2:market:*, v2:symbol_universe:* | Various V2 ingestors | **V2_RUNNING_PARTIAL** | config:symbols not migrated; binance:force replaced by v2:liquidations:events; market:state missing. | Write config:symbols -> v2:symbol_universe:contract (symbol-universe publisher already does this). Add v2:market:state publisher. |
| 36 | `rl/orchestrator_worker.py (promotion sub-system)` | Signal promotion state | promotion:status (hash, 8 fields) | v2:orchestrator:promotion_status | MISSING | **V2_MISSING_IMPLEMENTATION** | No V2 promotion state writer. | Port promotion-state writer with orchestrator pipeline. |

## Status aggregate

- V2_VALIDATED_RUNNING: 2
- V2_RUNNING_PARTIAL: 7
- V2_ADAPTER_REQUIRED: 4
- V2_MISSING_IMPLEMENTATION: 6
- V2_CREDENTIAL_BLOCKED: 3
- V2_OPERATOR_REQUIRED: 5
- V2_NOT_REQUIRED_WITH_PROOF: 9

## Audit-canonical counts vs current V2 keyspace

| Family | Count |
|---|---:|
| `v2:market:prices:*` | 27 |
| `v2:market:funding:*` | 25 |
| `v2:market:open_interest:*` | 25 |
| `v2:market:liquidations:*` | 1 |
| `v2:market:liquidations:latest:*` | 0 |
| `v2:market:liquidations:aggregate:*` | 0 |
| `v2:market:liquidation_levels:*` | 0 |
| `v2:market:ohlcv:*` | 37 |
| `v2:market:orderbook:*` | 12 |
| `v2:market:coinank:*` | 0 |
| `v2:market:kucoin:*` | 0 |
| `v2:market:coinapi:*` | 0 |
| `v2:market:microstructure:*` | 0 |
| `v2:features:*` | 64 |
| `v2:unified_features:*` | 170 |
| `v2:technical_analysis:*` | 25 |
| `v2:altdata:*` | 1 |
| `v2:altdata:lunarcrush:*` | 0 |
| `v2:altdata:nansen:*` | 0 |
| `v2:altdata:arkham:*` | 0 |
| `v2:altdata:tokenmetrics:*` | 0 |
| `v2:prediction:*` | 52 |
| `v2:trainer:*` | 4 |
| `v2:orchestrator:*` | 3 |
| `v2:risk:*` | 1 |
| `v2:paper:*` | 89 |
| `v2:position_history:*` | 0 |
| `v2:portfolio:*` | 0 |
| `v2:health:*` | 0 |
| `v2:liquidations:events_XLEN` | 0 |

## Legacy namespaces still present in Redis (static preserved)

| Family | Count |
|---|---:|
| `orchestrator:*` | 0 |
| `live_orders:*` | 0 |
| `exchange:order:*` | 0 |
| `ohlcv:list:*` | 25 |
| `latest:binance:*` | 89 |
| `latest:coinank:*` | 972 |
| `latest:coinank_endpoint:*` | 0 |
| `latest:ta:*` | 0 |
| `latest:coinapi:*` | 0 |
| `ta:*` | 0 |
| `unified_features:*` | 0 |
| `prediction:*` | 1 |
| `signals:*` | 7 |
| `wma:*` | 4 |
| `features:coinank:*` | 961 |
| `features:coinank_endpoint:*` | 0 |
| `features:kucoin:*` | 0 |
| `features:global_coinank:*` | 18 |
| `cursor:coinank:*` | 2101 |
| `coinank:*` | 13 |
| `raw:coinank:*` | 17 |
| `microfeat:*` | 0 |
| `msnap:coinapi_wsds:*` | 0 |
| `normalized:ohlcv:*` | 0 |
| `kc:*` | 150 |
| `tm:*` | 7 |
| `tokenmetrics:*` | 0 |
| `regime:*` | 175 |
| `regime_analysis:*` | 0 |
| `volatility:*` | 11 |
| `trainer:intent:*` | 0 |
| `rl:*` | 3 |
| `price:*` | 31 |
| `orderbook:*` | 67 |
| `instant:*` | 5 |
| `heartbeat:*` | 28 |
| `health:events_XLEN` | 0 |
| `pnl:decomp_XLEN` | 0 |
| `binance:force_XLEN` | 0 |
| `executed_signals_XLEN` | 1552 |
