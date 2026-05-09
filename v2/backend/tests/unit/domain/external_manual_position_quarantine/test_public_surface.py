from v2.backend.app.domain import external_manual_position_quarantine as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "ExternalManualPositionQuarantineDomainError",
        "ExternalPositionQuarantineRecord",
        "MANUAL_POSITION_NOT_PRESENT",
        "MANUAL_POSITION_QUARANTINED",
        "ManualPositionFlag",
    }
