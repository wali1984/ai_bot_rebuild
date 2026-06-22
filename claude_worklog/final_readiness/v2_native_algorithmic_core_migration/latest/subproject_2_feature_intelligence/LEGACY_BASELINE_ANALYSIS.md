# Subproject 2 — Feature Intelligence — Legacy Baseline Analysis

Generated: 2026-05-15
Live gate: `blocked_human_only`. Live symbols: `[]`.
Contract: `claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md`.

## Legacy sources consulted (read-only)

| Legacy path | SHA256 | Size (bytes) | V2 preserved path |
|-------------|--------|---------------|-------------------|
| `rl/microstructure_proactive.py` | `92946a87ebf60c6f6ae271da67b5ca9ab2d867ddd860df52b45c7d1bb9dfe43d` | 65,862 | `v2/legacy_preserved/full_runtime_closure/rl/microstructure_proactive.py` |
| `rl/toxicity_shield.py` | `e00f098be80a682d41e5c98b34bf3d98392eb84db57a675ea49a15fe3e924c46` | 6,227 | `v2/legacy_preserved/full_runtime_closure/rl/toxicity_shield.py` |
| `rl/unified_feature_builder.py` | `2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5` | 29,925 | `v2/legacy_preserved/full_runtime_closure/rl/unified_feature_builder.py` |
| `trading/market_regime_detector.py` | `714511302a2cd2826f2c7a6763db5001c2d0abac0030ff10756d716934ac5d87` | 36,243 | `v2/legacy_preserved/full_runtime_closure/trading/market_regime_detector.py` |

The legacy `feature_pipeline.py` (~1,437 lines) is the live daemon that writes
2,000+ derived feature keys to legacy Redis. It is not in the closure manifest
under this subproject's scope; its full port belongs to a separate subproject.

## Behaviors PORTED (native V2, paper/shadow only)

1. Microstructure bid/ask spread (bps).
2. Microstructure depth imbalance from bid/ask sizes.
3. Microstructure micro-price computation.
4. Realized volatility (pct) from a window of recent log-returns.
5. Toxicity proxy from normalized spread and abs(depth_imbalance).
6. Feature freshness flag: `FRESH` / `STALE` / `MISSING` based on
   `generated_utc` age.
7. Regime classifier: `TRENDING_UP` / `TRENDING_DOWN` / `RANGING` /
   `VOLATILE` / `UNCERTAIN` from realized volatility, trend strength, and
   depth imbalance.
8. Explicit `missing_inputs` labels — no fabricated values when inputs are
   absent.

## Behaviors PARTIALLY_PORTED

- The toxicity proxy uses a simple 2-factor combine. Legacy toxicity logic
  considers additional inputs (microstructure proactive flags, trade size
  outliers). Marked PARTIALLY_PORTED.

## Behaviors MISSING_IN_V2

- Full `unified_feature_builder` (2,000+ derived features and cross-timeframe
  aggregations).
- Funding rate / open interest derived features.
- WebSocket / REST native ingestor layer (still legacy in V2 today).
- Full `microstructure_proactive` behavior set beyond the toxicity proxy.
- Full `market_regime_detector` classifier (regime persistence, multi-window
  voting, micro vs macro regimes).

## Config / env mapping (informational; no Redis writes)

| Legacy expectation | V2 mapping |
|--------------------|-------------|
| `features:*` Redis keys (legacy) | not written by V2; V2 publishes its own status payload only. |
| `recent_close_prices` window | service parameter `max_age_seconds` (default 120). |
| toxicity normalization caps (50 bps spread, ±1 imbalance) | service-local constants. |

## Intentional V2 changes

- V2 never writes to legacy Redis.
- V2 makes missing inputs explicit instead of zero-filling.
- V2 narrows the regime label set to five canonical labels for simpler audit.

## Deprecated legacy behavior

- Legacy regime detector's hidden hysteresis state is intentionally NOT
  imported to V2; V2 emits a stateless classification per snapshot and lets
  the caller maintain hysteresis if needed.

## Migration completion contract classification

`PARTIALLY_MIGRATED`. Not `MIGRATED_CODEX_PASS`. Live, canary, legacy
shutdown, and Redis trim all remain `false`.
