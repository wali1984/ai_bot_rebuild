"""Canonical lineage chain definition.

Seven decision stages in order:
  market_data -> feature_snapshot -> model_output -> trainer_prediction
  -> orchestrator_decision -> risk_gateway_decision -> paper_execution_result

Seven required IDs that must all be non-null for a signal to be considered
fully linked:
  prediction_id, feature_snapshot_id, signal_id, orchestrator_decision_id,
  risk_decision_id, execution_intent_id, paper_ledger_entry_id
"""
from __future__ import annotations

LINEAGE_STAGE_ORDER: tuple[str, ...] = (
    "market_data",
    "feature_snapshot",
    "model_output",
    "trainer_prediction",
    "orchestrator_decision",
    "risk_gateway_decision",
    "paper_execution_result",
)

REQUIRED_LINEAGE_IDS: tuple[str, ...] = (
    "prediction_id",
    "feature_snapshot_id",
    "signal_id",
    "orchestrator_decision_id",
    "risk_decision_id",
    "execution_intent_id",
    "paper_ledger_entry_id",
)

MINIMUM_ACTIONABLE_IDS: tuple[str, ...] = (
    "prediction_id",
    "feature_snapshot_id",
    "signal_id",
    "orchestrator_decision_id",
    "risk_decision_id",
    "execution_intent_id",
)

BLOCK_REASON_RISK_DECISION_MISSING = "RISK_DECISION_MISSING"
BLOCK_REASON_ORCHESTRATOR_MISSING = "ORCHESTRATOR_DECISION_MISSING"
BLOCK_REASON_NO_EXECUTION_INTENT = "EXECUTION_INTENT_MISSING"
BLOCK_REASON_NO_PREDICTION = "PREDICTION_ID_MISSING"
