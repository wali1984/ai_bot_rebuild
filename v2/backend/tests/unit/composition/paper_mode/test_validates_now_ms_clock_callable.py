import pytest


def test_validates_now_ms_clock_callable():
    from v2.backend.app.composition.paper_mode import (
        PaperModeRuntimeCompositionError,
        build_paper_mode_runtime,
    )

    for value in (42, None, "not_callable"):
        with pytest.raises(PaperModeRuntimeCompositionError) as exc_info:
            build_paper_mode_runtime(now_ms_clock=value)
        assert exc_info.value.code == "must_be_callable"
        assert exc_info.value.field == "now_ms_clock"
