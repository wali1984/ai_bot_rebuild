from __future__ import annotations

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.market_state_integrity import (
    TrustGateResult,
    clear_decision_replays,
    get_decision_replay,
)
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def _decision() -> OrchestratorDecisionRecord:
    return OrchestratorDecisionRecord(
        decision_id="dec_risk_env",
        prediction_id="pred_risk_env",
        feature_snapshot_id="snap_risk_env",
        symbol="BTCUSDT",
        decision_ts_ms=10,
        decision_action="open_long",
        decision_reason_code="proceed_long",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.9,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )


def _envelope(*, score: float = 0.95) -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "exchange": "binance",
        "decision_time": "2026-06-11T00:01:05Z",
        "event_time": "2026-06-11T00:01:00Z",
        "available_at": "2026-06-11T00:01:00Z",
        "ingested_at": "2026-06-11T00:01:01Z",
        "timeframe_cutoffs": {"1m": "2026-06-11T00:01:00Z"},
        "feature_cutoff": "2026-06-11T00:01:00Z",
        "feature_version": "v2",
        "feature_hash": "risk_hash",
        "data_quality_score": score,
        "data_quality_flags": [],
        "is_backfilled": False,
        "is_final_candle": True,
        "missing_candle_count": 0,
        "duplicate_event_count": 0,
        "out_of_order_event_count": 0,
        "source_disagreement_score": 0.0,
        "latency_ms": 2500,
        "decision_id": "dec_risk_env",
    }


def test_risk_gateway_blocks_low_data_quality_score() -> None:
    clear_decision_replays()
    record = assemble_risk_decision_record(
        decision=_decision(),
        now_ms_clock=lambda: 1000,
        market_state_envelope=_envelope(score=0.2),
    )
    assert record.risk_action == "deny"
    assert record.risk_reason_code == "deny_default"
    replay = get_decision_replay("dec_risk_env")
    assert replay is not None
    assert replay["block_reason"] == "data_quality_below_threshold"


def test_risk_gateway_blocks_rejected_trust_gate() -> None:
    record = assemble_risk_decision_record(
        decision=_decision(),
        now_ms_clock=lambda: 1000,
        trust_gate_result=TrustGateResult(
            accepted=False,
            severity="reject",
            reject_reasons=("future_feature_cutoff",),
            warnings=(),
            data_quality_score=0.9,
            future_leak_detected=True,
            cutoff_mismatch_detected=False,
            replay_required=True,
            metrics={},
        ),
    )
    assert record.risk_action == "deny"
    assert record.risk_reason_code == "deny_default"


def test_risk_gateway_blocks_invalid_position_transition() -> None:
    record = assemble_risk_decision_record(
        decision=_decision(),
        now_ms_clock=lambda: 1000,
        market_state_envelope=_envelope(),
        position_state="LONG",
    )
    assert record.risk_action == "deny"
    assert record.risk_reason_code == "deny_default"


def test_risk_gateway_blocks_missing_snapshot_linkage_when_required() -> None:
    record = assemble_risk_decision_record(
        decision=_decision(),
        now_ms_clock=lambda: 1000,
        market_state_envelope=_envelope(),
        snapshot_evidence_required=True,
        replay_snapshot_id=None,
        mtf_snapshot_id=None,
        mtf_snapshot_valid=None,
    )
    assert record.risk_action == "deny"
    assert record.risk_reason_code == "deny_default"
