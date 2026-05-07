from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.services.shadow_mode_readiness import (
    assemble_shadow_mode_readiness_flag,
)


def test_assemble_returns_frozen_flag() -> None:
    flag = assemble_shadow_mode_readiness_flag(
        requested_state="not_ready",
        now_ms_clock=lambda: 1,
    )

    with pytest.raises(FrozenInstanceError):
        flag.state = "x"  # type: ignore[misc]
    assert isinstance(flag.__class__.__dict__.get("__slots__"), tuple)
    assert flag.__class__.__dict__.get("__slots__")
    with pytest.raises(AttributeError):
        setattr(flag, "unknown_attribute", "x")
