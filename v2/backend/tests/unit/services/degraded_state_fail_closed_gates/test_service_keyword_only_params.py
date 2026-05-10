import pytest

from v2.backend.app.services.degraded_state_fail_closed_gates import (
    assemble_degraded_state_record,
)


def test_service_keyword_only_params() -> None:
    with pytest.raises(TypeError):
        assemble_degraded_state_record(object())  # type: ignore[misc]
