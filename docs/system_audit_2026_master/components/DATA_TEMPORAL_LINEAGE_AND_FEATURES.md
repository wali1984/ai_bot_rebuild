# Data, temporal lineage, and feature-tensor reference

- **Audit date:** 2026-07-16
- **Scope:** source-to-feature-to-snapshot-to-tensor flow, point-in-time contracts, candle finality, dirty-sample admission, Redis and durable lineage
- **Evidence basis:** direct source inspection; no live-state mutation and no exchange action
- **Safety status:** the canonical candle layer is substantially fail-closed, but the complete feature path is **not yet point-in-time closed** because external/provider and reconstruction paths can lose or invent availability evidence.

This document is the low-level contract for reproducing the data side of the native trainer. It describes what the current code does, not what a clean-room implementation is assumed to do. “Required invariant” means the condition a correct copy must enforce. “Current gap” means the audited implementation does not prove that invariant on every path.

## 1. Authoritative source map

| Concern | Authoritative implementation |
|---|---|
| Canonical candle shape, finality, storage keys, resampling, MTF snapshot | `v2/backend/app/services/market_state_integrity/canonical_candles.py` |
| Timestamp parsing and market-state trust | `v2/backend/app/services/market_state_integrity/trust.py` |
| Legacy-shaped alignment and candle validators | `v2/backend/app/services/market_state_integrity/validators.py` |
| Market-state score and training/prediction/risk validity | `v2/backend/app/services/market_state_integrity/scoring.py` |
| Historical missing-mask exception | `v2/backend/app/services/market_state_integrity/sample_rejection.py` |
| Active Redis-native feature producer | `v2/backend/app/cli/v2_feature_pipeline_native_loop.py` |
| Parallel native feature service contract | `v2/backend/app/services/feature_pipeline_native/service.py` |
| Domain/status snapshot contract | `v2/backend/app/domain/features/models.py`, `v2/backend/app/services/feature_snapshots/service.py` |
| Optional provider PIT bridge | `v2/backend/app/services/provider_features/provider_feature_bridge.py` |
| TA/provider unified bridge | `v2/backend/app/services/feature_pipeline/unified_feature_bridge.py` |
| Exact 477-feature order and tensor assembly | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py` |
| Redis loading, MTF reconstruction, sample classification | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py` |
| Durable feature archive | `v2/backend/app/services/native_trainer/durable_feature_snapshot_archive.py` |
| Trusted replay labels | `v2/backend/app/services/native_trainer/trusted_replay/dataset.py` |
| Prediction/replay/archive publication | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py` |
| Runtime publication call order | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py` |

The exact feature registry is `FEATURE_SPEC`; this document does not redefine its order. A generated atlas or downstream schema must read that constant directly. A separately maintained list will drift.

## 2. End-to-end flow

```text
Binance WSS / Binance REST / resampled lower-timeframe candles
  + order book / funding / OI / liquidation / TA / structure / alt-data workers
  + optional CoinGlass and Moralis provider payloads
                                  │
                                  ▼
canonical candle records and current Redis source surfaces
  v2:market:kline_current:{exchange}:{symbol}:{timeframe}
  v2:market:ohlcv_closed:{exchange}:{symbol}:{timeframe}
  numerous v2:market:*, v2:features:*, v2:microstructure:*, v2:altdata:* keys
                                  │
                                  ▼
v2_feature_pipeline_native_loop.run_once
  select closed OHLCV
  compute OHLCV/TA/cost fields
  merge current external Redis values
  optionally attach provider_feature_context
                                  │
                                  ▼
v2_native_feature_snapshot_v1
  v2:features:latest:{symbol}:{timeframe}                  TTL 600 s
  v2:features:snapshot:{feature_snapshot_id}              default TTL 43,200 s
  v2:features:snapshots                                   ID list
  v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
                                  │
                                  ▼
TrainingDatasetLoader / V2UnifiedFeatureTensorBuilder
  fetch latest snapshot plus source payloads
  reconstruct 1m/5m/15m/1h/4h candle proof
  resolve the 477 ordered numeric slots
  build missing, stale, and source-availability channels
                                  │
                                  ▼
FeatureTensorRecord
  477 values + 477 missing + 477 stale + 477 availability = 1,908 inputs
                                  │
                                  ▼
prediction payload + replay snapshot
  v2:prediction:{symbol}:{timeframe}
  v2:replay:snapshots:{prediction_id}                     TTL 86,400 s
  trainer/orchestrator/risk/paper preview and signal keys
                                  │
                                  ▼
durable content-addressed archive
  .local_data/v2_native_trainer/durable_feature_snapshot_archive/
    blobs/{sha-prefix}/{content_sha256}.json
    index/snapshot_id/{safe-snapshot-id}.json
    manifest.jsonl
    checksum_manifest.json
                                  │
                                  ▼
later finalized candles -> trusted replay outcome row -> training
```

Source anchors: native snapshot assembly and writes are at `v2_feature_pipeline_native_loop.py:1490-1767`; trainer Redis reads are at `data_loader.py:924-1159`; tensor assembly is at `tensor_builder.py:1633-1821`; archive assembly is at `durable_feature_snapshot_archive.py:124-304`.

## 3. Timestamp vocabulary

These fields are not aliases.

| Field | Exact meaning | May be used as a fallback for |
|---|---|---|
| `event_time` | Time the source event economically occurred. For a finalized candle, normally its close/event timestamp. | Nothing unless the source contract explicitly defines availability at event time. |
| `ingested_at` | Time this system received or persisted the source record. | Never `event_time`; never silently synthesized for latency-sensitive evidence. |
| `available_at` | Earliest time the exact value was fully usable by the decision process, after finality, receipt, and required transformation. | The decision-time availability gate. |
| `generated_at` / `generated_utc` | Time a derived payload was created. | Record creation only. It must not silently replace source event, ingestion, feature cutoff, or model decision time. |
| `feature_cutoff` | Boundary of source information incorporated in a feature set. For a multi-source snapshot this must truthfully represent the latest contributing source cutoff, while each source retains its own cutoff. | PPO/MASA temporal comparison and archive selection. |
| `decision_time` | Timestamp at which the model’s inputs were frozen and the action was selected. | The right side of every feature-availability inequality. |
| `execution_time` | Timestamp of paper/live fill or simulated execution. | Outcome and execution attribution only; never model decision time. |

