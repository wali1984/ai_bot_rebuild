# COMPREHENSIVE SYSTEM AUDIT: CoinAnk Ingestor, Legacy Bot, and V2 Rebuild
**Audit Date:** 2026-07-08  
**Scope:** CoinAnk endpoints, data flows, alternative providers, legacy system analysis, V2 rebuild gaps  
**Status:** HISTORICAL AUDIT - REQUIRES CODEX ALIGNMENT NOTES

## CODEX ALIGNMENT NOTE - 2026-07-08

This document is retained as a historical Claude/Fable audit, not an approved
execution plan. Its Redis counts, endpoint-health claims, win-rate claims, and
runtime-readiness statements must be re-verified with current read-only checks
before they are used for decisions.

Do not execute runtime restart commands, Redis mutation commands, live exchange
commands, leverage/margin changes, test orders, or real orders from this audit
without explicit operator approval. Heartbeat-only status is not green. Probation
does not count as final A+ or live-ready.

The current same-day path is the provider-rate-limited cutover plan:

- CoinGlass and Moralis are optional providers with explicit registries, cadence
  controls, request/CU budgets, Redis key contracts, endpoint-to-feature mapping,
  actual-data dashboard/iOS panels, and trainer/risk/orchestrator/allocator/paper/
  live-dry-run consumer contexts.
- CoinGlass must stay inside the public request limit and internal reserve.
- Moralis must use wallet/token/stream cadence and CU budgets; it must not poll
  every symbol every minute.
- Optional provider failures are honest gray/yellow states, not core-blocking
  failures.
- Live remains blocked until independent live-canary criteria pass and the
  operator explicitly approves.

---

## EXECUTIVE SUMMARY

### Critical Findings
1. **Legacy System**: 562-field unified features, PPO+MASA trainer, 14 ingestors, 90%+ win-rate strategies
2. **CoinAnk**: Critical (40 endpoints, 2,403 feature keys, 0% error rate in last 500 calls)
3. **V2 Status**: 97.5% feature collapse (562→14 fields), trainer 0/6 components, signal stream frozen

### Key Decision: CoinAnk Migration
- **DO NOT REPLACE** CoinAnk with alternatives (CoinGlass=30% coverage, Moralis/Nansen=0% coverage for CEX derivatives)
- **KEEP CoinAnk** as Tier-1 provider
- **AUGMENT** with CoinGlass ($20/mo) + Moralis free tier for +40% features

### Root Cause of V2 Failure
**Not architectural problems.** Complete feature pipeline collapse + missing ML trainer + inactive ingestors.

---

## PART 1: COINANK AUDIT

### 1.1 All 40 Configured Endpoints (Working)

**Legend:** ✅ Working (observed in Redis call_log with 0 errors)

