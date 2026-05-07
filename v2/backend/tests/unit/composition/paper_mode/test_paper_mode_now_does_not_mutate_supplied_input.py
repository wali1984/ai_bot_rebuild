def test_paper_mode_now_does_not_mutate_supplied_input():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime

    requested_mode = "paper"
    requested_mode_id = id(requested_mode)
    runtime = build_paper_mode_runtime(now_ms_clock=lambda: 1)

    runtime.paper_mode_now(requested_mode=requested_mode)

    assert requested_mode == "paper"
    assert id(requested_mode) == requested_mode_id
