def test_returns_callable_evaluator():
    from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator

    clock = lambda: 123
    evaluator = build_risk_decision_evaluator(now_ms_clock=clock)

    assert callable(evaluator)
    assert evaluator is not clock