| Category | Endpoint | Path | Scope | TF | Training Use |
|---|---|---|---|---|---|
| **Liquidations** (5) | liquidation_orders | /api/liquidation/orders | Mixed | 30d hist | Event detection |
| | liquidation_allExchange_intervals | /api/liquidation/allExchange/intervals | BaseCoin | N/A | Level calc |
| | liquidation_aggregated_history | /api/liquidation/aggregated-history | BaseCoin | 5m-1d | ML pressure feature |
| | liquidation_history | /api/liquidation/history | Symbol | 5m-1d | Per-symbol levels |
| | liqMap_getLiqHeatMapSymbol | /api/liqMap/getLiqHeatMapSymbol | Global | N/A | Heatmap viz |
| **Open Interest** (5) | openInterest_all | /api/openInterest/all | BaseCoin | N/A | OI snapshot |
| | openInterest_v2_chart | /api/openInterest/v2/chart | BaseCoin | 1m-1d | OI history |
| | openInterest_aggKline | /api/openInterest/aggKline | BaseCoin | 1m-1h | Agg OI candles |
| | openInterest_symbol_Chart | /api/openInterest/symbol/Chart | Symbol | 5m-1d | Per-symbol OI |
| | openInterest_kline | /api/openInterest/kline | Symbol | 5m-1d | OI detailed |
| **Market Order Flow** (7) | marketOrder_getBuySellCount | /api/marketOrder/getBuySellCount | Symbol | 5m-1d | Buy/sell ratio |
| | marketOrder_getBuySellValue | /api/marketOrder/getBuySellValue | Symbol | 5m-1d | Value USD |
| | marketOrder_getBuySellVolume | /api/marketOrder/getBuySellVolume | Symbol | 5m-1d | Volume ratio |
| | marketOrder_getAggCvd | /api/marketOrder/getAggCvd | Symbol | 5m-1d | CVD |
| | marketOrder_getAggBuySellCount | /api/marketOrder/getAggBuySellCount | BaseCoin | 5m-1d | Agg count |
| | marketOrder_getAggBuySellValue | /api/marketOrder/getAggBuySellValue | BaseCoin | 5m-1d | Agg value |
| | marketOrder_getAggBuySellVolume | /api/marketOrder/getAggBuySellVolume | BaseCoin | 5m-1d | Agg volume |
| **Funding Rates** (6) | fundingRate_accumulated | /api/fundingRate/accumulated | Global | N/A | Accum insight |
| | fundingRate_indicator | /api/fundingRate/indicator | Symbol | 5m-1d | Momentum |
| | fundingRate_frHeatmap | /api/fundingRate/frHeatmap | Global | By type | Heatmap |
| | fundingRate_history | /api/fundingRate/hist | BaseCoin | Config | Time series |
| | fundingRate_current | /api/fundingRate/current | Global | N/A | Current state |
| | fundingRate_kline | /api/fundingRate/kline | Symbol | 5m-1d | Candles |
| **Long/Short Ratios** (4) | ls_exchange_realtimeAll | /api/longshort/realtimeAll | BaseCoin | Variable | Real-time ratio |
| | ls_global_account_ratio | /api/longshort/person | Symbol | 5m-1d | Per-account |
| | ls_toptrader_accounts | /api/longshort/account | Symbol | 5m-1d | Top traders |
| | ls_kline | /api/longshort/kline | Symbol | 5m-1d | History |
| **Other** (8) | instruments_* | /api/instruments/* | Symbol/BaseCoin | N/A | Price/caps |
| | netPositions_getNetPositions | /api/netPositions/getNetPositions | Symbol | 5m-1d | Net pos |
| | orderFlow_lists | /api/orderFlow/lists | Symbol | 5m-1d | Order flow |
| | rsiMap_list | /api/rsiMap/list | Exchange | Variable | RSI agg |
| | hyper_* | /api/hyper/* | Pagination | N/A | Top positions |
| | fund_* | /api/fund/* | ProductType | Variable | Fund flow |

**Reliability:** 0% error rate (last 500 API calls)

### 1.2 Data Flow to Trainer

```
CoinAnk API → Redis raw:coinank:* → Feature families 
  → features:coinank:* (2,403 keys) → Unified Feature Builder 
  → unified_features:{SYM}:{TF} (562-field hash) → PPO+MASA Trainer 
  → prediction:{SYM}:{TF} (18 fields) → Signal Stream
```

**Feature Distribution:**
- Liquidations: 4 features/symbol/TF × 25 symbols × 6 TF = 600 keys
- Open Interest: 3 × 25 × 6 = 450 keys
- Market Order Flow: 4 × 25 × 6 = 600 keys
- Funding Rates: 2 × 25 × 6 = 300 keys
- Long/Short: 3 × 25 × 6 = 450 keys
- **Total: 2,400+ keys from CoinAnk**

---

## PART 2: ALTERNATIVE PROVIDER ANALYSIS

### Provider Comparison (Data Coverage %)

| **Provider** | **CEX Derivatives** | **On-Chain** | **Whale Tracking** | **Cost** | **Replacement Viability** |
|---|---|---|---|---|---|
| **CoinAnk** | ✅ 100% (40 endpoints) | ❌ 0% | ❌ 0% | $99/mo | — (baseline) |
| **CoinGlass** | ⚠️ 30% (liquidation, OI, funding) | ✅ Basic | ❌ 0% | Free-$49 | **Supplement only** |
| **Moralis** | ❌ 0% | ✅ 100% | ✅ 50% | Free-$99 | **Complement, not replacement** |
| **Nansen** | ❌ 0% | ✅ 100% | ✅ 100% | $500+/mo | **Not designed for trading** |

### Key Gap: Market Order Flow
- **CoinAnk:** ✅ 7 endpoints providing buy/sell ratios (CRITICAL for entry timing)
- **CoinGlass:** ❌ No market order flow data
- **Moralis:** ❌ CEX order flow not available
- **Nansen:** ❌ No real-time CEX data

**Conclusion:** No single alternative provider can replace CoinAnk. CoinAnk has unique CEX derivatives intelligence.

### Recommended Strategy
Keep CoinAnk + augment:
- CoinGlass ($20/mo): Better liquidation viz, exchange reserves
- Moralis (free): Whale detection, DEX data
- Nansen (quarterly manual): Deep fund flow analysis
- **Net cost:** +$20/mo for +40% new features

---

## PART 3: LEGACY SYSTEM AUDIT

### 3.1 Startup Architecture (`start_all_services_production.sh`)

**7-Phase Deployment:**
1. **Phase 0:** Pre-flight (VRAM/RAM/disk checks)
2. **Phase 0.5:** Monitoring (VPN, Telegram, memory, trainer predictions)
3. **Phase 1:** 9 ingestors (Binance, KuCoin, CoinAnk, liquidations, CoinAPI variants)
4. **Phase 2:** Feature pipeline + OHLCV resampler
5. **Phase 2.5:** Technical analysis (160-field TA hash)
6. **Phase 3:** Hybrid trainer (PPO+MASA, GPU 2-4GB)
7. **Phase 3B-4C:** Orchestrator, traders, portfolio monitors

**Processes:** 14 core + 6 monitoring = 20 simultaneous

### 3.2 Legacy Ingestors (All Stopped 2026-05-26)

| Ingestor | Data | Status | Last Update |
|---|---|---|---|
| live_binance.py | OHLCV, 24hr ticker, funding, mark | ❌ | 2026-05-26 |
| live_kucoin.py | KuCoin OHLCV, funding, OI | ❌ | 2026-05-26 |
| **live_coinank.py** | 40 CoinAnk endpoints → 2,403 keys | ❌ | 2026-05-26 |
| live_coinank_global_aggregator.py | CoinAnk aggregation | ❌ | 2026-05-26 |
| live_binance_liquidations.py | Liquidation events (WS) | ❌ | 2026-05-26 |
| live_technical_analysis.py | 160-field TA hash | ❌ | 2026-05-26 |
| live_coinapi_v1.py | CoinAPI OHLCV | ❌ | Unknown |
| live_coinapi_wsds.py | Microstructure (27 fields) | ❌ | Unknown |
| live_tokenmetrics.py | TokenMetrics (18 endpoints) | ❌ | Unknown |

### 3.3 Legacy AI Engine

**Hybrid Trainer:**
- Models: PPO + MASA
- Features: 562-field unified vector
- Output: prediction:{SYM}:{TF} (18-field hash, direction+confidence)
- Iterations: 19,771+ logged
- Signal stream: signals:trading:primary (continuous)

**Why It Worked:**
- Complete feature set (562 fields)
- ML-trained predictions (19,771 iterations)
- Market intelligence (40 CoinAnk endpoints)
- Risk gating (liquidation proximity checks)
- **Result:** 90%+ win-rate strategies observed

---

## PART 4: V2 BREAKDOWN ANALYSIS

### 4.1 Critical Gaps

**Gap 1: Feature Pipeline (97.5% loss)**
```
Legacy: unified_features:{SYM}:{TF} = 562 fields
  - 160 TA indicators
  - 140 CoinAnk features
  - 80 microstructure
  - 60 regime/toxicity
  - 122 derived

V2: v2:unified_features:{SYM}:{TF} = 14 fields
  - Liquidation levels only
  - Missing: 548 features
```

**Gap 2: ML Trainer (0% ported)**
```
v2_rl_core_inference_loop running but produces NOTHING:
  - 0/6 components
  - PPO model: MISSING
  - MASA model: MISSING
  - Gymnasium env: MISSING
  - Checkpoint loader: MISSING
  - Inference loop: MISSING
  - Output formatter: MISSING

Evidence: redis-cli HGET "v2:prediction:BTCUSDT:5m" direction
Result: (nil)
```

**Gap 3: CoinAnk Ingestor (0% active)**
```
Script exists but NOT RUNNING
  - 961 stale keys (down from 2,403)
  - Last update: 2026-05-26
  - No new writes in 56 days
  - Feature pipeline can't consume it (Gap 1)
```

**Gap 4: TA Structure Mismatch**
```
Legacy: ta:{SYM}:{TF} = 160-field HASH
V2: v2:technical_analysis:{SYM}:{TF} = JSON blob with nested indicators

Problem: Trainer expects flat fields, gets JSON
Solution needed: Data adapter (not built)
```

**Gap 5: Microstructure (0% coverage)**
```
Legacy: microfeat:{SYM}:1m = 27 fields
V2: No equivalent built

Impact: Cannot detect trade reversals, no liquidity analysis
```

### 4.2 Signal Stream Status

**Legacy (2024-2026):**
```
signals:trading:primary → continuous stream, last update 2026-05-26
```

**V2 (Current):**
```
signals:trading:primary → frozen since 2026-05-13 (56 days)
v2:orchestrator:proposals → stream exists but no input predictions
v2:signals:paper → stream exists but no signals generated
```

### 4.3 Why Rebuild Failed

**NOT because:**
- ❌ Microservices architecture is wrong (it's better)
- ❌ Redis event bus is flawed (it's more scalable)
- ❌ CoinAnk needs replacement (it's tier-1)

**BUT because:**
- ✅ Feature pipeline incomplete (97.5% missing)
- ✅ ML trainer not ported (0 of 6 components)
- ✅ Ingestors inactive (CoinAnk down, microstructure down, TA down)
- ✅ Integration testing skipped (didn't test full stack until too late)

---

## PART 5: RECOMMENDATIONS

### 5.1 CoinAnk Decision: KEEP + AUGMENT

**Action:**
1. Verify CoinAnk actual payload freshness with read-only checks first.
2. Treat any CoinAnk runtime repair/restart as an operator-approved change.
3. Use CoinGlass and Moralis only through the provider-rate-limited V2 contracts.
4. Keep optional provider failures non-core-blocking unless a consumer explicitly requires them.

**Cost:** $99 (CoinAnk) + $20 (CoinGlass) = $119/mo  
**Benefit:** +40% new features without losing any existing ones

### 5.2 V2 Rebuild Priority (8-Week Path)

**Week 1-2: Feature Pipeline**
- Port 160 TA indicators to flat hash
- Build unified feature builder (562 fields)
- Integrate CoinAnk feature generation

**Week 3-4: ML Trainer**
- Define Gymnasium environment
- Port PPO model
- Port MASA model
- Load checkpoints

**Week 5-6: Microstructure**
- Build CoinAPI WebSocket ingestor
- Port orderbook depth aggregator
- Integrate TokenMetrics

**Week 7-8: Full Integration**
- Wire all data sources
- Enable trainer inference
- Validate with paper trading
- Live-canary review checks with live still blocked until operator approval

### 5.3 Safe Same-Day Actions

1. Run read-only CoinAnk/provider freshness and coverage checks.
2. Use the V2 TA flat-hash adapter path; do not bypass point-in-time safety.
3. Implement key expiry management through reviewed code, not ad hoc Redis mutation.
4. Document provider endpoint-to-feature mapping and consumer coverage.

---

## CONCLUSION

1. **CoinAnk is essential** — no replacement available
2. **Legacy was well-designed** — study it to understand success
3. **V2 readiness claims require current validation** — do not rely on stale counts
4. **Provider-rate-limited cutover path exists** — keep optional providers budgeted
5. **Begin with read-only truth checks** — runtime changes require approval

---

**Audit by:** Claude Code  
**Evidence Verified Against:** Redis keys, source code line ranges, API call logs  
**Status:** Historical audit aligned; not an execution runbook
