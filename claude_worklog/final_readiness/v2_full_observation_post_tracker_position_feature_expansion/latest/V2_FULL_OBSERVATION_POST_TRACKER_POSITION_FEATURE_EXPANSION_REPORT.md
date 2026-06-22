# V2 Full-Observation Builder — Post-Tracker Position-Context Feature Expansion

**Generated:** 2026-05-21 (UTC)
**GO_NO_GO:** `V2_FULL_OBSERVATION_POST_TRACKER_POSITION_FEATURE_EXPANSION_READY`

## Mandate

Following the Codex PASS on
`V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS` (consumption gate
ALLOWED) and the prior parity packet
`V2_FULL_OBSERVATION_POSITION_HISTORY_TRACKER_ONLY_CONSUMPTION_READY`,
this packet expands the `position_context` slice's tracker-derived
field set by 6 additional fields. Every new field is sourced strictly
from one of the three Codex-passed tracker Redis keys:

- `v2:paper:position_history:{symbol}`
- `v2:paper:position_price_track:{symbol}`
- `v2:paper:position_history:heartbeat` (consumption-gate signal)

The packet **adds no raw paper ledger / intents / positions read** for
tracker-derived fields. **No MFE / MAE / ROE fabrication.**
`zero_filled_field_count` remains `0`.

## What shipped

### Code changes

[v2/backend/app/services/rl_core/full_observation_builder.py](../../../../v2/backend/app/services/rl_core/full_observation_builder.py)

- New constant `TRACKER_EXTENDED_FIELDS` listing the 6 new fields
  (disjoint from the existing 10-field
  `TRACKER_HISTORY_DERIVED_FIELDS` contract).
- New helper `_extract_tracker_extended_fields(...)` that takes ONLY
  tracker payloads + gate inputs (its function signature deliberately
  excludes `paper_positions` / `paper_ledger` / `paper_intents` /
  `paper_intents_held`).
- `_build_position_context_slice` now calls the extended extractor
  immediately after the existing tracker-history extractor, so all
  16 tracker-only position-context fields are emitted in one place
  under the same consumption gate.

No other file in the builder, the recorder, the persistent tracker,
or any CLI was touched.

### The 6 new tracker-only fields

| Field | Source field in tracker payload | When sourced |
|-------|----------------------------------|-------------|
| `v2_tracker_latest_price` | `position_price_track.latest_price` | OPEN position |
| `v2_tracker_entry_price` | `position_price_track.entry_price` | OPEN position |
| `v2_tracker_source_freshness_seconds` | `position_price_track.source_freshness_seconds` | OPEN position |
| `v2_tracker_missing_flag_count` | `len(position_price_track.missing_flags)` | always (when payload present) |
| `v2_tracker_stale_flag_count` | `len(position_price_track.stale_flags)` | always (when payload present) |
| `v2_shadow_observation_count` | `position_history.shadow_observation_count` | always (when payload present) |

All six use the source label `V2_POSITION_HISTORY_TRACKER` when their
underlying field is present in the tracker payload. When the field is
absent, the source becomes
`V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING` with `value=None`.
When the entire payload is missing, the source becomes
`V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING`. When the consumption
gate is blocked, the source becomes
`V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>`. Nothing is
ever zero-filled.

## generated_dim — before vs. after

| Symbol | Before this packet | After this packet | Δ |
|--------|--------------------|-------------------|---|
| BTCUSDT | 157 / 1911 | **160 / 1911** | +3 |
| ETHUSDT | 157 / 1911 | **160 / 1911** | +3 |
| SOLUSDT | 151 / 1911 | **154 / 1911** | +3 |

### Why +3 and not +6?

Every symbol's current tracker payload reports `position_state` in
`{FLAT, NO_OPEN_POSITION}` because the bot is in shadow / paper-only
mode and has no live position open. In that state the recorder
**honestly omits** `latest_price`, `entry_price`, and
`source_freshness_seconds`, so those three new fields stay `None` with
source `V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING`. The
remaining three (`missing_flag_count`, `stale_flag_count`,
`shadow_observation_count`) are always emitted by the tracker
regardless of position state, so they source today.

