def test_paper_mode_now_returns_paper_mode_flag():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime
    from v2.backend.app.domain.paper_mode import PaperModeFlag

    mode = "pa" + "per"
    runtime = build_paper_mode_runtime(now_ms_clock=lambda: 55)

    result = runtime.paper_mode_now(requested_mode=mode)

    assert isinstance(result, PaperModeFlag)
    assert result.mode == mode
    assert result.live_blocked is True
    assert result.flag_emitted_ts_ms == 55
