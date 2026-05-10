import v2.backend.app.services.provenance_dedupe_attribution as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "DedupeServiceError",
        "ProvenanceServiceError",
        "assemble_dedupe_decision_record",
        "assemble_provenance_record",
    }
