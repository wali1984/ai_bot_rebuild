# 06 Signal Attribution Monitoring Plan

## Objective
Enforce end-to-end signal lineage visibility across decision pipeline.

## Required lineage checks
- `prediction_id` always references one `feature_snapshot_id`.
- `signal_id` always references one `prediction_id`.
- `decision_id` always references one `signal_id`.
- `risk_decision_id` always references one `decision_id`.
- `execution_intent_id` always references one `risk_decision_id`.

## Completeness metrics
- `signal_id_missing_rate`
- `confidence_missing_rate`
- `lineage_chain_complete_rate`
- `execution_lineage_complete_rate`

## Drift detection
- Track regressions from previous hourly packet.
- Emit alert on sudden rise in missing IDs or confidence gaps.

## Verification command examples
- read-only stream sample and lineage field check commands.
- schema validation command over packet outputs.
