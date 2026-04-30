# 11 Feature Attribution and Signal Explainability Architecture

## Lineage IDs (mandatory)
- `feature_snapshot_id`
- `prediction_id`
- `signal_id`
- `decision_id`
- `risk_decision_id`
- `execution_intent_id`

## Required explainability payload per prediction/signal/action
- source keys
- feature values
- feature freshness
- stale/missing/unused flags
- model version
- checkpoint
- confidence before/after
- top positive/negative drivers
- orchestrator reason
- risk decision
- execution/block reason

## Architectural purpose
Directly closes post-monitor feature attribution and explainability gaps through persisted lineage + explainability records.

## Display surfaces
- Signal Explainability page
- Confidence Driver Breakdown page
- Audit Ledger cross-linking
