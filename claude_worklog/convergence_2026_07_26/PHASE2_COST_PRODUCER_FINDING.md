# Phase 2 finding — exact-cost blocker is a producer deployment/wiring gap, not a data gap

**Date:** 2026-07-26

## Claim
The `exact_cost_provenance` strict-UTC clock lineage that `build_exact_cost_provenance`
requires (and that blocks directional routability) is **already emitted by the
current cost-producer code** — it is simply absent from the running
`v2:costs:round_trip_bps:{symbol}` payload, meaning the running producer is a stale
deployment (or a second, simpler writer owns the key).

## Raw evidence
- `v2/backend/app/services/paper_trade_management/adaptive_cost_model.py` `to_dict`
  (lines 293-344) emits every field the consumer needs:
  - `available_at` (line 318), `expires_at` (line 340)
  - `orderbook_observed_at` (328), `orderbook_available_at` (329),
    `orderbook_generated_at` (330), `orderbook_source_clock_field` (331)
  - `computed_utc` (317) becomes `generated_at`
- `build_exact_cost_provenance` (on_policy_behavior.py:245-296) requires exactly:
  `computed_utc`, `available_at`, `expires_at`, `orderbook_observed_at`,
  `orderbook_available_at`, `orderbook_generated_at`, with the ordering
  `orderbook_observed_at <= orderbook_available_at <= orderbook_generated_at <= ... <= expires_at`.
- Running payload `redis GET v2:costs:round_trip_bps:BTCUSDT` keys = {computed_utc,
  round_trip_cost_bps, spread_bps, spread_source, spread_age_seconds,
  impact_per_side_bps, taker_fee_bps_per_side, orderbook_key, freshness_status,
  estimator_version=adaptive_cost_model_v1, ...} — **missing** available_at,
  expires_at, and all three orderbook_* clocks.

## Verification command
`redis-cli GET v2:costs:round_trip_bps:BTCUSDT` and compare its keys to the
`adaptive_cost_model.CostEstimate.to_dict` field set.

## Phase-2 action (bounded)
Identify the running writer of `v2:costs:round_trip_bps:*`
(candidates: all_timeframe_prediction_signal_price_target_publisher.py, or a stale
adaptive_cost_model deployment) and deploy/wire it to emit the current
`adaptive_cost_model.to_dict` schema. Do NOT relax `build_exact_cost_provenance` in
the consumer (per convergence rule "fix the producer, not the consumer"). Once the
running payload carries the strict-UTC lineage, the canonical serving runtime's
directional records clear the `ordinary_paper_exact_cost` block.

## Confidence
High — the required fields exist in current source; the gap is runtime payload
population, verified against a runtime Redis read.

## Missing evidence
Which exact process/SHA currently writes the running key (needs a producer-side
trace); this determines whether the fix is a redeploy or a small wiring change.
