def test_returns_callable_recorder():
    from v2.backend.app.composition.paper_execution_ledger import (
        build_paper_execution_ledger_recorder,
    )

    clock = lambda: 123
    recorder = build_paper_execution_ledger_recorder(now_ms_clock=clock)

    assert callable(recorder)
    assert recorder is not clock
