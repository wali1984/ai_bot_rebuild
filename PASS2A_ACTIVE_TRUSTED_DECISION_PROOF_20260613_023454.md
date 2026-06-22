# Pass 2A Active Trusted Decision Proof: 20260613_023454

Generated: `2026-06-13`

Scope: paper-only trusted publisher proof with live submit disabled. No strategy logic, PPO, MASA, indicators, providers, live order submission, leverage mutation, or margin-mode mutation was changed.

## Result

| Field | Value |
|---|---:|
| Publisher proof run | `publisher_proof_pass2a/20260613_023013` |
| Evidence run | `pipeline_trust_evidence_pass2a/20260613_023454` |
| Recorded-state run | `recorded_state_verification_pass2a/20260613_023454` |
| Strict verifier exit code | `0` |
| Recorded-state verifier exit code | `0` |
| Critical failures | `0` |
| Active-stale count | `0` |
| Approved/pre-trade without replay snapshot | `0` |
| Approved/pre-trade without MTF snapshot | `0` |
| Any live order submitted | `false` |
| Routes to live | `false` |
| Live order allowed | `false` |
| Pass 2B can begin | `yes, paper/shadow edge proof only` |

## Live-control state

Read-only Redis checks confirmed live submit remained disarmed.

| Key | Required state | Observed state |
|---|---|---|
| `v2:live_gate:state` | `live_gate=blocked_human_only` | `blocked_human_only` |
| `v2:live_gate:state` | `order_transport_submit_enabled=false` | `false` |
| `v2:live_gate:state` | `live_trading_enabled=false` | `false` |
| `v2:live_gate:state` | `live_blocked=true` | `true` |
| `v2:live_gate:state` | `operator_approved=false` | `false` |
| `v2:live_gate:state` | `places_real_order=false` | `false` |
| `v2:live_gate:state` | `exchange_action_taken=false` | `false` |
| `v2:live_gate:state` | `release_mode=NON_LIVE` | `NON_LIVE` |
| `v2:trader:execution_state` | `trader_execution_enabled=false` | `false` |
| `v2:live_order_transport:status` | `order_submitted=false` | `false` |
| `v2:live_order_transport:status` | `places_real_order=false` | `false` |
| `v2:live_order_transport:status` | `runtime_submit_enabled=false` | `false` |
| `v2:live_order_transport:status` | `transport_submit_enabled=false` | `false` |
| `v2:live_order_transport:status` | `writes_exchange_orders=false` | `false` |

## Canonical closed-candle coverage

At least one symbol had full canonical closed-candle coverage. Current Redis had broad coverage across all required timeframes.

| Pattern | Count |
|---|---:|
| `v2:market:ohlcv_closed:binance:*:1m` | `142` |
| `v2:market:ohlcv_closed:binance:*:5m` | `142` |
| `v2:market:ohlcv_closed:binance:*:15m` | `142` |
| `v2:market:ohlcv_closed:binance:*:1h` | `142` |
| `v2:market:ohlcv_closed:binance:*:4h` | `142` |
| Symbols with all required timeframes | `142` |

Selected proof symbol: `1000BONKUSDT`.

## Trusted publisher output

The one-shot trusted publisher ran in paper-only/no-live mode and produced a fresh trusted HOLD/no-trade prediction with replay and MTF evidence.

| Field | Value |
|---|---|
| Prediction key | `v2:prediction:1000BONKUSDT:1m` |
| Prediction id | `v2h_b42a43489b641c15394ecc0386b3ea98` |
| Decision id | `decision_f6628a205ea92d85274d795b` |
| MTF snapshot id | `mtf_f6628a205ea92d85274d795b` |
| Replay snapshot id | `decision_f6628a205ea92d85274d795b` |
| Trust schema | `pipeline_trust_v3` |
| Feature cutoff | `2026-06-12T23:59:59Z` |
| Available at | `2026-06-13T02:30:00Z` |
| All-TF candle timestamps present | `true` |
| Routes to live | `false` |
| Live order allowed | `false` |

Current Redis counts after the proof:

| Pattern | Count |
|---|---:|
| `v2:prediction:*` | `1` |
| `v2:replay:snapshots:*` | `2` |
| `v2:market:mtf_snapshot:*` | `2` |
| `v2:decision:mtf_snapshot:*` | `0` |
| `v2:mtf_snapshot:*` | `0` |

Exported evidence counts:

| File | Records |
|---|---:|
| `candles.jsonl` | `4778` |
| `features.jsonl` | `4471` |
| `masa_ppo.jsonl` | `4` |
| `training_samples.jsonl` | `9` |
| `execution_records.jsonl` | `11` |
| `positions.jsonl` | `266` |
| `config_admin.jsonl` | `4` |
| `replay_snapshots.jsonl` | `4` |

## Verifier results

Strict verifier:

| Field | Value |
|---|---:|
| Exit code | `0` |
| Critical failures | `0` |
| Active-stale count | `0` |
| Approved/pre-trade without replay snapshot | `0` |
| Approved/pre-trade without MTF snapshot | `0` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |

Recorded-state verifier:

| Field | Value |
|---|---:|
| Exit code | `0` |
| Critical failures | `0` |
| Invalid state count | `9` |
| Invalid state rate | `0.00655` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |
| Position transition reject count | `0` |

Residual non-critical findings remain in candle/data-quality categories such as duplicate, out-of-order, gap, and non-positive-volume rows. Per the Pass 2 scope, these are tracked but were not remediated because they did not block strict or recorded-state verification and do not directly block active trusted paper/shadow decision proof.

## Classification fix applied

The strict verifier previously treated a stale blocked HOLD paper intent as an active decision requiring replay and MTF snapshot linkage.

The verifier now excludes inactive blocked paper intents from snapshot-required decision classification only when all of these are true:

| Condition | Requirement |
|---|---|
| Actual prediction key | Not `v2:prediction:*` and not `v2:signals:paper:*` |
| Runtime activity | Not active by trust flags |
| Action | `hold`, `no_trade`, `none`, or empty |
| Routing flags | No `approved`, `pre_trade_allowed`, `routed_to_paper`, `paper_fill_allowed`, `routes_to_orchestrator`, `trainer_consumable`, `prediction_eligible`, `risk_eligible`, or `paper_eligible` |
| Status text | Indicates blocked/hold/no-trade/not-tradable |

Active paper intents still fail if replay or MTF snapshot evidence is missing.

## Regression tests

Focused trust suite:

```text
85 passed
```

New coverage added:

| Test | Purpose |
|---|---|
| `test_inactive_blocked_hold_paper_intent_does_not_require_snapshots` | Confirms stale blocked HOLD paper intents do not create false critical snapshot failures. |
| `test_active_paper_intent_without_snapshots_still_fails` | Confirms active paper intents still require replay and MTF snapshot evidence. |

## Final recommendation

Pass 2A is complete.

Proceed to Pass 2B paper/shadow edge proof using only trusted decisions that carry `pipeline_trust_v3`, `mtf_snapshot_id`, `replay_snapshot_id`, `feature_cutoff`, `available_at`, all-TF candle timestamps, and live-disabled flags.

Do not proceed to live-canary execution yet. Pass 3 still requires the live canary state machine, exchange/local reconciliation, and order lifecycle reconciliation before any real Binance order can be submitted.
