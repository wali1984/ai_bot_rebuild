from v2.backend.app.services.shadow_mode_readiness import (
    assemble_shadow_mode_readiness_flag,
)


def test_assemble_records_clock_into_flag_emitted_ts_ms() -> None:
    flag = assemble_shadow_mode_readiness_flag(
        requested_state="not_ready",
        now_ms_clock=lambda: 42,
    )

    assert flag.flag_emitted_ts_ms == 42
