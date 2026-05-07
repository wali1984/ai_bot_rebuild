import pytest


def test_paper_mode_now_keyword_only_param():
    from v2.backend.app.composition.paper_mode import build_paper_mode_runtime

    runtime = build_paper_mode_runtime(now_ms_clock=lambda: 1)

    with pytest.raises(TypeError):
        runtime.paper_mode_now("paper")
