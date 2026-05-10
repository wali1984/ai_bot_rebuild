import v2.backend.app.composition.provenance_dedupe_attribution as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "ProvenanceDedupeAttributionRuntime",
        "ProvenanceDedupeAttributionRuntimeCompositionError",
        "build_provenance_dedupe_attribution_runtime",
    }
