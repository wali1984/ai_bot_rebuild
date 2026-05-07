import pytest


def test_paper_mode_now_propagates_service_error_for_non_string_mode():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime
    from v2.backend.app.services.paper_mode import PaperModeServiceError

    runtime = build_paper_mode_runtime(now_ms_clock=lambda: 1)

    with pytest.raises(PaperModeServiceError) as exc_info:
        runtime.paper_mode_now(requested_mode=123)

    assert exc_info.value.code == "must_be_str"
    assert exc_info.value.field == "requested_mode"
