import pytest

from v2.backend.app.composition.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionRuntimeCompositionError,
    build_provenance_dedupe_attribution_runtime,
)


def test_runtime_validates_now_ms_clock() -> None:
    with pytest.raises(ProvenanceDedupeAttributionRuntimeCompositionError):
        build_provenance_dedupe_attribution_runtime(now_ms_clock=1)  # type: ignore[arg-type]
