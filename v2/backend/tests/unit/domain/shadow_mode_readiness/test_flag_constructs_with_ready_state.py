import dataclasses

import pytest

from v2.backend.app.domain.shadow_mode_readiness import ShadowModeReadinessFlag


def test_flag_constructs_with_ready_state() -> None:
    flag = ShadowModeReadinessFlag(
        state="ready",
        flag_emitted_ts_ms=1730000000000,
        live_blocked=True,
    )

    assert flag.state == "ready"
    assert flag.flag_emitted_ts_ms == 1730000000000
    assert flag.live_blocked is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        flag.state = "x"
    assert isinstance(flag.__class__.__dict__.get("__slots__"), tuple)
    assert flag.__class__.__dict__.get("__slots__") != ()
    with pytest.raises(AttributeError):
        setattr(flag, "unknown", "x")
