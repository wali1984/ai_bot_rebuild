import pytest

from v2.backend.app.services.provenance_dedupe_attribution import (
    assemble_dedupe_decision_record,
)


def test_dedupe_service_keyword_only_params() -> None:
    with pytest.raises(TypeError):
        assemble_dedupe_decision_record(object())  # type: ignore[misc]
