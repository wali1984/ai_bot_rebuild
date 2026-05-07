import pytest

from v2.backend.app.services.paper_mode import (
    PaperModeServiceError,
    assemble_paper_mode_flag,
)


def test_assemble_rejects_clock_returning_bool() -> None:
    with pytest.raises(PaperModeServiceError) as exc_info:
        assemble_paper_mode_flag(
            requested_mode="paper",
            now_ms_clock=lambda: True,
        )
    assert exc_info.value.code == "must_be_int"
    assert exc_info.value.field == "now_ms_clock"
