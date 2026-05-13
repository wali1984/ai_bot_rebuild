import v2.backend.app.composition.execution_attribution_normalizer as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "ExecutionAttributionNormalizerCompositionError",
        "ExecutionAttributionNormalizerRuntime",
        "build_execution_attribution_normalizer_runtime",
    }
