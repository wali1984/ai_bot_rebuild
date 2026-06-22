# V2 Native Edge-Proof Operator Threshold Decision Packet

GO/NO-GO: `V2_NATIVE_EDGE_PROOF_OPERATOR_THRESHOLD_PACKET_READY`

This packet proposes numeric operator thresholds required before the edge-proof evaluator may ever emit `EDGE_PROVISIONAL_PAPER_PASS`. It does not accept the thresholds on behalf of the operator and does not approve canary, live trading, legacy shutdown, Redis trimming, or symbol adoption.

All threshold rows start with `operator_accepted=false`.

## Safety State

| Field | Value |
|---|---|
| live_gate | `blocked_human_only` |
| live_symbols | `[]` |
| approves_live | `false` |
| approves_canary | `false` |
| approves_legacy_shutdown | `false` |
| creates_approval_file | `false` |
| operator_thresholds_accepted | `false` |

## Threshold Summary

| Threshold | Conservative default | Aggressive default | Unit | Blocks canary | Blocks live | operator_accepted |
|---|---:|---:|---|---|---|---|
| `min_sample_count` | 1000 | 250 | replay bundles | true | true | false |
| `min_after_cost_expectancy_bps` | 8.0 | 3.0 | bps | true | true | false |
| `min_after_cost_lower_ci_bps` | 2.0 | 0.0 | bps | true | true | false |
| `max_drawdown_bps_rolling` | 150.0 | 300.0 | bps | true | true | false |
| `min_downside_pre_cascade_recall` | 0.80 | 0.60 | ratio | true | true | false |
| `max_false_positive_rate` | 0.20 | 0.35 | ratio | true | true | false |
| `max_false_negative_rate` | 0.15 | 0.30 | ratio | true | true | false |

## Threshold Details

### `min_sample_count`

- Recommended conservative default: `1000`
- Aggressive default: `250`
- Rationale: Edge proof should survive enough independent paper/shadow replay bundles to reduce luck, symbol clustering, and short-window market regime bias.
- Risk of setting too loose: A few favorable samples can overfit to one volatility regime and create a false edge claim.
- Risk of setting too strict: Proof may be delayed even when a real edge exists, especially if high-quality paper signals are sparse.
- Blocks canary: `true`
- Blocks live: `true`
- operator_accepted: `false`

### `min_after_cost_expectancy_bps`

- Recommended conservative default: `8.0`
- Aggressive default: `3.0`
- Rationale: The mean realized after-cost return must clear fees, slippage, latency noise, and paper/live drift with positive margin.
- Risk of setting too loose: Marginal edge can disappear under real fills or small cost-model error.
- Risk of setting too strict: The evaluator may reject viable low-turnover or lower-volatility strategies.
- Blocks canary: `true`
- Blocks live: `true`
- operator_accepted: `false`

### `min_after_cost_lower_ci_bps`

- Recommended conservative default: `2.0`
- Aggressive default: `0.0`
- Rationale: The bootstrap lower confidence bound should remain non-negative, preferably positive, so the edge is not only a point-estimate artifact.
- Risk of setting too loose: A positive average with a negative uncertainty band can be misread as proven edge.
- Risk of setting too strict: A noisy but improving model may remain blocked until substantially more samples accumulate.
- Blocks canary: `true`
- Blocks live: `true`
- operator_accepted: `false`

### `max_drawdown_bps_rolling`

- Recommended conservative default: `150.0`
- Aggressive default: `300.0`
- Rationale: Paper edge must not depend on tolerating deep rolling adverse excursions. Drawdown is a hard risk-control threshold, not an informational metric.
- Risk of setting too loose: A positive expectancy can hide unacceptable tail loss and liquidation exposure.
- Risk of setting too strict: Normal intraday volatility may block otherwise controlled strategies.
- Blocks canary: `true`
- Blocks live: `true`
- operator_accepted: `false`

### `min_downside_pre_cascade_recall`

- Recommended conservative default: `0.80`
- Aggressive default: `0.60`
- Rationale: The system must catch most downside pre-cascade events before scaling; missing these events is worse than over-blocking.
- Risk of setting too loose: V2 can pass while still missing large downside events.
- Risk of setting too strict: The system may overfit to rare shock labels or block progress when there are too few cascade examples.
- Blocks canary: `true`
- Blocks live: `true`
- operator_accepted: `false`

### `max_false_positive_rate`

- Recommended conservative default: `0.20`
- Aggressive default: `0.35`
- Rationale: Accepted trades must not be wrong too often after costs, or turnover and fee drag will dominate.
- Risk of setting too loose: The evaluator can pass a strategy that takes too many bad trades.
- Risk of setting too strict: It can reject a strategy with acceptable expectancy but moderate noise.
- Blocks canary: `true`
- Blocks live: `true`
- operator_accepted: `false`

### `max_false_negative_rate`

- Recommended conservative default: `0.15`
- Aggressive default: `0.30`
- Rationale: V2 should not miss too many profitable paper/shadow opportunities, because excessive false negatives can prove the gate is over-blocking edge.
- Risk of setting too loose: V2 can appear safe by refusing trades while failing to capture valid opportunities.
- Risk of setting too strict: The operator may force the model toward over-trading to avoid missed opportunities.
- Blocks canary: `true`
- Blocks live: `true`
- operator_accepted: `false`

## Operator Instructions

1. Review the conservative and aggressive defaults.
2. Choose one numeric value per threshold or enter a custom value.
3. Set `operator_accepted=true` only after an explicit human decision.
4. Do not treat this packet as canary, live, or shutdown approval.
5. Do not allow `EDGE_PROVISIONAL_PAPER_PASS` until evaluator code also enforces every accepted numeric threshold.

## Notes

- `min_v2_vs_legacy_action_match_rate` remains informational-only and is intentionally excluded from this seven-threshold acceptance packet.
- Existing Codex review artifacts may still require evaluator remediation before any PASS can be trusted. This packet only supplies operator decision material.
- No exchange call, Redis write, service stop, legacy mutation, or approval marker is part of this packet.
