# V2 vs Legacy — Data Completeness Audit (No-Exception Gap Map)

Generated EST: 2026-06-01T18:12:00-0400
Generated UTC: 2026-06-01T22:12:00Z
LIVE_GATE: blocked_human_only | live_symbols: [] | writes_legacy_redis: false
Total live V2 Redis keys: 614

This audit is grounded in **raw Redis reads** taken at generation time and
reconciles the two earlier Copilot audits (`LEGACY_SYSTEM_FULL_AUDIT.md`,
`V2_VS_LEGACY_AUDIT_2026-05-31.md`) against current state. Verify any row with
`redis-cli --scan --pattern <pattern> | wc -l`.

## Verdict
**Not yet complete — exceptions remain.** V2 natively and freshly produces the
full Binance-derived market + feature + prediction + paper-trading plane, but
~14 data categories are still empty. The credential fix (see
`CREDENTIAL_ENV_LOCAL_SOURCING_AUDIT.md`) removes the *key* blocker; the
remaining gaps are *ingestor implementation + scheduling*, not credentials.

## Category map (raw counts)

### Producing fresh data (no exception)
| Category | V2 pattern | Keys | Note |
|---|---|---|---|
| Price | `v2:market:prices:*` | 27 | Binance public, 60s refresh |
| OHLCV bars (1m) | `v2:market:ohlcv:binance:*:1m` | 19 | real candles |
| Order book | `v2:market:orderbook:*` | 37 | top/depth |
| Funding | `v2:market:funding:*` | 25 | |
| Open interest | `v2:market:open_interest:*` | 25 | |
| OI history (5m) | `v2:market:open_interest_hist:*:5m` | 27 | NEW this session (oi_change_pct) |
| Features latest | `v2:features:latest:*:1m` | 27 | **25/25 fields REAL, 0 missing** |
| Dedicated TA | `v2:technical_analysis:*` | 25 | family now exists (indicators sub-dict) |
| Predictions | `v2:prediction:*` | 52 | structural; confidence=null (wrapper, not real trainer) |
| Orchestrator | `v2:orchestrator:*` | 3 | arbitration only |
| Paper positions/pnl | `v2:paper:*` | 89 | paper-only |
| Risk decisions | `v2:risk:*` | 1 | |

### Exceptions — empty in V2 (0 keys)
| Category | V2 pattern | Blocker class | Path to close |
|---|---|---|---|
| Unified features (562-field) | `v2:unified_features:*` | partial: 170 keys but only ~14 fields/hash | port full feature_pipeline (562 fields) + fast/slow lane streams |
| CoinAnk market | `v2:market:coinank:*` | impl: bridge is public stub (no `apikey` header) | build authenticated CoinAnk ingestor (key now in env) + timer |
| CoinAnk features | `v2:features:coinank:*` | impl | same |
| KuCoin | `v2:market:kucoin:*` | impl: worker is descriptive stub | build public REST/WSS fetcher + timer |
| CoinAPI | `v2:market:coinapi:*` | impl: no V2 CLI | build v2_coinapi_v1 ingestor (key now in env) |
| Microstructure (WSDS) | `v2:market:microstructure:*` | operator: paid CoinAPI tier | operator approval |
| TokenMetrics | `v2:altdata:tokenmetrics:*` | operator: re-enable decision | operator approval (key in env) |
| LunarCrush | `v2:altdata:lunarcrush:*` | scheduling: client ready, key now loads | add systemd timer |
| Nansen | `v2:altdata:nansen:*` | scheduling + provider 403 | add timer; provider access |
| Arkham | `v2:altdata:arkham:*` | scheduling: presence-only worker | add timer |
| AlphaVantage | `v2:altdata:alphavantage:*` | credential: key absent from all files | operator supplies key |
| Opportunity/strategy | `v2:strategy:*` | impl: not ported | port opportunity_tracker |
| Portfolio state | `v2:portfolio:*` | impl: not ported | port portfolio observer (paper-only) |
| Regime | `v2:market:regime:*` | impl: not implemented | regime detector |
| Volatility | `v2:market:volatility:*` | impl: not implemented | volatility scalar |

## Reconciliation with earlier Copilot audits
- Copilot: "unified_features = 14 fields" — **confirmed** for
  `v2:unified_features:*` (sparse liquidation-engine hashes), but a separate,
  healthy `v2:features:latest:*` family carries **25/25 real** fields.
- Copilot: "predictions confidence null" — **confirmed**: 52 prediction keys
  exist but `confidence=null` (V2 RL core is a momentum wrapper; the real
  PPO/MASA trainer adoption is operator-gated per CLAUDE.md).
- Copilot: "legacy dead / V2 not self-sufficient" — **directionally correct**:
  V2 is self-sufficient for the Binance-derived plane only; provider-gated and
  ported-logic categories remain empty.

## Mapping to the burndown queue
Every exception above corresponds to an existing materialized task in
`V2_ZERO_EXCEPTION_PARITY_IMPLEMENTATION_BURNDOWN` (priority 1-3:
V2_RUNNING_PARTIAL / V2_ADAPTER_REQUIRED / V2_MISSING_IMPLEMENTATION). The
credential fix this session unblocks the CREDENTIAL_BLOCKED rows' key access;
their ingestor implementation is the remaining work.
