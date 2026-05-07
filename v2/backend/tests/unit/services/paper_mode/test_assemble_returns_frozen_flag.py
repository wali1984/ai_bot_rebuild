from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.services.paper_mode import assemble_paper_mode_flag


def test_assemble_returns_frozen_flag() -> None:
    flag = assemble_paper_mode_flag(
        requested_mode="paper",
        now_ms_clock=lambda: 1,
    )
    with pytest.raises(FrozenInstanceError):
        flag.mode = "x"  # type: ignore[misc]
    assert isinstance(flag.__class__.__dict__.get("__slots__"), tuple)
    with pytest.raises((AttributeError, TypeError)):
        setattr(flag, "unknown", "x")
