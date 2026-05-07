import pytest

from v2.backend.app.domain.paper_mode import PaperModeDomainError, PaperModeFlag


def test_flag_rejects_live_blocked_false() -> None:
    with pytest.raises(PaperModeDomainError) as exc_info:
        PaperModeFlag(
            mode="paper",
            flag_emitted_ts_ms=1730000000000,
            live_blocked=False,
        )
    assert exc_info.value.reason == "paper_mode_flag_requires_live_blocked_true"
    assert exc_info.value.field == "live_blocked"
