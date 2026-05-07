from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.domain.paper_mode import PaperModeFlag


def test_flag_constructs_with_live_blocked_mode() -> None:
    flag = PaperModeFlag(
        mode="live_blocked",
        flag_emitted_ts_ms=1730000000000,
        live_blocked=True,
    )
    assert flag.mode == "live_blocked"
    assert flag.flag_emitted_ts_ms == 1730000000000
    assert flag.live_blocked is True
    with pytest.raises(FrozenInstanceError):
        flag.mode = "x"
    assert isinstance(flag.__class__.__dict__.get("__slots__"), tuple)
    assert flag.__class__.__dict__.get("__slots__") != ()
    with pytest.raises(AttributeError):
        object.__setattr__(flag, "unknown", "x")
