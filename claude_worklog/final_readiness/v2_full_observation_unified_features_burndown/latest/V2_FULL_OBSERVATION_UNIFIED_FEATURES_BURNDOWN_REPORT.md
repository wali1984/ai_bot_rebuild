# V2 Full-Observation Builder — Unified-Features Burndown

**Generated:** 2026-05-21 (UTC)
**GO_NO_GO:** `V2_FULL_OBSERVATION_UNIFIED_FEATURES_BURNDOWN_READY_PARTIAL_PROGRESS`

## Mandate

Following the Codex PASS on the portfolio-state burndown, continue the
1911-dim full-observation parity push. This packet expands V2-buildable
gaps inside the `unified_features` slice. **No policy architecture
work. No checkpoint-compatibility claim. No live enablement.**

## What shipped

### Single file changed

[v2/backend/app/services/rl_core/full_observation_builder.py](../../../../v2/backend/app/services/rl_core/full_observation_builder.py)

The `_project_coinank` projector was extended from 16 sourced fields
to 22 (completes the subfamily target). All six new fields are
derived strictly from existing V2-native market payloads — **no new
Redis read, no paid aggregator, no legacy source**.

### Six new coinank fields

| Field | Derivation | Source label when present |
|-------|-----------|----------------------------|
| `coinank.seconds_until_next_funding` | `(funding.nextFundingTime − funding.time) / 1000` | `V2_DERIVED_FROM_FUNDING` |
| `coinank.funding_payload_age_seconds` | `(now − funding.time) / 1000` | `V2_DERIVED_FROM_FUNDING_TIMESTAMP` |
| `coinank.oi_payload_age_seconds` | `(now − open_interest.time) / 1000` | `V2_DERIVED_FROM_OPEN_INTEREST_TIMESTAMP` |
| `coinank.funding_oi_direction_agreement` | `1.0 if sign(funding_rate) == sign(oi_change_pct) else 0.0` | `V2_DERIVED_FROM_FUNDING_AND_FEATURES` |
| `coinank.funding_rate_bps` | `lastFundingRate × 10000` | `V2_DERIVED_FROM_FUNDING` |
| `coinank.mark_premium_to_index_bps` | `((markPrice − indexPrice) / indexPrice) × 10000` | `V2_DERIVED_FROM_FUNDING` |

When an input field is missing, the new field becomes `None` with a
specific `MISSING_FROM_V2_FUNDING` / `MISSING_FROM_V2_OI` /
`MISSING_FROM_V2_FEATURES` label. **Nothing is silently zeroed.**

## generated_dim — before vs. after

| Symbol | Before this packet | After this packet | Δ |
|--------|--------------------:|------------------:|--:|
| BTCUSDT | 217 / 1911 | **223 / 1911** | +6 |
| ETHUSDT | 217 / 1911 | **223 / 1911** | +6 |
| SOLUSDT | 207 / 1911 | **213 / 1911** | +6 |
| **Aggregate** | 641 / 5733 | **659 / 5733** | **+18** |

Coinank subfamily completed: **66 / 66 across all symbols**.

`zero_filled_field_count` remains `0` aggregate. State remains
`FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` — no
`FULL_OBSERVATION_BUILDER_COMPLETE` claim.

## missing_field_count

| Symbol | missing_field_count |
|--------|--------------------:|
| BTCUSDT | 1688 |
| ETHUSDT | 1688 |
| SOLUSDT | 1698 |

## Subfamily layout — present / target / gap

| Subfamily | Per-symbol target | Aggregate target | Aggregate present | Gap |
|-----------|------------------:|-----------------:|------------------:|----:|
| binance_klines | 20 | 60 | 60 | **0** |
| binance_orderbook | 15 | 45 | 45 | **0** |
| ccxt_ohlcv | 10 | 30 | 0 | 30 (OPERATOR_DECISION_REQUIRED) |
| **coinank** | **22** | **66** | **66** | **0 ← completed this packet** |
| liquidations | 12 | 36 | 24 | 12 (V2 WSS publisher missing) |
| portfolio_state_unified | 15 | 45 | 45 | **0** |
| technical_analysis | 25 | 75 | 72 | 3 (MACD_ZERO_RATIO_UNDEFINED at runtime) |
| token_metrics | 18 | 54 | 0 | 54 (EXTERNAL_SOURCE_REQUIRED) |

