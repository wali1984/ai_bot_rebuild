import pytest

from v2.backend.app.domain.shadow_mode_readiness import (
    ShadowModeReadinessDomainError,
    ShadowModeReadinessFlag,
)


def test_flag_rejects_live_enabled_state() -> None:
    with pytest.raises(ShadowModeReadinessDomainError) as exc_info:
        ShadowModeReadinessFlag(
            state="live_enabled",
            flag_emitted_ts_ms=1730000000000,
            live_blocked=True,
        )

    assert exc_info.value.reason == "shadow_mode_readiness_flag_unknown_state"
    assert exc_info.value.field == "state"
