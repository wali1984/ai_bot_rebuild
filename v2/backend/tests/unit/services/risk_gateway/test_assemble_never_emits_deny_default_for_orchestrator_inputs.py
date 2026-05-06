from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_never_emits_deny_default_for_orchestrator_inputs() -> None:
    cases = (
        ("open_long", "proceed_long", "long", "fresh", "HEALTHY", "allow_proceed_long"),
        ("open_short", "proceed_short", "short", "fresh", "HEALTHY", "allow_proceed_short"),
        ("hold", "hold_flat_direction", "flat", "fresh", "HEALTHY", "deny_orchestrator_held"),
        ("abstain", "abstain_low_confidence", "long", "fresh", "HEALTHY", "deny_orchestrator_abstained"),
    )
    reserved = "deny" + "_" + "default"
    observed: list[str] = []
    for index, (action, reason, direction, freshness, health, expected) in enumerate(cases):
        decision = OrchestratorDecisionRecord(
            decision_id=f"dec_no_reserved_{index}",
            prediction_id=f"pred_no_reserved_{index}",
            feature_snapshot_id=f"snap_no_reserved_{index}",
            symbol="BTCUSDT",
            decision_ts_ms=10,
            decision_action=action,
            decision_reason_code=reason,
            input_prediction_direction=direction,
            input_prediction_confidence_calibrated=0.85,
            input_prediction_freshness_flag=freshness,
            input_worker_health_status=health,
            live_blocked=True,
        )
        code = assemble_risk_decision_record(
            decision=decision,
            now_ms_clock=lambda: 1000,
        ).risk_reason_code
        assert code != reserved
        assert code == expected
        observed.append(code)

    assert observed == [
        "allow_proceed_long",
        "allow_proceed_short",
        "deny_orchestrator_held",
        "deny_orchestrator_abstained",
    ]
