# Paper Edge Threshold Replay Report

Task: `paper_edge_threshold_replay`
Generated: `2026-05-14T00:00:00Z`
Source-of-truth paper JSONL: `v2/runtime/paper_online/latest/paper_events.jsonl` (`4474` lines at audit)

## Run Status

`THRESHOLD_REPLAY_NOT_YET_RUN`

The Phase D threshold replay CLI (`v2/backend/app/cli/paper_edge_threshold_replay.py`) is specified in the parent task report but has not been authored or executed in this writing window. Until the CLI is implemented and executed against `v2/runtime/paper_online/latest/paper_events.jsonl`, this report cannot claim either `NO_TRADE_EDGE_NOT_FOUND` or a positive `PROFILE_READY` configuration.

The honesty rule from the parent task is preserved: if every combination blocks every fill, the truthful classification is `NO_TRADE_EDGE_NOT_FOUND`, and the tool MUST NOT be tuned to manufacture a false live-readiness signal.

## Required Sweep Grid (Spec Only)

| Parameter | Values |
| --- | --- |
| `min_expected_move_after_cost_bps` | 4, 6, 8, 10, 12, 15 |
| `min_confidence` | 0.58, 0.65, 0.70, 0.75 |
| `cooldown_seconds` | configurable per run |
| `flip_churn_window_seconds` | configurable per run |
| `max_fills_per_symbol_per_hour` | configurable per run |

## Required Per-Combination Output Schema (Spec Only)

```
{
  "min_expected_move_after_cost_bps": <int>,
  "min_confidence": <float>,
  "cooldown_seconds": <int>,
  "flip_churn_window_seconds": <int>,
  "max_fills_per_symbol_per_hour": <int>,
  "simulated_fill_count": <int>,
  "blocked_count": <int>,
  "simulated_fee_usdt": <float>,
  "simulated_pnl_usdt": <float>,
  "win_rate": <float>,
  "profit_factor": <float>,
  "edge_coverage": <float>,
  "no_trade_classification": <bool>
}
```

## Pre-Flight Constraints To Be Enforced By The CLI

1. Replay MUST consume only `v2/runtime/paper_online/latest/paper_events.jsonl` and any archived pre-filter JSONLs explicitly identified as inputs; it MUST NOT consume legacy `/AI BOT/` data.
2. Replay MUST NOT write back to any old Redis key.
3. Replay MUST NOT emit any approval token, Redis trim approval, exchange order event, or live-readiness flag.
4. Replay MUST preserve `live_gate=blocked_human_only` and `live_symbols=[]` in every output payload.
5. Replay MUST output classification `NO_TRADE_EDGE_NOT_FOUND` if every combination in the sweep blocks every fill.
6. Replay MUST NOT search for a profile that masks negative edge by over-tightening to zero fills and then declaring `PROFILE_READY` — zero fills is `NO_TRADE_EDGE_NOT_FOUND` by construction, never `PROFILE_READY`.
7. Replay MUST cite, per combination, the input pre-filter rows and the post-filter event count it considered.

## Why This Report Is Not Yet Quantitative

The pre-filter paper event JSONL contains structured rows with `confidence`, `prediction_id`, `feature_snapshot_id`, `slippage_bps`, `fee_usdt`, `paper_realized_pnl`, `risk_action`, and `risk_reason_code`, but it does NOT carry per-event `trainer_source`, `feature_freshness_state`, or `expected_move_after_cost_bps`. The Phase D replay therefore cannot legitimately evaluate `min_expected_move_after_cost_bps` sweeps against the pre-filter rows without first either:

1. Reconstructing `expected_move_after_cost_bps` per pre-filter event from `slippage_bps`, `fee_usdt`, `notional_usdt`, and the absent `predicted_move_bps` field, OR
2. Defining a pre-filter audit shim that imputes the missing fields with explicit `IMPUTED` provenance.

Both options must be designed before the replay output can be trusted. Producing pseudo-numbers from absent fields would be evidence fraud and is refused.

## Decision

`NO_TRADE_EDGE_NOT_FOUND_OR_PROFILE_READY` cannot be honestly emitted until the CLI is implemented, the missing-field reconstruction is designed under explicit provenance, and the full sweep has been executed. Until then this report stands as a spec + safety contract for the implementation, classified `THRESHOLD_REPLAY_NOT_YET_RUN`.