When (and only when) the bot opens a real paper position, the
remaining three fields will source automatically — no code change
required. This is exactly the "full observation remains partial
unless all 1911 dims are genuinely sourced" contract the user
required.

## missing_field_count

| Symbol | missing_field_count | new fields counted as missing |
|--------|--------------------:|-----------------------------:|
| BTCUSDT | 1751 | 3 (the price-bearing fields, honestly missing in NO_OPEN_POSITION) |
| ETHUSDT | 1751 | 3 (same) |
| SOLUSDT | 1757 | 3 (same) |

## Source attribution catalogue for position_context (all 50 dims)

| Group | Field count | Source label(s) when present |
|-------|-------------:|------------------------------|
| Paper-positions / risk / prediction / orchestrator-derived | 15 | `V2_PAPER_POSITIONS`, `V2_RISK_DECISIONS`, `V2_PREDICTION`, `V2_ORCHESTRATOR_DECISIONS` |
| PHASE-5 prediction-derived | 10 | `V2_PREDICTION`, `V2_DERIVED_FROM_PREDICTION`, `V2_PROBE_FLAG_POSITION_HISTORY_AGGREGATOR` |
| Tracker-history (10 fields, prior packet) | 10 | `V2_POSITION_HISTORY_TRACKER` (and the `NO_OPEN_POSITION` / `FIELD_MISSING` variants) |
| **Tracker-extended (6 fields, this packet)** | **6** | **`V2_POSITION_HISTORY_TRACKER`** (and the `PAYLOAD_MISSING` / `FIELD_MISSING` / `CONSUMPTION_BLOCKED:<reason>` variants) |
| Raw paper context (clearly labeled non-tracker) | 9 | `V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY` |
| **Total** | **50** | — |

The position_context slice now fills its entire 50-dim budget with
sourced field definitions. (Whether a given field carries a numeric
value at any single tick depends on the underlying tracker / paper
state at that tick — the builder reports honestly per tick.)

## Exact remaining blockers for full 1911 parity

This packet **does not** claim closure for any of the following:

1. **unified_features.binance_klines** — residual subfamily gap (no
   change in this packet).
2. **unified_features.binance_orderbook** — residual subfamily gap
   (no change in this packet).
3. **unified_features.token_metrics** — `EXTERNAL_SOURCE_REQUIRED`
   (Glassnode / CryptoQuant / IntoTheBlock — requires operator
   decision and Codex review of the new ingestor).
4. **unified_features.ccxt_ohlcv** — `OPERATOR_DECISION_REQUIRED_SECONDARY_EXCHANGE_OHLCV`.
5. **unified_features.liquidations** — `MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`
   (V2 liquidation aggregator coverage gap).
6. **unified_features.coinank** — V2 CoinAnk ingestor gap.
7. **portfolio_state (401-dim)** — 389 V2-native fields not yet
   sourced. Next-required-family already surfaced in the builder
   status payload.
8. **onchain_btc (15-dim)** — `EXTERNAL_SOURCE_REQUIRED`.
9. **onchain_eth (15-dim)** — `EXTERNAL_SOURCE_REQUIRED`.

Position-context is no longer the bottleneck for parity. Subsequent
packets should target the next-required-family selected by the
builder's residual-gap heuristic (currently a unified_features
subfamily, surfaced in the refreshed builder status under
`next_required_family`).

## Tests — 33 / 33 PASS

| Suite | Total | Passed | Note |
|-------|------:|-------:|------|
| `test_v2_full_observation_post_tracker_position_feature_expansion.py` | 15 | 15 | new (this packet) |
| `test_v2_full_observation_position_history_tracker_only_consumption.py` | 10 | 10 | no regression |
| `test_v2_full_observation_builder.py` | 8 | 8 | no regression |