Related compatibility fields include `source_event_time_est`, `source_received_time_est`, `source_available_time`, `decision_time_est`, `decision_cutoff`, `decision_cutoff_time_est`, `candle_open_time`, and `candle_close_time`. They must retain the same semantic role when normalized.

### 3.1 Required inequalities

For every source value `s` used in decision `d`:

```text
s.event_time     <= d.decision_time
s.ingested_at    <= d.decision_time
s.available_at   <= d.decision_time
s.feature_cutoff <= d.decision_time
```

For a finalized candle:

```text
candle_open_time < candle_close_time
candle_close_time <= available_at
is_closed == true
feature_eligible == true
available_at <= decision_time
```

For a derived feature using source set `S`, the safe definition is:

```text
feature.available_at = max(
    transform_finished_at,
    max(s.available_at for s in S)
)

feature.feature_cutoff = max(s.feature_cutoff or s.event_time for s in S)

feature.available_at <= decision_time
feature.feature_cutoff <= decision_time
```

For the cross-model order required by repository policy:

```text
MASA.feature_cutoff <= PPO.decision_time
```

The loader additionally rejects a mismatch when both MASA and PPO cutoffs exist but differ (`data_loader.py:579-585`).

For execution lineage:

```text
decision_time <= execution_time
```

The native prediction payload does not establish a canonical `execution_time`; that field arrives later through paper execution/feedback. A rebuild must not infer execution from publication time.

### 3.2 What current validators enforce

`EventTimeAligner.evaluate` rejects missing envelope timestamps, future feature cutoff, future availability, future source event, ingestion after decision, unfinished candles, live use of backfill, gaps, duplicates, out-of-order events, excess disagreement/latency, missing timeframe cutoffs, and MASA/PPO cutoff disagreement (`trust.py:670-798`).

`validate_event_time_alignment` rejects source event or source receipt after decision cutoff (`validators.py:19-54`). `validate_candle_completion` distinguishes confirmed closed, explicitly unclosed, and unknown finality (`validators.py:57-80`).

These checks are only as strong as the timestamps supplied to them. Synthesizing `ingested_at`, replacing `decision_time` with publication time, or omitting provider timestamps defeats the evidence without necessarily tripping the comparison.

## 4. Canonical candle contract

`CanonicalCandle` contains (`canonical_candles.py:24-50`):

| Field | Purpose |
|---|---|
| `symbol`, `exchange`, `timeframe` | Market identity. |
| `candle_open_time`, `candle_close_time` | Candle interval boundaries in milliseconds. |
| `event_time` | Source event time. |
| `ingested_at` | Local receipt time. |
| `available_at` | Earliest usable time. |
| `is_closed` | Finality assertion. |
| `source`, `source_sequence_id` | Producer and ordering reference. |
| `raw_payload_hash` | SHA-256 of raw/source material. |
| `ohlcv` | Numeric OHLCV plus optional quote volume, trade count, and taker fields. |
| `is_backfilled` | Historical/backfill indicator. |
| `feature_eligible` | Whether the candle may feed features. |

`to_dict()` also emits `candle_id`, `open_time`, `close_time`, `ts`, `closed_candle`, and `candle_closed_confirmed`. `candle_id` hashes exchange, symbol, timeframe, open, close, and raw payload hash (`canonical_candles.py:42-72`).

### 4.1 Storage separation

- Open/current: `v2:market:kline_current:{exchange}:{symbol}:{timeframe}`.
- Closed: `v2:market:ohlcv_closed:{exchange}:{symbol}:{timeframe}`.
- Compatibility: `v2:market:ohlcv:{exchange}:{symbol}:{timeframe}`.

`storage_records_for_candle` sends a candle to the closed key only when `is_closed` is true (`canonical_candles.py:219-223`). Tests lock this distinction at `test_canonical_candles_and_mtf_snapshot.py:73-114`.

### 4.2 Binance WebSocket finality

`canonical_from_binance_wss` reads:

- `k.t` open time;
- `k.T` close time;
- outer or kline `E` event time;
- `k.x` final/closed flag;
- OHLCV, quote volume, trade count, and taker volumes.

For a closed WSS candle:

```text
available_at = max(candle_close_time, event_time, ingested_at)
feature_eligible = true
```

For an open WSS candle, `feature_eligible=false` and it remains on the current key (`canonical_candles.py:138-176`). This is the strongest finality path because the exchange close flag is retained.

### 4.3 Binance REST finality

`canonical_from_binance_rest` has no exchange close flag. It declares:

```text
is_closed = candle_close_time <= ingested_at
event_time = candle_close_time
available_at = max(candle_close_time, ingested_at) when closed
is_backfilled = true
```

See `canonical_candles.py:179-216`. This is acceptable only when `ingested_at` is the actual fetch/receipt time and the remote row is known final.

### 4.4 Higher-timeframe resampling

`aggregate_closed_candles` (`canonical_candles.py:242-364`):

1. Requires an integral target/source timeframe ratio.
2. Ignores source rows without an explicit closed flag.
3. Rejects a source close later than `now_ms_value`.
4. Requires every expected lower-timeframe slot.
5. Rejects an unfinished target window.
6. Computes OHLCV from the complete ordered slots.
7. Uses the maximum source `event_time` and maximum source `available_at`.
8. Hashes the source candle IDs and raw hashes into the resampled candle lineage.

Tests cover complete aggregation, a missing slot, and unfinished target windows at `test_canonical_candles_and_mtf_snapshot.py:145-237`.

## 5. Multi-timeframe decision snapshot

Required timeframes are exactly:

