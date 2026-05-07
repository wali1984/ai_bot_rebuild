import pytest

from v2.backend.app.domain.paper_mode import PaperModeDomainError, PaperModeFlag


def test_flag_rejects_float_for_flag_emitted_ts_ms() -> None:
    with pytest.raises(PaperModeDomainError) as exc_info:
        PaperModeFlag(
            mode="paper",
            flag_emitted_ts_ms=1730000000000.5,
            live_blocked=True,
        )
    assert (
        exc_info.value.reason
        == "paper_mode_flag_emitted_ts_ms_must_be_non_negative_int"
    )
    assert exc_info.value.field == "flag_emitted_ts_ms"
