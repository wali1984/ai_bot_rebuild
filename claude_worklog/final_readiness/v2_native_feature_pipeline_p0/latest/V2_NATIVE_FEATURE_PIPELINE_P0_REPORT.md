# V2 Native Feature Pipeline (P0.1) Report

Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Outcome

Delivered a V2-native feature pipeline that computes feature snapshots
from raw OHLCV + orderbook + funding/OI/liquidation inputs. The
implementation is computational, not a bridge: it does not read legacy
features:* Redis keys as authoritative and does not import any Redis
client.

## Files

- v2/backend/app/services/feature_pipeline_native/__init__.py
- v2/backend/app/services/feature_pipeline_native/service.py
- v2/backend/app/cli/v2_feature_pipeline_native.py
- v2/backend/tests/integration/cli/test_v2_feature_pipeline_native.py
- v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/v2_feature_pipeline_native_status.json

## Test result

11/11 tests pass under v2/backend/tests/integration/cli/test_v2_feature_pipeline_native.py.

## Components ported

- OHLCV-derived: ret_pct, log_return, range_pct, body_pct, true_range_pct, gap_pct.
- TA indicators: ema_12, ema_26, rsi_14, macd, macd_signal, macd_hist, bb_width_pct.
- Multi-timeframe: htf_ret_pct, htf_rsi_14.
- Microstructure: bid_ask_spread_bps, depth_imbalance, micro_price, toxicity_proxy.
- Funding/OI/liquidation: funding_rate, oi_change_pct, last_liq_bps_24h.
- Portfolio-aware: paper_position_present, paper_position_notional, paper_unrealized_bps, paper_position_age_seconds.
- Freshness flags: FRESH / STALE / MISSING for OHLCV, orderbook, higher-tf,
  funding, OI, liquidation, paper position.
- feature_snapshot_id: v2_fsnap_<sha256> chain-of-custody id over a
  sorted payload.
- Explicit missing_feature_flags and stale_feature_flags emitted per snapshot.
- categories_present enumeration.

## Components missing (under migration contract)

- Full unified_feature_builder.py (2000+ feature dimensions).
- Regime state machine and hysteresis.
- Native WebSocket/REST ingestor layer (separate P0).
- Cross-exchange aggregation.
- TokenMetrics, AlphaVantage derived features.

## Safety invariants verified

- Runtime gate blocked_human_only.
- Runtime symbols empty.
- approves_live / approves_canary / approves_legacy_shutdown / approves_redis_trim all false.
- is_bridge_only false.
- reads_legacy_features_keys_as_authoritative false.
- writes_to_legacy_redis false.
- exchange_mutation_reachable false.
- Service module imports only stdlib + v2 internal modules + pytest (test). No redis / ccxt / binance / torch / SB3 imports.

## Dependency closure

Imports across all four files unique top-level:
__future__, argparse, dataclasses, datetime, hashlib, json, math,
pathlib, pytest, statistics, sys, typing, v2.

Zero forbidden imports. Zero unresolved local imports.

## Config / env parity

Six service parameters, all documented with defaults and legacy
equivalents. Global legacy config parity (1917 keys) remains
non-complete and is tracked separately in
CONFIG_ZERO_MISS_PARITY_MATRIX.json.

## Migration completion contract classification

PARTIALLY_MIGRATED. Not MIGRATED_CODEX_PASS.

## GO/NO-GO

V2_NATIVE_FEATURE_PIPELINE_P0_READY

## Addendum (2026-05-16) — P0.1 trainer-consumable snapshot

Added a trainer-consumable snapshot output contract to unblock P0.2.

- New service methods:
  - FeaturePipelineNativeService.emit_trainer_consumable_snapshot(inputs)
  - FeaturePipelineNativeService.build_deterministic_default_inputs(symbol, timeframe, generated_utc)
- New CLI flag: --emit-latest-snapshot --symbol BTCUSDT --timeframe 1m
- Emitted artifacts (schema v2_native_feature_snapshot_v1):
  - v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
  - v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
- New tests:
  v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py
  (8/8 pass).
- Snapshot payload includes:
  - schema_version=v2_native_feature_snapshot_v1
  - worker_id, feature_snapshot_id (v2_fsnap_<sha256>), generated_at
  - symbol, timeframe, features (23 features in default-input mode)
  - feature_count, categories_present (7 categories), missing_feature_flags,
    stale_feature_flags, source_inputs, source_freshness_seconds,
    feature_freshness_state (CURRENT|STALE|MISSING)
  - trainer_consumable=true
  - runtime gate blocked_human_only, runtime symbols empty, approval flags false

The addendum does not change the original P0.1 READY status; it adds the
output-contract artifacts required by P0.2.

