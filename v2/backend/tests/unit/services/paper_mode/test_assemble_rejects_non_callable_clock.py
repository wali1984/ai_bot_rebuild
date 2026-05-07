import pytest

from v2.backend.app.services.paper_mode import (
    PaperModeServiceError,
    assemble_paper_mode_flag,
)


def test_assemble_rejects_non_callable_clock() -> None:
    with pytest.raises(PaperModeServiceError) as exc_info:
        assemble_paper_mode_flag(
            requested_mode="paper",
            now_ms_clock=42,  # type: ignore[arg-type]
        )
    assert exc_info.value.code == "must_be_callable"
    assert exc_info.value.field == "now_ms_clock"
