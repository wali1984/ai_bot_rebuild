def test_public_surface():
    from v2.backend.app.composition import paper_mode

    assert paper_mode.__all__ == (
        "build_paper_mode_runtime",
        "PaperModeRuntime",
        "PaperModeRuntimeCompositionError",
    )
    assert callable(paper_mode.build_paper_mode_runtime)
    assert isinstance(paper_mode.PaperModeRuntimeCompositionError, type)
    assert issubclass(paper_mode.PaperModeRuntimeCompositionError, Exception)
    assert not issubclass(paper_mode.PaperModeRuntimeCompositionError, ValueError)
    assert isinstance(paper_mode.PaperModeRuntime, type)
