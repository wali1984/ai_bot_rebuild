import pytest

from v2.backend.app.domain.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionDomainError,
)

from ._fixtures import DEDUPE_NEW, dedupe_record


def test_dedupe_decision_record_rejects_duplicate_of_decision_id_when_state_is_new() -> None:
    with pytest.raises(ProvenanceDedupeAttributionDomainError):
        dedupe_record(dedupe_state=DEDUPE_NEW, duplicate_of_decision_id="decision-0")
