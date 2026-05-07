import pytest

from v2.backend.app.services.paper_mode import assemble_paper_mode_flag


def test_assemble_keyword_only_params() -> None:
    with pytest.raises(TypeError):
        assemble_paper_mode_flag("paper", lambda: 1)  # type: ignore[misc]

    flag = assemble_paper_mode_flag(
        requested_mode="paper",
        now_ms_clock=lambda: 1,
    )
    assert flag.mode == "paper"
