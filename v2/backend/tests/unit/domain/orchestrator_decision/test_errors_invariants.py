from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionDomainError


def test_error_carries_reason_field_and_value_error_message():
    without_field = OrchestratorDecisionDomainError("must_be_int")
    assert without_field.reason == "must_be_int"
    assert without_field.field is None
    assert str(without_field) == "must_be_int"
    assert isinstance(without_field, ValueError)

    with_field = OrchestratorDecisionDomainError(
        "must_be_int", field="decision_ts_ms"
    )
    assert with_field.reason == "must_be_int"
    assert with_field.field == "decision_ts_ms"
    assert str(with_field) == "decision_ts_ms: must_be_int"
