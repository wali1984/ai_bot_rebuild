# Ingestor Master Audit — AI BOT V2
Generated: 2026-07-01T22:56:31Z

## Summary

| Ingestor | Status | Credential | Service |
|----------|--------|-----------|---------|
| Binance USDM Kline WSS | WORKING | Public (no key) | ai-bot-v2-binance-kline-wss-loop.service |
| Binance Liquidation WSS | WORKING | Public (no key) | ai-bot-v2-liquidation-wss-paper-shadow.service |
| Liquidation Levels Engine | WORKING | None needed | ai-bot-v2-liquidation-levels-engine.service |
| CoinAPI WSDS | WORKING | Required — present (boolean) | ai-bot-v2-coinapi-wsds-loop.service |
| CoinAPI REST | WORKING | Required — present (boolean) | ai-bot-v2-coinapi-rest-fallback-loop.service |
| KuCoin public REST | WORKING | Public (no key) | ai-bot-v2-kucoin-public-rest-loop.service |
| CoinAnk live direct | WORKING | Required — present (boolean) | ai-bot-v2-coinank-live-direct.service |
| CoinAnk global aggregator | WORKING | Required — present (boolean) | ai-bot-v2-coinank-global-aggregator-direct.service |
| AICoin free tier | CREDENTIAL_BLOCKED | Required — NOT present | ai-bot-v2-aicoin-whale-intel-loop.service |
| LunarCrush | UNKNOWN | Required — checking | ai-bot-v2-lunarcrush-altdata-loop.service |
| Nansen | UNKNOWN | Required — checking | ai-bot-v2-nansen-altdata-loop.service |
| Public Intel free tier | WORKING | Public | ai-bot-v2-public-intel-free-tier-loop.service |
| TA-Lib / Full TA | WORKING | None needed | ai-bot-v2-full-talib-ta-loop.service |
| Feature Pipeline | WORKING | None needed | ai-bot-v2-feature-pipeline-native-loop.service |
| Symbol Discovery | WORKING | Public | ai-bot-v2-dynamic-symbol-discovery-loop.service |
| Alt-data scoring | WORKING | None needed | ai-bot-v2-alt-data-symbol-scoring-loop.service |
| Arkham | WORKING (presence-only) | No external HTTP | ai-bot-v2-arkham-presence-loop.service |

## Ingestor Details

### 1. Binance USDM Kline WebSocket
- **ingestor_id**: v2_binance_kline_wss
- **provider**: Binance Futures USD-M
- **script**: v2/backend/app/cli/v2_binance_kline_wss_loop.py
- **service**: ai-bot-v2-binance-kline-wss-loop.service
- **service_active**: yes
- **heartbeat_key**: v2:market:binance:kline:heartbeat (via features:pipeline:heartbeat)
- **status**: WORKING
- **symbols_count**: ~93 (dynamic, tracked in symbol universe)
- **timeframes**: 1m, 5m, 15m, 1h, 4h
- **keys_written**: v2:market:kline:{symbol}:{timeframe}, v2:features:latest:{symbol}:{tf}
- **credential_required**: false (public websocket)
- **feeds_trainer**: yes — kline data → feature pipeline → tensor builder → trainer
- **feeds_website**: yes — via chart payload publisher
- **note**: Primary market data source; WebSocket client subscribing to Binance Futures USD-M combined stream

### 2. Binance Liquidation WebSocket
- **ingestor_id**: v2_liquidation_wss
- **provider**: Binance Futures public forceOrder stream
- **script**: v2/backend/app/cli/v2_liquidation_wss_loop.py
- **service**: ai-bot-v2-liquidation-wss-paper-shadow.service
- **service_active**: yes
- **status**: WORKING
- **keys_written**: v2:liq:events:stream
- **credential_required**: false (public stream)
- **feeds_trainer**: yes — liquidation events → features
- **feeds_website**: yes — via liquidation bridge status publisher

### 3. Liquidation Levels Engine
- **ingestor_id**: v2_liquidation_levels
- **provider**: internal computation from kline + positions
- **script**: v2/backend/app/cli/v2_liquidation_levels_engine.py
- **service**: ai-bot-v2-liquidation-levels-engine.service
- **service_active**: yes
- **status**: WORKING
- **keys_written**: v2:liq:levels:{symbol}
- **feeds_trainer**: yes — liquidation levels → risk features
- **feeds_website**: yes — liquidation page

