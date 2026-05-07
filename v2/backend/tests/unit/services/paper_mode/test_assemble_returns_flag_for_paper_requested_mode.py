from v2.backend.app.domain.paper_mode import PaperModeFlag
from v2.backend.app.services.paper_mode import assemble_paper_mode_flag


def test_assemble_returns_flag_for_paper_requested_mode() -> None:
    flag = assemble_paper_mode_flag(
        requested_mode="paper",
        now_ms_clock=lambda: 1000,
    )
    assert flag.mode == "paper"
    assert flag.flag_emitted_ts_ms == 1000
    assert flag.live_blocked is True
    assert isinstance(flag, PaperModeFlag)
