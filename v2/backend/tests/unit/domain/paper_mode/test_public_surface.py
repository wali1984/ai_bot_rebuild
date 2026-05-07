import v2.backend.app.domain.paper_mode as paper_mode


def test_public_surface() -> None:
    assert paper_mode.__all__ == (
        "PaperModeDomainError",
        "PaperModeFlag",
        "PAPER_MODE_PAPER",
        "PAPER_MODE_LIVE_BLOCKED",
    )
