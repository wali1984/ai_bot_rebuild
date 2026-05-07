import pytest

from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)


def test_shadow_mode_readiness_now_keyword_only_param():
    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=lambda: 1)

    with pytest.raises(TypeError):
        runtime.shadow_mode_readiness_now("not_ready")