```text
1m, 5m, 15m, 1h, 4h
```

`build_multi_timeframe_decision_snapshot` (`canonical_candles.py:429-502`) selects, for every required timeframe, the latest candle satisfying:

```text
explicit closed flag == true
candle_close_time <= decision_time
available_at is present
available_at <= decision_time
```

It rejects with timeframe-specific reasons including:

- `DECISION_TIME_MISSING`
- `MISSING_CLOSED_CANDLE_{tf}`
- `AVAILABLE_AT_MISSING_{tf}`
- `AVAILABLE_AT_AFTER_DECISION_{tf}`
- `CANDLE_CLOSE_TIME_MISSING_{tf}`
- `FUTURE_CANDLE_{tf}`

The snapshot carries:

- `decision_id` and `mtf_snapshot_id` derived from a stable hash;
- selected candle ID/open/close/availability/event/source/raw hash per timeframe;
- `missing_timeframes` and `gap_flags`;
- `all_tf_candle_timestamps`;
- `all_source_event_times`;
- source raw hashes;
- `valid` and `reject_reasons`.

### 5.1 Aggregate-cutoff defect

Current code sets:

```python
feature_cutoff = min(close_times)
```

at `canonical_candles.py:468-469`, and `test_canonical_candles_and_mtf_snapshot.py:240-250` explicitly asserts that behavior.

This is a semantic defect if `feature_cutoff` is described as the most recent information used. With 1m through 4h inputs, the minimum is the oldest contributing close. A downstream check of only this aggregate can therefore pass even when a later contributing source would violate the intended cutoff. The per-timeframe checks currently protect the canonical builder, but the collapsed field is misleading after that detail is discarded.

A correction would change MTF snapshot IDs, replay/archive content hashes, downstream cutoff comparisons, fixtures, and historical equivalence. It requires a migration decision, not a local one-line edit.

## 6. Active Redis-native feature assembly

`v2_feature_pipeline_native_loop.run_once` is the source path that writes `v2:features:latest:{symbol}:{timeframe}` (`v2_feature_pipeline_native_loop.py:1499-1767`).

Per symbol/timeframe it:

1. Reads canonical closed and compatibility OHLCV keys.
2. Filters to closed rows at the cycle’s `decision_ms`.
3. Builds core market and OHLCV/TA/cost features.
4. Reads order book, OI history, long/short, and liquidation context.
5. Calls `_merge_external_v2_features`.
6. Assigns closed-candle timing and freshness.
7. Creates `v2_native_feature_snapshot_v1`.
8. Optionally attaches provider bridge context.
9. Hashes the complete snapshot into `feature_snapshot_id`.
10. Writes latest, per-ID archive, index, TA mirrors, and heartbeat.

### 6.1 Native snapshot fields

The active payload at `v2_feature_pipeline_native_loop.py:1571-1626` includes:

- schema/worker/symbol/timeframe;
- `features` and feature counts;
- categories;
- missing/stale flags;
- freshness and trainer/prediction/paper booleans;
- candle finality/open/close;
- estimated source event/receipt/availability;
- feature cutoff and estimated decision time;
- OHLCV source key and counts;
- external source labels/count;
- cost evidence sources/missing fields/status;
- unclosed-row exclusion and source-presence flags;
- generation timestamps;
- blocked live-gate metadata.

The active producer defines:

```text
source_event_time_est    = selected candle close
source_received_time_est = snapshot generation time
source_available_time    = snapshot generation time
available_at             = snapshot generation time
feature_cutoff           = selected candle close
decision_time_est        = snapshot generation time
```

This proves when the aggregate snapshot was generated, not when every external feature became available.

### 6.2 Core freshness gate

`trainer_consumable`, `valid_for_prediction`, and `valid_for_paper` are based on the selected closed OHLCV being present and not stale (`v2_feature_pipeline_native_loop.py:1532-1591`). External/provider staleness does not participate equivalently in this top-level Boolean.

### 6.3 Redis and file writes

| Surface | Value | Retention/behavior |
|---|---|---|
| `v2:features:latest:{symbol}:{timeframe}` | Full native snapshot | 600 seconds. |
| `v2:features:snapshot:{feature_snapshot_id}` | Same serialized snapshot | `V2_FEATURE_SNAPSHOT_TTL_SECONDS`, default 12 hours/43,200 seconds. |
| `v2:features:snapshots` | Current list of IDs emitted by the cycle | Same snapshot TTL. |
| `v2:technical_analysis:{symbol}:{timeframe}` | TA mirror | 600 seconds. |
| `v2:features:pipeline:heartbeat` | Aggregate worker status | 300 seconds. |
| `v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json` | First emitted snapshot only | Overwritten file mirror. |

Constants and writes: `v2_feature_pipeline_native_loop.py:37-47`, `1490-1497`, and `1650-1766`.

## 7. External and provider feature paths

### 7.1 Direct external Redis merge

`_merge_a_plus_context_features` (`v2_feature_pipeline_native_loop.py:657-738`) reads current:

- `v2:context:htf:{symbol}`;
- `v2:context:cross_asset`;
- `v2:regime:gate:{symbol}:{timeframe}`;
- `v2:market:trade_tape_features:{symbol}`.

`_merge_external_v2_features` (`v2_feature_pipeline_native_loop.py:768+`) additionally reads families such as:

- full TA;
- liquidation levels;
- unified features;
- direct order book and microstructure;
- CoinAPI WSDS/microfeatures;
- public-intel, symbol-score, AICoin, whale-wall, Santiment, and other alt data;
- smart-money/provider-derived surfaces.

The generic `_read_json_key`, `_read_hash_key`, and numeric merge helpers do not require each payload’s `event_time`, `available_at`, or `feature_cutoff` to be present and at/before the current decision. The source label is recorded, but the individual temporal envelope is not retained in the snapshot.

**Current gap:** a historical/backfill feature build can combine an older candle cutoff with whatever value is currently stored in an external Redis key. Even on a live build, the resulting snapshot cannot prove that every merged field was available before its decision time.

