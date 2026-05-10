import pytest

from v2.backend.app.domain.provenance_dedupe_attribution import (
    ProvenanceDedupeAttributionDomainError,
)

from ._fixtures import DEDUPE_DUPLICATE_OF_PRIOR, dedupe_record


def test_dedupe_decision_record_requires_duplicate_of_decision_id_when_state_is_duplicate_of_prior() -> None:
    with pytest.raises(ProvenanceDedupeAttributionDomainError):
        dedupe_record(dedupe_state=DEDUPE_DUPLICATE_OF_PRIOR)
