import pytest

from v2.backend.app.domain.external_manual_position_quarantine import (
    MANUAL_POSITION_QUARANTINED,
    ExternalManualPositionQuarantineDomainError,
    ManualPositionFlag,
)


def test_flag_rejects_live_blocked_false() -> None:
    with pytest.raises(ExternalManualPositionQuarantineDomainError):
        ManualPositionFlag(
            state=MANUAL_POSITION_QUARANTINED,
            live_blocked=False,
        )