### 7.2 Provider bridge behavior

`ProviderFeatureSnapshot` retains provider, key, status, TTL, event/availability/cutoff/generation times, exclusion reasons, and canonicalized features (`provider_feature_bridge.py:21-45`).

The bridge correctly excludes:

- missing payload;
- heartbeat-only/empty payload;
- no-expiry TTL contract violation;
- parsed `available_at > decision_time`;
- parsed `feature_cutoff > decision_time`.

However (`provider_feature_bridge.py:217-269`):

- `available_at` falls back to `generated_at`/`generated_utc`;
- `feature_cutoff` falls back to `event_time` and then `available_at`;
- an unparseable or absent timestamp does not itself add an exclusion;
- `stale`/`is_stale`, `RATE_LIMITED`, or `DEGRADED` marks the row stale but does not add an exclusion reason;
- features are canonicalized whenever the separate exclusion list is empty, including stale rows.

Thus `stale=true` is not equivalent to `excluded_from_features=true`.

The active feature loop passes its current `generated_at` as provider decision time at `v2_feature_pipeline_native_loop.py:1632-1647`, but catches every provider exception and continues at lines 1648-1649. Optional provider failure does not block the core snapshot.

### 7.3 Unified bridge missing decision time

`build_unified_feature_payload` can check provider timing when its `decision_time` argument is supplied (`unified_feature_bridge.py:15-57`). The feature loop calls it at `v2_feature_pipeline_native_loop.py:1719-1726` without a `decision_time`, so that publication path creates a provider context with no comparison boundary. The payload can still report `point_in_time_safe=true` because the violations list is empty when no comparison was performed.

There are also two different “unified” key contracts. `_merge_external_v2_features` reads the hash `v2:unified_features:{symbol}:{timeframe}` at `v2_feature_pipeline_native_loop.py:791-794`, while `build_unified_feature_payload` writes JSON to `v2:features:unified:{symbol}:{timeframe}` (`unified_feature_bridge.py:12-55`). No adapter in this path makes those names equivalent. Refreshing one surface is not proof that the other consumer saw the same values.

### 7.4 Trainer supplemental reads

The loader’s general snapshot path reads `v2:features:latest` and then supplements it with current funding, OI, order book, liquidation, structure, alt-data, microstructure, TA, Moralis, confluence, smart-money, risk, and orchestrator keys (`data_loader.py:924-1119`). `_get_merged` merges mappings and nested `features` in key order (`data_loader.py:694-708`).

These supplemental values are not universally checked against the original snapshot’s decision time. The prediction-specific fast path is narrower—it uses the native snapshot plus closed MTF candles (`data_loader.py:1128-1159`)—but ordinary reconstruction/training paths can observe values newer than the archived snapshot.

## 8. REST, raw-list, and fallback gaps

### 8.1 Feature-loop raw arrays

`_closed_klines` accepts either canonical mappings or exchange-like arrays (`v2_feature_pipeline_native_loop.py:411-436`). For mappings it requires a close flag and, when available, rejects future availability. For list/tuple rows it has no close flag or `available_at`; it accepts the row solely when element 6, the close timestamp, is no later than `decision_ms`.

### 8.2 Loader raw arrays

`TrainingDatasetLoader._closed_candle_series_from_raw` (`data_loader.py:710-744`) requires close flags for mapping rows. For list/tuple rows, however, it calls `canonical_from_binance_rest(..., ingested_at=close_ms)`.

That creates:

```text
event_time   = close time
ingested_at  = close time       # synthesized, not observed
available_at = close time
is_closed    = true
```

for every historical row whose close is in the past. This erases actual fetch latency and makes the row appear available at close. It is unsuitable as proof for a latency-sensitive historical decision.

### 8.3 Training-time timestamp inference

`scoring._with_training_snapshot_time_inference` can infer source event, receipt, decision cutoff, candle close, and candle open from a current trainer-consumable snapshot’s generation time (`scoring.py:192-242`). It explicitly says this is training-only and not exchange/live availability proof.

`PIPELINE_TRUST_UNSAFE_FINALITY_INFERENCE` can also set `candle_closed_confirmed=true` in a development-only path. It is disabled unless explicitly enabled (`scoring.py:230-234`). Enabling it changes sample admission and must never be presented as exchange finality evidence.

## 9. Three snapshot contracts that must not be conflated

### 9.1 Active Redis native snapshot

Producer: `v2_feature_pipeline_native_loop.py`.

Schema: `v2_native_feature_snapshot_v1`.

Fields: flat `features`, masks/flags, candle/timing metadata, provider context, Redis lineage.
Primary native trainer input: `v2:features:latest:{symbol}:{timeframe}`.

### 9.2 `FeaturePipelineNativeService` snapshot

Producer/facade: `feature_pipeline_native/service.py:559-643`.

Schema: also `v2_native_feature_snapshot_v1`.
It computes from `NativeFeatureInputs`, uses configured source-age thresholds, and exposes source ages/categories. Its deterministic default-input builder can fabricate a complete ramp/orderbook context for CLI/evidence use (`service.py:645+`). `emit_trainer_consumable_snapshot` currently sets `trainer_consumable=True` at line 635 even when its freshness state is stale or missing.

Same schema name does not guarantee identical provenance or admission semantics.

### 9.3 Domain/status snapshot

Types: `domain/features/models.py:7-81`.

Service: `feature_snapshots/service.py:19-81`.
Schema: `trainer_features.v1`.

It uses:

- `feature_values` rather than native `features`;
- feature groups;
- freshness per source;
- source key/ingestor/snapshot references;
- stale/missing/unused lists;
- `confidence_input_ready`.

`v2_feature_snapshot_builder.py` writes this contract to public/local/worklog status files. It is not the same payload the CUDA loader reads from `v2:features:latest`, and its status worker must not be treated as evidence that the Redis-native trainer snapshot was persisted.

