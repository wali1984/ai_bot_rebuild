def test_paper_mode_now_returns_new_callable_not_input_clock():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime

    now_ms_clock_lambda = lambda: 999

    runtime = build_paper_mode_runtime(now_ms_clock=now_ms_clock_lambda)

    assert runtime.paper_mode_now is not now_ms_clock_lambda
