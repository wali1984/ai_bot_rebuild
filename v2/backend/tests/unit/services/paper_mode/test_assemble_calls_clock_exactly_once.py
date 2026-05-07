from v2.backend.app.services.paper_mode import assemble_paper_mode_flag


def test_assemble_calls_clock_exactly_once() -> None:
    calls: list[int] = []

    def clock() -> int:
        calls.append(1)
        if len(calls) == 1:
            return 1000
        return 999_999_999

    flag = assemble_paper_mode_flag(
        requested_mode="paper",
        now_ms_clock=clock,
    )
    assert len(calls) == 1
    assert flag.flag_emitted_ts_ms == 1000
