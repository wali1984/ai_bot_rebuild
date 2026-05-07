def test_paper_mode_now_invokes_clock_exactly_once_per_call():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime

    calls = [0]

    def clock():
        calls[0] += 1
        return calls[0]

    runtime = build_paper_mode_runtime(now_ms_clock=clock)

    runtime.paper_mode_now(requested_mode="paper")
    assert calls == [1]
    runtime.paper_mode_now(requested_mode="live_blocked")
    assert calls == [2]