`next_required_family` (selected by the builder's residual-gap
heuristic): **`liquidations`**.

## Exact remaining blockers for full 1911 parity

1. **`unified_features.liquidations`** (12 dim gap) — needs a real
   V2 WSS event publisher writing
   `v2:market:liquidations:latest:{sym}` and
   `v2:market:liquidations:aggregate:{sym}`. Today **both keys are
   absent in Redis**, so the slots remain honestly
   `MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`. This packet does not
   fabricate them.
2. **`unified_features.technical_analysis`** (3 dim gap) — the 25th
   slot (`macd_signal_strength`) is `None` with source
   `MACD_ZERO_RATIO_UNDEFINED` whenever `macd == 0`. This is a
   mathematically-degenerate state, not a missing source. The
   honest position is to leave it None.
3. **`unified_features.ccxt_ohlcv`** (30 dim gap) — gated by
   `OPERATOR_DECISION_REQUIRED_SECONDARY_EXCHANGE_OHLCV`.
4. **`unified_features.token_metrics`** (54 dim gap) — gated by
   `EXTERNAL_SOURCE_REQUIRED_NO_V2_NATIVE_TOKEN_METRICS`.
5. **`unified_features` slice tail** (1293 dim) — explicit
   `MISSING_LEGACY_V3_EXTRA_NO_V2_SOURCE` (legacy V3 fields with no
   V2-native equivalent today).
6. **`portfolio_state`** (401 dim slice) — residual V2-native field
   gap (handled by separate portfolio-state burndown packets).
7. **`onchain_btc` / `onchain_eth`** (15 dim each) — gated by
   `EXTERNAL_SOURCE_REQUIRED`.

## Why I did NOT expand liquidations or technical_analysis here

- **Liquidations**: I checked Redis directly. Neither
  `v2:market:liquidations:latest:{BTC,ETH,SOL}USDT` nor
  `v2:market:liquidations:aggregate:{BTC,ETH,SOL}USDT` exist. The
  user's rule was explicit: "additional liquidation fields only if
  real WSS event keys exist." They don't. So the gap remains.
- **Technical_analysis 25th slot**: The slot is *defined* and
  *sourced*; it just evaluates to `None` because `macd == 0`
  makes the strength ratio undefined. The honest position is to
  leave it None — re-defining it to `0.0` would silently invent
  a "no signal" semantic the model has never seen.
- **`token_metrics` / `onchain_btc` / `onchain_eth` /
  `ccxt_ohlcv`**: All explicitly listed by the user as fields that
  must remain missing absent operator decision or external source.
  Their source labels are unchanged by this packet.

## Tests — 49 / 49 PASS

| Suite | Total | Passed | Note |
|-------|------:|-------:|------|
| `test_v2_full_observation_unified_features_burndown.py` | 16 | 16 | new (this packet) |
| `test_v2_full_observation_builder.py` | 8 | 8 | no regression |
| `test_v2_full_observation_position_history_tracker_only_consumption.py` | 10 | 10 | no regression |
| `test_v2_full_observation_post_tracker_position_feature_expansion.py` | 15 | 15 | no regression |

The new test file pins:

- Each of the six new field names is emitted with a V2-native source
  attribution when its underlying market payload is present.
- `seconds_until_next_funding` is computed correctly from
  `funding.nextFundingTime − funding.time` and returns `28800.0`
  (the standard 8-hour funding interval) for a synthetic happy path.
- Missing inputs propagate to `None` with the correct
  `MISSING_FROM_V2_*` label — no silent zero.
