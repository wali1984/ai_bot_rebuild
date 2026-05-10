from __future__ import annotations

from v2.backend.app.domain.provenance_dedupe_attribution import (
    DEDUPE_DUPLICATE_OF_PRIOR,
    DEDUPE_NEW,
    DEDUPE_STALE_OUT_OF_ORDER,
    DedupeDecisionRecord,
    ProvenanceRecord,
)
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RiskDecisionRecord,
)


TRAINER_FIELDS = {
    "model_version": "hybrid_trainer_v2026_05",
    "checkpoint_id": "ckpt_duplicate_signal_blocked_2026_05",
    "confidence_raw": 0.77,
    "confidence_calibrated": 0.74,
    "trainer_worker_liveness": "alive",
}


def risk_record() -> RiskDecisionRecord:
    return RiskDecisionRecord(
        risk_decision_id="risk-1",
        decision_id="decision-1",
        prediction_id="prediction-1",
        feature_snapshot_id="feature-1",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1000,
        risk_action=RISK_DECISION_ACTION_DENY,
        risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT,
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )


def provenance_record(**overrides: object) -> ProvenanceRecord:
    values = {
        "provenance_id": "prov:decision-1:coinank:worker-a",
        "source_id": "coinank",
        "ingestor_id": "worker-a",
        "source_ts_ms": 1000,
        "ingest_ts_ms": 1250,
        "freshness_ms": 250,
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "feature_snapshot_id": "feature-1",
        "risk_decision_id": "risk-1",
        **TRAINER_FIELDS,
        "live_blocked": True,
    }
    values.update(overrides)
    return ProvenanceRecord(**values)


def dedupe_record(**overrides: object) -> DedupeDecisionRecord:
    values = {
        "dedupe_decision_id": "dedupe:decision-1:DEDUPE_NEW",
        "dedupe_state": DEDUPE_NEW,
        "duplicate_of_decision_id": None,
        "dedupe_reason": "first_seen",
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "feature_snapshot_id": "feature-1",
        "risk_decision_id": "risk-1",
        **TRAINER_FIELDS,
        "live_blocked": True,
    }
    values.update(overrides)
    return DedupeDecisionRecord(**values)


__all__ = [
    "DEDUPE_DUPLICATE_OF_PRIOR",
    "DEDUPE_NEW",
    "DEDUPE_STALE_OUT_OF_ORDER",
    "TRAINER_FIELDS",
    "dedupe_record",
    "provenance_record",
    "risk_record",
]
