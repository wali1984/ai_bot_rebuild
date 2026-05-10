import pytest

from v2.backend.app.domain.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionDomainError,
)

from ._fixtures import dedupe_record


def test_dedupe_decision_record_rejects_unknown_dedupe_state() -> None:
    with pytest.raises(ProvenanceDedupeAttributionDomainError):
        dedupe_record(dedupe_state="UNKNOWN")