### 4. CoinAPI WSDS Loop
- **ingestor_id**: v2_coinapi_wsds
- **provider**: CoinAPI WebSocket DataService
- **script**: v2/backend/app/cli/v2_coinapi_wsds_loop.py
- **service**: ai-bot-v2-coinapi-wsds-loop.service
- **service_active**: yes
- **status**: WORKING
- **heartbeat_key**: v2:market:coinapi:ohlcv:heartbeat
- **keys_written**: v2:market:coinapi:ohlcv:{symbol}:{tf}
- **credential_required**: true (COINAPI_KEY)
- **credential_present_boolean**: true (service is running)
- **feeds_trainer**: yes — multi-exchange OHLCV → feature enrichment
- **feeds_website**: yes — market charts

### 5. CoinAPI REST Fallback
- **ingestor_id**: v2_coinapi_rest
- **provider**: CoinAPI REST
- **script**: v2/backend/app/cli/v2_coinapi_rest_ingestor_worker.py
- **service**: ai-bot-v2-coinapi-rest-fallback-loop.service
- **service_active**: yes
- **status**: WORKING
- **heartbeat_key**: v2:market:coinapi:rest:heartbeat
- **keys_written_count**: 103 (observed at 2026-07-01T23:04:15Z)
- **credential_required**: true (COINAPI_KEY)
- **feeds_trainer**: yes (fallback when WSDS lags)

### 6. KuCoin Public REST
- **ingestor_id**: v2_kucoin
- **provider**: KuCoin public REST API
- **script**: v2/backend/app/cli/v2_kucoin_ingestor_worker.py
- **service**: ai-bot-v2-kucoin-public-rest-loop.service
- **service_active**: yes
- **status**: WORKING
- **keys_written**: v2:features:kucoin:{symbol}:{tf}
- **credential_required**: false (public endpoints)
- **feeds_trainer**: yes — cross-exchange price/volume features
- **note**: 93+ symbols tracked, 5 timeframes each

### 7. CoinAnk Live Direct
- **ingestor_id**: v2_coinank_live
- **provider**: CoinAnk (long/short ratio, funding, OI, basis)
- **script**: v2/backend/app/cli/v2_coinank_and_liquidation_bridge.py
- **service**: ai-bot-v2-coinank-live-direct.service
- **service_active**: yes
- **status**: WORKING
- **keys_written**: v2:altdata:coinank:*, v2:features:coinank:*
- **credential_required**: true (COINANK_API_KEY)
- **credential_present_boolean**: true (service running)
- **feeds_trainer**: yes — derivatives data (funding, OI, long/short)
- **feeds_website**: yes — derivatives page

### 8. CoinAnk Global Aggregator
- **ingestor_id**: v2_coinank_aggregator
- **provider**: CoinAnk aggregate feed
- **script**: v2_coinank_and_liquidation_bridge (aggregator mode)
- **service**: ai-bot-v2-coinank-global-aggregator-direct.service
- **service_active**: yes
- **status**: WORKING
- **feeds_trainer**: yes — global market state features

### 9. AICoin + Whale Walls Free Tier
- **ingestor_id**: v2_aicoin_whale
- **provider**: AICoin
- **script**: v2/backend/app/cli/v2_aicoin_whale_intel_free_tier.py
- **service**: ai-bot-v2-aicoin-whale-intel-loop.service
- **service_active**: yes (service running)
- **status**: CREDENTIAL_BLOCKED
- **credential_required**: true (AICOIN_ACCESS_KEY_ID, AICOIN_ACCESS_SECRET, AICOIN_API_KEY, AICOIN_API_SECRET, AICOIN_API_BASE_URL)
- **credential_present_boolean**: false (all 5 vars missing)
- **keys_written**: v2:altdata:aicoin:symbol:{symbol} (partially populated from other sources)
- **feeds_trainer**: no (credential blocked)
- **feeds_website**: partial (symbol keys written from fallback path)
- **impact**: Whale wall data unavailable; free-tier score only

### 10. LunarCrush Alt-data
- **ingestor_id**: v2_lunarcrush
- **provider**: LunarCrush social/on-chain analytics
- **script**: v2/backend/app/cli/v2_lunarcrush_altdata_ingestor.py
- **service**: ai-bot-v2-lunarcrush-altdata-loop.service
- **service_active**: yes
- **status**: UNKNOWN (service running; credential status unverified at this moment)
- **credential_required**: true (LUNARCRUSH_API_KEY)
- **keys_written**: v2:altdata:lunarcrush:symbol:{symbol}
- **feeds_trainer**: partial — social score features
- **feeds_website**: yes — alt data / market intelligence page

