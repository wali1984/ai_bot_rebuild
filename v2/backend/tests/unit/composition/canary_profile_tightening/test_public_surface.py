import v2.backend.app.composition.canary_profile_tightening as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "CanaryProfileTighteningCompositionError",
        "CanaryProfileTighteningRuntime",
        "build_canary_profile_tightening_runtime",
    }
