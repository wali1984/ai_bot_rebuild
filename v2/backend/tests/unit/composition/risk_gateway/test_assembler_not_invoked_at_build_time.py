def test_assembler_not_invoked_at_build_time():
    from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator

    n = [0]

    def clock():
        n[0] += 1
        return 1

    build_risk_decision_evaluator(now_ms_clock=clock)

    assert n == [0]
