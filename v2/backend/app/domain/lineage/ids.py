"""Deterministic lineage ID derivation from a base prediction_id.

All IDs are derived via a stable prefix + prediction_id convention so they
are reproducible without a DB round-trip.  Purely functional; no I/O.
"""
from __future__ import annotations


def derive_orchestrator_decision_id(prediction_id: str) -> str:
    return f"orch_{prediction_id}"


def derive_risk_decision_id(prediction_id: str) -> str:
    return f"risk_{prediction_id}"


def derive_execution_intent_id(prediction_id: str) -> str:
    return f"pei_{prediction_id}"


def derive_signal_id(tick_id: str) -> str:
    return f"sig_{tick_id}"


def derive_paper_ledger_entry_id(tick_id: str) -> str:
    return f"pledger_{tick_id}"


def derive_all_ids(*, prediction_id: str, tick_id: str, feature_snapshot_id: str) -> dict[str, str]:
    return {
        "prediction_id": prediction_id,
        "feature_snapshot_id": feature_snapshot_id,
        "signal_id": derive_signal_id(tick_id),
        "orchestrator_decision_id": derive_orchestrator_decision_id(prediction_id),
        "risk_decision_id": derive_risk_decision_id(prediction_id),
        "execution_intent_id": derive_execution_intent_id(prediction_id),
        "paper_ledger_entry_id": derive_paper_ledger_entry_id(tick_id),
    }
