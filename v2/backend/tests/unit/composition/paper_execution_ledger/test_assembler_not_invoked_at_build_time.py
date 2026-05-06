def test_assembler_not_invoked_at_build_time():
    from v2.backend.app.composition.paper_execution_ledger import (
        build_paper_execution_ledger_recorder,
    )

    n = [0]

    def clock():
        n[0] += 1
        return 1

    build_paper_execution_ledger_recorder(now_ms_clock=clock)

    assert n == [0]
