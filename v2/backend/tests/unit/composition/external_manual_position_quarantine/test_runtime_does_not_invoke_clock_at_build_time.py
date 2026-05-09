from v2.backend.app.composition.external_manual_position_quarantine import (
    build_external_position_quarantine_runtime,
)


def test_runtime_does_not_invoke_clock_at_build_time() -> None:
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        return 1

    build_external_position_quarantine_runtime(now_ms_clock=clock)

    assert calls == 0
