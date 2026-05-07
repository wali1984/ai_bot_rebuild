from v2.backend.app.domain.paper_mode import PaperModeFlag
from v2.backend.app.services.paper_mode import assemble_paper_mode_flag


def test_assemble_returns_flag_for_live_blocked_requested_mode() -> None:
    flag = assemble_paper_mode_flag(
        requested_mode="live_blocked",
        now_ms_clock=lambda: 2000,
    )
    assert flag.mode == "live_blocked"
    assert flag.flag_emitted_ts_ms == 2000
    assert flag.live_blocked is True
    assert isinstance(flag, PaperModeFlag)
