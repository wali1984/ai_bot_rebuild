import pytest

from v2.backend.app.domain.shadow_mode_readiness import (
    ShadowModeReadinessDomainError,
    ShadowModeReadinessFlag,
)


def test_flag_rejects_float_for_flag_emitted_ts_ms() -> None:
    with pytest.raises(ShadowModeReadinessDomainError) as exc_info:
        ShadowModeReadinessFlag(
            state="not_ready",
            flag_emitted_ts_ms=1730000000000.5,
            live_blocked=True,
        )

    assert exc_info.value.field == "flag_emitted_ts_ms"