## 10. Exact 477-feature schema

The authoritative ordered registry is:

```text
v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py:17-508
FEATURE_SPEC: tuple[tuple[feature_name, nominal_source_label], ...]
```

Current locked cardinality:

```text
len(FEATURE_SPEC) == 477
feature names are unique
155 names begin with taf_
```

The cardinality and full-TA mapping are tested at `test_ta_full_feature_expansion.py:19-28`.

The registry spans these source families:

| Family | Representative content |
|---|---|
| Prices and derivatives | last/mark/index price, basis, funding, OI, OI change, long/short ratios. |
| OHLCV and trade composition | OHLC, base/quote volume, trade count, taker buy/sell volumes and ratios. |
| Order book | best bid/ask, spread, depth, imbalance, slope, price impact, update age, sequence/latency fields. |
| Microstructure trust | feed latency, spread instability, persistence, cancellation, book/tape divergence, sweep/cascade risk. |
| Base TA | RSI, MACD, ATR, EMA, Bollinger and derived features. |
| Full TA-Lib | 155 `taf_*` fields mapped explicitly by `TA_FULL_FEATURE_MAP` at `tensor_builder.py:511-670`. |
| Liquidation and liquidity | levels, distances, clusters, cascade risk, zones, aggregate liquidation flow. |
| Market structure | FVG, BOS/CHOCH, order/breaker/mitigation blocks, sweeps, premium/discount, structure trend. |
| Volume/order flow | VWAP, volume profile, CVD, trade imbalance, large trades, tape/sweep prints. |
| Alternative/provider data | public intel, Nansen, LunarCrush, AICoin, whale walls, Santiment, Moralis/smart money, confluence. |
| Context | higher-timeframe, cross-asset, regime, session, portfolio/risk/orchestrator context. |
| Fast-move additions | cascade components, squeeze probability/trap/direction, cross-asset lead. |
| 1h anchors | eight `htf1h_taf_*` fields. |

The second tuple member is a nominal source label, not proof that the resolved value actually came from that exact Redis key. Runtime fallbacks can override the reported label with provider or CoinAnk sources, but many generic fallback values retain the static label.

## 11. Tensor resolution and layout

`FeatureTensorRecord` fields are defined at `tensor_builder.py:673-688`.

For each `FEATURE_SPEC[i]`, the builder resolves a finite numeric value from direct source payloads, native snapshot values, aliases, provider context, TA maps, and derived fallbacks. It then emits (`tensor_builder.py:1764-1821`):

```text
values[i]              = resolved numeric value, or 0.0 when missing
missing_mask[i]        = 1 when no finite value exists, else 0
stale_mask[i]          = 1 when exact feature name is stale or the latest snapshot is not CURRENT
source_availability[i] = 0 when missing, else 1
```

Coverage is:

```text
data_coverage_percent = 100 * count(missing_mask == 0) / 477
```

`model_vector` concatenates in this exact order (`tensor_builder.py:690-697`):

| Offset, inclusive | Length | Channel |
|---:|---:|---|
| `0..476` | 477 | values |
| `477..953` | 477 | missing mask cast to float |
| `954..1430` | 477 | stale mask cast to float |
| `1431..1907` | 477 | source availability cast to float |
| total | **1,908** | model input |

`test_ta_full_feature_expansion.py:31-52` locks the 1,908 width and honest missing masks for absent TA fields.

### 11.1 Availability is not temporal proof

`source_availability[i]=1` only means the builder found a finite numeric value. It does not mean that source had an `available_at`, was fresh, matched the decision’s as-of time, or came from the nominal source. The name is therefore semantically broader than the implementation.

### 11.2 Stale matching limitation

Stale flags are collected as strings from payloads and compared to the exact feature name (`tensor_builder.py:1764-1789`). A family flag such as `ohlcv_closed_window` does not necessarily mark every OHLCV feature stale unless the whole latest snapshot state is non-current.

### 11.3 Zero-value fallback defect

Generic fallback assignment uses Boolean `or`, for example at `tensor_builder.py:1633-1636` and `1697-1700`. Legitimate `0.0` values can therefore be replaced by a later alias or treated as absent. This is material for imbalance, return, direction-code, and neutral-state fields. Correct lookup must distinguish `None` from zero.

### 11.4 Tensor identity boundary

`tensor_id` hashes:

```text
symbol | timeframe | feature_snapshot_id | values | missing_mask | stale_mask
```

at `tensor_builder.py:1793-1800`.

It does not independently hash per-source event/availability timestamps, source labels, or the full source envelope. It relies on `feature_snapshot_id` to bind those details. If a snapshot ID is reused or source timing is not inside the hashed snapshot, the tensor ID is not a complete temporal identity.

## 12. Loader trust-row reconstruction

`TrainingDatasetLoader._build_example_from_payloads` (`data_loader.py:1161-1259`):

1. Builds the tensor.
2. Derives expected-move/action labels.
3. Reads decision-time missing/stale lineage from the feature snapshot when present.
4. Classifies coverage/missing/stale state.
5. Builds a fresh five-timeframe trust snapshot.
6. Adds realized outcome/PPO entry fields when matched.
7. Runs `classify_training_sample` and extra MTF/MASA/PPO checks.

The trust row contains snapshot/tensor IDs, MTF snapshot, cutoffs, availability, source event/receipt, finality, masks, source hashes, all timeframe close/event arrays, and backfill indicators (`data_loader.py:1261-1367`).

Important fallback order:

```text
decision_time = latest.decision_time
             or latest.decision_cutoff
             or latest.generated_at

feature_cutoff = latest.feature_cutoff
              or latest.decision_cutoff
              or MTF snapshot cutoff
              or latest.generated_at

available_at = latest.available_at
            or latest.source_available_time
            or latest.generated_at
```

These fallbacks preserve operability but can turn record generation time into unproven source timing.

## 13. Dirty-sample gates

### 13.1 Classification states

The loader classifies:

