from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_ALLOW_CLOSE_ONLY_INTELLIGENT_CLOSE_GUARD,
    RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC,
    RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
    RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
    RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
    RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH,
    RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
    RiskDecisionRecord,
)


def test_risk_decision_reason_constants_are_exact_distinct_and_prefixed() -> None:
    allow_reasons = (
        RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        RISK_DECISION_REASON_ALLOW_CLOSE_ONLY_INTELLIGENT_CLOSE_GUARD,
    )
    deny_reasons = (
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        RISK_DECISION_REASON_DENY_DEFAULT,
        RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
        RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
        RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH,
        RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED,
        RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
        RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
        RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
        RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC,
    )
    assert allow_reasons == (
        "allow_proceed_long",
        "allow_proceed_short",
        "allow_close_only_intelligent_close_guard",
    )
    assert deny_reasons == (
        "deny_orchestrator_abstained",
        "deny_orchestrator_held",
        "deny_default",
        "deny_kill_switch_active",
        "deny_halt_manager_active",
        "deny_reduce_only_latch",
        "deny_auto_deleverager_triggered",
        "deny_shared_risk_budget_exhausted",
        "deny_margin_governor_leverage_increase_blocked",
        "deny_phase_controller_warmup",
        "deny_adaptive_microstructure_toxic",
    )
    assert len(set(allow_reasons + deny_reasons)) == 14
    assert all(reason.startswith("allow_") for reason in allow_reasons)
    assert all(reason.startswith("deny_") for reason in deny_reasons)


def _record(*, risk_action: str, risk_reason_code: str) -> RiskDecisionRecord:
    return RiskDecisionRecord(
        risk_decision_id=f"risk_{risk_reason_code}",
        decision_id="decision_1",
        prediction_id="prediction_1",
        feature_snapshot_id="feature_1",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action=risk_action,
        risk_reason_code=risk_reason_code,
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )


def test_new_legacy_gate_deny_reasons_construct_risk_decision_records() -> None:
    for reason in (
        RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
        RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
        RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH,
        RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED,
        RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
        RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
        RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
        RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC,
    ):
        record = _record(
            risk_action=RISK_DECISION_ACTION_DENY,
            risk_reason_code=reason,
        )
        assert record.risk_reason_code == reason
        assert record.live_blocked is True


def test_new_close_only_reason_constructs_as_allow_prefixed_record() -> None:
    record = _record(
        risk_action=RISK_DECISION_ACTION_ALLOW,
        risk_reason_code=RISK_DECISION_REASON_ALLOW_CLOSE_ONLY_INTELLIGENT_CLOSE_GUARD,
    )
    assert (
        record.risk_reason_code
        == RISK_DECISION_REASON_ALLOW_CLOSE_ONLY_INTELLIGENT_CLOSE_GUARD
    )
    assert record.live_blocked is True
