import v2.backend.app.composition.current_signal_lineage_adapter as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "CurrentSignalLineageAdapterCompositionError",
        "CurrentSignalLineageAdapterRuntime",
        "build_current_signal_lineage_adapter_runtime",
    }
