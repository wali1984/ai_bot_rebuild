import v2.backend.app.composition.live_canary_blocker_guard as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "LiveCanaryBlockerGuardCompositionError",
        "LiveCanaryBlockerGuardRuntime",
        "build_live_canary_blocker_guard_runtime",
    }
