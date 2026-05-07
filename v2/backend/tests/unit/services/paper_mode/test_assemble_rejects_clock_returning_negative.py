import pytest

from v2.backend.app.services.paper_mode import (
    PaperModeServiceError,
    assemble_paper_mode_flag,
)


def test_assemble_rejects_clock_returning_negative() -> None:
    with pytest.raises(PaperModeServiceError) as exc_info:
        assemble_paper_mode_flag(
            requested_mode="paper",
            now_ms_clock=lambda: -1,
        )
    assert exc_info.value.code == "must_be_nonnegative"
    assert exc_info.value.field == "now_ms_clock"
