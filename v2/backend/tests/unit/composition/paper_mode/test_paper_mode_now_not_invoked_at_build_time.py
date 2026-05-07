def test_paper_mode_now_not_invoked_at_build_time():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime

    calls = [0]

    def clock():
        calls[0] += 1
        return 123

    build_paper_mode_runtime(now_ms_clock=clock)

    assert calls == [0]
