import pytest

from v2.backend.app.domain.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionDomainError,
)

from ._fixtures import provenance_record


def test_provenance_record_rejects_negative_source_ts_ms() -> None:
    with pytest.raises(ProvenanceDedupeAttributionDomainError):
        provenance_record(source_ts_ms=-1, freshness_ms=126)
