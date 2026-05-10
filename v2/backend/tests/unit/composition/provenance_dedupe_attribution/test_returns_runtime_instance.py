from v2.backend.app.composition.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionRuntime,
    build_provenance_dedupe_attribution_runtime,
)


def test_returns_runtime_instance() -> None:
    runtime = build_provenance_dedupe_attribution_runtime(now_ms_clock=lambda: 1)
    assert isinstance(runtime, ProvenanceDedupeAttributionRuntime)
