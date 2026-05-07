def test_public_surface():
    import v2.backend.app.composition.shadow_mode_readiness as module

    assert module.__all__ == (
        "build_shadow_mode_readiness_runtime",
        "ShadowModeReadinessRuntime",
        "ShadowModeReadinessRuntimeCompositionError",
    )
    assert callable(module.build_shadow_mode_readiness_runtime)
    assert isinstance(module.ShadowModeReadinessRuntimeCompositionError, type)
    assert issubclass(module.ShadowModeReadinessRuntimeCompositionError, Exception)
    assert not issubclass(module.ShadowModeReadinessRuntimeCompositionError, ValueError)
    assert isinstance(module.ShadowModeReadinessRuntime, type)
