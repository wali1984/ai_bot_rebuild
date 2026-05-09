from v2.backend.app.domain.external_manual_position_quarantine import (
    MANUAL_POSITION_NOT_PRESENT,
    ManualPositionFlag,
)


def test_flag_constructs_with_not_present() -> None:
    flag = ManualPositionFlag(
        state=MANUAL_POSITION_NOT_PRESENT,
        live_blocked=True,
    )

    assert flag.state == MANUAL_POSITION_NOT_PRESENT
    assert flag.live_blocked is True
