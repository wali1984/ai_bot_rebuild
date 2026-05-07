from v2.backend.app.domain.shadow_mode_readiness import (
    SHADOW_MODE_NOT_READY,
    SHADOW_MODE_READY,
)


def test_state_constants_have_expected_string_values() -> None:
    assert SHADOW_MODE_NOT_READY == "not_ready"
    assert SHADOW_MODE_READY == "ready"
