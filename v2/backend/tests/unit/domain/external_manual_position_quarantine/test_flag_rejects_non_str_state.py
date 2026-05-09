import pytest

from v2.backend.app.domain.external_manual_position_quarantine import (
    ExternalManualPositionQuarantineDomainError,
    ManualPositionFlag,
)


def test_flag_rejects_non_str_state() -> None:
    with pytest.raises(ExternalManualPositionQuarantineDomainError):
        ManualPositionFlag(state=1, live_blocked=True)  # type: ignore[arg-type]
