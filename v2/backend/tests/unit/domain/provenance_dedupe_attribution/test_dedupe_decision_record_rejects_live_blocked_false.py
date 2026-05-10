import pytest

from v2.backend.app.domain.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionDomainError,
)

from ._fixtures import dedupe_record


def test_dedupe_decision_record_rejects_live_blocked_false() -> None:
    with pytest.raises(ProvenanceDedupeAttributionDomainError):
        dedupe_record(live_blocked=False)
