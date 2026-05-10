import pytest

from v2.backend.app.domain.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionDomainError,
)

from ._fixtures import provenance_record


def test_provenance_record_rejects_ingest_ts_before_source_ts() -> None:
    with pytest.raises(ProvenanceDedupeAttributionDomainError):
        provenance_record(source_ts_ms=2000, ingest_ts_ms=1000, freshness_ms=0)