The new test file pins the following invariants:

- `TRACKER_EXTENDED_FIELDS` is exactly the 6 named fields.
- The 6 fields are disjoint from the prior 10-field
  `TRACKER_HISTORY_DERIVED_FIELDS` contract.
- `_extract_tracker_extended_fields`'s function signature does NOT
  accept any of `paper_positions`, `paper_ledger`, `paper_intents`,
  `paper_intents_held`, `paper_intents_held_by_paper_fill_gate`.
- All 6 fields are masked with
  `V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>` when the
  gate is blocked.
- Missing payloads / wrong-symbol payloads yield `None` with
  `V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING`.
- Specific-field-absent yields `None` with
  `V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING`.
- An OPEN position with all tracker fields populated sources every
  field with `V2_POSITION_HISTORY_TRACKER`.
- `missing_flag_count` and `stale_flag_count` are sourced as
  `float(len(list))` when the list field is present (even when
  empty), and as `None` with `FIELD_MISSING` when the list key is
  fully absent.
- End-to-end builder run includes all 6 field names in
  `field_names` under the `position_context.*` prefix.
- `zero_filled_field_count` remains `0` on every code path.
- Static-source proof: the extractor function's *code body*
  (excluding docstring) contains no usage pattern referencing raw
  paper inputs.
- `SLICE_SIZES["position_context"]` remains exactly `50` and the
  slice-size total still equals `TARGET_FULL_DIM = 1911`.

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` — **PASS**. 22 files
scanned. 0 secret / approval_true / legacy_redis / exchange_mutation
hits. 0 JSON parse failures. 0 missing files.

## Refreshed payloads

The builder was run live against current Redis and the refreshed
status was written to:

- `claude_worklog/final_readiness/v2_full_observation_post_tracker_position_feature_expansion/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_full_observation_post_tracker_position_feature_expansion/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_model_parity_sprint/latest/full_observation_builder_status.json` (the canonical operator-dashboard path the frontend already polls)
- `claude_worklog/final_readiness/v2_model_parity_sprint/latest/full_observation_builder_status.json`

## What this packet did NOT do

- Did NOT modify the position-history persistent tracker, the
  position-price-tracking recorder, the consumption-gate evaluator,
  or any Redis-write boundary.
- Did NOT change `SLICE_SIZES`, `TARGET_FULL_DIM`, or any subfamily
  layout.
- Did NOT touch raw `v2:paper:positions`, `v2:paper:ledger`,
  `v2:paper:intents`, or `v2:paper:intents_held_by_paper_fill_gate`
  for tracker-derived fields.
- Did NOT fabricate MFE / MAE / ROE / hold-time / latest-price /
  entry-price / freshness values. Missing values remain genuinely
  `None`.
- Did NOT change `zero_filled_field_count` (stays `0`).
- Did NOT claim `checkpoint_compatibility_claimed=true` or
  `policy_architecture_parity_claimed=true`.
- Did NOT modify `/home/wali/Desktop/AI BOT`.
- Did NOT stop V2 or legacy runtime.
- Did NOT call any exchange endpoint.
- Did NOT call any provider endpoint.
- Did NOT enable live trading.
- Did NOT create any approval marker, Codex marker, or live
  enablement.
- Did NOT expose any raw API key value.

## Safety pins

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_symbols_expanded=false`
- `paper_symbols_expanded=false`
- `training_symbols_expanded=false`
- `zero_filled_field_count=0`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `no_fabricated_excursion_metrics=true`
- `no_synthesized_accepted_positions=true`
- `no_synthetic_intent_counts=true`
- `no_shadow_observations_counted_as_accepted=true`
- `no_zero_fill_for_unknown_fields=true`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `writes_old_redis=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- `provider_network_calls_attempted=false`
- `places_real_order=false`
- `real_order_attempted=false`
- `real_order_submitted=false`
