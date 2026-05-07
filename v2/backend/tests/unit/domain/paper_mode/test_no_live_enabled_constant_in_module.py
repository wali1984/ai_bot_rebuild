import v2.backend.app.domain.paper_mode as paper_mode


def test_no_live_enabled_constant_in_module() -> None:
    assert hasattr(paper_mode, "PAPER_MODE_LIVE_ENABLED") is False
    assert hasattr(paper_mode, "live_enabled") is False
    assert hasattr(paper_mode, "PAPER_MODE_LIVE") is False
    assert "PAPER_MODE_LIVE_ENABLED" not in paper_mode.__all__
    assert "live_enabled" not in paper_mode.__all__
    assert "PAPER_MODE_LIVE" not in paper_mode.__all__
