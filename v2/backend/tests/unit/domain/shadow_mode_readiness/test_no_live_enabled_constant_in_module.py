def test_no_live_enabled_constant_in_module() -> None:
    import v2.backend.app.domain.shadow_mode_readiness as module

    assert hasattr(module, "SHADOW_MODE_LIVE_ENABLED") is False
    assert hasattr(module, "live_enabled") is False
    assert hasattr(module, "SHADOW_MODE_LIVE") is False
    assert "SHADOW_MODE_LIVE_ENABLED" not in module.__all__
    assert "live_enabled" not in module.__all__
    assert "SHADOW_MODE_LIVE" not in module.__all__
