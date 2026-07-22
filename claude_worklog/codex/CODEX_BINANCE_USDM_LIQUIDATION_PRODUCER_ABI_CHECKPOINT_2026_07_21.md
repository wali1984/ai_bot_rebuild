# Binance USD-M Liquidation Producer ABI Checkpoint — 2026-07-21

## Immutable checkpoint identity

- Branch: `codex/liquidation-levels-bridge-remediation-20260721`
- Producer code commit: `a08d177fb9`
- Parent checkpoint: `f4142f7676`
- Family: Binance USD-M candle/mark evidence identity only
- Provider calls: 0
- Redis reads/writes: 0
- Services started/restarted/stopped: 0
- Order, leverage, margin, allocator, strategy, reward, and risk behavior changes: 0

This checkpoint makes existing Binance public-data outputs satisfy the strict
liquidation-surface source adapter without inferring product identity. It does
not yet publish a liquidation surface or grant trainer authority.

## Evidence counts

- Files changed in producer commit: 7
- Production code sites changed: 3
- Concrete source routes covered: 4
  - Binance USD-M kline WebSocket -> canonical closed candle
  - Binance USD-M `/fapi/v1/klines` -> canonical closed candle
  - Binance USD-M all-symbol mark-price WebSocket -> current mark evidence
  - Binance USD-M `/fapi/v1/premiumIndex` fallback -> funding/mark evidence
- Unique ABI identity fields made explicit: 4
  - `symbol`
  - `venue`
  - `product_type`
  - `source_endpoint`
- New producer-to-adapter tests: 3
- Combined targeted tests: 238 passed, 0 failed
- Python producer modules compiled: 3
- Runtime/provider endpoints contacted: 0
- Defects remaining in this family: 0

## Exact ABI changes

### Canonical closed candles

`CanonicalCandle.to_dict()` now serializes:

```json
{
  "exchange": "binance",
  "venue": "binance_usdm",
  "product_type": "USD-M"
}
```

The class is currently instantiated only for Binance USD-M sources. Both
native WSS and REST constructors, plus canonical higher-timeframe resampling,
therefore carry the same explicit identity. OHLCV values, finality clocks,
raw-payload hashes, and Redis keys are unchanged.

### Mark-price WebSocket

`v2_binance_mark_price_wss_seeder._normalize_row()` now emits exact
`venue=binance_usdm` and `product_type=USD-M` fields alongside its existing
schema, source, transport, symbol, event time, and availability time.

### Premium-index REST fallback

`v2_native_ingestors_live_loop._fetch_funding()` now normalizes the returned
symbol and emits:

```json
{
  "venue": "binance_usdm",
  "product_type": "USD-M",
  "source": "binance_public_rest_premium_index_fallback",
  "source_endpoint": "/fapi/v1/premiumIndex",
  "transport": "rest_fallback"
}
```

This prevents a payload from passing merely because it uses a broad Binance
label. The adapter still validates the exact Redis key, symbol, clocks,
positive mark, source, transport, and endpoint.

## Producer-to-adapter verification

The new handoff tests serialize real producer outputs into exact Redis bytes,
construct a consumer-observation receipt, and then call the strict adapter.

1. Canonical REST candle -> `adapt_binance_finalized_candles`
2. WSS mark producer -> `adapt_binance_mark_price`
3. Native REST fallback -> `adapt_binance_mark_price`

The existing adversarial adapter cases continue to reject wrong venue,
product, endpoint, clocks, finality, price, source, and self-authorization.

## Point-in-time and authority result

- Candle finality remains end-exclusive.
- Producer `available_at` remains distinct from the consumer receipt clock.
- The consumer receipt remains the adapted observation's authoritative
  availability time.
- No future candle, future mark, or inferred receipt is accepted.
- No producer output gains `trainer_authority`.
- Missing or incompatible evidence still fails closed and will later be
  represented to training by an unavailable mask, not a fabricated value.

## Verification evidence

Final combined command:

```text
PYTHONPATH="$PWD/v2/backend:$PWD" \
  '/home/wali/Desktop/AI BOT REBUILD/.venv/bin/pytest' -q \
  v2/backend/tests/unit/services/liquidation_surface/test_source_adapters.py \
  v2/backend/tests/unit/services/liquidation_surface/test_model.py \
  v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py \
  v2/backend/tests/unit/test_canonical_candles_and_mtf_snapshot.py \
  v2/backend/tests/unit/cli/test_v2_binance_mark_price_wss_seeder.py \
  v2/backend/tests/unit/cli/test_v2_binance_public_metadata_websocket_primary.py
```

Result: `238 passed in 0.37s` with one pre-existing `pytest_asyncio`
configuration deprecation warning.

Additional checks:

```text
'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/ruff' check \
  v2/backend/tests/unit/services/liquidation_surface/test_source_adapters.py
'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m compileall -q \
  v2/backend/app/services/market_state_integrity/canonical_candles.py \
  v2/backend/app/cli/v2_binance_mark_price_wss_seeder.py \
  v2/backend/app/cli/v2_native_ingestors_live_loop.py
git diff --check
git diff --cached --check
```

Results: changed adapter test lint clean; all three modules compiled; both diff
checks clean. A whole-file Ruff invocation reported pre-existing formatting and
lint debt in legacy producer files. No broad formatting cleanup was retained;
the final producer commit contains only 118 added lines and no deletions.

## Files in producer commit

- `v2/backend/app/cli/v2_binance_mark_price_wss_seeder.py`
- `v2/backend/app/cli/v2_native_ingestors_live_loop.py`
- `v2/backend/app/services/market_state_integrity/canonical_candles.py`
- `v2/backend/tests/unit/cli/test_v2_binance_mark_price_wss_seeder.py`
- `v2/backend/tests/unit/cli/test_v2_binance_public_metadata_websocket_primary.py`
- `v2/backend/tests/unit/services/liquidation_surface/test_source_adapters.py`
- `v2/backend/tests/unit/test_canonical_candles_and_mtf_snapshot.py`

## Remaining producer blocker

CoinAnk Plan3 open-interest evidence still lacks a committed, reproducible
pre-request clock and post-response observation receipt in the active runtime
path. The ignored `legacy_owned_runtime` file must not be patched as an
untracked one-off. The next family must establish a tracked source/projection
path, preserve Plan3 rate limits, and prove a real producer-to-adapter handoff
before any surface publisher or trainer integration is enabled.
