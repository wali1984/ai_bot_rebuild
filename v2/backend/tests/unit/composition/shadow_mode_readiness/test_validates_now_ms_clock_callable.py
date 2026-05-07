import pytest

from v2.backend.app.composition.shadow_mode_readiness import (
    ShadowModeReadinessRuntimeCompositionError,
    build_shadow_mode_readiness_runtime,
)


def test_validates_now_ms_clock_callable():
    for value in (42, None, "not_callable"):
        with pytest.raises(ShadowModeReadinessRuntimeCompositionError) as exc_info:
            build_shadow_mode_readiness_runtime(now_ms_clock=value)
        assert exc_info.value.code == "must_be_callable"
        assert exc_info.value.field == "now_ms_clock"
