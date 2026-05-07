def test_public_surface() -> None:
    import v2.backend.app.domain.shadow_mode_readiness as module

    assert module.__all__ == (
        "ShadowModeReadinessDomainError",
        "ShadowModeReadinessFlag",
        "SHADOW_MODE_NOT_READY",
        "SHADOW_MODE_READY",
    )