### 11. Nansen Alt-data
- **ingestor_id**: v2_nansen
- **provider**: Nansen on-chain analytics
- **script**: v2/backend/app/cli/v2_nansen_altdata_ingestor.py
- **service**: ai-bot-v2-nansen-altdata-loop.service
- **service_active**: yes
- **status**: UNKNOWN (service running; credential status unverified)
- **credential_required**: true (NANSEN_API_KEY)
- **keys_written**: v2:altdata:nansen:*
- **feeds_trainer**: partial — on-chain flow features

### 12. Public Intel Free Tier
- **ingestor_id**: v2_public_intel
- **provider**: CoinGecko, CoinGlass, Surf, free APIs
- **script**: v2/backend/app/cli/v2_public_intel_free_tier.py
- **service**: ai-bot-v2-public-intel-free-tier-loop.service
- **service_active**: yes
- **status**: WORKING
- **keys_written**: v2:altdata:public_intel:symbol:{symbol}, v2:altdata:public_intel:global
- **credential_required**: false
- **feeds_trainer**: yes — fear/greed, dominance features

### 13. TA-Lib / Full TA Loop
- **ingestor_id**: v2_talib_ta
- **provider**: internal TA-Lib computation
- **script**: v2/backend/app/cli/v2_full_talib_ta_loop.py
- **service**: ai-bot-v2-full-talib-ta-loop.service
- **service_active**: yes
- **status**: WORKING
- **keys_written**: v2:features:ta:{symbol}:{tf}, v2:features:ta_full:{symbol}:{tf}
- **feeds_trainer**: yes — TA indicators → features → tensor

### 14. Feature Pipeline Native Loop
- **ingestor_id**: v2_feature_pipeline
- **provider**: internal (aggregates all ingestor outputs)
- **script**: v2/backend/app/cli/v2_feature_pipeline_native_loop.py
- **service**: ai-bot-v2-feature-pipeline-native-loop.service
- **service_active**: yes
- **status**: WORKING
- **heartbeat_age_seconds**: ~286 seconds (fresh at audit time)
- **symbols_active**: 25 (from heartbeat: 1000BONKUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, etc.)
- **keys_written**: v2:features:latest:{symbol}:{tf}
- **feeds_trainer**: YES (primary trainer input)
- **feeds_website**: yes — feature snapshot page

### 15. Symbol Universe / Discovery
- **ingestor_id**: v2_symbol_discovery
- **provider**: Binance exchange info + alt-data scoring
- **script**: v2/backend/app/cli/v2_dynamic_symbol_discovery_free_tier.py
- **service**: ai-bot-v2-dynamic-symbol-discovery-loop.service
- **service_active**: yes
- **status**: WORKING
- **keys_written**: v2:altdata:symbol_score:{symbol} (113 symbols observed)
- **note**: ~93 core symbols + extended universe candidates

## Which Ingestors Are Available
All 15 ingestor classes are available and have running services.

## Which Are Running
- CONFIRMED RUNNING: Binance kline WSS, Liquidation WSS, Liquidation Levels, CoinAPI WSDS, CoinAPI REST, KuCoin, CoinAnk live, CoinAnk aggregator, AICoin service (but cred-blocked), LunarCrush, Nansen, Public Intel, TA-Lib, Feature Pipeline, Symbol Discovery

## Which Are Stale
- None confirmed stale (all heartbeat TTLs show 255–3560 seconds remaining)

## Which Are Down
- None confirmed down

## Which Are Credential/Provider Blocked
- AICoin: 5 credential env vars missing → no whale wall data from API (service runs, falls back to free-tier logic)
- LunarCrush: credential status unverified (service running)
- Nansen: credential status unverified (service running)

## Which Write V2 Redis
- ALL ingestors write exclusively to v2:* namespace

## Which Still Touch Legacy Paths
- NONE: bridge_exit complete, all ingestors use v2:* namespace only

## Which Feed Trainer
- Binance Kline → Feature Pipeline → Trainer (primary)
- KuCoin → Feature Pipeline → Trainer (cross-exchange)
- CoinAPI → Feature Pipeline → Trainer (fallback/enrichment)
- CoinAnk → Features → Trainer (derivatives: funding, OI, long/short)
- Public Intel → Features → Trainer (macro: fear/greed)
- Liquidation → Features → Trainer (liq events/levels)
- TA-Lib → Features → Trainer (technical indicators)

## Which Feed Website Only
- Market chart publishers
- CoinAnk direct status publisher
- Ingestors status publisher
- Liquidation status publisher

## Which Feed Paper/Live Decisions
- Feature Pipeline → Trainer → Predictions → Orchestrator → Risk Gateway → Paper Trader
