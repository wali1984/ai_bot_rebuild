import pytest

from v2.backend.app.domain.external_manual_position_quarantine import (
    ExternalManualPositionQuarantineDomainError,
    ManualPositionFlag,
)


def test_flag_rejects_unknown_state() -> None:
    with pytest.raises(ExternalManualPositionQuarantineDomainError):
        ManualPositionFlag(state="live_owned", live_blocked=True)
