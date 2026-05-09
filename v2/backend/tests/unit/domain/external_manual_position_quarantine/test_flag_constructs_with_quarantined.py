from v2.backend.app.domain.external_manual_position_quarantine import (
    MANUAL_POSITION_QUARANTINED,
    ManualPositionFlag,
)


def test_flag_constructs_with_quarantined() -> None:
    flag = ManualPositionFlag(
        state=MANUAL_POSITION_QUARANTINED,
        live_blocked=True,
    )

    assert flag.state == MANUAL_POSITION_QUARANTINED
    assert flag.live_blocked is True
