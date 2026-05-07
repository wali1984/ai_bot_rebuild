def test_returns_paper_mode_runtime_instance():
    from v2.backend.app.composition.paper_mode import (
        PaperModeRuntime,
        build_paper_mode_runtime,
    )

    clock = lambda: 123
    runtime = build_paper_mode_runtime(now_ms_clock=clock)

    assert isinstance(runtime, PaperModeRuntime)
    assert callable(runtime.paper_mode_now)
    assert runtime.paper_mode_now is not clock