- `funding_oi_direction_agreement` is `1.0` when both directions
  match, `0.0` when they disagree, and `None` (with the specific
  missing-source label) when either input is absent.
- `funding_rate_bps` and `mark_premium_to_index_bps` are honest unit
  conversions; no extra hidden math.
- Payload-age fields are non-negative and carry the
  `V2_DERIVED_FROM_*_TIMESTAMP` source.
- The coinank projector's output is **exactly 22 slots** (subfamily
  size budget unchanged).
- When all inputs are absent, every data slot is `None` with
  `MISSING_FROM_V2_*`; the single probe-flag slot
  (`v2_coinank_aggregator_source_available`) emits `0.0` with
  `V2_PROBE_FLAG_NO_COINANK_AGGREGATOR_PRESENT` — honest evidence,
  not fabricated data.
- `TARGET_FULL_DIM == 1911`, `SLICE_SIZES` unchanged, slice-size sum
  still equals 1911.
- `compact_observation_v1.dim == 26` (existing runtime policy input
  unchanged).
- `token_metrics`, `onchain_btc`, `onchain_eth`, `ccxt_ohlcv`
  source labels unchanged.
- Aggregate `zero_filled_field_count == 0` end-to-end.
- Builder result never claims
  `FULL_OBSERVATION_BUILDER_COMPLETE` on a partial vector.
- Builder status payload pins
  `checkpoint_compatibility_claimed=false`,
  `policy_architecture_parity_claimed=false`,
  `live_gate=blocked_human_only`, `live_symbols=[]`, and the four
  `approves_*=false` flags.

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` — **PASS**. 22 files
scanned. 0 secret / approval_true / legacy_redis / exchange_mutation
hits. 0 JSON parse failures. 0 missing files.

## Refreshed payloads

The builder was run live against current Redis and the refreshed
status was written to:

- `claude_worklog/final_readiness/v2_full_observation_unified_features_burndown/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_full_observation_unified_features_burndown/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_model_parity_sprint/latest/full_observation_builder_status.json` (the canonical operator-dashboard path)
- `claude_worklog/final_readiness/v2_model_parity_sprint/latest/full_observation_builder_status.json`
- `v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json`

The operator-dashboard payload for this packet
(`operator_dashboard_payload.json`) mirrors the worklog
status JSON for the public frontend at
`v2/frontend/public/v2_full_observation_unified_features_burndown/latest/operator_dashboard_payload.json`.

## What this packet did NOT do

- Did NOT add any new Redis consumer; the publisher reads only the
  V2-native keys it was already authorised to read.
- Did NOT call any external paid aggregator (CoinAnk / Glassnode /
  CryptoQuant / IntoTheBlock / token-metrics provider).
- Did NOT call any exchange endpoint.
- Did NOT expand liquidations / token_metrics / onchain_btc /
  onchain_eth / ccxt_ohlcv (those remain
  `EXTERNAL_SOURCE_REQUIRED` / `OPERATOR_DECISION_REQUIRED` or
  blocked on a missing V2 publisher).
- Did NOT modify any tracker writer, consumption gate, or
  position-history daemon.
- Did NOT mutate `paper_symbols`, `training_symbols`, or
  `live_symbols`.
- Did NOT change `SLICE_SIZES`, `TARGET_FULL_DIM`, or
  `compact_observation_v1.dim`.
- Did NOT claim `FULL_OBSERVATION_BUILDER_COMPLETE`,
  `checkpoint_compatibility_claimed=true`, or
  `policy_architecture_parity_claimed=true`.
- Did NOT silently zero-fill any field. Missing inputs propagate to
  `None` with explicit source labels.
- Did NOT modify `/home/wali/Desktop/AI BOT`.
- Did NOT stop or modify the legacy or V2 runtime.
- Did NOT create any approval token, Codex marker, or live
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
- `compact_observation_v1.dim=26`
- `no_zero_fill_for_unknown_fields=true`
- `no_legacy_features_consumed_as_current_truth=true`
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
