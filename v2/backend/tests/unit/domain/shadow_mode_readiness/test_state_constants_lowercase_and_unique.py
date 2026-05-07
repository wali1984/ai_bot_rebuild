from v2.backend.app.domain.shadow_mode_readiness import (
    SHADOW_MODE_NOT_READY,
    SHADOW_MODE_READY,
)


def test_state_constants_lowercase_and_unique() -> None:
    assert isinstance(SHADOW_MODE_NOT_READY, str)
    assert isinstance(SHADOW_MODE_READY, str)
    assert SHADOW_MODE_NOT_READY != ""
    assert SHADOW_MODE_READY != ""
    assert SHADOW_MODE_NOT_READY == SHADOW_MODE_NOT_READY.lower()
    assert SHADOW_MODE_READY == SHADOW_MODE_READY.lower()
    assert len((SHADOW_MODE_NOT_READY, SHADOW_MODE_READY)) == len(
        {SHADOW_MODE_NOT_READY, SHADOW_MODE_READY}
    )
