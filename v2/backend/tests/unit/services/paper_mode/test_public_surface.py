from v2.backend.app.services import paper_mode


def test_public_surface() -> None:
    assert paper_mode.__all__ == (
        "assemble_paper_mode_flag",
        "PaperModeServiceError",
    )
    assert callable(paper_mode.assemble_paper_mode_flag)
    assert issubclass(paper_mode.PaperModeServiceError, ValueError)
