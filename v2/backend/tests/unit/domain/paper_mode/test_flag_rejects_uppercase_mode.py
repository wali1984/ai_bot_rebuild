import pytest

from v2.backend.app.domain.paper_mode import PaperModeDomainError, PaperModeFlag


def test_flag_rejects_uppercase_mode() -> None:
    with pytest.raises(PaperModeDomainError) as exc_info:
        PaperModeFlag(
            mode="PAPER",
            flag_emitted_ts_ms=1730000000000,
            live_blocked=True,
        )
    assert exc_info.value.reason == "paper_mode_flag_unknown_mode"
    assert exc_info.value.field == "mode"