- `TRAINABLE` when coverage is at least 20%, no recorded stale fields, and no recorded missing fields;
- `MISSING_MASKED` when missing fields remain;
- `STALE_MASKED` when stale fields remain;
- `INSUFFICIENT_V2_DATA_COVERAGE` below 20%;
- `MARKET_STATE_REJECTED` after trust/contract rejection.

See `data_loader.py:311-334` and `1161-1259`. Prediction publication applies a separate configured coverage threshold, default 70%, so 20% loader construction is not equivalent to prediction eligibility (`hybrid_cuda_trainer/config.py:29-33`, `94-116`).

### 13.2 Hard temporal/finality rejects

The historical missing-mask override cannot waive (`sample_rejection.py:15-28`):

- `AVAILABLE_AT_AFTER_DECISION_TIME`;
- `FEATURE_CUTOFF_AFTER_DECISION_TIME`;
- backfilled/unavailable-at-decision evidence;
- unfinished or unknown candle finality;
- stale feature family;
- missing source event or decision cutoff;
- source/feature timestamp after decision cutoff.

MTF-specific extra checks reject missing/invalid snapshot, propagated MTF reasons, MASA/PPO mismatch, MASA cutoff after decision, and backfill marked live (`data_loader.py:571-588`).

### 13.3 Missing-mask exception

Historical/trusted replay may train with explicitly masked absent schema families when all of these are proved (`sample_rejection.py:57-153`):

- explicit `safe_to_train_with_missing_mask=true`;
- historical/replay scope;
- reconstructable classification;
- lineage and classification masks;
- source availability recorded/preserved;
- no stale family;
- no core OHLC family missing;
- no hard temporal/finality rejection;
- no unrelated reject reason.

`classify_training_sample` then removes only tolerated missing-family/integrity-score reasons (`sample_rejection.py:156-184`).

The replay loader contains an additional direct exception: when the sole reason is `MISSING_CRITICAL_FEATURE_FAMILY`, it sets the safe flag, clears rejection reasons, and admits the row (`data_loader.py:1718-1746`). Stale-masked rows still reject.

### 13.4 High-confidence-loss trust exception

For a losing row with confidence at least 0.70, `_feedback_trust_rejection_reasons` removes every `MISSING_TRUST_*` reason (`data_loader.py:527-568`). It does not remove explicit future-availability/cutoff reasons.

This allows loss-calibration rows whose required lineage fields are absent. Such rows may be useful diagnostically, but they are not equivalent to fully reproducible training evidence and must be counted separately.

### 13.5 Other dirty conditions

Rows also reject or quarantine for:

- explicit paper-admission/entry-gate quarantine reasons;
- incomplete required feedback fields;
- non-finite or missing required targets;
- feature snapshot missing/empty;
- future-label names present in the input feature dictionary;
- no later finalized candles for replay;
- missing 5m/15m/1h/4h outcome horizons;
- missing entry price.

Trusted replay checks and horizons are at `trusted_replay/dataset.py:17-30` and `234-302`.

### 13.6 Trusted replay label defect relevant to lineage

Trusted replay uses a default two-basis-point round-trip cost (`dataset.py:267-273`) and builds after-cost movement from finalized candles. At `dataset.py:321-323`, it calls:

```python
trade_outcome = _trade_outcome(abs(after_cost) if target_action in {"long", "short"} else 0.0)
```

Therefore every nonzero move large enough to create a long/short target becomes `WIN` regardless of the prediction's `selected_action`; a prediction that chose the wrong side can still receive a win label. This is a label-integrity defect, not future leakage, but it makes replay outcomes unsuitable as unquestioned truth.

## 14. Redis lineage surfaces

### 14.1 Feature and candle keys

The most relevant native keys are:

| Key/pattern | Role |
|---|---|
| `v2:market:kline_current:{exchange}:{symbol}:{timeframe}` | Current/unfinalized canonical candle. |
| `v2:market:ohlcv_closed:{exchange}:{symbol}:{timeframe}` | Closed canonical candle series. |
| `v2:market:ohlcv:{exchange}:{symbol}:{timeframe}` | Compatibility candle source. |
| `v2:features:latest:{symbol}:{timeframe}` | Current native feature snapshot. |
| `v2:features:snapshot:{feature_snapshot_id}` | TTL-bound immutable-by-ID snapshot copy. |
| `v2:features:snapshots` | Snapshot ID index/list. |
| `v2:features:ta_full:{symbol}:{timeframe}` | Full TA input. |
| `v2:features:unified:{symbol}:{timeframe}` | TA/provider bridge payload. |
| `v2:unified_features:{symbol}:{timeframe}` | Separate hash read by the direct external merge; not the same key as `v2:features:unified:*`. |
| `v2:prediction:{symbol}:{timeframe}` | Current model prediction. |
| `v2:replay:snapshots:{prediction_id}` | Replay snapshot, nominally 24-hour TTL. |

The loader’s complete supplemental key list is constructed at `data_loader.py:937-992` and `1040-1118`; it is the source of truth for all current tensor-side dependencies.

### 14.2 Trainer lineage keys

Constants at `hybrid_cuda_trainer/config.py:39-51` define:

- `v2:trainer:hybrid_cuda:heartbeat`;
- `v2:trainer:hybrid_cuda:status`;
- `v2:trainer:hybrid_cuda:metrics`;
- risk/orchestrator/paper preview keys;
- `v2:trainer:hybrid_cuda:signals:paper:{symbol}`;
- `v2:trainer:hybrid_cuda:signals:paper:{symbol}:{timeframe}`.

The publisher also writes per-ID decision records and candidate/signal indexes at `publisher.py:1423-1545`.

## 15. Durable archive contract

The archive is intended to be the disk source of truth after Redis TTL expiry (`durable_feature_snapshot_archive.py:1-22`).

Required record fields (`durable_feature_snapshot_archive.py:24-40`):

```text
snapshot_id
symbol
timeframe
feature_cutoff
decision_time
available_at
mtf_snapshot_id
features
missing_mask
stale_mask
source_availability
source_hashes
schema_version
content_sha256
created_at
```

