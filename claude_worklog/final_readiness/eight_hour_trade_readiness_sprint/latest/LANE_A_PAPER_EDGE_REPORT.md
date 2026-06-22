# Lane A — Paper Edge Model Repair (8h Sprint)

Generated: 2026-05-15
Lane: A
Live gate: `blocked_human_only`. Live symbols: `[]`.

## Inputs

- `claude_worklog/final_readiness/expected_move_model_review/latest/operator_dashboard_payload.json`
- `claude_worklog/final_readiness/expected_move_model_review/latest/threshold_replay_results.json`
- `claude_worklog/final_readiness/expected_move_model_review/latest/false_block_audit.json`

## Current shadow false-block state

| Field | Value |
|-------|-------|
| observations_total | 409 |
| completed_observations | 347 |
| false_block_count | 126 |
| false_block_rate | 0.363 |
| no_trade_correct_count | 221 |
| no_trade_correct_rate | 0.637 |
| edge_status | `EDGE_PENDING_MODEL_REVIEW_REQUIRED` |
| outcome_status | `BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED` |
| safe_threshold_candidate_count | 0 |

Interpretation:
- The shadow observer would have flagged 126 of 347 blocked intents as
  "could have beaten costs". That is the analysis-only `false_block_count`.
- 221 of 347 blocked intents were correctly blocked
  (`no_trade_correct_count` = 221). The bot's strict gate is right ~63.7%
  of the time.
- Zero policy combinations in the replay sweep have a sample large enough and a
  precision high enough to authorize paper fills under the strict gate.

## Threshold replay sweep

Replay sweep dimensions (from `threshold_replay_results.json`):

- `expected_move_after_cost_bps`: 4, 6, 8, 10, 12, 15
- `min_confidence_calibrated`: 0.60, 0.65, 0.70, 0.75
- `cooldown_mode`: `60m_observed_strict`, `30m_source_limited_no_change`,
  `10m_source_limited_no_change`

Result: **0 safe threshold candidates** across 72 rows. All rows are classified
`INSUFFICIENT_ALLOWED_SAMPLE` or `SOURCE_LIMITED_COOLDOWN_CHANGE_NOT_ALLOWED`.

Top precision rows (analysis-only):

| min_em_after_cost_bps | min_conf_calibrated | cooldown_mode | true_allow | false_allow | precision | net_bps_after_costs | classification |
|-----------------------|---------------------|---------------|------------|-------------|-----------|---------------------|----------------|
| 15 | 0.60 | 60m_observed_strict | 6 | 2 | 0.750 | 123.16 | INSUFFICIENT_ALLOWED_SAMPLE |
| 15 | 0.65 | 60m_observed_strict | 5 | 2 | 0.714 | 118.96 | INSUFFICIENT_ALLOWED_SAMPLE |
| 15 | 0.70 | 60m_observed_strict | 5 | 2 | 0.714 | 118.96 | INSUFFICIENT_ALLOWED_SAMPLE |

The best rows show precision ~71-75% but only 5-8 allow events; not enough sample
to authorize a policy change.

## Decision

Keep the strict paper gate. No global or selective threshold change is
authorized by current evidence. The router's selected blocker
`PAPER_EDGE_UNPROVEN` remains open.

Recommended remediation:
1. Continue shadow soak to grow the allowed-sample count.
2. Re-run the replay sweep once `true_allow_count >= 30` per row to gate any
   threshold change.
3. Do NOT loosen `min_expected_move_after_cost_bps` below 15 without Codex
   approval and explicit operator acknowledgment.

## What this lane does NOT do

- Does not authorize paper fills.
- Does not loosen the global paper gate.
- Does not authorize canary or live trading.
- Does not invent outcomes for source-limited cooldown modes.

## GO/NO-GO for Lane A

`LANE_A_PAPER_EDGE_RECOVERY_READY_KEEP_GATE_STRICT`

Live remains `blocked_human_only`.
