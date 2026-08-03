# Pass 2B Paper/Shadow Edge Proof: 20260613_024915

Generated: `2026-06-13`

Scope: read-only paper/shadow edge proof over trusted `pipeline_trust_v3` runtime evidence. No strategy logic, PPO, MASA, indicators, providers, live trading, live order submission, leverage mutation, or margin-mode mutation was changed.

## Result

| Field | Value |
|---|---:|
| Evidence run | `pipeline_trust_evidence_pass2b/20260613_024901` |
| Recorded-state run | `recorded_state_verification_pass2b/20260613_024901` |
| Edge proof run | `pass2b_edge_proof/20260613_024915` |
| Strict verifier exit code | `0` |
| Recorded-state verifier exit code | `0` |
| Critical failures | `0` |
| Active-stale count | `0` |
| Edge verdict | `INSUFFICIENT_SAMPLE` |
| Pass 3 live-canary safety implementation may begin | `yes, implementation only` |
| Tiny live canary may activate | `no` |

## Live-control state

Live submit remained disabled throughout the Pass 2B run.

| Key | Field | Value |
|---|---|---:|
| `v2:live_gate:state` | `live_gate` | `blocked_human_only` |
| `v2:live_gate:state` | `order_transport_submit_enabled` | `false` |
| `v2:live_gate:state` | `live_trading_enabled` | `false` |
| `v2:live_gate:state` | `live_blocked` | `true` |
| `v2:live_gate:state` | `operator_approved` | `false` |
| `v2:live_gate:state` | `places_real_order` | `false` |
| `v2:live_gate:state` | `exchange_action_taken` | `false` |
| `v2:live_gate:state` | `release_mode` | `NON_LIVE` |
| `v2:trader:execution_state` | `trader_execution_enabled` | `false` |
| `v2:live_order_transport:status` | `order_submitted` | `false` |
| `v2:live_order_transport:status` | `places_real_order` | `false` |
| `v2:live_order_transport:status` | `runtime_submit_enabled` | `false` |
| `v2:live_order_transport:status` | `transport_submit_enabled` | `false` |
| `v2:live_order_transport:status` | `writes_exchange_orders` | `false` |
| `v2:live_order_transport:status` | `leverage_changed` | `false` |
| `v2:live_order_transport:status` | `margin_mode_changed` | `false` |

## Runtime/evidence counts

Redis counts at report time:

| Pattern | Count |
|---|---:|
| `v2:prediction:*` | `10` |
| `v2:signals:paper:*` | `10` |
| `v2:replay:snapshots:*` | `12` |
| `v2:market:mtf_snapshot:*` | `12` |
| `v2:paper:intents` | `1` |

Exported evidence counts:

| File | Records |
|---|---:|
| `candles.jsonl` | `4087` |
| `features.jsonl` | `4471` |
| `masa_ppo.jsonl` | `12` |
| `predictions.jsonl` | `10` |
| `mtf_snapshots.jsonl` | `12` |
| `replay_snapshots.jsonl` | `24` |
| `training_samples.jsonl` | `9` |
| `execution_records.jsonl` | `11` |
| `positions.jsonl` | `266` |
| `config_admin.jsonl` | `4` |

## Verification results

Strict verifier:

| Field | Value |
|---|---:|
| Exit code | `0` |
| Critical failures | `0` |
| Total findings | `186` |
| Non-critical failures | `182` |
| Passes | `4` |

Recorded-state verifier:

| Field | Value |
|---|---:|
| Exit code | `0` |
| Records loaded | `8915` |
| Decisions loaded | `22` |
| Execution records loaded | `720` |
| Features loaded | `660` |
| Invalid state count | `18` |
| Invalid state rate | `0.012839` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |
| Position transition reject count | `0` |
| Trades blocked by data quality | `0` |
| Training samples rejected count | `0` |

The remaining verifier findings are non-critical for Pass 2B. They are tracked but were not remediated because this pass is limited to trusted paper/shadow edge measurement.

## Decision and trade classification

| Field | Count |
|---|---:|
| Total prediction records | `10` |
| Trusted `pipeline_trust_v3` predictions included | `10` |
| Actionable predictions | `0` |
| HOLD/no-trade predictions | `10` |
| Blocked predictions | `10` |
| Paper intents linked to trusted decisions | `0` |
| Simulated fills linked to trusted decisions | `0` |
| Open paper trades | `0` |
| Closed paper trades | `0` |
| Rejected orders | `0` |
| Canceled orders | `0` |
| Expired orders | `0` |
| Invalid feedback rows | `0` |
| Live order records included | `0` |
| Stale pre-v3 predictions included | `0` |
| Decisions missing replay snapshot | `0` |
| Decisions missing MTF snapshot | `0` |

## Edge metrics

Closed paper/shadow trade count is `0`, so trade expectancy cannot be claimed.

| Metric | Value |
|---|---:|
| Gross PnL | `0` |
| Fees | `0` |
| Slippage | `0` |
| Net PnL after fees/slippage | `0` |
| Expectancy per trade | `0` |
| Profit factor | `0.0` |
| Win rate | `0.0` |
| Average win | `0.0` |
| Average loss | `0.0` |
| Largest win | `0.0` |
| Largest loss | `0.0` |
| Max drawdown | `0.0` |
| Consecutive wins | `0` |
| Consecutive losses | `0` |
| Exposure time seconds | `0` |
| Average hold time seconds | `0.0` |

Symbol breakdown, long/short breakdown, model-action breakdown, and regime/mode breakdown are empty because no closed paper/shadow trades were present.

## Verdict

`INSUFFICIENT_SAMPLE`

Reason: the trusted decision path is valid, but the evidence set contains only trusted HOLD/no-trade predictions and no closed paper/shadow trades. This proves the edge-proof harness and trusted filtering, not profitability.

This is not `EDGE_DATA_INVALID` because:

| Check | Result |
|---|---:|
| Strict verifier critical failures | `0` |
| Recorded-state verifier exit | `0` |
| Included decisions missing replay evidence | `0` |
| Included decisions missing MTF evidence | `0` |
| Stale pre-v3 decisions included | `0` |
| Live order records included | `0` |
| Positive training samples from rejected/canceled/expired/blocked records | `0` |

## Tests

Focused trust and Pass 2B suite:

```text
102 passed
```

New Pass 2B test coverage includes:

| Test area | Covered |
|---|---|
| Trusted decision with replay + MTF is included | yes |
| Decision missing replay snapshot is invalid | yes |
| Decision missing MTF snapshot is invalid | yes |
| Stale pre-v3 decision is excluded | yes |
| Live order record is excluded | yes |
| HOLD/no-trade not included in trade expectancy | yes |
| Rejected/canceled/expired/blocked order cannot create positive training result | yes |
| Fees/slippage are subtracted from net PnL | yes |
| Insufficient sample returns `INSUFFICIENT_SAMPLE` | yes |
| Positive sufficient sample returns `EDGE_POSITIVE` | yes |
| Negative sufficient sample returns `EDGE_NEGATIVE` | yes |
| Strict verifier failure returns `EDGE_DATA_INVALID` | yes |

## Recommendation

Pass 2B framework is complete and returned `INSUFFICIENT_SAMPLE` on current evidence.

Next step: implement Pass 3 live-canary safety layer while paper/shadow collection continues.

Do not activate live trading yet. Pass 3 must implement the live position state machine, exchange/local reconciliation, order lifecycle reconciliation, tiny canary caps, human-arm requirement, kill switch requirement, and no leverage/margin mutation while keeping live submit disabled by default.
