import v2.backend.app.domain.provenance_dedupe_attribution as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "DEDUPE_DUPLICATE_OF_PRIOR",
        "DEDUPE_NEW",
        "DEDUPE_STALE_OUT_OF_ORDER",
        "DedupeDecisionRecord",
        "ProvenanceDedupeAttributionDomainError",
        "ProvenanceRecord",
    }
