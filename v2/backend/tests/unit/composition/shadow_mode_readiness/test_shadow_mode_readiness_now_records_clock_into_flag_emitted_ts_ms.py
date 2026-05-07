from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)


def test_shadow_mode_readiness_now_records_clock_into_flag_emitted_ts_ms():
    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=lambda: 1700000000000)

    result = runtime.shadow_mode_readiness_now(requested_state="not_ready")

    assert result.flag_emitted_ts_ms == 1700000000000
