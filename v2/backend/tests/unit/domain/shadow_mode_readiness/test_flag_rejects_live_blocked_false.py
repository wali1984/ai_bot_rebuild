import pytest

from v2.backend.app.domain.shadow_mode_readiness import (
    ShadowModeReadinessDomainError,
    ShadowModeReadinessFlag,
)


def test_flag_rejects_live_blocked_false() -> None:
    with pytest.raises(ShadowModeReadinessDomainError) as exc_info:
        ShadowModeReadinessFlag(
            state="not_ready",
            flag_emitted_ts_ms=1730000000000,
            live_blocked=False,
        )

    assert exc_info.value.reason == "shadow_mode_readiness_flag_requires_live_blocked_true"
    assert exc_info.value.field == "live_blocked"