`verify_record` validates required fields, nonempty features, content hash, timestamp parseability, `feature_cutoff <= decision_time`, and `available_at <= decision_time` (`durable_feature_snapshot_archive.py:236-262`).

Storage is content-addressed by `content_sha256`, with a separate snapshot-ID index (`durable_feature_snapshot_archive.py:97-115`, `265-304`). A changed content hash for an existing snapshot ID raises `SNAPSHOT_ID_CONTENT_HASH_CHANGED`.

### 15.1 Durability limitations

- JSON object/index writes use temporary-file replacement.
- `manifest.jsonl` is append-only through a plain file append without an explicit interprocess lock or `fsync` (`durable_feature_snapshot_archive.py:111-121`).
- Publisher calls `append_snapshot(..., update_checksum_manifest=False)` (`publisher.py:1180-1187`), so the checksum manifest is not current after every prediction.
- `iter_index_records` prefers `manifest.jsonl` when it exists (`durable_feature_snapshot_archive.py:395-428`).
- Rollover deletes blob and index paths but does not remove/rewrite manifest entries (`durable_feature_snapshot_archive.py:555-584`).
- Checksum-manifest rebuild iterates the preferred manifest records, so deleted/tombstoned entries can remain represented (`durable_feature_snapshot_archive.py:526-543`).
- Cursor replay over the append-only manifest can repeatedly encounter an entry whose blob/index was deleted.

## 16. Publication/archive split-brain defect

The prediction payload is created with a predeclared replay ID/key and `replay_snapshot_write_success=false` (`publisher.py:1092-1098`).

`publish_prediction` then makes a top-level copy (`publisher.py:1176-1180`). Archive success/failure fields, paper-block flags, and replay-write success are mutated only on that copy. The runtime ignores the returned Boolean and calls `publish_lineage` with the original payload (`runtime.py:675-717`).

`publish_lineage` requests replay-write validation (`publisher.py:1288-1291`), but `validate_prediction_trust_contract` accepts either:

```text
replay_snapshot_write_success is true
OR
replay_snapshot_id and replay_snapshot_key are merely present
```

at `trust.py:348-352`. No Redis client is passed, so the optional key-existence check at `trust.py:366-374` does not run.

Consequences:

1. Redis replay write can fail.
2. `publish_prediction` can return false.
3. Runtime can still publish orchestrator/risk/paper lineage.
4. The original payload’s predeclared key can satisfy the trust contract without existing.
5. Durable-archive failure blocks are lost with the copied payload.
6. Archive, current prediction, replay snapshot, signal, and paper lineage can disagree.

This is fail-open lineage behavior. Any rebuild must make publication result, replay persistence, archive persistence, and downstream eligibility one explicit transaction/state machine, or carry a durable failure state that every downstream gate honors.

## 17. Identity and lineage chain

| ID/hash | Input material | Boundary/limitation |
|---|---|---|
| `candle_id` | Exchange, symbol, timeframe, open, close, raw-payload hash | Binds one canonical candle version. |
| `mtf_snapshot_id` | Decision time, selected candle metadata, missing/gap flags | Binds five-timeframe selection, including current minimum-cutoff semantics. |
| `feature_snapshot_id` | Hash of the native snapshot payload before ID insertion | Binds serialized feature snapshot, including generation time and attached context present at hashing. |
| `tensor_id` | Symbol, timeframe, feature snapshot ID, values, missing and stale masks | Does not independently bind per-source timestamps/source labels. |
| `content_sha256` | Canonical durable archive record excluding its hash field | Strong content identity when record verification succeeds. |
| `prediction_id` | Symbol, timeframe, tensor ID, model ID | Does not bind exact checkpoint weights when model ID is architecture-derived. |

Lineage must be verified by following all links, not by trusting any one ID.

## 18. Rebuild requirements

A faithful but temporally safe copy needs all of the following:

1. Preserve raw source record, source sequence, event time, actual ingestion time, and raw hash.
2. Store open and finalized candles separately.
3. Require explicit source finality or a documented REST finality rule; do not synthesize ingestion at close.
4. Build higher timeframes only from complete finalized lower-timeframe slots.
5. Select all required MTF candles as of one immutable decision time.
6. Store each feature’s source key, source record ID/hash, event time, available time, cutoff, transformation version, and stale state.
7. Resolve external/provider data with an as-of query, not a latest-key lookup.
8. Reject missing or unparseable temporal proof for required features.
9. Compute aggregate availability/cutoff from per-source maxima while retaining the full vector.
10. Freeze and content-hash an immutable feature snapshot before tensor construction.
11. Build the exact 477-slot values/missing/stale/availability layout in `FEATURE_SPEC` order.
12. Treat numeric presence separately from temporal availability.
13. Never use Boolean truthiness to resolve numeric fallback values.
14. Persist replay and durable archive evidence before declaring a prediction eligible.
15. Verify archive content hash and Redis/archive linkage before feedback/replay reuse.
16. Keep future labels outside the feature dictionary and behind finalized outcome horizons.
17. Record dirty-sample exception reason and lane; never silently convert an exception into ordinary clean evidence.
18. Bind prediction/checkpoint identity to the exact weight artifact hash.

## 19. Change-impact matrix

