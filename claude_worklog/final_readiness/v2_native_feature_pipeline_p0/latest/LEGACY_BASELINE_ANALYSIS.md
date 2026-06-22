# V2 Native Feature Pipeline (P0.1) — Legacy Baseline Analysis

Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].
Contract: claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md.

## Legacy sources consulted (read-only V2-owned mirrors)

| Legacy path | SHA256 | Size (bytes) | V2-owned path |
|-------------|--------|---------------|---------------|
| feature_pipeline.py | 143938e735342179105155a12c50d7c495bdd1c16d570586cb369d03d7d4b2e8 | 69156 | v2/legacy_owned_runtime/feature_pipeline.py |
| rl/unified_feature_builder.py | 2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5 | 29925 | v2/legacy_owned_runtime/rl/unified_feature_builder.py |
| rl/obs_schema.py | 9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f | 17346 | v2/legacy_owned_runtime/rl/obs_schema.py |
| rl/tf_aggregator.py | d20049f79b916723c59362bfb5cf0c74d4d8ae7cc0bf57f8a929b15b83c7f9f4 | 6496 | v2/legacy_owned_runtime/rl/tf_aggregator.py |
| rl/microstructure_features.py | aca206e60f83a94ac2f447fb6aae6715c6b55ee573619100b6d20eae3dfca0d0 | 20760 | v2/legacy_owned_runtime/rl/microstructure_features.py |
| rl/microstructure_aggregator.py | 355e26df9bab22b01b4b01ec17fa926c2dc81c33c18bd4799fbb41bbc713e74d | 17428 | v2/legacy_owned_runtime/rl/microstructure_aggregator.py |
| rl/microstructure_overlay.py | eff2a1e69f5b839e46e8cad2f7dd77eb2697723e1ed945acc643471550d34f3b | 50596 | v2/legacy_owned_runtime/rl/microstructure_overlay.py |
| rl/portfolio_aware_features.py | 4224832092df169348a34cfc7b53b23f429a730868e3b58d0517e5deb9d33d53 | 18352 | v2/legacy_owned_runtime/rl/portfolio_aware_features.py |
| rl/portfolio_risk_features.py | 9ba168b9e870486b6e1a19d022b445c1daad88d2f077a65b3861a8689f05c30f | 15814 | v2/legacy_owned_runtime/rl/portfolio_risk_features.py |
| ingest/technical_analysis.py | 909437e7e77bcf6a03371c546b074a20e7a216bcd72b13ba783dcd78154dbee0 | 34191 | v2/legacy_owned_runtime/ingest/technical_analysis.py |

## Behaviors PORTED (native V2 computation, paper-only)

1. OHLCV-derived features: simple return pct, log return, range pct,
   body pct, true range pct (ATR-style), open-to-prior-close gap pct.
2. TA indicators: EMA(12), EMA(26), RSI(14), MACD (line, signal, hist),
   Bollinger Bands width pct.
3. Multi-timeframe aggregation: higher-timeframe return pct + RSI(14)
   when a higher-tf close window is supplied.
4. Microstructure features: bid/ask spread bps, depth imbalance, micro
   price, toxicity proxy (normalized spread + abs imbalance).
5. Funding / OI / liquidation derived features: funding_rate,
   oi_change_pct vs prior snapshot, last 24h liquidation notional in
   bps of price.
6. Portfolio-aware (paper): paper_position_present (0/1),
   paper_position_notional, paper_unrealized_bps, paper_position_age_seconds.
7. Freshness flags: FRESH / STALE / MISSING for every input class.
8. Feature snapshot id: v2_fsnap_<sha256> over symbol, timeframe,
   generated_utc, and sorted feature dict — chain-of-custody integrity.
9. Explicit missing-feature flags: every category that cannot be
   computed contributes named entries to missing_feature_flags instead
   of zero-filling.
10. Categories present list: explicit enumeration of which categories
    were satisfied by the inputs.

## Behaviors PARTIALLY_PORTED

- TA indicators: legacy optionally uses ta-lib for additional
  indicators (Stochastic, Williams %R, ADX, Ichimoku). V2 ports the
  core trio (EMA, RSI, MACD, ATR, BBands width) only.
- Multi-timeframe: legacy aggregates many timeframes with cross-TF
  consensus. V2 ports one higher-timeframe slot per snapshot.
- Microstructure: legacy microstructure_overlay.py wraps a much richer
  state machine. V2 ports the core features only.
- Portfolio-aware: legacy derives richer cross-position features. V2
  ports per-symbol paper-position features only.

## Behaviors MISSING_IN_V2

- Full unified_feature_builder.py (2000+ feature dimensions).
- Regime state machine and hysteresis.
- Native WebSocket / REST ingestor layer (separate P0).
- Cross-exchange aggregation (Binance vs KuCoin vs CoinAPI).
- TokenMetrics, AlphaVantage derived features.
- Legacy features:* Redis publish path (V2 does not write to legacy
  Redis; this is intentional).

## Config / env mapping (informational; no legacy Redis writes)

| V2 parameter | Default | Purpose |
|--------------|---------|---------|
| ohlcv_max_age_seconds | 120 | OHLCV freshness threshold |
| orderbook_max_age_seconds | 30 | orderbook freshness threshold |
| funding_max_age_seconds | 3600 | funding freshness threshold |
| oi_max_age_seconds | 300 | OI snapshot freshness threshold |
| liquidation_max_age_seconds | 3600 | liquidation freshness threshold |
| paper_position_max_age_seconds | 300 | paper position freshness threshold |

The full legacy config inventory (1917 keys) is classified in
claude_worklog/final_readiness/zero_miss_legacy_core_lift_remediation/latest/CONFIG_ZERO_MISS_PARITY_MATRIX.json.

## Intentional V2 changes

- V2 never reads legacy features:* Redis keys as authoritative.
- V2 never writes to legacy Redis.
- V2 returns explicit missing flags instead of zero-filling absent
  inputs.
- V2 emits a deterministic feature_snapshot_id for chain-of-custody.

## Deprecated legacy behavior

- The optional ta-lib path is intentionally NOT a hard dependency in
  V2; V2 implements the indicator math directly with the standard
  library only.
- The legacy publish/subscribe to features:updated channel is
  intentionally NOT replicated. V2 emits a single status payload per
  worker tick.

## Migration completion contract classification

PARTIALLY_MIGRATED. Not MIGRATED_CODEX_PASS. Runtime gate stays
blocked_human_only; runtime symbols stay empty.
