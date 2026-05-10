import pytest

from v2.backend.app.domain.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionDomainError,
)

from ._fixtures import provenance_record


def test_provenance_record_rejects_live_blocked_false() -> None:
    with pytest.raises(ProvenanceDedupeAttributionDomainError):
        provenance_record(live_blocked=False)