| Change | Direct effects | Required migration/verification |
|---|---|---|
| Add/remove/reorder `FEATURE_SPEC` | Tensor offsets and input width; masks; source labels; model/checkpoint shapes; replay reconstruction | New schema version, checkpoint incompatibility handling, tensor fixtures, archive reader compatibility, all feature tests. |
| Change a feature alias/fallback | Numeric values, missing coverage, tensor IDs, predictions | Zero-value tests, source attribution tests, before/after sampled tensors. |
| Change finality rule | Available candles, MTF validity, sample count, signal cadence | WSS/REST/resampler/MTF tests and historical reclassification report. |
| Change `feature_cutoff` from minimum to maximum | MTF IDs, temporal gates, archive hashes, replay selection | Explicit schema migration and fixture regeneration; audit every consumer assuming minimum. |
| Change timestamp fallback | Training acceptance, prediction eligibility, archive validity | PIT adversarial tests with missing, malformed, future, and late-ingested sources. |
| Change external/provider source | Feature values and freshness without necessarily changing schema | Source-specific as-of contract, TTL/freshness tests, provider masks, reconstruction test. |
| Change missing/stale policy | Dataset composition, coverage, model behavior | Clean/missing/stale matrix, hard-reason non-bypass tests, exception counters. |
| Change snapshot TTL | Redis memory and replay reconstructability | Archive-read proof, referenced-ID retention, expiry integration test. |
| Change archive rollover | Replay cursor, pinned references, checksum state | Crash/partial-write, tombstone, cursor-resume, pinning and checksum tests. |
| Change Redis key | Every producer/consumer and dashboard | Dual-read/write migration or coordinated cutover; registry scan. |
| Change snapshot schema name only | Does not make contracts equivalent | Field-by-field adapter and provenance validation. |

## 20. Required test suites for changes

Run the narrow suite relevant to the change in an isolated test environment. Do not point integration tests at production/workspace Redis or live paper state.

```bash
.venv/bin/pytest -q \
  v2/backend/tests/unit/test_canonical_candles_and_mtf_snapshot.py \
  v2/backend/tests/unit/services/market_data_trust/test_event_time_aligner_contract.py \
  v2/backend/tests/unit/services/market_data_trust/test_real_path_guards.py \
  v2/backend/tests/unit/services/provider_features/test_provider_feature_bridge.py \
  v2/backend/tests/unit/services/feature_pipeline/test_provider_unified_feature_bridge.py \
  v2/backend/tests/unit/cli/test_v2_feature_pipeline_native_loop.py \
  v2/backend/tests/integration/cli/test_v2_feature_pipeline_native.py \
  v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py \
  v2/backend/tests/unit/services/native_trainer/test_ta_full_feature_expansion.py \
  v2/backend/tests/unit/services/native_trainer/test_advanced_indicator_tensor_fields.py \
  v2/backend/tests/unit/services/native_trainer/test_historical_missing_mask_admission.py \
  v2/backend/tests/unit/services/native_trainer/test_durable_feature_snapshot_archive.py \
  v2/backend/tests/unit/services/native_trainer/test_trusted_replay_bootstrap.py \
  v2/backend/tests/unit/services/native_trainer/test_trusted_replay_cursor.py \
  v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py
```

Minimum adversarial fixtures must include:

- open WSS candle;
- closed WSS candle received late;
- REST row fetched after the hypothetical decision;
- missing and future `available_at`;
- missing and future feature cutoff;
- incomplete resampling slot set;
- unfinished 1h/4h target window;
- one missing required MTF candle;
- provider payload stale but otherwise numeric;
- provider timestamps absent, malformed, and after decision;
- external current key newer than historical snapshot;
- legitimate numeric zero through every fallback path;
- family-level stale flag versus exact feature names;
- missing-mask replay with and without core OHLC;
- high-confidence loss with missing trust envelope;
- replay/archive write failure followed by attempted lineage publication;
- rollover manifest entry whose blob/index was deleted;
- tensor/order assertion for every feature offset.

## 21. Operator/developer checklist

Before calling a snapshot or training row point-in-time safe, answer all of these from evidence:

1. What exact source record and hash produced each used feature?
2. Was its candle/window final?
3. What were `event_time`, actual `ingested_at`, and `available_at`?
4. Were all three at or before the original model decision time?
5. Did an external/provider latest-key read occur after the snapshot cutoff?
6. Are per-source cutoffs retained, or only the misleading aggregate minimum?
7. Is a source-availability bit being mistaken for temporal availability?
8. Was any timing/finality value inferred from `generated_at`?
9. Was a missing-mask or high-confidence exception used?
10. Does the replay key exist and does the durable archive hash verify?
11. Can the exact 1,908 input vector be reconstructed without reading newer Redis state?
12. Does the prediction identify the exact weight artifact, not just architecture?

If any answer is unknown, the row is not clean promotion evidence.

## 22. Known gaps register

| Severity | Gap | Effect |
|---|---|---|
| Critical | External latest-key merges lack per-source as-of enforcement | Historical/current feature lineage cannot prove no future value entered. |
| Critical | Publisher copy/return handling permits replay/archive failure to diverge from downstream lineage | A signal can reference a nonexistent replay snapshot or missing durable archive. |
| High | Raw REST/list reconstruction sets ingestion to candle close | Hides fetch latency and can launder historical availability. |
| High | MTF aggregate `feature_cutoff` is minimum close | Misstates latest information used and weakens collapsed downstream checks. |
| High | Missing provider timestamps do not exclude; stale provider data can remain included | Numeric provider fields can enter without complete timing/freshness proof. |
| High | Loader supplements snapshots with current Redis state | Archived feature snapshots can be reconstructed with newer values. |
| High | High-confidence losing rows discard all missing-trust reasons | Some training evidence is not reproducible. |
| Medium | Replay missing-family exception admits masked rows | Dataset is intentionally heterogeneous; clean and exception rows must remain separate. |
| Medium | Source availability equals numeric presence | Consumers can overstate provenance/freshness. |
| Medium | Boolean `or` fallbacks replace legitimate zeros | Tensor values and masks can be wrong. |
| Medium | Stale flags often require exact feature-name match | Family staleness can be under-represented. |
| Medium | Archive rollover leaves append-only manifest references | Replay/checksum traversal can encounter deleted records. |
| Medium | Multiple incompatible snapshot contracts share similar names | Operators/adapters can connect the wrong snapshot plane. |

The safe conclusion is narrow: canonical closed-candle selection is well defended when canonical mappings and complete timestamps reach it. The full native feature and replay pipeline is not yet end-to-end point-in-time provable.
