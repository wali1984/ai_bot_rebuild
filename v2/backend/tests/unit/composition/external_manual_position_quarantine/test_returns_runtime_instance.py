from v2.backend.app.composition.external_manual_position_quarantine import (
    ExternalManualPositionQuarantineRuntime,
    build_external_position_quarantine_runtime,
)


def test_returns_runtime_instance() -> None:
    runtime = build_external_position_quarantine_runtime(now_ms_clock=lambda: 1)

    assert isinstance(runtime, ExternalManualPositionQuarantineRuntime)
