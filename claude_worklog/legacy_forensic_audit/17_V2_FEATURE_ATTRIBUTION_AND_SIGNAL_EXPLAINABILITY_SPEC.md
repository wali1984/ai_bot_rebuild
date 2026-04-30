# 17 V2 Feature Attribution and Signal Explainability Spec

## Objective
Define V2 data-to-action explainability so every prediction/signal/action is traceable to source keys, feature values, freshness, model outputs, and downstream risk/execution decisions.

## Required pages
- Feature Flow Map
- Feature Freshness Monitor
- Trainer Prediction Monitor
- Signal Explainability
- Data Source Utilization
- Confidence Driver Breakdown
- Risk Decision Explanation
- Execution Attribution Ledger

## Required record fields per prediction/signal/action
- `feature_snapshot_id`
- `prediction_id`
- `signal_id`
- `decision_id`
- `risk_decision_id`
- `execution_intent_id`
- `order_id` (if any)
- `model_version`
- `checkpoint_id`
- `source_keys`
- `feature_values`
- `feature_freshness`
- `confidence_before`
- `confidence_after`
- `top_positive_drivers`
- `top_negative_drivers`
- `missing_source_flags`
- `stale_source_flags`
- `ignored_source_flags`
- `natural_language_explanation`
- `raw_evidence_pointers`

## Explainability chain (must be linkable)
`feature_snapshot` → `prediction` → `confidence_event` → `signal` → `orchestrator_decision` → `risk_decision` → `execution_intent` → `order/outcome`

## V2 data model concepts
- `feature_snapshots`
- `feature_values`
- `ingestor_sources`
- `prediction_events`
- `confidence_events`
- `signal_events`
- `orchestrator_decisions`
- `risk_decisions`
- `execution_intents`
- `attribution_links`

## Source utilization semantics
For each ingestor source and key, V2 must show status:
- `used`
- `ignored`
- `stale`
- `missing`

## Evidence requirements
Every UI explanation card must include references to:
- source artifact path
- source file and line/range (or stream entry id)
- verification command
- timestamp and environment context

## Non-goals / guardrails
- No automatic risk approvals from summarizers.
- No hidden confidence transformations without evidence.
- No missing-link execution records.

## Acceptance criteria (high level)
1. A user can open any executed/blocked action and see full upstream chain.
2. A user can identify exact features/keys that changed confidence.
3. A user can detect stale/missing/ignored sources at decision time.
4. A user can verify model/checkpoint and confidence drivers for each signal.
5. Ledger records are replayable and evidence-backed.
