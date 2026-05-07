import pytest

from v2.backend.app.services.shadow_mode_readiness import (
    assemble_shadow_mode_readiness_flag,
)


def test_assemble_keyword_only_params() -> None:
    with pytest.raises(TypeError):
        assemble_shadow_mode_readiness_flag("not_ready", lambda: 1)  # type: ignore[misc]

    flag = assemble_shadow_mode_readiness_flag(
        requested_state="not_ready",
        now_ms_clock=lambda: 1,
    )
    assert flag.flag_emitted_ts_ms == 1
