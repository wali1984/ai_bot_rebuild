def test_paper_mode_now_propagates_live_blocked_mode():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime

    runtime = build_paper_mode_runtime(now_ms_clock=lambda: 11)

    result = runtime.paper_mode_now(requested_mode="live_blocked")

    assert result.mode == "live_blocked"
    assert result.live_blocked is True
    assert result.flag_emitted_ts_ms == 11
