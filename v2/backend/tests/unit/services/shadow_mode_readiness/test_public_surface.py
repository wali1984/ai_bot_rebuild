def test_public_surface() -> None:
    import v2.backend.app.services.shadow_mode_readiness as package

    assert package.__all__ == (
        "assemble_shadow_mode_readiness_flag",
        "ShadowModeReadinessServiceError",
    )
    assert callable(package.assemble_shadow_mode_readiness_flag)
    assert issubclass(package.ShadowModeReadinessServiceError, ValueError)
