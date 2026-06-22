# V2 CoinAnk Aggregator Decision Refinement Report

GO/NO-GO: `V2_COINANK_AGGREGATOR_DECISION_REFINEMENT_READY`

Read-only probe. Does NOT modify `full_observation_builder.py`,
legacy, or any external feed. Does NOT approve live, canary,
leverage/margin, exchange mutation, legacy shutdown, or Redis trim.

## Subfamily state

- Target per symbol: **22**
- Filled per symbol today: **16** (after round-2/round-3 builder
  derivations — funding/OI/basis/derived signs and absolutes)
- Missing per symbol today: **6**

## Decomposition of the 6 missing slots

All 6 slots correspond to legacy CoinAnk paid-aggregator data
families. None are derivable from current V2 funding/OI/price data
alone.

| Slot | V2 source status | Derivable today? |
| ---- | ---------------- | :--------------: |
| `long_short_ratio_global` | EXTERNAL_PAID_AGGREGATOR_REQUIRED | no |
| `long_short_ratio_top_traders` | EXTERNAL_PAID_AGGREGATOR_REQUIRED | no |
| `exchange_netflow_proxy` | EXTERNAL_PAID_AGGREGATOR_REQUIRED | no |
| `whale_position_intent_proxy` | EXTERNAL_PAID_AGGREGATOR_REQUIRED | no |
| `regional_long_share` | EXTERNAL_PAID_AGGREGATOR_REQUIRED | no |
| `regional_short_share` | EXTERNAL_PAID_AGGREGATOR_REQUIRED | no |

Rationale: legacy CoinAnk paid feed publishes a global long/short
ratio, top-trader bucketing, exchange netflow, whale-position
intentions, and regional shares. V2 has no equivalent source today;
`coinank_market_intelligence_status.global_aggregate_result.long_short_ratio`
is the cross-symbol global proxy, not a per-symbol value. Treating
all 6 slots as paid-aggregator-required is the honest classification.

## Counts

- `computable_from_v2_without_aggregator_count = 0`
- `external_paid_aggregator_required_count = 6`

## Operator decision options

- **DEFER_COINANK_AGGREGATOR** (current default): keep 6 slots
  explicit-missing.
- **APPROVE_COINANK_AGGREGATOR_SCOPE**: provide credentials and V2
  ingestor scope for the CoinAnk paid aggregator; separate Codex review
  pair required before adoption.

Current default state: **DEFER_COINANK_AGGREGATOR**.

## Safety

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- `modifies_full_observation_builder = false`
- `modifies_legacy = false`
- `creates_external_feed = false`
- `creates_credentials = false`
- `loads_any_blob = false`
- `no_raw_credentials_in_packet = true`
