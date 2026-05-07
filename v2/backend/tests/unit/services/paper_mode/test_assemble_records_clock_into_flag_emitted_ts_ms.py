from v2.backend.app.services.paper_mode import assemble_paper_mode_flag


def test_assemble_records_clock_into_flag_emitted_ts_ms() -> None:
    flag = assemble_paper_mode_flag(
        requested_mode="paper",
        now_ms_clock=lambda: 42,
    )
    assert flag.flag_emitted_ts_ms == 42
