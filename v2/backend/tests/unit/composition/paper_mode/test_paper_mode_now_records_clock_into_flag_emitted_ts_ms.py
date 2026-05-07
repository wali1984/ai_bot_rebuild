def test_paper_mode_now_records_clock_into_flag_emitted_ts_ms():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime

    runtime = build_paper_mode_runtime(now_ms_clock=lambda: 1700000000000)

    result = runtime.paper_mode_now(requested_mode="paper")

    assert result.flag_emitted_ts_ms == 1700000000000
