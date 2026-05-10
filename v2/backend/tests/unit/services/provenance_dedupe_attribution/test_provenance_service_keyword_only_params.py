import pytest

from v2.backend.app.services.provenance_dedupe_attribution import (
    assemble_provenance_record,
)


def test_provenance_service_keyword_only_params() -> None:
    with pytest.raises(TypeError):
        assemble_provenance_record(object())  # type: ignore[misc]
