import pytest

from v2.backend.app.services.paper_mode import (
    PaperModeServiceError,
    assemble_paper_mode_flag,
)


def test_assemble_rejects_unrecognized_requested_mode() -> None:
    with pytest.raises(PaperModeServiceError) as exc_info:
        assemble_paper_mode_flag(
            requested_mode="foo_bar_synthetic",
            now_ms_clock=lambda: 1,
        )
    assert exc_info.value.code == "paper_mode_service_unrecognized_requested_mode"
    assert exc_info.value.field == "requested_mode"
