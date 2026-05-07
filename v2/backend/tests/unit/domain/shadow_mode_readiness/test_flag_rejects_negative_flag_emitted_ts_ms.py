import pytest

from v2.backend.app.domain.shadow_mode_readiness import (
    ShadowModeReadinessDomainError,
    ShadowModeReadinessFlag,
)


def test_flag_rejects_negative_flag_emitted_ts_ms() -> None:
    with pytest.raises(ShadowModeReadinessDomainError) as exc_info:
        ShadowModeReadinessFlag(
            state="not_ready",
            flag_emitted_ts_ms=-1,
            live_blocked=True,
        )

    assert (
        exc_info.value.reason
        == "shadow_mode_readiness_flag_emitted_ts_ms_must_be_non_negative_int"
    )
    assert exc_info.value.field == "flag_emitted_ts_ms"
