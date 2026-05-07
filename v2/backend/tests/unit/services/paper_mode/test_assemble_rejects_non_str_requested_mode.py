import pytest

from v2.backend.app.services.paper_mode import (
    PaperModeServiceError,
    assemble_paper_mode_flag,
)


def test_assemble_rejects_non_str_requested_mode() -> None:
    for requested_mode in (42, None):
        with pytest.raises(PaperModeServiceError) as exc_info:
            assemble_paper_mode_flag(
                requested_mode=requested_mode,  # type: ignore[arg-type]
                now_ms_clock=lambda: 1,
            )
        assert exc_info.value.code == "must_be_str"
        assert exc_info.value.field == "requested_mode"
